# my_app_gateway Scope-1 Audit — Authorization & IDOR (Aug 2026)

Read-only audit of `/Users/alvaro/Workspace/Repos/alvarolizama/my_app_gateway`
(Phoenix 1.8 LLM proxy gateway). Scope: Category 1 (authz/IDOR) across 15
LiveViews + StatsExportController + ProxyController + Accounts/Rollup/Logs
contexts. Parent agent had pre-verified router.ex, DashboardAuth, ApiAuth,
UserAuth on_mount, SessionController impersonation.

## Findings (S1-n)

| ID | Sev | file:line | What |
|---|---|---|---|
| S1-1 | HIGH | team_members_live.ex:60-64, handlers 247/298/319/342/364/407/445/478 | 1b — mount `check_access` (admin-only) but no attach_hook, 16 handlers never re-check role. Mitigating GOOD: every mutating handler re-validates `member.team_id == socket.assigns.team.id` (301,323,345,367,411,452,488) |
| S1-2 | HIGH | monitor_live.ex:60, 283, 302 | 1b — `assign(:is_admin, true)` UNCONDITIONAL (no mount role read, no hook). `reactivate_credential`/`reset_breaker` fire with zero checks; router `:admin` session is the only gate |
| S1-3 | MEDIUM | dashboard_live.ex:352,365 + dashboard_live.html.heex:230-325 | 1c/1d — `/dashboard` is in the all-users `:dashboard` live_session (router.ex:67-69); `model_usage_stats_org/2` computed for every user, heex renders `stats.org.*` with ZERO `@is_admin` guards. Code comment (line 126) says org view belongs in /dashboard/stats — intent violated. Aggregates only, no per-user PII |
| S1-4 | HIGH | api_auth.ex:30,91-92 + accounts.ex:192-196,461-474 | 1j — suspension never revokes data plane. `admin_update_user(%{"status"=>"suspended"})` writes ONLY user.status; `active_membership` checks TeamMember.status; `get_team_member_by_api_key` filters only `ak.status=="active"`. Suspended user keeps full /v1/* API access |
| S1-5 | MEDIUM | user.ex:36,42-49 + accounts.ex:172-174 | 1i latent — `registration_changeset` casts shared `@permitted` incl. `:global_role/:status/:google_id`, no inclusion validation. UNREACHABLE today (zero callers of `register_user`, no route). Latent critical if wired |
| S1-6 | MEDIUM | api_keys_live.ex (whole file) | 1f — orphan, 0 router refs. Mount never redirects despite moduledoc; mostly fail-closed (empty data for non-admins) |
| S1-7 | LOW | stats_live.ex:90,107 | 5g — unguarded `String.to_existing_atom(field)` / `String.to_integer(hour)` crash LiveView. Admin-only → availability |
| S1-8 | LOW | services_live.ex:143,157,182,199,345; teams_live.ex:196,210,273,319,340,372; user_stats_live.ex:29 | 5g/1d-pattern — bang `get_!` on event ids → NoResultsError/CastError crashes. Admin-only |
| S1-9 | LOW | logs.ex:204-221; export:165 vs logs.ex:23,302 | unescaped `%#{search}%` LIKE (admin-only); export requests limit 50_000 but clamp_limit caps 500 → silent CSV truncation |
| S1-10 | LOW | stats_export_controller.ex:82,110 → rollup.ex:592-599,2030-2032 | 5g — team_id/model_id query params → `== ^param` on binary_id → CastError 500 on malformed UUID |

## Verified-GOOD patterns (worth reusing)

- **Fail-closed scopers** (accounts.ex:382-389, 395-399):
  `scope_member_ids`: admin→nil (unrestricted), user→own membership ids,
  **unknown→[]** (matches nothing). Same for `scope_team_ids`. The
  catch-all `def scope_member_ids(_), do: []` clause is the load-bearing one.
- **`maybe_member_ids` query composer** (rollup.ex:2067-2071): nil=no filter,
  list=`in ^ids`; applied in every drill-down (breakdown_by_model 271,
  breakdown_by_member 390, breakdown_by_provider_for_model 600,
  breakdown_by_member_for_model 687). Org-wide-by-design functions
  (breakdown_by_team/service) only called from admin-gated paths.
- **require_admin_hook fleet**: credits/logs/settings/users/user_stats/
  providers_live all `assign(:is_admin, user.global_role == "admin")` +
  `attach_hook(:require_admin, :handle_event, ...)` halting every event.
  services/teams_live: explicit mount role redirect precedes the
  `assign(:is_admin, true)` — hardcoded true is CORRECT there.
- **Per-team IDOR re-validation** (team_members_live.ex): every mutating
  handler checks `member.team_id != socket.assigns.team.id` before acting —
  the pattern for LiveViews scoped to a URL-param parent resource.
- **Routing-layer access checks** (routing/router.ex:99-119, 379-384;
  providers.ex:569-606): model alias resolved against
  `list_accessible_aliases(team_member)` (team grants ∪ member extras;
  services get service-grants only) → `:model_not_found` when ungranted;
  `visible_to_member?` filters member-exclusive providers from the
  team-cached candidate list.
- **Export controller scoping** (stats_export_controller.ex): every CSV path
  injects `team_member_ids: scope_member_ids(user)` (77,140,166); team
  drill-down admin-only via `team_export_allowed?` (48,69-70);
  `load_team_breakdown` non-admin→[] (314-318); formula-injection guard
  `csv_sanitize_formula` (298-302); period whitelist (320-322).
- **users_live root protections**: root admin can't be suspended (434),
  deleted (465), or demoted (600-607 `protect_root_user`); self-delete
  blocked (473); sort field `to_existing_atom` rescued + whitelisted
  (500-504).
- **settings_live enum whitelist**: `field` param guarded
  `when field in [...]` before `to_existing_atom` (94-96,105-107).

## Audit mechanics that worked

- Spec-file delegation (checklist in /tmp, short dispatch goal) — per the
  skill's subagent playbook; worked as designed.
- Orphan check: `grep -c 'ApiKeysLive' router.ex` → 0, then read the orphan's
  mount anyway (1f).
- Severity calibration required grep of CALLERS before rating 1i:
  `grep -rn 'register_user' lib/` → only the def → latent, not critical.
- The status-revocation recipe (now 1j): read what suspend WRITES, then read
  every auth path's WHERE/guards for a user.status re-check.
