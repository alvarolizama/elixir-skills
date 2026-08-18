# Drill-down Daily Sparklines

Pattern for adding a per-dimension stacked-bar sparkline chart below KPI
cards in drill-down views (model, team, service detail pages). Proven in
MyApp's StatsLive (2026-08-08).

## What it looks like

When an admin clicks into a model (e.g. gpt-4), the page shows:
1. KPI cards (requests, cost, tokens, TPS)
2. **A sparkline card**: stacked bars per day, colored by provider, with
   hover tooltips showing daily breakdown + a side legend with totals.
3. Detail tables below (provider breakdown, member breakdown, etc.)

Same pattern for teams (models per day) and services (models per day).

## Rollup module — daily series query

Add one function per drill-down dimension. Each returns rows shaped
`%{date: DateTime, label: String, request_count: integer}`.

```elixir
def daily_series_by_provider_for_model(model_alias_id, opts \\ [])
def daily_series_by_provider_for_model(nil, _opts), do: []

def daily_series_by_provider_for_model(model_alias_id, opts)
    when is_binary(model_alias_id) do
  from = Keyword.get(opts, :from)
  to = Keyword.get(opts, :to)
  timezone = Keyword.get(opts, :timezone, "Etc/UTC")

  bucketed =
    RequestLog
    |> where([rl], rl.model_alias_id == ^model_alias_id)
    |> maybe_member_ids(Keyword.get(opts, :member_ids))
    |> join_providers()  # your app's provider joins
    |> maybe_from(from)
    |> maybe_to(to)
    |> select([...], %{
      bucket: fragment(
        "date_trunc('day', ? AT TIME ZONE ?) AT TIME ZONE ?",
        rl.inserted_at, ^timezone, ^timezone
      ),
      label: p.name,
      id: rl.id
    })
    |> subquery()

  query =
    from(b in bucketed,
      group_by: [b.bucket, b.label],
      order_by: [b.bucket, b.label],
      select: %{
        date: b.bucket,
        label: b.label,
        request_count: count(b.id)
      }
    )

  Repo.all(query)
  |> Enum.map(fn row -> %{
      date: to_utc_datetime(row.date),
      label: row.label || "—",
      request_count: row.request_count
    } end)
end
```

Key rules:
- Use `date_trunc('day', ...)` with the same `AT TIME ZONE` pattern as
  `hourly_series/2` (materialize bucket in subquery to avoid GROUP BY
  param-mismatch errors).
- `label` is the human-readable dimension value (provider name, model name).
- Return `[]` when the filter is nil (no drill-down selected).
- Scope with `maybe_member_ids` — drill-downs must respect the user's role.

## LiveView wiring

### 1. Add assigns in `empty_data_assigns/0`

```elixir
drilldown_series: [],
drilldown_series_labels: []
```

### 2. Wire queries in `breakdown_tasks/2` per `live_action`

For `:models` drill-down (when `model_id` is present):
```elixir
fn -> {:drilldown_series, Rollup.daily_series_by_provider_for_model(model_id, opts)} end,
fn -> {:drilldown_series_labels,
       Rollup.daily_series_by_provider_for_model(model_id, opts)
       |> Enum.map(& &1.label) |> Enum.uniq() |> Enum.sort()} end
```

Same pattern for `:teams` and `:services` with their respective rollup
functions. Both run inside the async `Task.async_stream` so they don't
block other queries.

### 3. Add sparkline helpers (public `def` so HEEx can call them)

```elixir
def pivot_daily_series(rows) when is_list(rows) do
  days = rows |> Enum.map(&DateTime.to_date(&1.date)) |> Enum.uniq() |> Enum.sort()
  series =
    rows
    |> Enum.group_by(& &1.label)
    |> Map.new(fn {label, entries} ->
      {label, Map.new(entries, &{DateTime.to_date(&1.date), &1.request_count})}
    end)
  %{days: days, series: series}
end

def daily_series_max(%{series: series}) do
  series |> Enum.flat_map(fn {_, by_date} -> Map.values(by_date) end)
  |> Enum.max(fn -> 0 end)
end

def sparkline_bar_height(count, max) when max > 0 do
  pct = :math.sqrt(count / max) * 100
  max(Float.round(pct, 1), 4.0)
end
def sparkline_bar_height(_, _), do: 0.0

def sparkline_color(index), do: provider_color(index)

def sparkline_label_total(by_date), do: by_date |> Map.values() |> Enum.sum()
```

## HEEx template

Insert between the KPI cards grid and the first detail table. Wrap in
`<%= if @drilldown_series != [] do %>` so the card doesn't appear when
no drill-down is selected.

