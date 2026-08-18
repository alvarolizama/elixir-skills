# MyApp Audit — Third Pass (August 2026)

Authorization & Access Control audit focused on LiveView event handlers,
IDOR in drill-downs, controller scoping, session management, and info
disclosure. 14 LiveViews, 4 controllers, 2 plugs, router, endpoint,
user_auth, OAuth module, accounts context, 4 config files reviewed.

## What Changed Since Previous Passes

All previous findings (A1/A2 missing admin guards, M5 OAuth allowlist fail-open,
M6 OAuth timing attack) have been **fixed**:
- ProvidersLive, UsersLive, AlertsLive, TeamsLive, ServicesLive, LogsLive,
  CreditsLive, SettingsLive all now have `attach_hook(:require_admin, ...)`.
- OAuth state uses `Plug.Crypto.secure_compare/2` (oauth_controller.ex:46).
- OAuth domain allowlist is fail-closed: `nil -> false`, `[] -> false`
  (google.ex:130-141).
- Session renewal (`configure_session(renew: true)`) present on all 4
  identity-change points: login, OAuth callback, impersonate start, impersonate
  stop.
- `list_users` now has `limit: 500` (accounts.ex:93).
- ModelsLive uses per-handler `if socket.assigns.is_admin` checks.
- SupervisedServicesLive has a read-only hook that halts ALL events.

## New Findings (This Pass)

### MEDIUM: Session cookie missing hardening (7b)
`endpoint.ex:7-12`: `@session_options` lacks `secure`, `http_only`,
`encryption_salt`, `max_age`. Hardcoded `signing_salt: "TwS/TtVu"`.

### MEDIUM: Upstream error messages stored with partial key fragments (4d)
`proxy_controller.ex:267` -> `alerts_live.ex:450`: `error_message` from
upstream (may contain `sk-proj-...XXXX`) is stored in DB and rendered in
the Alerts admin page.

### MEDIUM: DB SSL verification disabled (NEW category)
`runtime.exs:50`: `ssl_opts: [verify: :verify_none]` -- no MITM protection
on the database connection. Common in cloud DB setups (AlloyDB, Cloud SQL).

### MEDIUM: Suspended account enumeration (8a)
`session_controller.ex:54-68`: Different flash for suspended vs invalid
credentials reveals which emails exist and are suspended.

### MEDIUM: No Phoenix filter_parameters configured (4e)
No `config :phoenix, :filter_parameters` in any config file.

### LOW: Root admin default email fallback (8b)
`session_controller.ex:188`, `users_live.ex:388`: `|| "admin@MyApp.local"`.

### LOW: list_teams unbounded (3)
`accounts.ex:23`: `Repo.all(Team)` without limit.

### INFO: ApiKeysLive orphan module (1f)
`api_keys_live.ex` exists but has no route in `router.ex`. Dead code.

## Verified-Good Patterns (Confirmed Still Intact)

| Pattern | File:Line | Status |
|---------|-----------|--------|
| OAuth state secure_compare | oauth_controller.ex:46 | FIXED (was !=) |
| OAuth domain allowlist fail-closed | google.ex:130-141 | FIXED (was true/true) |
| Session renewal on login | session_controller.ex:49 | Present |
| Session renewal on OAuth | oauth_controller.ex:92 | Present |
| Session renewal on impersonate | session_controller.ex:145,177 | Present |
| attach_hook in admin LiveViews | providers_live.ex:46, users_live.ex:50, etc. | FIXED (all 8 admin LVs) |
| TeamMembersLive IDOR check | team_members_live.ex:290,312,334,356,400,441,477 | Present |
| StatsLive team drill-down scoped | stats_live.ex:211 | Present |
| StatsLive member drill-down scoped | stats_live.ex:246 | Present |
| StatsExportController team admin-only | stats_export_controller.ex:47,60 | Present |
| DashboardLive membership validation | dashboard_live.ex:138,161 | Present |
| SupervisedServicesLive read-only hook | supervised_services_live.ex:62 | Present |
| Login no_user_verify timing-safe | accounts.ex:298 | Present |
| list_users limit 500 | accounts.ex:93 | FIXED (was unbounded) |
| force_ssl in prod | prod.exs:16 | Present |
| SECRET_KEY_BASE raise if missing | runtime.exs:67-72 | Present |
| WEBHOOK_SECRET raise if missing | runtime.exs:102-103 | Present |
| PubSub reload coalescing | dashboard_live.ex:93, logs_live.ex:131, etc. | Present |
| Login uniform error message | accounts.ex:287-299 (backend) | Present -- but controller (M1) still differentiates |

## Audit Methodology

1. Read router.ex to map all pipelines, live_session blocks, on_mount hooks.
2. Read both plugs (api_auth.ex, dashboard_auth.ex) and user_auth.ex.
3. Read all 4 controllers (session, oauth, stats_export, proxy).
4. Read all 14 LiveViews -- for each: mount, handle_event count vs
   attach_hook count, handle_params IDOR, handle_info PubSub.
5. Read endpoint.ex for session_options.
6. Read accounts.ex authenticate_user for enumeration.
7. Read oauth/google.ex for domain allowlist logic.
8. Read runtime.exs and config.exs for secrets and filter_parameters.
9. Cross-referenced each finding against the real code before reporting.

## Key Grep Commands Used

```bash
# LiveView event/hook triage:
for f in lib/*/live/*_live.ex; do
  echo "$f: events=$(grep -c 'def handle_event' $f) hook=$(grep -c attach_hook $f)"
done

# Orphan LiveView check:
ls lib/*/live/*_live.ex | xargs -n1 basename
grep -o '[A-Z][A-Za-z]*Live' lib/*/router.ex | sort -u

# Session renewal:
grep -n 'configure_session.*renew' lib/*/controllers/*.ex

# filter_parameters:
grep -rn 'filter_parameters' config/

# SSL verification:
grep -rn 'verify.*verify_none\|verify_none' config/
```
