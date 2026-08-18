# Audit-to-fix batch (2026-08-15/16)

## Context

Full audit of my_app_gateway (LLM proxy/gateway) — 49 findings originally
reported across ETS, Proxy, Partitions, Índices, Migraciones, Queries,
and LiveViews. Parent verified each finding against real code before
dispatching fixes.

## Corrections to original report

3 findings eliminated (already fixed by prior work):
- **A12** `flush_remaining` duplicate `{:sse_done}` — `handle_event`
  sets `acc.done = true` (openai_adapter.ex:288); `flush_remaining`
  checks `if acc.done` before re-sending (line 313). No duplication.
- **M8** `subscription_id` orphaned in `request_logs` — migration
  `20260726214614_remove_subscriptions.exs:10` already dropped it.
- **M15** orphaned index on `model_providers.subscription_id` — same
  migration dropped the column (line 6); index went with it.

2 findings reclasified:
- **A11** SSE `\n\n` sanitization — adapter splits on `\n\n` and
  rejoins with `\n` (openai_adapter.ex:283). Framing is safe. Downgraded.
- **A4** completion RAM accumulation — only chunks with `"usage"`
  accumulate in `acc.completion`, not all chunks. Real issue is
  estimation accuracy, not RAM. Reclasified to Medio.

## Fixes implemented (44 valid findings, 17 applied this batch)

### Fase 1 — Quick wins (triviales)
- **C7** `maybe_preload_team` — `cond` skips preload when team is
  loaded struct (hot path), uses `force: true` only when nil/NotLoaded
  (cold path). 1 DB query saved per proxy request.
  **Pitfall:** `Ecto.assoc_loaded?(nil)` returns `true` — must also
  check `team != nil` or the guard bypasses preload on nil team.
  **Pitfall:** `Repo.preload` without `force: true` silently skips
  nil fields (Ecto treats nil as "loaded"). Need `force: true` in
  cold path.
- **A13** `agent_type` truncated to 255 chars in `api_auth.ex`
  (same as `client_agent` already did).
- **M1** `read_concurrency: true` added to 4 ETS tables:
  `window.ex` (2 tables), `inflight.ex`, `included_waiter.ex`.
- **A5** Drop duplicate ASC index (DESC covers all queries).
- **A6** Index on `credential_name` (Rollup queries).
- **A7** Partial index `status_code >= 400` (top_errors).
- **A8** Partial index `agent_type IS NOT NULL` (agent_breakdown).

### Fase 2 — Hot path DB queries
- **C6** `Routing.Cache.fetch_accessible_aliases/3` — caches
  `list_accessible_aliases` with 60s TTL, same pattern as
  `fetch_model_providers`. Invalidation in providers.ex on
  team member/alias mutations.
- **C5** Single-flight in `ensure_loaded` — `:ets.insert_new`
  placeholder `{:loading, key}`; concurrent callers poll up to 50ms.
  Collapses thundering-herd from N DB queries to 1.
- **C1** Partition cron worker (not yet implemented — planned).

### Fase 3 — Proxy stream
- **A2** `@max_route_retries 20` guard on `route_and_acquire`
  recursion. Tail-recursive already (BEAM handles it), but unbounded
  with N saturated credentials.
- **A3** `maybe_capture_usage` — secondary check `String.starts_with?`
  to filter chunks where "usage" appears as LLM text content.
- **A4** `decode_usage_chunk` — only accumulate completion when
  `acc.usage == nil` (no usage received yet). Stops unbounded
  accumulation after usage frame.

### Fase 4 — LiveViews
- **A14** MonitorLive: DashboardCache wraps for day_stats,
  per_model_cost, per_model_avg_latency. Debounce PubSub refreshes
  with `:refresh_pending` assign. `list_model_aliases` moved to mount.
- **A15** `load_budget_activity` — providers query filtered by
  `top_provider_ids` instead of `Repo.all`.
- **A16** LogsLive: redundant 5s `send_interval` removed.
  `top_models`/`top_users` cached with 3.5s TTL.

### Fase 5 — Hardening
- **M2** `bump_counter` — `Logger.warning` when entry evicted
  between `ensure_loaded` and `bump_counter`.
- **M3** `StickyTracker.get` — direct `:ets.delete` replaces
  `GenServer.cast` for expired entries (public table, any process
  can delete).

## Migration timestamp collision pitfall

Two subagents creating migrations in the same second generated
identical timestamps (`20260815233004` ×2, `20260815233005` ×2).
Parent renamed to `...33006`, `...33007`, `...33008` before tests.
Module names in migration files don't include timestamps, so no
code changes needed — just the filenames.

## Verification

- `mix compile --warnings-as-errors` → exit 0
- `mix test` → 862/862 passed (including the RouterTest that
  initially failed due to the `assoc_loaded?(nil)` pitfall)
- Warnings from `M2` `Logger.warning` are expected (test scenario
  evicts budget entries intentionally)
