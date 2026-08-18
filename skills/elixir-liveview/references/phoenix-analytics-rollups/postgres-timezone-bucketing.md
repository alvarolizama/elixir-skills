# Postgres Timezone-Aware Bucketing (Ecto)

Verified 2026-07-31 in MyApp's stats/dashboard rollups. Generic recipe
for bucketing an append-only log table by the USER'S local timezone while
the data is stored as UTC.

## 1. Know your column's PHYSICAL type

A schema `field :inserted_at, :utc_datetime` can hide a physical column that
is `timestamp` WITHOUT time zone (MyApp's `request_logs` is
`timestamp(0) NOT NULL`). Ecto still dumps/loads it as UTC, so comparisons
(`inserted_at >= ^utc_datetime`) work — but SQL timezone math does NOT behave
like timestamptz.

Check the migration, not just the schema:

```sql
-- \d request_logs or:
SELECT column_name, data_type FROM information_schema.columns
WHERE table_name = 'request_logs' AND column_name = 'inserted_at';
```

## 2. The SQL patterns

Column `inserted_at` = naive storing UTC hours, `tz` = IANA zone string
passed as a bind param (`^timezone`).

| Goal | SQL |
|---|---|
| Bucket by local hour | `date_trunc('hour', inserted_at AT TIME ZONE ?) AT TIME ZONE ?` ✅ |
| Local hour-of-day (0-23) | `EXTRACT(hour FROM (inserted_at AT TIME ZONE 'Etc/UTC') AT TIME ZONE ?)` ✅ |
| Naive → local timestamp | `inserted_at AT TIME ZONE 'Etc/UTC' AT TIME ZONE ?` |
| Filter from local midnight | compute in Elixir: `DateTime.new!(local_date, ~T[00:00:00], tz) |> DateTime.shift_zone!("Etc/UTC")` |

Why: `date_trunc('hour', x AT TIME ZONE tz) AT TIME ZONE tz` works because the
double conversion is self-inverse and the truncation in the middle lands in the
local scale (verified for whole and half-hour offsets). A SINGLE `AT TIME ZONE`
on a naive column makes Postgres interpret the value as local time and convert
forward → `EXTRACT(hour FROM x AT TIME ZONE tz)` yields UTC+offset. Fix: declare
the naive as UTC first (`AT TIME ZONE 'Etc/UTC'`), then convert.

## 3. Parametrized GROUP BY vs SELECT → subquery materialization

Postgres treats `GROUP BY f(x, $1)` and `SELECT f(x, $2)` as formally different
expressions → `ERROR 42803: column "r0.inserted_at" must appear in the GROUP BY
clause or be used in an aggregate function`. This fires even when both `$1`/`$2`
carry the same value.

Fix — materialize the bucket in a subquery, then aggregate the outer query on
the column:

```elixir
bucketed =
  RequestLog
  |> where([rl], rl.inserted_at >= ^from)
  |> select([rl], %{
    bucket: fragment("date_trunc('hour', ? AT TIME ZONE ?) AT TIME ZONE ?",
                     rl.inserted_at, ^timezone, ^timezone),
    id: rl.id,
    provider_cost_usd: rl.provider_cost_usd,
    prompt_tokens: rl.prompt_tokens,
    completion_tokens: rl.completion_tokens,
    latency_ms: rl.latency_ms
  })
  |> subquery()

query =
  from(b in bucketed,
    group_by: b.bucket,
    order_by: b.bucket,
    select: %{
      hour: b.bucket,
      request_count: count(b.id),
      cost_usd: fragment("COALESCE(SUM(?), 0)", b.provider_cost_usd),
      prompt_tokens: coalesce(sum(b.prompt_tokens), 0),
      completion_tokens: coalesce(sum(b.completion_tokens), 0),
      total_latency_ms: coalesce(sum(b.latency_ms), 0)
    }
  )
```

Same pattern for `EXTRACT`-based grouping (hour-of-day) and minute buckets.

## 4. Parametrize the trunc unit

`date_trunc(?, x, ...)` with the unit as a bind param (`^unit`) works fine —
Postgres accepts `date_trunc(text, ...)`. This lets `busiest_hours` and
`busiest_minutes` share ONE private function instead of duplicated bodies:

```elixir
defp busiest_buckets(team_id, unit, opts) when unit in ["hour", "minute"] do
  # subquery with: fragment("date_trunc(?, ? AT TIME ZONE ?) AT TIME ZONE ?", ^unit, ...)
end
```

## 5. Decoding the bucket column

Subquery fragments may decode as `DateTime` OR `NaiveDateTime` depending on
context. Normalize with a helper:

```elixir
defp to_utc_datetime(%DateTime{} = dt), do: dt
defp to_utc_datetime(%NaiveDateTime{} = ndt), do: DateTime.from_naive!(ndt, "Etc/UTC")
```

## 6. Calendar periods (Elixir side)

Centralize local calendar boundaries in a `Periods` module returning UTC
instants for query filters:

- `start_of_day_utc(tz)`: `DateTime.now(tz) |> DateTime.to_date() |> DateTime.new!(~T[00:00:00], tz) |> DateTime.shift_zone!("Etc/UTC")`
- `start_of_month_utc(tz)`: same with `Date.new!(year, month, 1)`.
- `period_bounds(period, tz)` → `%{from, to}` for `today/7d/30d/90d/month`
  using LOCAL calendar days (today = start of local day → now; 7d = start of
  local day − 6 days, etc.). `"today"` becomes the local calendar day, NOT a
  24h rolling window.

## 7. Deterministic timezone tests

Anchor to `Periods.start_of_day_utc(tz)` instead of wall-clock math:

- `today_start - 3600` → yesterday local (excluded from "today").
- `today_start + 3600` → today local (included) — but if `now` is before
  01:00 local, the candidate is in the future: use `min(candidate, now - 60)`.
- If today is the 1st of the month, "yesterday" falls in the PREVIOUS month —
  compute `expected_monthly` dynamically (`Date.add(today, -1).month == today.month`).
