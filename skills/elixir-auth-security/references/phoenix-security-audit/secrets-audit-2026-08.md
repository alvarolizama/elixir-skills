# my_app_gateway Scope-2 Audit — Secrets, Sessions, OAuth, Config (Aug 2026)

Repo: `alvarolizama/my_app_gateway` (Phoenix 1.8 LLM proxy gateway; stores upstream
provider API keys). Read-only subagent audit per spec `/tmp/tg-audit-scope2-secrets.md`.
Headline: **CRITICAL plaintext upstream keys at rest** (4a), **HIGH plaintext keys
in LiveView socket assigns** (4c). 10 findings total (1C / 1H / 4M / 4L).

⚠️ Context: the parent agent ran **parallel remediation during the audit** — the
working tree changed mid-audit (endpoint.ex gained the Plug.Parsers cap +
`Plugs.Attack`, accounts.ex gained the suspended-branch timing fix, runtime.exs
gained the `LIVE_VIEW_SIGNING_SALT` override). Line numbers below = disk state at
audit end; see the "concurrent remediation" pitfall in SKILL.md.

## Findings (S2-n)

- **S2-1 CRITICAL 4a** — `providers/credential.ex:3-4,25` + migration
  `20260725230002:8`. `api_key_encrypted` stores provider keys AS-IS
  (moduledoc admits "encryption-at-rest is a post-MVP concern"); `:string`
  column, zero encrypt/decrypt/Cloak in lib/. Every OpenAI/Anthropic key
  recoverable from any DB dump. Fix: cloak_ecto or crypto_one_time_aead →
  `:binary` column, key in env with runtime raise, rotate keys.
- **S2-2 HIGH 4c** — Full plaintext keys preloaded into socket assigns while
  only last-4 renders: `providers_live.ex:56-63,635`, `models_live.ex:97-108,
  727-729,1079`, `monitor_live.ex:115-137`, `team_members_live.ex:1221-1223`.
  In-template `mask_key` only; no SQL projection. Fix: `right(?, 4)` fragment
  projection or virtual `masked_key`.
- **S2-3 MEDIUM 10b/8e (contradicted parent's verified-good)** — endpoint.ex
  `@session_options:16-30` freezes `SESSION_SIGNING_SALT`/`SESSION_ENCRYPTION_SALT`
  at compile time with repo defaults; runtime.exs:151-158 raise checks presence
  but never configures Plug.Session; Dockerfile has no SESSION_* build ARGs →
  env rotation is a silent no-op. Medium (not High) because `secret_key_base`
  IS runtime. Fix: build ARGs or a module plug reading salts at boot.
- **S2-4 MEDIUM 4b-variant** — Edit-credential modal embeds the FULL key in the
  DOM: `providers_live.ex:211-219,482-496` + `core_components.ex:320-329`
  (`value={normalize_value(...)}` renders for password inputs too). Fix: blank
  the field in the edit changeset (handler already treats empty = keep).
- **S2-5 MEDIUM 8f** — `proxy_controller.ex:1544` catch-all
  `error_details(other)` sends `inspect(other)` to API clients in the 500 JSON
  body. Fix: static message + server-side Logger.
- **S2-6 MEDIUM 4c/4d-variant** — Key fragments: `monitor_live.ex:241-245`
  displays FIRST 8 chars (whole-key fallback ≤8 bytes);
  `proxy_controller.ex:1289,1385,1430-1434` persists last-4 into
  `request_logs.provider_key_prefix` (permanent partitioned table, rendered in
  logs_live.ex:662-666), same whole-key fallback ≤4 bytes. Fix: last-4
  everywhere, `"****"` fallbacks, consider dropping the column.
- **S2-7 LOW 8d** — `logs.ex:213` `"%#{search}%"` ilike without escaping
  (admin-only LogsLive). Fix: copy escape from `Accounts.search_users/2`.
- **S2-8 LOW 8b** — `webhook_worker.ex:152` `"my_app_gateway-dev-secret"` HMAC
  fallback; prod-mitigated by runtime.exs:143-145 raise. Signing itself is
  proper HMAC-SHA256 at runtime.
- **S2-9 LOW retention** — `audit_logs` unbounded (no prune job; Oban crontab
  only Budgets.ResetWorker); `request_logs` default partition grows forever
  (daily-partition cron "post-MVP" per migration moduledoc).
- **S2-10 LOW 4b-variant** — Webhook destination `headers` map (customer
  Bearer tokens) rendered as JSON into edit-form textarea DOM
  (`teams_live.ex:527-534`; `destination.ex:18`).

## Verified-good (highlights)

- App-issued API keys hashed sha256 + prefix, hash-before-lookup
  (`accounts.ex:461-474, 630-643, 872-885`); bcrypt passwords; no `api_token`
  on users; `@derive Jason.Encoder` excludes `password_hash`.
- `authenticate_user/2` timing-safe in ALL branches (suspended branch fix
  landed mid-audit as uncommitted WIP, accounts.ex:308).
- `search_users/2` escapes `\ % _`, prefix-only, min 3 chars, limit 10.
- Upstream 401/402/403 error messages scrubbed (`sk-|gsk_|sk-ant-|...` →
  `[REDACTED]`) + truncated BEFORE persisting to credentials/request_logs
  (`openai_adapter.ex:354-372`); streaming path persists no error bodies.
- `filter_parameters` configured (`config.exs:86-93`, covers api_key → also
  matches `api_key_encrypted` via substring).
- Zero `String.to_atom` in lib/; zero IO.inspect; no secret-adjacent Logger.
- Webhook signing = real HMAC-SHA256 via `:crypto.mac/4`, runtime read.
- No inline `<script>` in layouts (root.html.heex:11-12 external bundle only)
  → CSP `script-src 'unsafe-inline'` gratuitous; `style-src` still needed for
  `style={...}` chart attributes.
- API bearer auth: hash-then-query, uniform 401 (`plugs/api_auth.ex:27-65`).
- Audit log payload clean (impersonation emails only).

## Parent-scope (not re-reported)

endpoint.ex cookie attrs, runtime.exs fail-closed secrets, oauth_controller
state/renew, google.ex domain allowlist + legacy /userinfo (no id_token /
verified_email), session_controller uniform login error, router CSP with
'unsafe-inline', Plug.Parsers length cap, DB SSL verify_none opt-in.
