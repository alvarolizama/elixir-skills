# MyApp — Logs LiveView Surface (as of 2026-08-05)

What exists in the live logs page so future sessions extend instead of
duplicating. Repo: `/Users/alvaro/Workspace/Repos/MyApp`.

## LiveView

- `lib/my_app_web/live/logs_live.ex` — real-time request log page
  (`/dashboard/logs`).

## KPI strip (5 cards, `lg:grid-cols-5`)

Current layout after merging "Conectados" + "En vuelo" and adding
"Top Modelos" (2026-08-05):

1. **Actividad** (`#live-indicators`) — merged card showing
   `N conectados N en vuelo` inline. Uses `@online_users` and
   `@api_inflight` assigns. No avatar circles (removed).
2. **Top Modelos** (`#top-models`) — new card listing top 5 models by
   request count in rolling 5-min window. Shows model name, count, and
   provider_key_prefix per row. Uses `@top_models` assign.
3. **Req/min** — `@summary.req_per_min` (rolling 5 min).
4. **Latencia prom** — `@summary.avg_latency_ms` (rolling 5 min).
5. **Errores** — `@summary.error_count` + `@summary.error_rate` (rolling 5 min).

## Context queries (MyApp.Logs)

- `realtime_summary/2` — existing rolling-window summary (request_count,
  req_per_min, avg_latency_ms, error_count, error_rate).
- `requests_by_model/3` — **new** (2026-08-05): groups by
  `[model_requested, provider_key_prefix, credential_name]`, returns
  `[%{model, count, provider_key_prefix, credential_name}]` ordered by
  count desc, limit 5.

## Assigns added to mount/3

- `:top_models` — defaults to `[]`, computed in `refresh_summary/1` and
  `load_logs/2` via `Logs.requests_by_model/1`.

## Template notes

- Merged card uses `flex items-baseline gap-3` with
  `text-2xl font-bold` for values and `text-xs text-base-content/40` for
  labels — no separate card header per metric.
- Top models list uses `space-y-1` with per-row `flex justify-between`,
  model name truncated, count + key prefix on the right.
- Both new assigns are refreshed on the same 5-second tick as the other
  KPIs (`@summary_tick_interval_ms`).
