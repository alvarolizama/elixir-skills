# MyApp — Stats Page Analytics Surface (as of 2026-07-30)

What already exists so future sessions extend instead of duplicating.
Repo: `/Users/alvaro/Workspace/Repos/MyApp`.

## Modules

- `lib/MyApp/metrics/rollup.ex` — pure-query rollups over
  `request_logs`. Public API:
  - `hourly_series/2`, `top_consumers/2`, `agent_breakdown/1` (map for KPIs)
  - `breakdown_by_model/2`, `breakdown_by_member/2`, `breakdown_by_team/1`
  - `breakdown_by_provider_for_model/2`, `breakdown_by_member_for_model/2`,
    `breakdown_by_team_for_model/2`
  - `breakdown_by_model_for_member/2` — models used by a specific member
  - `provider_ranking/2` — failures + latency ranking with tiers
  - `model_ranking/2` — same scoring but grouped by ModelAlias
  - `user_ranking/2` — per-user consumption ranking with per-type token breakdown
  - `usage_by_hour_of_day/2` — 24 rows (0..23 UTC), zero-filled
  - `busiest_hours/2`, `busiest_minutes/2` — top-N buckets (`:limit` opt)
  - `peak_concurrency/2` — sweep-line estimate `%{max_concurrent, at}`
  - `breakdown_by_agent/2` — top agents by real cost (ordered list)
- `lib/my_app_web/live/stats_live.ex` + `.html.heex` — Stats dashboard.
- Tests: `test/MyApp/metrics/rollup_test.exs` (fixtures: real contexts
  + `log_request/3` helper with explicit `inserted_at`),
  `test/my_app_web/live/stats_live_test.exs`.

## user_ranking/2 — enriched per-user ranking (added 2026-07-30)

**Purpose:** help admins decide which users get personal API keys and which
models they use most. Shows per-user: gasto, tokens in/out, desglose por
billing_mode (pay_per_token vs included), y modelo más usado.

**Implementation pattern:** two-phase query:
1. **Base query** — join RequestLog → TeamMember → Team → User →
   ModelProvider → Credential. Group by user, order by cost desc, limit.
   Returns: team_member_id, team_name, user_email, request_count, cost_usd,
   prompt_tokens, completion_tokens.
2. **Enrichment queries** — use the member_ids from step 1 to run:
   - `token_breakdown_by_type/3` — groups by (member_id, billing_mode),
     returns `%{in: %{type => tokens}, out: %{type => tokens}, requests: %{type => count}}`
   - `top_model_per_member/3` — groups by (member_id, model_name),
     finds max_by request_count, computes % of total.

**Key design decisions:**
- Two-phase avoids a single query with GROUP BY ROLLUP or window functions
  that would be harder to maintain
- Enrichment queries use the member_ids list from step 1 (not a subquery)
  to keep each query simple and testable
- `billing_mode` comes from `model_providers` (the join through
  ModelProvider → Credential), NOT from the credential itself
- Template renders per-type cells with conditional content: if req > 0,
  show tokens + req count; otherwise show "—"

**Template location:** `stats_live.html.heex`, inside the admin-only block
after `#model-ranking`. Uses `format_compact/1` for token counts (K/M
notation) and `format_number/1` for request counts.

## provider_ranking scoring formula

- Failure = `status_code >= 400` (repo convention, same as Alerts).
- `reliability = (1 - error_rate) * 100` (absolute).
- `speed = min_avg_latency / provider_avg_latency * 100` (relative to the
  fastest provider in the period — absolute ms thresholds are unfair
  across providers serving different models).
- `score = round(0.6 * reliability + 0.4 * speed)`.
- Tiers: S ≥ 90, A ≥ 75, B ≥ 60, C ≥ 40, D < 40.
- `< 10` requests in period → `score: nil`, `tier: "—"`, sorted to the end.
- Providers with no logs in the period don't appear (inner join).

## Stats :index layout (current order, as of 2026-07-30)

1. KPI cards
2. **Patrones de uso** — `#usage-patterns`:
   - `#hour-distribution` (24-bar CSS histogram, UTC, tooltip exact counts)
   - `#peak-concurrency` (admin only — labeled "Estimado desde los logs")
   - `#busiest-hours`, `#busiest-minutes` (top 5 lists)
3. **Top 5 tables** — Equipos, Miembros
4. **Ranking de proveedores** — `#provider-ranking` (admin only)
5. **Ranking de modelos** — `#model-ranking` (admin only)
6. **Ranking de usuarios** — `#user-ranking` (admin only, added 2026-07-30)

Periods: 7d/30d/90d via `@periods` map; `handle_params` → `load_data`
re-runs everything on period change.

## Scoping rules

- `scope_for(user)`: admin → org-wide (`team_id: nil`); manager → their
  teams; user → own member_ids.
- `provider_ranking`, `model_ranking`, `user_ranking`, and `peak_concurrency`:
  admin-only AND org-wide (infra metrics, not consumption) — loaders return
  `[]`/`nil` otherwise, template gates on `global_role == "admin"`.
- Other breakdowns follow `scope[:team_id]`.

## Known gaps / possible extensions

- No CSV export for ranking/patterns yet (`stats_export_controller.ex`
  only handles models/teams).
- `peak_concurrency` is an estimate; exact historical concurrency would
  require persisting the `Limits.Manager` in-flight watermark.
- Score does not feed routing decisions (deliberate — visualization only).
- `request_logs.agent_type` is NOT NULL in the DB (don't test nil cases).

## Ecto query binding gotcha (2026-07-30)

When joining 5+ tables, Ecto binding positions are cumulative:
```elixir
RequestLog                                        # [rl]
|> join(:inner, [rl], tm in TeamMember, ...)     # [rl, tm]
|> join(:inner, [rl, tm], t in assoc(tm, :team)) # [rl, tm, t]
|> join(:inner, [rl, tm], u in assoc(tm, :user)) # [rl, tm, t, u]
|> join(:left, [rl], mp in ModelProvider, ...)    # [rl, tm, t, u, mp]
|> join(:left, [rl, _tm, _t, _u, mp], c in Credential, ...)  # [rl, tm, t, u, mp, c]
```
The 6th join MUST reference all 5 prior bindings by position. Using `[_, mp]`
when `mp` is at position 5 (not 2) will cause `column t1.credential_id does
not exist` errors because the binding resolves to the wrong table.

**Rule:** after 3+ joins, always use explicit binding names or count positions
carefully. Named bindings (`[rl, tm, t, u, mp, c]`) are safer than `_` skips
when the join order might change.
