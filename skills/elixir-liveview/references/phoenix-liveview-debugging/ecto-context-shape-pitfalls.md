# Ecto query & context function shape pitfalls

A class of bug that surfaces at RUNTIME in a `KeyError` or
`(BadMapError)` from deep inside a LiveView template: the context
function returns a map missing keys the template expects, or the Ecto
filter map leaks `""` strings that Ecto can't cast to `:boolean`.

## "Empty string" is NOT a valid value for boolean filter fields

`Logs.list_logs(filters)` and many Ecto-backed context functions accept a
loose filter map. `maybe_where(:streaming, value)` does
`where(query, [rl], field(rl, ^field) == ^value)`. If `value == ""`,
Ecto chokes:

```
** (Ecto.Query.CastError) value "" in `where` cannot be cast to type :boolean
```

**Fix**: drop empty values BEFORE forwarding to the context function.

```elixir
defp drop_empty_filters(filters) do
  filters
  |> Enum.reject(fn {_k, v} -> v in [nil, ""] end)
  |> Map.new()
end

defp load_logs(socket, mode) do
  base_filters =
    socket.assigns.filters
    |> Map.put("team_member_ids", ids)
    |> drop_empty_filters()
  ...
end
```

Same applies to numeric fields that might be `""` from an empty form input.

## Context functions must return the full keyset the caller assumes

If a template reads `@summary_5d.avg_tps` and the context function returns
a partial map when no data exists, the render raises `KeyError: :avg_tps`.

Two fixes:
1. Make the context function ALWAYS return the full keyset, with sensible
   zero/nil values when there's no data:

   ```elixir
   def cost_summary_for_members([], _opts) do
     %{
       total_cost_usd: Decimal.new(0),
       total_prompt_tokens: 0,
       total_completion_tokens: 0,
       total_cache_read_tokens: 0,
       total_cache_creation_tokens: 0,
       request_count: 0,
       avg_latency_ms: nil,
       avg_tps: 0.0,
       avg_ttft_ms: nil
     }
   end
   ```

2. Mirror the same shape in any `default_*/0` you assign to the socket on
   mount, so the first render and the post-load render look identical.

## `Enum.sort_by([_rl, m], desc: m.count)` — `m` is not a binding

`order_by: [_rl, m], desc: m.count` references a binding `m` that does NOT
exist — the second element of a 2-element list is not named, it just
discards. Either:

```elixir
order_by(asc_nulls_last: :count)   # anonymous key — works on select maps
```

or define the aggregate as a field on a `select` map and use a named
key:

```elixir
|> select([rl], %{model_requested: rl.model_requested, count: count(rl.id)})
|> order_by(asc: :count)
```

## `order_by: [asc_nulls_last: aps.priority]` requires the JOIN binding

If the query is `left_join: aps in assoc(ma, :model_providers)`, ordering
by `ma.priority` orders the parent; ordering by `aps.priority` orders the
joined children. Pick the right binding for the desired ordering, or
order by both:

```elixir
order_by: [asc: ma.name, asc_nulls_last: aps.priority]
```

## Postgres: `'2xx'|'4xx'|'5xx'` is ambiguous in SELECT

A bare `'2xx'|'4xx'|'5xx'` literal (no `AS` alias, no parentheses) is
parsed as a union of three rows, not a string with embedded pipes.
Postgres error: `ERROR 42725 (ambiguous_function) operator is not unique:
unknown | unknown`.

**Fix**: repeat the full CASE expression in the SELECT instead of
short-handing to the GROUP BY literal:

```elixir
|> group_by([rl], fragment("CASE WHEN ? BETWEEN 200 AND 299 THEN '2xx'
                             WHEN ? BETWEEN 400 AND 499 THEN '4xx'
                             WHEN ? BETWEEN 500 AND 599 THEN '5xx' END",
                          rl.status_code, rl.status_code, rl.status_code))
|> select([rl], {fragment("CASE ... END", rl.status_code, rl.status_code, rl.status_code),
                count(rl.id)})
```

Or alias the group_by fragment and reference it in the select.

## Matching on `0.0` warns under `--warnings-as-errors`

```elixir
defp fmt_tps(0.0), do: "—"   # warning: pattern matching on 0.0 is
                              # equivalent to matching only on +0.0
```

**Fix** for --warnings-as-errors CI:

```elixir
defp fmt_tps(tps) when tps in [+0.0, -0.0, 0.0], do: "—"
```

or compare with `==`:

```elixir
defp fmt_tps(0.0), do: "—"
defp fmt_tps(tps) when tps == 0.0, do: "—"
```

## `cost_summary_for_X` should not assume there is at least one row

When the underlying query returns ZERO rows (no request logs match),
`Repo.one(query)` returns `nil`, not a map. Two patterns:

1. Guard before extracting:
   ```elixir
   case Repo.one(query) do
     nil -> default_summary()
     result -> to_summary(result)
   end
   ```

2. Use `aggregate_with_default` to coerce nil aggregates to 0 (e.g.
   `coalesce(sum(x), 0)` in the SELECT so the column is always present).

The first is simpler when the SELECT uses `count()` and `sum()` — both
return `0` for empty groups, so `nil` only happens if the WHERE filters
all rows out. Pick the right guard for the query shape.

## Real-time counters: increment in PubSub handler, decrement on done

A common Ecto-less in-memory pattern (ETS-backed counters, sticky routing,
rate limits) requires symmetric increment/decrement to stay consistent:

- On `start_request/1`: insert into ETS + broadcast `:started`.
- On `finish_request/1`: ETS delete + broadcast `:done`.

The matching LiveView handler that subscribes:

```elixir
def handle_info({:started, entry}, socket) do
  {:noreply, update(socket, :counter, &(&1 + 1))}
end

def handle_info({:done, id}, socket) do
  {:noreply, update(socket, :counter, &max(&1 - 1, 0))}
end
```

The `update/3` macro only fires if the assign key already exists. If you
forget to assign `:counter` on mount, the first `:started` raises
`KeyError`. Pattern: always assign the initial value in mount.
