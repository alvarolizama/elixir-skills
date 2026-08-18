# Ecto/Postgres Aggregation Pitfalls

Hard-won constraints when writing aggregate queries with Ecto fragments
against Postgres (hit in MyApp's `Metrics.Rollup`, July 2026).

## 1. Dynamic fragment strings are forbidden

```elixir
# COMPILE ERROR — "(Ecto.Query.CompileError) fragment(...) does not allow
# strings to be interpolated as the first argument via the `^` operator"
unit = "hour"
fragment(^"date_trunc('#{unit}', ?)", rl.inserted_at)
```

Fix: write the fragment with a literal string. If you need the same query
for two units (`hour` / `minute`), duplicate the query body — a small,
honest duplication:

```elixir
defp busiest_buckets(team_id, "hour", opts) do
  # ... group_by([rl], fragment("date_trunc('hour', ?)", rl.inserted_at))
end

defp busiest_buckets(team_id, "minute", opts) do
  # ... group_by([rl], fragment("date_trunc('minute', ?)", rl.inserted_at))
end
```

## 2. Parameterized date_trunc unit breaks GROUP BY

```sql
-- Postgrex.Error 42803 grouping_error:
-- column "r0.inserted_at" must appear in the GROUP BY clause
SELECT date_trunc($1, inserted_at), count(id) ... GROUP BY date_trunc($2, inserted_at)
```

Postgres can't prove `$1 == $2`, so the SELECT expression doesn't match
the GROUP BY expression. Same fix: literal unit inside the fragment.

## 3. AVG / percentile_cont return float, NOT Decimal

`Decimal.to_float/1` crashes with FunctionClauseError on a plain float.
Aggregate columns come back with mixed types depending on the source
column — normalize:

```elixir
defp to_float!(%Decimal{} = d), do: Decimal.to_float(d)
defp to_float!(n) when is_integer(n), do: n / 1
defp to_float!(n) when is_float(n), do: n
```

Useful aggregate fragments that work well:

```elixir
error_count: fragment("COUNT(*) FILTER (WHERE ? >= 400)", rl.status_code)
avg_latency_ms: fragment("AVG(?)", rl.latency_ms)
p95_latency_ms:
  fragment("percentile_cont(0.95) WITHIN GROUP (ORDER BY ?)", rl.latency_ms)
hour: fragment("CAST(EXTRACT(hour FROM ?) AS integer)", rl.inserted_at)
```

## 4. Sorting {DateTime, _} tuples needs a custom comparator

`Enum.sort_by(list, fn {ts, d} -> {ts, d} end, DateTime)` raises —
`DateTime.compare/2` can't compare tuples. For sweep-line event lists
(ends before starts on tie):

```elixir
Enum.sort(events, fn {ts_a, delta_a}, {ts_b, delta_b} ->
  case DateTime.compare(ts_a, ts_b) do
    :lt -> true
    :gt -> false
    :eq -> delta_a <= delta_b   # -1 (end) before +1 (start)
  end
end)
```

## 5. Deterministic time-bucket tests

```elixir
# FLAKY — when the test runs at hh:05, Map.put(:minute, 10) lands in the
# FUTURE and falls outside a "last N hours" window:
now = DateTime.utc_now()
busy = DateTime.add(now, -3600, :second) |> Map.put(:minute, 10)

# DETERMINISTIC — truncate to the hour first, then offset:
hour_now = DateTime.utc_now() |> DateTime.truncate(:second)
           |> Map.put(:minute, 0) |> Map.put(:second, 0)
busy = DateTime.add(hour_now, -3600, :second) |> DateTime.add(600, :second)
```

Rule: any test asserting on `date_trunc` buckets or hour-of-day
distributions must build its timestamps from a truncated base, never by
mutating fields of `now`.

## 6. mix precommit reformats after your commit

Repos with a `precommit` alias run `mix format` as part of it. Formatting
may change files you already committed (heex line wraps, `def f(attrs \\ %{})`
normalization). Expect a trailing "style: mix format" commit and re-run
`mix precommit` to confirm the suite is still green.
