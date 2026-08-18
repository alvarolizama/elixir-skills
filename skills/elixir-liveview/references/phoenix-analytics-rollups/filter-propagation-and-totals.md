# Filter Propagation & Table Totals — Stats Drill-Down

Added 2026-08-04. Covers two bugs fixed together: KPI cards ignoring the
selected filter, and missing total rows in breakdown tables.

## Bug 1: KPI Cards Ignore Drill-Down Filter

**Symptom**: On `/dashboard/stats/models?model_id=X`, the breakdown tables
show data for model X, but the KPI cards (Requests, Cost, Tokens, TPS) show
org-wide totals for the period.

**Root cause**: `load_summary` → `fetch_summary(user, opts)` where `opts`
only has `:from`/`:to`. The `model_filter`, `team_filter`, and
`service_filter` from `socket.assigns` are never passed to
`Logs.cost_summary/1`.

**Fix** (in `stats_live.ex`):

```elixir
defp load_summary(socket, user, opts) do
  summary = fetch_summary(user, opts, socket.assigns)  # pass assigns
  ...
end

defp fetch_summary(%{global_role: "admin"}, opts, assigns) do
  opts
  |> apply_stats_filters(assigns)
  |> Logs.cost_summary()
end

defp apply_stats_filters(opts, assigns) do
  base = Map.new(opts)
  cond do
    assigns[:model_filter]   -> Map.put(base, :model_alias_id, assigns.model_filter)
    assigns[:team_filter]    -> Map.put(base, :team_id, assigns.team_filter)
    assigns[:service_filter] -> Map.put(base, :team_member_id, assigns.service_filter)
    true -> base
  end
end
```

This works because `Logs.cost_summary/1` uses `apply_log_filters/2` which
already supports `:model_alias_id`, `:team_id`, `:team_member_id`, etc.

## Bug 2: Service Filter Breaks breakdown_by_model

**Symptom**: Selecting a service in `/dashboard/stats/services` shows empty
"Modelos usados" table.

**Root cause**: `Rollup.breakdown_by_model(service_id, opts)` passes
`service_id` as the first arg (`team_id`). But services have
`team_id = nil` — they're virtual team members. The
`maybe_join_team(service_id)` join filters `tm.team_id == service_id`
which matches nothing.

**Fix**: Use `team_member_id` option instead:

```elixir
# In load_breakdowns(:services, ...):
Rollup.breakdown_by_model(nil, Keyword.put(opts, :team_member_id, service_id))
```

Added `maybe_team_member_id/2` to `rollup.ex`:

```elixir
defp maybe_team_member_id(query, nil), do: query
defp maybe_team_member_id(query, id) when is_binary(id) do
  where(query, [rl], rl.team_member_id == ^id)
end
```

## Table Totals Pattern

Add `breakdown_total/1` helper to the LiveView module:

```elixir
def breakdown_total([]), do: nil
def breakdown_total(rows) when is_list(rows) do
  %{
    request_count: Enum.reduce(rows, 0, & &1.request_count + &2),
    cost_usd: Enum.reduce(rows, Decimal.new(0), fn r, acc -> Decimal.add(acc, r.cost_usd) end),
    prompt_tokens: Enum.reduce(rows, 0, & &1.prompt_tokens + &2),
    completion_tokens: Enum.reduce(rows, 0, & &1.completion_tokens + &2)
  }
end
```

With entity count helpers:

```elixir
def distinct_providers(rows), do: rows |> Enum.map(& &1.model_provider_id) |> Enum.reject(&is_nil/1) |> Enum.uniq() |> length()
def distinct_users(rows), do: rows |> Enum.map(& &1.user_email) |> Enum.uniq() |> length()
```

**HEEx gotcha**: Render `<tfoot>` directly inside `<%= if has_data?(@list) do %>`.
Do NOT wrap in `<%= if total do %>` — the compiler knows the list is
non-empty inside `has_data?()` so `breakdown_total(rows)` always returns a
map (truthy), causing a "will always evaluate to true" warning with
`--warnings-as-errors`.
