# Ecto Analytics Query Pitfalls (Postgres rollups)

Pitfalls hit while building rollup/analytics queries (`request_logs`-style
aggregate dashboards: rankings, hour distributions, peak buckets, concurrency
estimates). Each one cost a RED test cycle.

## 1. `fragment(^dynamic_string, ...)` is a compile error — duplicate the body

Ecto forbids interpolating the fragment string itself:

```text
** (Ecto.Query.CompileError) to prevent SQL injection attacks, fragment(...)
does not allow strings to be interpolated as the first argument via the `^`
operator, got: `^trunc_fragment`
```

**Fix:** when the only variation is a SQL keyword (e.g. `date_trunc` unit),
write one function clause per variant with the literal fragment — small
duplication is the intended escape hatch:

```elixir
defp busiest_buckets(team_id, "hour", opts) do
  RequestLog
  |> group_by([rl], fragment("date_trunc('hour', ?)", rl.inserted_at))
  |> select([rl], %{bucket: fragment("date_trunc('hour', ?)", rl.inserted_at), ...})
  # ...
end

defp busiest_buckets(team_id, "minute", opts) do
  # same body with 'minute' literals
end
```

## 2. `date_trunc($1, col)` with a parameterized unit → grouping_error 42803

Even before the Ecto compile issue: passing the trunc unit as a *parameter*
makes Postgres reject the query:

```text
** (Postgrex.Error) ERROR 42803 (grouping_error) column "r0.inserted_at" must
appear in the GROUP BY clause or be used in an aggregate function
```

Postgres cannot prove `$1 == $3` between the SELECT and GROUP BY copies of
`date_trunc($1, inserted_at)`, so it treats them as different expressions.
The unit must be a **literal inside the fragment string** (see §1).

## 3. `AVG` / `percentile_cont` return float OR Decimal depending on column type

`Decimal.to_float/1` crashes at runtime:

```text
** (FunctionClauseError) no function clause matching in Decimal.to_float/1
    The following arguments were given to Decimal.to_float/1: 400.0
```

Postgres `AVG(int)` → `numeric` (Ecto: `Decimal`), but
`percentile_cont(...) WITHIN GROUP (...)` → `double precision` (Ecto: plain
float), and integer columns can come back as integers. Normalize at the
boundary:

```elixir
defp to_float!(%Decimal{} = d), do: Decimal.to_float(d)
defp to_float!(n) when is_integer(n), do: n / 1
defp to_float!(n) when is_float(n), do: n
```

Never assume one type from aggregate fragments — defensively convert.

## 4. `Repo.query!` with a `binary_id` UUID param needs `Ecto.UUID.dump!/1`

Raw SQL in tests (e.g. inserting a row that bypasses schema defaults):

```text
** (DBConnection.EncodeError) Postgrex expected a binary of 16 bytes, got
"445acd54-..."
```

Casting in SQL (`$1::uuid`) does NOT help — Postgrex infers the type from the
column and demands the 16-byte binary at encode time:

```elixir
Repo.query!("INSERT INTO t (ref_id, ...) VALUES ($1, ...)",
  [Ecto.UUID.dump!(struct.id), ...])
```

Related: check the actual DB constraints before writing the fixture. A column
with `NOT NULL DEFAULT 'unknown'` (e.g. `agent_type`) makes "row with NULL"
an *impossible* test scenario — the insert dies with `23502
not_null_violation`. Test the limit/ordering behavior instead of an
unreachable state.

## 5. Time-derived test fixtures must be truncated, not field-patched

A test that builds "one hour ago at minute :10" from the current time:

```elixir
busy = DateTime.add(now, -3600, :second) |> Map.put(:minute, 10)
```

passes or fails depending on **which minute the suite runs** (if `now.minute
< 10`, the patched timestamp lands in a different hour bucket than intended —
two fixtures collapse into one bucket and counts double up). This surfaces as
"precommit failed but the file passed 5 minutes ago".

**Fix:** truncate to the bucket boundary first, then offset:

```elixir
hour_now = DateTime.utc_now() |> DateTime.truncate(:second)
           |> Map.put(:minute, 0) |> Map.put(:second, 0)
busy  = DateTime.add(hour_now, -3600, :second) |> DateTime.add(600, :second)
quiet = DateTime.add(hour_now, -7200, :second) |> DateTime.add(600, :second)
```

Any fixture whose assertion depends on bucket boundaries (hour/day/week
truncation) must anchor to a truncated base, never to raw `utc_now()`.

## 6. Estimating peak concurrency from request logs (sweep line)

When the system only persists completion events (`inserted_at` + `latency_ms`),
peak in-flight concurrency is recoverable without new instrumentation:

1. Each request's flight interval is `[inserted_at - latency_ms, inserted_at]`
   (the log row is written at completion). `nil` latency → treat as 0.
2. Emit two events per row: `(start, +1)`, `(end, -1)`.
3. Sort by timestamp; **on ties, ends (-1) before starts (+1)** — a request
   ending exactly when another starts is not concurrent.
4. Reduce tracking the running max and the first timestamp that reached it.

Caveats to document in the UI: it is an *estimate* (assumes log time ≈
completion time), and it loads the period's `(inserted_at, latency_ms)` pairs
into memory — dashboard-scale only, never hot path. Live in-flight counters
(ETS) tell you *now*; only the sweep tells you *history*.

Sorting gotcha: `Enum.sort_by(events, & &1, DateTime)` does NOT work on
`{DateTime, delta}` tuples (DateTime.compare/2 on tuples fails). Use
`Enum.sort/2` with an explicit comparator on `DateTime.compare/3` and the
delta tie-break.

## 7. `fragment()` with `binary_id` params fails in Ecto queries (not just raw SQL)

When building scope/filter queries with nullable UUID columns, using
`fragment("? IS NULL OR ? = ?", col, col, ^param)` can fail with:

```text
** (DBConnection.EncodeError) Postgrex expected a binary of 16 bytes, got
\"9a70073c-d037-413b-8bd9-32ed08cb4a85\"
```

This happens even when the column is `uuid` and the parameter *looks* like a
UUID. The root cause: test schemas that define `@primary_key {:id, :binary_id,
autogenerate: true}` can produce **string** UUIDs (36-char `"xxxxxxxx-xxxx-..."`)
rather than raw 16-byte binaries. Postgrex infers the column type as `uuid` and
demands the binary encoding — the string encoding is rejected.

The `fragment()` function passes parameters to Postgrex with less type
negotiation than Ecto's built-in operators.

**Fix:** replace the `fragment()` with Ecto's native `is_nil/1` and `==`:

```elixir
# BROKEN — fragment with string UUID param
from(mp in ModelProvider,
  where: fragment("? IS NULL OR ? = ?", mp.exclusive_id, mp.exclusive_id, ^member_id)
)

# FIXED — native Ecto operators handle type coercion
from(mp in ModelProvider,
  where: is_nil(mp.exclusive_id) or mp.exclusive_id == ^member_id
)
```

Ecto's `==` operator performs proper type coercion for `binary_id` columns — it
accepts both string UUIDs and raw binaries. `is_nil/1` generates `IS NULL`
without needing a parameter at all.

**Rule:** when querying nullable UUID/FK columns with conditions like
`col IS NULL OR col = ^param`, always use `is_nil(col) or col == ^param`
instead of `fragment()`. Reserve `fragment()` for SQL functions that have no
Ecto equivalent (`date_trunc`, `EXTRACT`, window functions, etc.).
