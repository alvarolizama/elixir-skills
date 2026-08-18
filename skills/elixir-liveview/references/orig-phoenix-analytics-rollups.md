---
name: phoenix-analytics-rollups
description: "Use when building Phoenix stats dashboards over log tables."
version: 1.1.0
author: Álvaro Lizama
license: MIT
metadata:
  hermes:
    tags: [phoenix, ecto, analytics, dashboards, liveview, MyApp]
---

# Phoenix Analytics Rollups

Building analytics features (rankings, Top-N tables, usage patterns, peak
metrics) over append-only log tables in Phoenix/Elixir apps.

## Architecture pattern (proven in MyApp)

1. **Pure-query rollup module** — e.g. `MyApp.Metrics.Rollup`. No
   GenServer, no new tables. Ecto queries with Postgres fragments, then
   post-process (scoring, tiers, zero-fill) in Elixir. Durable table stays
   the single source of truth.
2. **TDD per function** — test file mirrors the module
   (`test/<app>/metrics/rollup_test.exs`), fixtures via the REAL contexts
   + log-insert helper with explicit `inserted_at`.
3. **LiveView wiring** — assign empty defaults in `mount/3`, load in the
   `load_breakdowns`-style function per `live_action`, respect period
   filters (`:from`/`:to` opts) and role scoping.
4. **Infra metrics are admin-only** — rankings, concurrency, provider
   health: gate both the loader (returns `[]`/`nil` for non-admins) and
   the template (`if @current_user.global_role == "admin"`). Consumption
   analytics (top models/teams/members/agents, hour patterns) follow the
   existing role scope.

## Member usage tiers (3-bucket classification)

Classify users/members into **alto / regular / bajo** by composite score — useful for spotting power users, dormant accounts, and abuse patterns. Verified in MyApp (`Rollup.member_usage_tiers/2`):

### Composite score 0-100

Normalize each metric to 0-100 against the max in the set, then weight:

```
score = 0.25 * total_tokens +
        0.20 * cost_usd +
        0.15 * request_count +
        0.15 * active_days +
        0.15 * peak_rpm +
        0.10 * p95_rpm
```

### Tercile thresholds

- `score >= 66` → "alto" (badge-error)
- `score >= 33` → "regular" (badge-warning)
- `score < 33` → "bajo" (badge-ghost)

### RPM stats per member

Bucket requests by minute per member, then:

- `peak_rpm` = max requests in any 1-minute bucket
- `avg_rpm` = mean of per-minute counts
- `p95_rpm` = nearest-rank 95th percentile (when <20 samples, use peak)

### Key rules

- **No new tables** — pure query module like the rest of `Rollup`. Compute on-the-fly per period filter.
- **Active days** = `COUNT(DISTINCT date_trunc('day', inserted_at))` — prevents a single burst day from inflating the score.
- **Admin-only** — gate both the loader (returns `[]` for non-admins) and the template.
- **Badge helpers**: `tier_badge_class("alto" | "regular" | "bajo")` in the LiveView, reused by `StatsLive`, `TeamsLive`, and `TeamMembersLive`.

## Live KPI strip with rolling-window breakdowns

When a logs/stats page shows live KPIs (rolling 5-min window), adding a
**breakdown card** (e.g. "Top Models") requires a new query function that
groups by the dimension + any metadata you want to display (provider key
prefix, credential name). Pattern from MyApp `requests_by_model/3`:

```elixir
def requests_by_model(filters \\ %{}, window_seconds \\ 300, limit \\ 5) do
  cutoff = DateTime.utc_now() |> DateTime.add(-window_seconds, :second) |> DateTime.truncate(:second)

  RequestLog
  |> apply_log_filters(filters)
  |> where([rl], rl.inserted_at >= ^cutoff)
  |> group_by([rl], [rl.model_requested, rl.provider_key_prefix, rl.credential_name])
  |> select([rl], %{model: rl.model_requested, count: count(rl.id), ...})
  |> order_by(desc: :count)
  |> limit(^limit)
  |> Repo.all()
end
```

