# my_app_gateway Re-Audit Delta (2026-08, session audit)

Quick interactive re-audit (no subagents) after the big scope-1/scope-2 audits.
Value: which scope-2 findings remain open + net-new items + TWO self-corrections
where the session report flagged things already fixed.

## Still open (confirmed on disk this session)

- **S2-1 CRITICAL** — `credential.api_key_encrypted` still plaintext
  (moduledoc line 3-4 unchanged, no cloak/crypto in lib/). Remains the #1 fix.
- **hackney 1.25.0 via tzdata** — `mix deps.audit`: 4 advisories (1 high SSL
  post-handshake timeout, SSRF normalize bypass, 2x CRLF injection), all fixed
  in 4.0.1. Surface: tzdata DB downloads only. Fix: `{:hackney, "~> 4.0", override: true}`
  (verify tzdata compat) or migrate to the `tz` package (pure Elixir).
- **seeds.exs:11** — prod default admin password `my_app_gateway-admin-secret-1`
  still the fallback when TOKENGATE_ADMIN_PASSWORD unset. Fix: raise in prod.
- **Webhook destination SSRF** — still no URL/IP validation on admin-registered
  `observability_destinations.url`. Admin-only so Low/Medium.
- **CSP `script-src 'unsafe-inline'`** — still present (router.ex:13);
  S2 verified no inline scripts exist, so it could be dropped.

## Self-corrections (session reported these; they were ALREADY fixed)

- ❌ "CSV formula injection in stats_export_controller" — FALSE.
  `csv_sanitize_formula/1` exists (~line 298) and prefixes `= + - @ \t \r`;
  it was applied to the log/error rows during the original remediation wave.
  Lesson: grep for the fix function before flagging.
- ❌ "No rate limiting on /login" — FALSE. `lib/tokengate_web/plugs/attack.ex`
  exists (IP throttle plug in the endpoint). Lesson: `ls plugs/` before
  claiming a missing control.

## Verified-good (re-confirmed)

- API keys: sha256 hash-before-lookup, `strong_rand_bytes(24)`, prefix-only display.
- Login: Bcrypt + no_user_verify, uniform error (no email enumeration).
- Sessions: encrypted cookie, SameSite=Lax, renew:true, sliding max_age 4h,
  prod salts required via runtime raise.
- OAuth: secure_compare on state, domain allowlist fail-closed.
- Impersonation: admin-only, no-self, root-admin protected, audited.
- Proxy: forwards only whitelisted headers (user-agent/http-referer/x-title) —
  no client Authorization leak upstream.
- request_logs stores no prompts/completions; upstream error messages scrubbed.
- Prod: force_ssl default-on (build-time opt-out), check_origin env-configurable.
