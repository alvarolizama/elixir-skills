# MyApp Delta Audit — worked example (2026-08-02)

Reference captured from a real delta security audit of the MyApp Phoenix
app (Aug 2026). Use as a template for future delta audits on the same codebase
or similar Phoenix/Elixir apps.

## Scope
- Delta since 2026-07-31 (prior audit).
- ~50 commits.
- Report delivered in Spanish (user's language).

## How prior findings were verified to be fixed
- **H1 (attach_hook absent in teams/services/logs LiveViews):** Used the
  skill's fast triage `grep -c attach_hook` per LiveView. All three now had
  `attach_hook(socket, :require_admin, :handle_event, ...)`. Verified by
  reading the actual hook body — it checked `socket.assigns[:is_admin]` and
  `{:halt, put_flash(...)}` on failure.
- **H2 (session fixation):** `grep -n "configure_session"` across
  session_controller.ex and oauth_controller.ex. All 4 identity-change points
  (create, impersonate, stop_impersonating, oauth create_session) had
  `configure_session(renew: true)`.

## Proactive improvements that were ALSO found (not audit findings)
These appeared as `security:` commit titles — verify each rather than trusting
the title:

| Commit | Claim | What was verified |
|--------|-------|-------------------|
| `60a9015` | filter_parameters | Added to config.exs — password/secret/token/api_key/client_secret/authorization |
| `86dc593` | Postgres TLS verify_peer | runtime.exs cond — verify_peer + system CA bundle, ECTO_SSL_VERIFY opt-out |
| `09114b2` + `94d5530` | session cookie hardening | endpoint.ex — encryption_salt, http_only, max_age 8h, SESSION_COOKIE_SECURE env |
| `ca6b41d` | uniform login error | merged :suspended/:unauthorized into single "Credenciales inválidas." + Logger.warning; test updated to assert new string |
| `2391da7` | scrub API key fragments | openai_adapter.ex sanitize_msg → scrub_secrets with `@api_key_pattern` regex, applied before truncate in extract_error_message |

**Important:** commit `94d5530` (prod 403 on login) DELIBERATELY REVERTED part
of `86dc593` — the prod DB used self-signed certs, so `verify_peer` against
system CAs broke the connection. The fix flipped the default back to
`verify_none` with `ECTO_SSL_VERIFY=true` as opt-in. This is a real-world
example of a security hardening that was technically correct but operationally
unusable, and got reverted. Note the trade-off: `verify_none` default (can't
verify self-signed DB certs) vs MITM exposure on the DB connection.

## New findings from this delta (patterns to reuse)
1. **NM1 — search wildcard abuse.** `Accounts.search_users/2` builds
   `"%#{String.downcase(query)}%"` and passes to `ilike` via `^pattern`. Ecto
   parameterizes (no injection), but `%` and `_` in user input act as
   wildcards → enumerate all users with a `%` query. Fix: escape
   `\`→`\\`, `%`→`\%`, `_`→`\_` before building the pattern.
2. **NL1 — read-only view loads full join table.** `SupervisedServicesLive`
   does `Repo.all(from(sma in ServiceModelAlias, ...))` without scoping to
   `service_ids`. Template filters display, but the full data set sits in
   socket assigns. Fix: `where: sma.service_id in ^service_ids`.
3. **NL2 — hardcoded salt defaults.** `endpoint.ex` uses
   `System.get_env("SESSION_SIGNING_SALT", "TwS/TtVu")`. If unconfigured, all
   deployments share salts. Fix: raise on missing in prod or random per-boot.

## Findings that PERSISTED (re-verified, unchanged)
- M1 plaintext `api_key_encrypted` — still `field :api_key_encrypted, :string`,
  adapter still reads plaintext. Product decision pending.
- M3 rollup `Repo.all` without limits — ~21 occurrences in rollup.ex.
- L2 API key prefix shown in alerts table.
- L4 dashboard_live loads full model_catalog.

## Reporting format used
Spanish-language delta report with sections:
1. Executive summary (resolved/persisted/new counts)
2. Previous findings — status table (✅ CORREGIDO / ⚠️ PERSISTE)
3. New findings (NM1/NL1/NL2 with fixes)
4. Proactive improvements table
5. Remediation priority (updated)
6. "No files edited" statement

The user asked this in Spanish, so the report was written in Spanish even
though the skill guidance is English. Match the user's language for the report.