**LiveView wiring:** compute in the same function that refreshes the other
KPIs (`refresh_summary/1` in MyApp), assign to socket, render as a
compact list (no table) inside a card. When merging two related KPIs
(e.g. "Conectados" + "En vuelo"), use a single card with inline
label-value pairs: `1 conectados 0 en vuelo`.

## Query recipes

- **Ranking con tiers** — aggregate per entity (requests, errors via
  `COUNT(*) FILTER (WHERE status >= 400)`, avg/p95 latency), compute
  score in Elixir: weighted reliability (absolute) + speed (relative to
  best in set). Tiers from thresholds. Min sample size → no tier, sort
  to the end. See `references/MyApp-analytics-surface.md`.
  The `score_ranking_row/3` helper accepts a `type` atom (`:provider`
  or `:model`) so the same scoring logic serves multiple entity types —
  only the output map keys differ (`provider_name` vs `model_name`).
- **Drill-down detail view** — when a summary table (e.g. members in a
  team drill-down) has clickable rows, link to a dedicated `:member`
  live_action route (`/dashboard/stats/members/:member_id`). Load the
  member with `Accounts.get_team_member!(id, :with_assoc)`, scope-check
  (`member_id in Accounts.scope_member_ids(user)` for non-admins), and
  render a per-model breakdown table using `breakdown_by_model_for_member/2`.
- **Concurrency peak from completion logs** — logs are written at
  completion, so each request spanned
  `[inserted_at - latency_ms, inserted_at]`. Sweep line over +1/-1
  events (ends before starts on tie) gives max overlap + first timestamp.
  Label it "estimado" in the UI — it's honest, not exact.
- **Hour-of-day distribution** — timezone-aware: `EXTRACT(hour FROM
  (? AT TIME ZONE 'Etc/UTC') AT TIME ZONE ?)` grouped count, zero-fill
  0..23 in Elixir. A single `AT TIME ZONE` on a naive-UTC column yields
  UTC+offset (wrong). See `references/postgres-timezone-bucketing.md`.
  For the bar chart itself (sqrt scale, Y-axis ticks, tooltips, colors),
  see `references/css-bar-chart-readability.md`.
- **Busiest buckets** — `date_trunc('hour'|'minute', inserted_at)`
  grouped, ordered by count desc, `limit`. Parametrize the unit with
  `^unit` as a bind param (works — see pitfalls update); for local-hour
  bucketing use the subquery + `AT TIME ZONE` pattern from
  `references/postgres-timezone-bucketing.md`.
- **Timeline / journey aggregation (pure-Elixir bucketing)** — when you
  need a chronological page-like timeline over a create-event log
  (`page.create`-style rows), you can group in Elixir instead of SQL
  `date_trunc`. Fetch ordered rows, `Enum.group_by` on a compound period
  tuple (`{y,m,d}` / `{y,m}` / `{y}`), sort buckets by key, and map to
  labeled buckets. This pairs with **adaptive granularity** and a
  **cumulative trajectory**. Full recipe (MyApp.Journey): see
  `references/timeline-aggregation-recipe.md`.

## UI conventions (Álvaro)

- Spanish UI, empty state per card, hints explaining what the metric is.
- Numbers: compact K/M/B in KPIs with exact value in `title` tooltip;
  thousands separators in tables; raw values in CSV.
- Follow existing card patterns (`card bg-base-100 border ...`,
  `table table-sm`, hero icons via `<.icon>`).
- Reorder big template blocks with marker-based string surgery in
  `execute_code` (read file → cut block between markers → re-insert at
  target marker) instead of giant error-prone patches.
- **One chart per card** — never stack two unrelated charts inside one
  card body. When a card has multiple visualizations with different
  dimensions (e.g. horizontal model-provider bars + vertical hour
  distribution), split into separate cards in the same grid. Each card
  adapts its height to its own content instead of fighting for space.
  Move long explanatory text into a compact inline `<span>` in the
  card header (`hidden sm:inline`) instead of a 3-line `<p>` that eats
  vertical space.

