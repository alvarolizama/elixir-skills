# Web-layer + hot-path audit findings (2026-07-27)

Consolidated findings from a 3-auditor parallel review of MyApp
(hot path, web layer, data layer). Data-layer findings live in
`data-layer-audit-findings.md` — this file covers the other two audits.
Status: NOT yet fixed (except the alias-rewrite bug, see
`debugging-no-available-provider.md`).

## 🔴 Critical

### Web: IDOR in CSV stats export (cross-team data leak)
`stats_export_controller.ex:84-92` and `:54-64`. When `team_id` or `model_id`
query params are present, `Rollup.breakdown_by_member(team_id, opts)` and
`Rollup.breakdown_by_provider_for_model(model_id, opts)` run WITHOUT applying
the caller's scope. Any authenticated user can export any team's member
breakdown (emails, costs) via `/dashboard/stats/export?type=teams&team_id=<uuid>`.
Route only uses `:browser_auth` (authenticated, not admin, not scoped).
Fix: verify `team_id` is in the user's scope before running the query; apply
member/team scope filters inside the Rollup queries.

### Hot path: 4-6 synchronous Postgres queries per successful request
Contradicts the "ETS/atomics only" contract in the proxy controller moduledoc:
- `Providers.list_accessible_aliases/1` (UNION+JOIN) — per route attempt (up to 3)
- `Providers.list_model_providers/1` (SELECT + preloads) — per route attempt
- `Providers.current_pricing/1` (`providers.ex:256`) — per successful response
- `Oban.insert` for `Logs.WriteWorker` (`proxy_controller.ex:549`) — per success
- `Oban.insert` for `Budgets.SyncWorker` (`budgets/manager.ex:111`) — per success
- `Budgets.Manager.ensure_loaded` does a `SUM` aggregate on cache miss/rollover
Fix: ETS caches with invalidation for aliases/providers/pricing; throttle the
sync-worker enqueue (unique job already dedupes, but the insert itself is a DB
write); batch log writes.

### Hot path: budget gate bypass via `max_tokens`
`proxy_controller.ex:522-529`: `estimated_usage` trusts `payload["max_tokens"]`
verbatim — `max_tokens: 0` (or negative) makes `estimated_cost ≈ 0`, so the
pre-request `Budgets.check` always passes. Fix: clamp
`max(payload["max_tokens"] || @default, 1)`.

## 🟠 High

### Web: `ProvidersLive` and `UsersLive` have NO admin guard in mount/handle_event
Both rely 100% on the router's `live_session :admin`. `ModelsLive` does it
right (`is_admin` assign + per-event checks) — mirror that pattern. Every
destructive event (`delete_provider`, `delete_credential`, `save_user`,
`reset_password`, `toggle_status`) executes with no permission check in the
handler.

### Web: provider API keys stored and rendered in plaintext
`credential.ex` documents "stores the key as-is for now". Form input is
`type="text"` (visible in DOM); `mask_key/1` shows it in templates. Fix:
cloak/cloak_ecto at rest, `type="password"`, never send plaintext back for edit.

### Web: no rate limiting on destructive LiveView events
`replace_key`, `revoke_key`, `delete_provider/team/credential`,
`remove_member`, `reset_password`, `toggle_status` — all spammable. Add Hammer
or a small ETS limiter per user+event.

### Hot path: `Limits.Manager.acquire_concurrency` rollback can go negative
`limits/manager.ex:89-100`: increment-then-check rolls back with
`:ets.update_counter(key, {2, -1})` (no floor). Concurrent over-limit rollbacks
can drive the counter negative → temporary limit bypass. Fix: use the
`{2, -1, 0, 0}` form (floor at 0) like `release_concurrency/1` already does.

### Hot path: `CircuitBreakerManager.wait_until_registered` busy-waits
`circuit_breaker_manager.ex:143-154`: up to 200 `Registry.lookup` retries with
no sleep — burns CPU in the request process when breakers start lazily.
Fix: `Process.sleep(1)` between attempts or register in `start_link`.

### Web: OAuth auto-registration when `allowed_domains` is nil or []
`oauth/google.ex:125-137`: `nil` and `[]` both mean "allow ALL domains" — a
deploy without the allowlist lets ANY Google account self-register into the
dashboard. Fix: treat nil/[] as "auto-registration disabled".

## 🟡 Medium (selected)

- N+1: `DashboardLive.load_personal_data` (2N+1 queries over memberships),
  `ApiKeysLive.load_managed_team_members` (N+1 over teams),
  `TeamsLive.load_teams` (per-team `list_destinations`).
- `Accounts.list_users` — `Repo.all(User)` with no limit/pagination.
- Streaming: `OpenAIAdapter.stream_chat_completion` uses unlinked `Task.start`
  — client disconnect orphans the upstream stream (Finch pool leak). Monitor
  the caller and halt on `:DOWN`.
- Auth-error deactivation is fire-and-forget (`Task.start`) — until the DB
  update lands, the breaker still allows the bad credential (window of
  repeated 401s). Force-open the breaker synchronously for `:auth_error`.
- OAuth state compared with `!=` — use `Plug.Crypto.secure_compare/2`.
- `Metrics.Collector.push_latency` read-modify-write on public ETS — p95
  drifts under load (documented tradeoff).
- `LogsLive` runs a `cost_summary` aggregate per `:new_log` broadcast —
  debounce or use an ETS counter.
- `dashboard_live.ex:194`: `socket.assigns[:period || "today"]` — always reads
  `:period` (atom is truthy); harmless today but latent bug. Should be
  `socket.assigns[:period] || "today"`.
- `TeamMembersLive`: `change_role` accepts any string for `team_role`; nothing
  prevents removing the last manager of a team.

## Audit fan-out pattern that worked

Full-project review recipe: parent runs the mechanical gates first
(`mix compile --warnings-as-errors`, `mix format --check-formatted`,
`mix deps.unlock --check-unused`, full `mix test`), then dispatches 3 parallel
read-only review subagents with disjoint scopes — (1) proxy hot path +
GenServers, (2) web layer (authz, N+1, pagination, secrets), (3) data layer
(schemas vs migrations, indexes, Oban workers). Parent fixes the failing test
itself while they run. Subagents must verify each suspicion against real code
before reporting; demand severity + file:line + suggested fix per finding.
