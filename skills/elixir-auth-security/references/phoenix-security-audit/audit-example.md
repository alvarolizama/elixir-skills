# MyApp Security Audit — Worked Example

Full audit of the MyApp LLM proxy gateway web layer (July 2026).
17 files reviewed, 16 findings (2 critical, 4 high, 6 medium, 4 low).

## Project Context

MyApp is an OpenAI-compatible LLM proxy gateway built with Phoenix/Elixir.
Key features:
- Multi-provider routing (priority fallback, circuit breakers)
- Team-based access control (admin, manager, user roles)
- API key management (per-team-member keys)
- Budgets and rate limiting
- Real-time metrics dashboard via LiveView
- CSV export of stats

## Attack Surface Map

```
router.ex
├── :browser pipeline (fetch_current_user)
│   ├── public: /login, /auth/google, /auth/google/callback
│   ├── live_session :dashboard (require_authenticated)
│   │   ├── /dashboard (DashboardLive)
│   │   ├── /dashboard/stats (StatsLive)
│   │   ├── /dashboard/teams (TeamsLive)
│   │   ├── /dashboard/teams/:id/members (TeamMembersLive)
│   │   └── /dashboard/logs (LogsLive)
│   └── live_session :admin (require_admin)
│       ├── /dashboard/providers (ProvidersLive)
│       ├── /dashboard/users (UsersLive)
│       ├── /dashboard/models (ModelsLive)
│       └── /dashboard/keys (ApiKeysLive)
├── :browser_auth pipeline (require_authenticated)
│   └── /dashboard/stats/export (StatsExportController)
└── :proxy_api pipeline (ApiAuth plug — bearer token)
    ├── /v1/models (ProxyController)
    └── /v1/chat/completions (ProxyController)
```

## Key Findings

### CRITICAL: IDOR in CSV Export (C1, C2)

**File:** `lib/my_app_web/controllers/stats_export_controller.ex:84-92`

The `/dashboard/stats/export` endpoint is behind `:browser_auth` (requires
authentication but NOT admin). When `team_id` is passed as a query param,
`build_teams_csv/3` calls `Rollup.breakdown_by_member(team_id, opts)` directly
— **without verifying the user has access to that team**.

```elixir
defp build_teams_csv(user, team_id, opts) do
  rows =
    if team_id do
      Rollup.breakdown_by_member(team_id, opts)  # ← NO scope check
    else
      load_team_breakdown(user, opts)
    end
```

Any authenticated user can pass `?type=teams&team_id=ANY_UUID` and get
member-level breakdowns (emails, costs, tokens) for any team.

Same pattern with `model_id` — `Rollup.breakdown_by_provider_for_model(model_id, opts)`
returns cross-team data without scoping.

**Severity:** Critical — data exfiltration across team boundaries.
**Fix:** Validate `team_id` against user's managed teams before querying.

### HIGH: ProvidersLive missing admin guard in mount + handle_event (A1)

**File:** `lib/my_app_web/live/providers_live.ex:24-35, 87-259`

Unlike `ModelsLive` (which sets `is_admin` in mount and checks it in every
`handle_event`) and `TeamsLive` (which redirects non-admins in mount),
`ProvidersLive` trusts the router's `live_session :admin` entirely. No
`is_admin` assign, no permission check in any of its 10+ destructive
`handle_event` handlers (`delete_provider`, `delete_credential`,
`toggle_provider`, `save_credential`, etc.).

**Severity:** High — defense-in-depth failure. The router protects the route
today, but any router reconfiguration or new route addition exposes all
destructive operations.

### HIGH: UsersLive same pattern (A2)

**File:** `lib/my_app_web/live/users_live.ex:22-33`

Same as ProvidersLive — no admin check in mount or any handler. All user
management operations (create, edit, suspend, reset password) lack per-handler
permission verification.

### HIGH: Plaintext API key storage (A3)

**File:** `lib/MyApp/providers/credential.ex:3-4`

