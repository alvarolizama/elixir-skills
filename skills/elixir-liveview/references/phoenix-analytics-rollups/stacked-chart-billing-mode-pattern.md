# Stacked Bar Chart with Billing-Mode Separation and Provider Drill-Down

Pattern from MyApp's `hour-distribution` chart refactor (2026-08-06).

## Problem

A stacked bar chart needs to communicate TWO dimensions at once:
1. What was used (model alias)
2. How it was paid for (billing mode: included vs pay_per_token)

The naive approach (one color per model alias regardless of billing mode)
mixes free and paid usage visually, making it hard to spot where money
is actually going.

## Solution Architecture

### 1. Query Layer

Join the full provider chain and group by billing mode:

```elixir
RequestLog
|> join(:left, [rl], mp in ModelProvider, on: rl.model_provider_id == mp.id)
|> join(:left, [rl, mp], c in Credential, on: mp.credential_id == c.id)
|> join(:left, [rl, mp, c], p in Provider, on: c.provider_id == p.id)
|> join(:left, [rl], ma in ModelAlias, on: rl.model_alias_id == ma.id)
|> select([rl, mp, c, p, ma], %{
  hour: fragment("CAST(EXTRACT(hour FROM (? AT TIME ZONE 'Etc/UTC') AT TIME ZONE ?) AS integer)",
    rl.inserted_at, ^timezone),
  model: fragment("COALESCE(?, ?)", ma.name, rl.model_requested),
  billing_mode: fragment("COALESCE(?, 'unknown')", mp.billing_mode),
  provider_name: p.name,
  credential_name: c.name,
  cost_usd: rl.provider_cost_usd,
  id: rl.id
})
|> subquery()
|> then(fn subq ->
  from(r in subq,
    group_by: [r.hour, r.model, r.billing_mode, r.provider_name, r.credential_name],
    select: %{
      hour: r.hour,
      model: r.model,
      billing_mode: r.billing_mode,
      provider_name: r.provider_name,
      credential_name: r.credential_name,
      cost_usd: fragment("COALESCE(SUM(?), 0)", r.cost_usd),
      request_count: count(r.id)
    }
  )
end)
```

### 2. Post-Processing (per hour)

Build `hour_row` with billing-mode separation:

```elixir
by_model =
  hour_rows
  |> Enum.group_by(& &1.model)
  |> Enum.map(fn {model, entries} ->
    requests = Enum.reduce(entries, 0, &(&1.request_count + &2))
    cost = Enum.reduce(entries, Decimal.new(0), fn e, acc -> Decimal.add(acc, e.cost_usd) end)
    billing_mode = entries |> List.first() |> Map.get(:billing_mode, "unknown")

    providers =
      entries
      |> Enum.map(fn e ->
        %{
          provider_name: e.provider_name || "—",
          credential_name: e.credential_name || "—",
          requests: e.request_count,
          cost_usd: Decimal.new(to_string(e.cost_usd))
        }
      end)
      |> Enum.filter(&(&1.requests > 0))
      |> Enum.sort_by(& &1.requests, :desc)

    %{
      model: model,
      requests: requests,
      cost_usd: cost,
      billing_mode: billing_mode,
      providers: providers
    }
  end)
  |> Enum.sort_by(& &1.requests, :desc)

%{
  hour: hour,
  total_requests: total_requests,
  included_requests: included_requests,
  pay_per_token_requests: pay_per_token_requests,
  total_cost_usd: total_cost,
  models: by_model
}
```

### 3. Bar Segments

Two visual layers in `flex-col-reverse` (bottom = first in list):

```elixir
def model_segments(hour_row, all_models) do
  hour_total = hour_row.total_requests
  return [] if hour_total <= 0

  # 1. Bottom layer: included (gray)
  included_segment =
    if hour_row.included_requests > 0 do
      pct = Float.round(hour_row.included_requests / hour_total * 100, 1)
      [%{height_pct: pct, color: "bg-base-300/30", is_pay_per_token: false}]
    else
      []
    end

  # 2. Above: pay_per_token per model alias (colors)
  ppt_segments =
    all_models
    |> Enum.with_index()
    |> Enum.map(fn {model_info, idx} ->
      model_data =
        Enum.find(
          hour_row.models,
          %{requests: 0},
          &(&1.model == model_info.model and &1.billing_mode == "pay_per_token")
        )

      if model_data.requests > 0 do
        pct = Float.round(model_data.requests / hour_total * 100, 1)
        %{
          height_pct: pct,
          color: model_color_light(idx),
          is_pay_per_token: true
        }
      end
    end)
    |> Enum.reject(&is_nil/1)

  included_segment ++ ppt_segments
end
```