```heex
<div class="card bg-base-100 border border-base-300 shadow-sm">
  <div class="card-body p-4 gap-2">
    <div class="flex items-center justify-between">
      <h2 class="card-title text-base">
        <.icon name="hero-chart-bar" class="w-5 h-5 text-base-content/60" />
        Uso diario por proveedor
      </h2>
      <span class="text-[10px] text-base-content/40 hidden sm:inline">
        {period_label(@period)}
      </span>
    </div>

    <div class="flex gap-4 mt-2">
      <%!-- Chart --%>
      <div class="flex-1">
        <div class="flex items-end gap-px h-32 relative">
          <div :for={day <- pivoted.days}
               class="flex-1 flex flex-col items-center justify-end h-full group relative">
            <%!-- Tooltip --%>
            <div class="hidden group-hover:block absolute -top-1 -translate-y-full ...">
              <div class="bg-base-300 text-base-content text-[10px] rounded-md px-2 py-1 shadow-lg whitespace-nowrap">
                <div class="font-semibold">{Calendar.strftime(day, "%d %b")}</div>
                <div :for={label <- labels} class="flex justify-between gap-2">
                  <span class="truncate max-w-[100px]">{label}</span>
                  <span class="tabular-nums">
                    {format_number(Map.get(pivoted.series[label] || %{}, day, 0))}
                  </span>
                </div>
              </div>
            </div>

            <%!-- Stacked bar --%>
            <div class="w-full flex flex-col-reverse rounded-t overflow-hidden">
              <div :for={label <- labels}
                   class={["w-full", sparkline_color(Enum.find_index(labels, &(&1 == label)) || 0)]}
                   style={"height: #{sparkline_bar_height(Map.get(pivoted.series[label] || %{}, day, 0), spark_max)}%"}
                   title={"#{label}: #{format_number(Map.get(pivoted.series[label] || %{}, day, 0))}"}
              />
            </div>
          </div>
        </div>

        <%!-- Day labels --%>
        <div class="flex gap-px mt-1">
          <span :for={day <- pivoted.days}
                class="flex-1 text-center text-[9px] text-base-content/40">
            {Calendar.strftime(day, "%d")}
          </span>
        </div>
      </div>

      <%!-- Legend --%>
      <div class="w-40 shrink-0 border-l border-base-300 pl-3">
        <div class="text-[10px] font-semibold text-base-content/60 uppercase tracking-wide mb-2">
          Proveedores
        </div>
        <div class="space-y-1.5">
          <div :for={{label, idx} <- Enum.with_index(labels)}
               class="flex items-center gap-1.5">
            <span class={["w-2 h-2 rounded-sm shrink-0", sparkline_color(idx)]} />
            <span class="text-[10px] truncate flex-1">{label}</span>
            <span class="text-[9px] text-base-content/50 shrink-0">
              {format_number(sparkline_label_total(pivoted.series[label] || %{}))}
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
```

Adapt the title and legend label ("Proveedores" → "Modelos") per view.

## Testing

The sparkline card only renders when `drilldown_series != []`, which
requires a drill-down filter (`model_id`, `team_id`, or `service_id`).
In LiveView tests, the async data load means the card won't appear on
`live/3` initial mount — wait with the same `wait_stats_loaded/1` helper
used by the page's own tests.

```elixir
defp wait_stats_loaded(view, attempts \\ 200)
defp wait_stats_loaded(view, attempts) when attempts > 0 do
  state = :sys.get_state(view.pid)
  case get_in(state, [Access.key(:socket), Access.key(:assigns), Access.key(:stats_loading)]) do
    false -> view
    _ -> Process.sleep(10); wait_stats_loaded(view, attempts - 1)
  end
end
```

For the pure helpers (`pivot_daily_series`, `sparkline_bar_height`, etc.),
unit-test them directly against sample data (no LiveView mount needed):

```elixir
test "sparkline helpers work with sample data" do
  rows = [
    %{date: ~U[2026-08-01 00:00:00Z], label: "OpenRouter", request_count: 10},
    %{date: ~U[2026-08-02 00:00:00Z], label: "OpenRouter", request_count: 20}
  ]
  pivoted = StatsLive.pivot_daily_series(rows)
  assert length(pivoted.days) == 2
  assert StatsLive.daily_series_max(pivoted) == 20
  assert StatsLive.sparkline_bar_height(20, 20) == 100.0
end
```

## When NOT to use this pattern

- **Index/overview pages** — use the existing `hour_distribution` or
  `model_provider_stacked` cards. Daily sparklines are for drill-downs
  where the dimension is already fixed.
- **Real-time dashboards** — use the ETS rolling-window pattern
  (`references/ets-rolling-window-sparklines.md`) instead. Daily buckets
  are too coarse for sub-minute updates.