```elixir
# The `api_key_encrypted` field stores the key as-is for now;
# encryption-at-rest is a post-MVP concern.
field :api_key_encrypted, :string
```

Provider API keys (OpenAI, Anthropic, etc.) stored in plaintext. The form
input uses `type="text"` (visible in DOM). `mask_key/1` slices the plaintext
value that's already loaded in assigns.

### HIGH: No rate limiting on LiveView destructive events (A4)

No LiveView in the app has rate limiting on any `handle_event`. The proxy API
has two-gate throttling, but the dashboard admin does not. A user can spam:
`replace_key` (generates new API keys), `revoke_key`, `delete_provider`,
`suspend_user`, `reset_password`.

### MEDIUM: N+1 in DashboardLive mount (M1)

```elixir
# dashboard_live.ex:172-186
Enum.map(memberships, fn membership ->
  limits = Accounts.effective_limits(membership)  # query per membership
  spend = Budgets.spend(membership.id)             # query per membership
end)
```

`effective_limits/1` also does `Repo.preload(team_member, [:team])` internally.

### MEDIUM: N+1 in ApiKeysLive for admin (M2)

```elixir
# api_keys_live.ex:37-41
Accounts.list_teams()
|> Enum.map(fn team ->
  {team, Accounts.list_team_members_for_team(team.id)}  # query per team
end)
```

### MEDIUM: N+1 in TeamsLive webhooks (M4)

```elixir
# teams_live.ex:69-74
teams |> Enum.map(fn team ->
  {team.id, Observability.list_destinations(team.id)}  # query per team
end)
```

### MEDIUM: list_users without pagination (M3)

```elixir
# accounts.ex:81
def list_users, do: Repo.all(User)
```

Loads all users into memory. UsersLive streams them all.

### MEDIUM: OAuth allowlist fail-open (M5)

```elixir
# google.ex:127-132
case config()[:allowed_domains] do
  nil -> true   # ← anyone can auto-register
  [] -> true    # ← anyone can auto-register
end
```

### MEDIUM: OAuth state non-timing-safe comparison (M6)

```elixir
# oauth_controller.ex:46
if state != stored_state do  # ← timing attack
```

### LOW: Elixir syntax bug in assigns access (B1)

```elixir
# dashboard_live.ex:194
period = socket.assigns[:period || "today"]
```

`:period || "today"` evaluates the atom `:period` (always truthy), so this
ALWAYS reads `socket.assigns[:period]`. Should be
`socket.assigns[:period] || "today"`.

### LOW: PubSub storm in LogsLive (B3)

Every `:new_log` broadcast triggers `refresh_summary/1` which runs a
`cost_summary` query against Postgres — in every connected LogsLive. No
debounce.

## Audit Methodology Used

1. **Read all 17 files** (router, 2 plugs, user_auth, OAuth helper, 3 controllers,
   9 LiveViews) via `read_file` and `terminal cat -n`.
2. **Cross-referenced context functions** — read `accounts.ex`, `logs.ex`,
   `rollup.ex` to verify preloads and scope behavior.
3. **Verified each finding** before reporting:
   - IDOR: confirmed `breakdown_by_member/2` doesn't filter by user scope.
   - Missing admin guard: confirmed by comparing with ModelsLive's pattern.
   - Plaintext secrets: read the schema module doc.
   - N+1: traced each `Enum.map` to the context function it calls.
4. **Rated severity** by impact:
   - Critical = data exfiltration / unauthorized access to other teams' data
   - High = defense-in-depth failure or secret exposure
   - Medium = performance issue or OAuth misconfiguration
   - Low = bug that doesn't directly cause a security issue

## Key Grep Commands Used

