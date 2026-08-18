# MyApp Stats Services View — /dashboard/stats/services

Added 2026-07-31. Drill-down analytics for services, mirroring the teams view structure.

## Routes

```elixir
live "/dashboard/stats/services", StatsLive, :services
```

## Rollup function

`MyApp.Metrics.Rollup.breakdown_by_service/1` — joins `RequestLog` with `Service` on `team_member_id` (services are virtual team members with `service.id == team_member_id` in logs). Returns per-service: requests, cost, tokens in/out, avg TPS.

## StatsLive assigns

- `:breakdown_service` — list of service aggregates (all services view)
- `:service_filter` — selected service_id for drill-down
- `:services` — list of all services for the filter select (admin only)

## Template structure

Same as `:teams` but for services:
1. Filter select + CSV export button
2. When service selected: 4 KPI cards (Costo, Requests, Tokens in/out, TPS) + "Modelos usados" table + "Quitar filtro" button
3. When no filter: "Todos los servicios" table with clickable rows linking to drill-down

## Key differences from :teams

- No `:breakdown_member` — services don't have members, they ARE the virtual member
- No scoping beyond admin check (services are admin-only by design)
- Uses `hero-wrench-screwdriver` icon instead of `hero-user-group`

## Event handlers

- `set_service_filter` — patch to `?service_id=X`
- `clear_service_filter` — patch to remove service_id param

## Files

- `lib/MyApp/metrics/rollup.ex` — `breakdown_by_service/1`
- `lib/my_app_web/live/stats_live.ex` — load/services filter handlers
- `lib/my_app_web/live/stats_live.html.heex` — `:services` template block
- `lib/my_app_web/router.ex` — route
- `lib/MyApp/accounts.ex` — `list_services/1` (simple alphabetical list)
