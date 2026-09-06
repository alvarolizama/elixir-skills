# Analytics Rollups & Dashboards

**Symptom:** building (or fixing) a stats dashboard — KPI cards,
rankings, sparklines, charts, drill-downs — where queries hit Postgres,
data is post-processed in Elixir, and the LiveView must stay responsive
under repeated reloads.

## Architecture pattern

1. **Pure-query rollup module** (e.g. `MyApp.Metrics.Rollup`) — no
   GenServer, no new tables. Ecto queries + Postgres fragments,
   post-process in Elixir.
2. **TDD per function** — test file mirrors the module; fixtures via
   real contexts + explicit `inserted_at`.
3. **LiveView wiring** — assign empty defaults in `mount/3`, load per
   `live_action`, respect period filters.
4. **Admin-only gate** — both the loader (returns `[]` for non-admins)
   and the template (`:if={@admin}`).

## Query recipes

- **Ranking with tiers** — aggregate per entity (requests, errors via
  `COUNT(*) FILTER (WHERE status >= 400)`, avg/p95 latency), score in
  Elixir, tiers from thresholds.
- **Composite score** — normalize each metric to 0–100 against the max
  in the set, then weight: `0.25 * tokens + 0.20 * cost + 0.15 *
  requests + 0.15 * active_days + ...`. Terciles: `≥66` "high",
  `≥33` "regular", `<33` "low".
- **Hour-of-day distribution** —
  `EXTRACT(hour FROM (? AT TIME ZONE 'Etc/UTC') AT TIME ZONE ?)` +
  zero-fill 0..23 in Elixir.
- **Busiest buckets** — `date_trunc('hour', inserted_at)` grouped +
  ordered by count desc.

### Postgres timezone bucketing

1. Know the column's PHYSICAL type (naive UTC vs `timestamptz`) — the
   conversion differs.
2. Naive UTC columns need `AT TIME ZONE 'Etc/UTC'` BEFORE converting to
   the target zone.
3. Parametrized `GROUP BY` (dynamic `date_trunc` unit / timezone arg)
   fails — materialize the computed bucket in a subquery, then group
   the outer query.
4. `date_trunc` unit can be parametrized via a fragment with an
   explicit cast (`type(^unit, :string)`), but the bucket expression
   must stay constant per query.
5. Decode the bucket column to `DateTime`/`Date` explicitly; don't rely
   on Ecto's type inference for `date_trunc` aggregates.
6. Deterministic timezone tests: truncate to the hour FIRST, then
   offset — otherwise `Map.put(:minute, 10)` at `hh:05` lands in the
   FUTURE and falls outside "last N hours" windows.

### Aggregation pitfalls

- **Dynamic fragment strings are forbidden** —
  `fragment("...")` with interpolated strings raises
  `(Ecto.Query.CompileError) fragment(...) does not allow strings to be
  interpolated as the first argument via the ^ operator`. Use
  `type(^value, :string)` casts instead.
- `AVG` / `percentile_cont` return **float, not Decimal** — don't
  pattern-match `%Decimal{}`.
- Sorting `{DateTime, _}` tuples needs a custom comparator.
- `try/rescue` misses `:noproc` (GenServer not up) — use
  `try/catch` (`catch _, _ -> :ok`).

## ETS rolling window (realtime sparklines)

- ETS table (`:public, :set, write_concurrency: true`) owned by a
  GenServer; minute index = integer (not `:minute`).
- **Caller-process writes** (`update_counter`) — no GenServer bottleneck
  on the hot path.
- Backfill from Postgres on boot — with `try/catch`, NOT `try/rescue`.
- Rotation (periodic sweep) deletes old keys every 60s.
- Sparkline as inline SVG with a `sparkline_points/1` helper; snapshot
  with zero-fill for missing minutes.

## ETS TTL query cache (dashboard query bundles)

Coalesce Postgres queries across N connected LiveViews:

- **TTL expiry (e.g. 5s), NOT PubSub invalidation** — simpler and avoids
  cache-thrash on high-frequency events.
- `write_concurrency: true` (writes dominate on cache fill), NOT
  `read_concurrency: true`.
- GenServer owns only the table; reads are caller-process.
- Cache key: `{user_id, period, timezone}`.
- Refactor into **compute bundle** (pure: no socket, returns a map; runs
  only on cache miss) + **apply bundle** (cheap: no DB, applies the map
  to socket assigns) — keeps the dashboard assign path DB-free.

## Filter propagation & totals

- KPI cards must respect the drill-down filter — a filter applied only
  to the breakdown table produces KPIs that contradict the rows.
- Sortable columns: re-sort the LOADED lists in the event handler —
  never operate on `socket.assigns` from mount (empty) state; use the
  socket returned by the load branch.

## Chart readability (CSS bar charts)

- Linear scale hides small bars — sqrt scale + minimum height floor.
- Y axis with nice-number ticks on the SAME scale as the bars.
- Per-bar tooltip via pure CSS `group-hover`.
- Solid colors, not washed-out `/40` variants.
- Denser X labels with visual hierarchy.

## Dual-line / stacked SVG charts

- Rollup query returns both series; the chart builder is a pure function
  of the series maps.
- Beware normalization double-counting: if the normalizer already
  subtracts cache tokens from the prompt-token field, then
  `total_input = input_tokens + cache_tokens` — don't add cache
  again.
- "$0.00 cost with requests > 0" ⇒ the raw token fields aren't reaching
  the estimator — find where the totals dropped a dimension.
- Legend hierarchy: top-level series, then provider drill-down, with
  hover context carrying exact values.

## UI conventions

- One chart per card; long text in a compact `<span>` in the card
  header.
- Numbers: compact K/M/B in KPIs with the exact value in a `title`
  tooltip.
- `Float.round/2` with an integer precision crashes — use `2.0` or
  `|| 0.0` defaults.
- `System.system_time(:minute)` does NOT exist — use
  `div(System.system_time(:second), 60)`.