```bash
# Find handle_event clauses that DON'T check is_admin:
grep -n 'def handle_event' lib/my_app_web/live/*_live.ex
grep -n 'is_admin\|global_role.*admin' lib/my_app_web/live/*_live.ex

# Find Repo.all without limit:
grep -n 'def list_\|Repo.all' lib/MyApp/*.ex | grep -v 'limit'

# Find plaintext secret fields:
grep -rn 'api_key_encrypted' lib/MyApp/providers/*.ex lib/my_app_web/live/*_live.ex

# Find OAuth state comparison:
grep -n 'state.*stored_state\|stored_state.*state' lib/my_app_web/controllers/oauth_controller.ex

# Find N+1 patterns (Enum.map calling context functions):
grep -n 'Enum\.map.*Accounts\.\|Enum\.map.*Observability\.' lib/my_app_web/live/*_live.ex
```

## Report Structure Produced

The final report used:
- 🔴 CRITICAL / 🟠 HIGH / 🟡 MEDIUM / 🟢 LOW severity emojis
- Per-finding: ID (C1, A1, M1, B1...), file:line, category, description, fix
- Summary table by category × severity
- Prioritized remediation list (immediate → urgent → short-term → medium-term → low)
- Explicit "No files were edited" statement
- All UI strings noted in Spanish (the app's language)

---

## Second Pass (August 2026) — Secrets, sessions, OAuth, proxy headers

11 files reviewed (the proxy stack + OAuth + session lifecycle). Found:
1 critical, 2 high, 4 medium, 4 low. The same four `live_session`/scope
claims held, but the new code surface introduced one new class of finding
the first pass missed: **plaintext secrets loaded into LiveView assigns
even when masked in HTML** (SEC-002 / 4c), and the upstream-error-message
scrub gap (SEC-003 / 4d-adjacent).

### Confirmed-good patterns

| Area | Where | Why it's safe |
|---|---|---|
| 7a session fixation | `session_controller.ex:49-50, 145-147, 177-179`; `oauth_controller.ex:92-93` | Every `put_session(:user_id, …)` is preceded by `configure_session(renew: true)`. Login, impersonation start, impersonation stop, OAuth — all four. |
| 6b OAuth state comparison | `oauth_controller.ex:46` | `Plug.Crypto.secure_compare/2`. |
| 6a OAuth domain allowlist | `oauth/google.ex:129-141` | Fail-closed: `nil → false`, `[] → false`. |
| Proxy header allowlist | `proxy_controller.ex:229-243` + `openai_adapter.ex:286-308` | Strict whitelist, `user-agent`/`http-referer`/`x-title` only. Adapter builds headers from scratch — client's `Authorization` is **not** propagated. No cookie forwarding. |
| Self-issued API keys | `accounts.ex:821-826` | `tg-` + 24 random bytes (192 bits) → SHA-256 hex. No bcrypt (correctly so — input already high-entropy). |
| Password hashing | `accounts/user.ex:148-153` | `Bcrypt.hash_pwd_salt/1`, 12-char min, `no_user_verify/1` for constant-time unknown-email. |
| CSRF | `router.ex:9` | `:protect_from_forgery` in `:browser` pipeline. |
| 4d secrets in logs (current code) | `grep -rn 'IO\.inspect\|Logger\.\(debug\|info\|warn\|error\)' lib/` | Zero hits outside `release.ex`. No `Plug.Logger`. |
| API key in LiveView | various | `key_prefix` (8 chars) only, never the hash. |
| OAuth token handling | `oauth_controller.ex` | `access_token` is local; never persisted. `client_secret` only in app env. |
| Request log privacy | `logs/request_log.ex:19-23` | "Never stores prompt or completion content — only metadata." |

### Critical: Plaintext `api_key_encrypted` again (4a)

Confirmed by reading `providers/credential.ex:3-25`: the moduledoc literally
says *"stored as-is for now; encryption-at-rest is a post-MVP concern"*, and
`Map.get(credential, :api_key_encrypted)` is a field read, not a decrypt.
Same severity as A3 above — but the second pass found a new adjacent finding
(**SEC-002**) that the first pass missed.

### High: Plaintext key in LiveView socket assigns (4c)

Even though `mask_key/1` only renders the last 4 chars, the LiveView
(`providers_live.ex:57-65`) does `Repo.all(from(p in Provider,
left_join: c in assoc(p, :credentials), preload: [credentials: c]))`. The
full `api_key_encrypted` is materialized into the LiveView process state.
The socket serializer, the HEEx debugger, or a future `IO.inspect` would
dump the entire struct. This is **High** — independent of encryption-at-rest,
because even after SEC-001 lands, the LiveView still decrypts into the
socket.

**Fix:** Project away the column at the Repo boundary so the secret never
enters the BEAM (see `### 4c` in SKILL.md).

### Medium: Upstream error messages may echo the bad key (4d-adjacent)

`proxy_controller.ex:267` does `disable_credential_async(route.credential,
"auth_error_#{status}", error_message)`. The `error_message` comes from
`OpenAIAdapter.extract_error_message/1`, which extracts whatever JSON the
upstream returns. OpenAI's 401 envelope includes a partial key echo
(`sk-proj-…XXXX`). That fragment ends up in `provider_credentials.error_message`.
The dashboard UI only shows `error_reason` (line 669), so it's not visible
in the UI — but anyone with DB read access sees the partial key.

**Fix:** Scrub key prefixes in the adapter before returning the message to
the controller.

### Medium: Session cookie hardening (7b)

`endpoint.ex:7-12` has only `store: :cookie, key: "_my_app_key",
signing_salt: "TwS/TtVu", same_site: "Lax"`. Missing: `encryption_salt`,
explicit `secure: true`, explicit `http_only: true`, `max_age:`. The
session contents today are only UUIDs (`:user_id`, `:impersonator_id`) and
a random `:oauth_state` — Low impact today — but the day someone adds a
token to the session, the missing encryption becomes a leak.

### Medium: `Phoenix.Logger` filter not configured (4e)

`config/config.exs:61-64` doesn't set `config :phoenix, :filter_parameters`.
Default is `[]`. No `Plug.Logger` today, but the day someone adds one (or
a third-party error reporter like Sentry serializes conn params), the
password fields and API keys flow to logs in plaintext.

### Medium: Hardcoded webhook secret fallback (8b)

`webhook_worker.ex:152`:
```elixir
secret = Application.get_env(:MyApp, :webhook_secret, "MyApp-dev-secret")
```
An operator who forgets to set the env var in prod silently signs every
outgoing webhook with a publicly-known string. Fix: `fetch_env!/2`.

### Low: Login error enumeration (8a)

`session_controller.ex:54-69` returns `"Tu cuenta está suspendida."` for a
suspended user and `"Credenciales inválidas."` for unknown. Distinguishes
the two cases. Free to fix: uniform message + log the real reason.

### Low: `force_ssl` excludes localhost (8c)

`prod.exs:14-22` excludes `localhost`/`127.0.0.1` from `force_ssl`. Mostly
a documentation concern — `runtime.exs` raises if `PHX_HOST` is unset, so
the operator has to deliberately set `PHX_HOST=localhost`. Document it.

### Methodology additions this pass

- **Read the `Finch.build` call site** to confirm the proxy builds headers
  from scratch (vs. forwarding `conn.req_headers`). The list of forwarded
  headers is the *single source of truth* — if the adapter builds its own
  list, the proxy controller's filtering is irrelevant.
- **Trace the upstream-error-message path all the way to the DB column.**
  The dangerous part isn't the in-memory pass-through; it's the
  `update_credential(%{error_message: msg})` that persists whatever the
  upstream sent.
- **For session fixation, grep the four sites explicitly** (login, OAuth,
  impersonate start, impersonate stop) and `grep -B 1 'put_session(:user_id'`
  to confirm `configure_session(renew: true)` is on the line before. The
  fix is one line — easy to forget a site when adding a new login path.
- **For PROXY header forwarding, the right question is "what does the
  adapter send up?"** not "what does the controller extract?". The
  controller's `@forwarded_header_keys` is irrelevant if the adapter
  blanket-forwards `conn.req_headers`.
