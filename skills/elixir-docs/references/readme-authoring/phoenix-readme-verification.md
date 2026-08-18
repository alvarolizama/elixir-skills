# Phoenix README Verification Recipe

Exact verification sequence for a Phoenix/Elixir app README, with the greps that caught real discrepancies in a MyApp README rewrite (2026-08-08). Adapt paths for other apps; the pattern is stack-general.

## 1. Page inventory — the router is the truth

```bash
grep -nE '(live|post|get|forward|scope) ' lib/my_app_web/router.ex
```

- Every `live "/path", SomeLive` = a real page. Every `post/get` = a real endpoint.
- `live_session` blocks tell you the access role (e.g. `:admin` = admin-only page) — feature claims like "managers can X" must match the session + any in-module hooks.
- **Orphan check:** `ls lib/my_app_web/live/` and diff against the router. Modules present but unrouted (found: `ApiKeysLive` — key management had moved into the dashboard; the module was legacy) are NOT features. Do not list them.

## 2. Page purposes — batched moduledoc reads

```bash
for f in lib/my_app_web/live/*_live.ex; do
  echo "═══ $f ═══"; sed -n '/@moduledoc """/,/"""/p' "$f" | head -20
done
```

- Gives each page's real scope in one turn. `@moduledoc false` means read the render/events manually — page still exists.
- Treat moduledoc *claims* as unverified until step 3 (see below — one moduledoc promised a response header the code never set).

## 3. Claim-by-claim greps

| Old-README claim | Grep | What it caught |
|---|---|---|
| "Audit log — impersonation, credential changes, team/user mgmt" | `grep -rln "Auditing.audit" lib/` | ONLY `session_controller.ex` (impersonate start/stop). Rewrote claim to "impersonation start/stop is persisted to the audit log". |
| "`X-MyApp-Savings` header" | `grep -rn "x-MyApp-savings" lib/` | Only in a `@moduledoc` — no `put_resp_header` site. Dropped the claim; kept the verified `X-MyApp-Cost` (had a real set-site). |
| "Webhooks HMAC-signed" | `grep -rn "x-MyApp-signature" lib/` | Real header set in the webhook worker — claim kept. |
| "Impersonation UI" | `grep -n "impersonate" lib/my_app_web/live/users_live.ex` | Real button in Users page — claim kept with page path. |
| Env var existence | `grep -n "System.get_env" config/runtime.exs` | Real vars listed WITH line numbers — but see boilerplate trap below. |

**Boilerplate trap:** `runtime.exs` ships commented-out blocks (Mailgun adapter, `SOME_APP_SSL_KEY_PATH` SSL example). The grep above lists them. Confirm the var is read by *uncommented* code — read 5-10 lines of context around each hit.

## 4. Env var defaults — read, don't copy

```bash
sed -n '1,60p' config/runtime.exs   # wherever the System.get_env blocks live
```

Copy defaults straight from `System.get_env("VAR", "default")` calls. The old README had drifted on several; reading source also surfaced two vars the old README never listed (`CIRCUIT_BREAKER_RATE_LIMIT_COOLDOWN_MS`, `ROUTING_SLOW_PENALTY_MS`). Endpoint-level vars may live elsewhere — found `SESSION_MAX_AGE_SECONDS` in `lib/my_app_web/endpoint.ex`, not runtime.exs.

## 5. Install/deploy facts

- `mix.exs` → Elixir requirement (`elixir: "~> 1.15"`), key deps + versions, `setup` alias steps (the real quick-start command).
- `priv/repo/seeds.exs` → seeded admin email/password + their override env vars. Publish both in a table.
- `Dockerfile` → exposed port, entrypoint behavior (migrations before boot? seed on first boot?), build ARGs (e.g. `DISABLE_FORCE_SSL`), runtime bypass env vars (`SKIP_MIGRATIONS=1`). Health-check requirements (e.g. curl in the runtime image) are deploy facts worth one line.

## 6. UI language check

Page titles/labels in the LiveViews (`assign(:page_title, "Créditos · …")`, button labels) reveal the actual UI language. MyApp: hardcoded Spanish strings despite an `en` gettext dir. The README (English) now carries a note: "the admin UI language is Spanish". An unchecked gettext dir would have suggested i18n that isn't wired up.

## Structure that worked

1. Logo + one-paragraph pitch + hero screenshot (path verified to exist)
2. `> **Note:**` UI language callout
3. Features grouped: **Gateway/API** → **Admin UI (with real paths)** → **Platform** (internals compressed to 4 bullets)
4. Requirements → Quick start (clone → `mix setup` → `mix phx.server` → seeded-credentials table → first milestone)
5. Usage snippet (verified base URL path + key prefix from code)
6. Configuration: required-prod vars table, then optional-vars table (`Var | Default | What it tunes`)
7. Production/Docker → Tech stack (one line) → `mix precommit` → License

Then the reply to the user listed: features confirmed (with the file each was verified against), old claims removed/corrected (with the grep that disproved each), and verified features added. That discrepancy report is part of the deliverable.