### 4. Legend (Hierarchical)

```html
<div class="w-56 shrink-0 border-l border-base-300 pl-4">
  <div class="text-[10px] font-semibold text-base-content/60 uppercase tracking-wide mb-2">
    Total período
  </div>

  <div class="space-y-2.5">
    <div :for={entry <- legend.entries}>
      <!-- Model alias header -->
      <div class="flex items-center gap-1.5">
        <span class={["w-2.5 h-2.5 rounded-sm shrink-0", entry.color]} />
        <span class="text-[10px] font-medium truncate flex-1">{entry.model}</span>
        <span class="text-[9px] text-base-content/50 shrink-0">
          {format_number(entry.requests)} req
        </span>
      </div>

      <!-- Provider breakdown -->
      <div :if={entry.providers != []} class="pl-4 mt-0.5 space-y-0.5">
        <div :for={prov <- entry.providers} class="flex items-center justify-between text-[9px]">
          <span class="text-base-content/50 truncate mr-2">
            {prov.provider_name}
            <span :if={prov.credential_name != "—"} class="text-base-content/30">
              ({prov.credential_name})
            </span>
          </span>
          <span class="text-base-content/40 shrink-0 whitespace-nowrap">
            {format_number(prov.requests)} req
            <span :if={Decimal.compare(prov.cost_usd, Decimal.new(0)) == :gt} class="text-warning">
              · ${format_decimal(prov.cost_usd)}
            </span>
          </span>
        </div>
      </div>
    </div>
  </div>

  <!-- Totals -->
  <div class="mt-3 pt-2 border-t border-base-300">
    <div class="text-[10px] font-semibold">
      {format_number(legend.total_requests)} requests
    </div>
    <div :if={Decimal.compare(legend.total_cost_usd, Decimal.new(0)) == :gt}
         class="text-[10px] text-warning font-medium">
      ${format_decimal(legend.total_cost_usd)} total
    </div>
  </div>
</div>
```

### 5. Hover Context

`legend_data/2` rebuilds the legend from the hovered hour's data instead
of the period aggregate:

```elixir
def legend_data(stacked_rows, hovered_hour) do
  source_models =
    if hovered_hour do
      hour_row = Enum.find(stacked_rows, &(&1.hour == hovered_hour))
      if hour_row, do: hour_row.models, else: []
    else
      # Period aggregate with provider drill-down
      stacked_rows
      |> Enum.flat_map(& &1.models)
      |> Enum.group_by(& &1.model)
      |> Enum.map(fn {model, entries} ->
        requests = Enum.reduce(entries, 0, &(&1.requests + &2))
        cost = Enum.reduce(entries, Decimal.new(0), fn e, acc -> Decimal.add(acc, e.cost_usd) end)

        providers =
          entries
          |> Enum.flat_map(& &1.providers)
          |> Enum.group_by(fn p -> {p.provider_name, p.credential_name} end)
          |> Enum.map(fn {{p_name, c_name}, p_entries} ->
            p_requests = Enum.reduce(p_entries, 0, &(&1.requests + &2))
            p_cost = Enum.reduce(p_entries, Decimal.new(0), fn e, acc -> Decimal.add(acc, e.cost_usd) end)
            %{provider_name: p_name, credential_name: c_name, requests: p_requests, cost_usd: p_cost}
          end)
          |> Enum.sort_by(& &1.requests, :desc)

        %{model: model, requests: requests, cost_usd: cost, providers: providers}
      end)
    end
  # ... build entries from all_models + source_models
end
```

## Key Design Decisions

1. **Legend is primary, bars are overview** — the legend carries the
   detailed breakdown; the bars provide temporal context.
3. **Gray = free, colors = paid** — the muted included segment lets the
   eye focus on what actually costs money.
3b. **Solid colors beat `/40` variants** — `model_color_light` (daisyUI
   `/40` opacity) was replaced by solid `model_color` in both segments
   and legend swatches: at 40% opacity the model colors are
   indistinguishable on small bars. The light helper was deleted as
   orphaned code. Bar heights later moved to a sqrt scale with an 8%
   floor plus Y-axis ticks and CSS tooltips — see
   `references/css-bar-chart-readability.md`.
3. **Legend width `w-56`** (or wider) — the provider drill-down needs
   more horizontal space than a simple flat list.
4. **Provider + credential** — showing both distinguishes between multiple
   API keys from the same provider (e.g. "OpenAI (Producción)" vs
   "OpenAI (Staging)").
5. **Cost only when > 0** — avoids cluttering the included rows with $0.