## ETS rolling-window for realtime sparklines

When a Monitor/dashboard needs a live per-minute sparkline over the last
N minutes, querying Postgres every 5s is wasteful. Pattern (proven in
MyApp's `Metrics.Window`):

1. **New ETS table** (`:named_table, :public, :set, write_concurrency: true`)
   owned by a GenServer. Keys are `{model_alias_id, minute_index}` →
   count. `minute_index` = `div(System.system_time(:second), 60)` (integer
   minute offset from Unix epoch).
2. **Caller-process writes** — `record_request/1` runs `:ets.update_counter/4`
   in the caller's process (same pattern as `Collector`). No GenServer
   bottleneck on the hot path. Hook it into the existing `Collector.record_request/1`
   — one extra `Window.record_request(attrs)` line right before the PubSub
   broadcast.
3. **Snapshot builds the window** — `snapshot/0` reads all ETS keys,
   zero-fills missing minutes, returns `model_alias_id => [counts]` (oldest
   → newest, exactly 60 entries).
4. **Backfill on boot** — `init/1` calls `Rollup.minute_series_by_model/1`
   to pre-populate from Postgres so the sparkline isn't empty after a
   restart. Wrap in `try/catch` (NOT `try/rescue`) — see pitfalls below.
5. **GenServer rotation** — every 60s, `handle_info(:sweep)` deletes keys
   older than the window. Broadcasts `:window_rotated` on PubSub so
   LiveViews refresh.
6. **Register in the metrics supervisor** — add to `Metrics.Supervisor`
   children alongside `Collector`.

### Sparkline SVG in HEEx

Build sparklines as inline SVG with a function component:

```elixir
def sparkline_points(counts) do
  max_val = Enum.max(counts, fn -> 1 end)
  step = 120 / 60  # width / bucket_count

  counts
  |> Enum.with_index()
  |> Enum.map(fn {count, i} ->
    x = Float.round(i * step, 2)
    y = Float.round(30 - count / max_val * 30, 2)
    "#{x},#{y}"
  end)
  |> Enum.join(" ")
end

def sparkline_area_path(counts) do
  "M0,30 L#{sparkline_points(counts)} L120,30 Z"
end
```

In the template: `<svg viewBox="0 0 120 30">` with a `<path>` (fill) and
`<polyline>` (stroke). Both classes use daisyUI semantic colors
(`fill-primary/10`, `stroke-primary`).

### Trading-terminal LiveView pattern

Watchlist of "tickets" (one per model alias) with:
- **Indices strip** at top — RPS, in-flight, error rate, cost, total.
  Cards with `format_number` + `Float.round` for percentages.
- **Ticket rows** — model name, sparkline, RPM, volume, total, in-flight
  badge. Clickable (`phx-click="toggle-expand"`) for drill-down.
- **Drill-down** per model — `Rollup.breakdown_by_credential/2` shows
  credential name, provider, p95 latency, error rate, cost, status dot.
  Expandable inline with `@expanded_model` assign.

## Dual-line comparison SVG chart (real vs estimated)

When a page needs to compare two cost series over time (e.g. real spend
vs a calculated estimate with custom pricing parameters), use a
full-width inline SVG with two overlaid polylines — not a compact
sparkline. Proven in MyApp's CalculatorLive (`/dashboard/calculator`).

### Chart structure

- **ViewBox** `0 0 800 220` — wider than sparklines, scales with container.
- **Y-axis** — 5 grid lines + labels from `0` to `max_val * 1.1` (10% head
  room). Format ticks with `:erlang.float_to_binary/2` (decimals: 1 for
  ≥$1, decimals: 4 for sub-dollar values).
- **Real cost** — solid `<polyline>` (`stroke-success`, width 2) + area
  fill (`fill-success/10`) built as an `M...L...Z` path.
- **Estimated cost** — dashed `<polyline>` (`stroke-primary`, width 2,
  `stroke-dasharray="4,2"`) — no fill, visually distinct from real.
- **X-axis labels** — 6-7 evenly spaced timestamps (filter by
  `rem(i, step) == 0`), formatted with `Calendar.strftime/2`.
- **Legend** — inline flex above the SVG: colored square + label.

### Elixir chart builder

Build points in the LiveView (not the template):

```elixir
def chart_points(chart_data) do
  # pad_left=70, pad_right=20, pad_top=10, pad_bottom=35
  # plot_w = width - pad_left - pad_right; plot_h = height - pad_top - pad_bottom
  # step_x = plot_w / (count - 1) when count > 1
  # max_val = Enum.max of max(real, estimated) per row, * 1.1, min 0.01
  # For each row: x = pad_left + i * step_x
  #   real_y = pad_top + plot_h - (real / max_val * plot_h)
  #   est_y  = pad_top + plot_h - (est  / max_val * plot_h)
  # Returns %{real_points: "x,y x,y ...", est_points: "...",
  #   real_area: "M... L... Z", y_ticks: [...], x_labels: [...]}
end
```

### `for={%{}}` form — Phoenix.Component.form/1 requires a `for` attr

When a LiveView form recalculates on every input change (no Ecto
changeset) — e.g. a calculator with `phx-change="calculate"` — pass
`for={%{}}` (an empty map) to satisfy the `form/1` component's required
`:for` attribute. Omitting it compiles but emits a **runtime warning**
rendered into the page:

```heex
<.form for={%{}} id="calculator-form" phx-change="calculate" phx-submit="calculate">
  <select name="model_id" ...>
  <input name="cost_input" ...>
</.form>
```

`phx-change` fires on every input mutation (not just submit), so the
event handler receives all field values as `params` and can recompute
the chart data reactively — no submit button needed.

Full recipe (LiveView, SVG template, hourly rollup query for per-model
token breakdown + cost): `references/dual-line-svg-chart.md`.

## Drill-down daily sparklines (stacked bar charts)

When a drill-down view (model detail, team detail, service detail) needs
to show how usage evolved day-by-day across a dimension (provider for
models, model for teams/services), use a stacked-bar sparkline card
instead of a raw table. Proven in MyApp's StatsLive drill-downs.

See `references/drilldown-daily-sparklines.md` for the full recipe:
- Rollup daily-series queries (`date_trunc('day', ...)`, timezone-aware)
- LiveView wiring (`drilldown_series` + `drilldown_series_labels` assigns)
- Pivot helpers (`pivot_daily_series/1`, `sparkline_bar_height/2` with sqrt scale)
- HEEx template with CSS-only tooltips and side legend
- Testing strategy (async wait + pure helper unit tests)

## ETS TTL cache for dashboard query bundles

When a LiveView subscribes to a PubSub topic that fires on every domain
event (e.g. `metrics:updated` on every proxied request), even with a
debounce, N connected dashboards → N Postgres query sets per debounce
window. An ETS TTL cache coalesces these: the first miss computes the
full query bundle, subsequent hits within TTL skip all Postgres queries.

**Distinct from the rolling-window ETS** (`Metrics.Window`): the rolling
window keeps incremental per-minute counts for sparklines. This cache
stores **the full result bundle of a multi-query Postgres load** with a
TTL, keyed by `{user_id, period, timezone}`.

Key design points:
- **TTL expiry, not PubSub invalidation** — the broadcast still triggers
  the LiveView reload cycle, but the reload reads from cache first. With
  5s TTL and 2s debounce, Postgres is hit every ~5-6s instead of every
  ~2s. Multiple dashboards for the same user share one entry.
- **`write_concurrency: true`** (not `read_concurrency`) — writes happen
  on every miss, reads on every hit; both are concurrent.
- **GenServer only owns the table** — `fetch_or_compute/2` runs entirely
  in the caller's process (same pattern as `Collector` and `Window`).
- **The refactor: compute bundle + apply bundle** — separate the query
  logic (pure, no socket, returns a plain map) from the assign logic
  (socket only). The query result is cacheable; the assign is not.
  **Critical:** any `load_*` that populates assigns read by the compute
  function (e.g. `load_model_catalog` → `assigns[:model_catalog]`) must
  run in `mount/3` BEFORE `load_metrics`, because a cache hit skips the
  compute function entirely.

Full recipe (module structure, the before/after refactor, registration,
testing including the `monotonic_time` TTL pitfall):
`references/ets-ttl-query-cache.md`.

## Composite indexes on partitioned tables

When an append-only log table is **native Postgres RANGE-partitioned**
(e.g. `request_logs` partitioned by `inserted_at` daily), indexes must
be created on the parent table with raw SQL — Postgres propagates them
to every existing and future partition automatically. Use
`@disable_ddl_transaction true` + `@disable_migration_lock true` in the
migration module because `CREATE INDEX CONCURRENTLY`-style operations
on partitioned tables cannot run inside a transaction.

**Audit pattern:** grep all Ecto queries that filter by a column +
`inserted_at` range. If the column has no composite index including
`inserted_at`, every dashboard query does a full partition scan. The
most common missing index is `(foreign_key_id, inserted_at)` — the FK
alone has an index (from the FK constraint), but the composite with
time is what the `WHERE fk IN ... AND inserted_at >= ...` pattern needs.

## Pitfalls — READ BEFORE WRITING ECTO AGGREGATES

`references/ecto-postgres-aggregation-pitfalls.md` has the full list with
code. Top hits:

- **Ecto binding positions in multi-join queries** — when joining 5+ tables,
  binding positions are cumulative. Using `[_, mp]` when `mp` is at position
  5 (not 2) causes cryptic `column t1.credential_id does not exist` errors.
  After 3+ joins, always use explicit binding names or count positions
  carefully. Named bindings (`[rl, tm, t, u, mp, c]`) are safer than `_` skips.
  See `references/MyApp-analytics-surface.md` for the full pattern.
- `fragment(^dynamic_string)` is FORBIDDEN (SQL-injection guard). A
  parameterized `date_trunc(?, ...)` unit via `^unit` bind param DOES
  work (verified 2026-07-31: busiest_hours/minutes share one clause) —
  do NOT duplicate the query body per unit anymore. The real GROUP BY
  trap is **parametrized expressions**: `GROUP BY date_trunc(... AT TIME
  ZONE $1)` + `SELECT date_trunc(... AT TIME ZONE $2)` fail with
  `ERROR 42803 (column must appear in GROUP BY)` because the expressions
  are formally different. Fix: materialize the bucket in a `subquery()`,
  then `group_by`/`select`/`order_by` the outer query on that column.
- **Naive `timestamp` columns** (schema says `:utc_datetime` but the
  physical column has no time zone — e.g. MyApp's `request_logs`)
  need `AT TIME ZONE 'Etc/UTC'` BEFORE converting to the target zone.
  Full recipes: `references/postgres-timezone-bucketing.md`.
- Postgres `AVG`/`percentile_cont` return **float, not Decimal** —
  `Decimal.to_float/1` crashes. Normalize with a helper.
- Time-bucket tests must truncate `now` (to hour/day) — `Map.put(:minute, n)`
  on `now` makes tests flaky depending on when they run.
- `mix precommit` reformats files AFTER your commit — expect a follow-up
  "style: mix format" commit; run precommit again to confirm green.
- **`System.system_time(:minute)` does NOT exist** — Elixir time units are
  `:second`, `:millisecond`, `:microsecond`, `:nanosecond` (or a positive
  integer). `:minute` and `:hour` are NOT valid. Use
  `div(System.system_time(:second), 60)` for an integer minute-index.
  This bit us in three places (`record_request`, `snapshot`, `rotate`) —
  check ALL call sites when you use a custom time unit.
- **`Float.round/2` crashes on integers** — `Float.round(0, 1)` (where `0`
  is an integer, not `0.0`) raises `FunctionClauseError`. In HEEx templates,
  `@assign || 0` defaults to an **integer** 0, which then gets passed to
  `Float.round/2` and crashes the render. Always use `|| 0.0` as the default
  when the value feeds into `Float.round/2`.
- **`try/rescue` does NOT catch `:noproc` EXIT signals** — when a GenServer
  calls `Repo` in `init/1` during tests (sandbox Ecto), the caller may
  receive a `{:noproc, ...}` EXIT, not an exception. `try/rescue` won't
  catch it — the GenServer dies and the linked LiveView channel crashes
  with `EXIT from #PID`. Use `try/catch` (`catch _, _ -> :ok`) to trap
  both exceptions AND exits. Critical for any GenServer that touches the
  Repo in `init/1` and runs under the Ecto sandbox.

## Adding a new aggregated metric (KPI column + summary field)

When telemetry grows a new per-row field (e.g. `cache_read_tokens`,
`cache_creation_tokens`) and you must surface it in BOTH the logs table
AND the dashboard summary, the change touches 4 layers — keep them in
lockstep or you get KeyErrors at runtime.

### The 4 layers (all must be updated)

1. **Schema** — field already added via migration. Verify it is in the
   `cast` call (Ecto silently drops write attempts otherwise) and has
   `default: 0` so old rows behave.
2. **Logs context — every `cost_summary/...` entry point** that ships to
   LiveView dashboards. In MyApp there are three:
   - `Logs.cost_summary_for_team/2` — `SELECT` block + returned map
   - `Logs.cost_summary_for_members/2` — both the `[]` **fallback map**
     AND the normal path (the empty-list short-circuit returns a
     separate map; forgetting it = `KeyError` on `@metrics`)
   - `Logs.cost_summary/1` — the filtered, period-aware variant
   Use `coalesce(sum(rl.<field>), 0)` in each SELECT and surface the
   result in the returned map. The shape MUST be identical across all
   three or downstream call sites break.
3. **Dashboard LiveView** — extend the metrics map in
   `load_summary_metrics/3` (or `empty_metrics/0`) with the new key.
   Same shape requirement — `empty_metrics` mirrors the real one.
4. **Logs LiveView table** — add a `<th>` after the related column
   (Input/Output) and a `<td>` calling a small `format_X_tokens/2`
   helper. Update the empty-state row's `colspan` to total column count
   (one bump per column added). If the table uses grouped headers
   (`<th colspan="N">` bands), bump the band's colspan too.

### "— when both zero" KPI column helper

Narrow metrics that are zero for most rows (cache hits, errors, retrieval
docs) deserve a "—" cell until any row actually has a non-zero value —
otherwise the table fills with `0 / 0` noise. Pattern:

```elixir
defp format_cache_tokens(read, creation)
     when (read in [nil, 0]) and (creation in [nil, 0]),
     do: "—"

defp format_cache_tokens(read, creation) do
  "#{format_number(read || 0)} / #{format_number(creation || 0)}"
end
```

Same shape is reused for the dashboard card: a `format_cache_value/2`
helper that returns `"—"` when both are 0, otherwise `format_compact/1`
of the sum. Keep the visual style identical to the adjacent in/out
metrics (label `text-xs text-base-content/50`, value
`text-lg font-bold`, separator `text-base-content/30`).

### Verification recipe after the 4-layer change

```bash
mix compile --warnings-as-errors --force
mix test test/<app>/<context>_test.exs                       # context tests
mix test test/<app>_web/live/<dashboard>_live_test.exs       # dashboard
mix test test/<app>_web/live/<logs>_live_test.exs            # logs table
```

A KeyError at runtime means one of the three summary functions or
`empty_metrics/0` was missed. Run with `mix test` first because the
dashboard LiveView test mounts the empty metrics map; if the field is
missing from `empty_metrics`, the test crashes on `Map.get/2` access
even when no logs exist.

## Error-path logs must carry the same dimension keys as happy-path logs

When a request fails BEFORE the pipeline resolves its foreign keys (gate
errors: rate limit, concurrency exceeded, budget), the cheap thing is to log
only the human-readable name (`model_requested` string) and leave the FKs
(`model_alias_id`, `model_provider_id`) nil. Don't. Every drill-down and
`cost_summary` variant filters by the FK, so those rows become invisible in
exactly the bursts an admin opens the page to inspect ("Sin datos para este
periodo" while 429s are flooding). Fix: resolve the FK on the cold error
path (e.g. one indexed lookup by the globally-unique alias name) and persist
it. The hot/success path keeps its zero-extra-query discipline; the error
path already failed, so one lookup costs nothing.

Same principle for observability fields: if the upstream gives you a real
error message, persist it (scrubbed) next to the classified reason — a
generic `"provider_error_500"` label forces ops to SSH into the box to learn
"max connections reached".

## Verification

```bash
mix test test/<app>/metrics/rollup_test.exs
mix test test/<app>_web/live/<page>_live_test.exs
mix compile --warnings-as-errors
mix precommit   # then commit any format changes it makes
```

## References

- `references/ecto-postgres-aggregation-pitfalls.md` — Ecto/Postgres
  fragment rules, type surprises, sort comparators, test determinism.
- `references/timeline-aggregation-recipe.md` — pure-Elixir timeline
  bucketing over a create-event log: adaptive granularity, cumulative
  trajectory/sparkline, golden-angle HSL per-category colors, idempotent
  empty payload, utc_datetime dual-dispatch.
- `references/postgres-timezone-bucketing.md` — timezone-aware bucketing:
  naive `timestamp` columns, `AT TIME ZONE` patterns, subquery
  materialization for parametrized GROUP BY, calendar periods, tests.
- `references/MyApp-analytics-surface.md` — what already exists in
  MyApp's Stats page (modules, assigns, formulas, section order) so
  you extend instead of duplicating.
- `references/MyApp-stats-services-view.md` — services drill-down view
  (`/dashboard/stats/services`), rollup function, assigns, and template
  structure for the per-service analytics.
- `references/MyApp-logs-liveview-surface.md` — Logs LiveView page
  (`/dashboard/logs`): KPI strip layout, assigns, rolling-window queries,
  and the merged "Actividad" + "Top Modelos" cards.
- `references/css-bar-chart-readability.md` — hand-rolled CSS bar charts
  that stay readable: sqrt scale + height floor for skewed distributions,
  nice-number Y-axis ticks positioned on the same transform, pure-CSS
  `group-hover` tooltips, solid vs `/40` daisyUI colors, X-label density
  hierarchy.
- `references/ets-rolling-window-sparklines.md` — ETS rolling-window
  pattern for realtime per-minute sparklines: GenServer + public table,
  caller-process `update_counter`, Postgres backfill on boot, `try/catch`
  for sandbox, trading-terminal LiveView layout (indices strip,
  watchlist, drill-down), breakdown_by_credential query.
- `references/ets-ttl-query-cache.md` — ETS TTL cache for dashboard query
  bundles: coalescing Postgres queries across multiple connected
  LiveViews sharing the same PubSub broadcast. The compute-bundle +
  apply-bundle refactor, `monotonic_time` TTL testing pitfall, and when
  to use `write_concurrency` vs `read_concurrency`.
- `references/drilldown-daily-sparklines.md` — stacked-bar daily sparkline
  charts for drill-down views (model → provider, team → model, service →
  model). Rollup daily-series queries, LiveView wiring, pivot helpers,
  HEEx template with tooltips, and testing.
- `references/dual-line-svg-chart.md` — dual-line SVG comparison chart
  (solid + dashed polylines) for real-vs-estimated cost over time.
  Includes the estimated-cost formula, `for={%{}}` reactive form pattern,
  chart builder function, summary cards, and verification recipe.
