# Deploy & Runtime Config Security Audit — Session Notes

Findings from the my_app_gateway full-codebase audit (2026-08) that live outside
the web layer: dependencies, Dockerfile, runtime config, data-layer TLS.
These are easy to miss when the audit focuses on router/plugs/LiveViews.

## Checklist additions for any Phoenix deploy audit

### 1. Run `mix deps.audit` and triage the dependency chain

```bash
mix deps.audit
# For each flagged package, find WHY it's in the tree:
grep -n '"<pkg>"' mix.lock        # which dep requires it
mix deps | grep -i <pkg>
```

my_app_gateway case: `hackney 1.25.0` flagged with 4 advisories (SSL
post-handshake without timeout — HIGH, SSRF allowlist bypass, 2x CRLF
injection; all fixed in 4.0.1). It enters via `tzdata` (timezone DB
downloads), not via the app's own HTTP client (`req`/`finch` are clean).
Triage note: surface is limited when the flagged lib only serves an
auxiliary purpose, but still fix — `{:hackney, "~> 4.0", override: true}`
or migrate `tzdata` → `tz` (pure Elixir, drops hackney entirely).

### 2. Dockerfile: security features disabled by default

Grep the Dockerfile for `ARG`/`ENV` pairs that toggle security behavior:

```bash
grep -n 'ARG\|ENV' Dockerfile | grep -i 'ssl\|tls\|secure\|auth\|debug'
```

my_app_gateway case: `ARG DISABLE_FORCE_SSL="1"` as the BUILD DEFAULT — the
shipped image never redirects HTTP→HTTPS and sets no HSTS unless the
operator remembers to override. `force_ssl` is compile-time in Phoenix, so
this choice is baked into the image. Fix: default to `"0"`; the plain-HTTP
deploy (VPN tunnel) sets the ARG explicitly. A security feature that is
opt-IN at build time gets silently dropped; make it opt-OUT.

### 3. Entrypoint + seeds: hardcoded fallback credentials

```bash
grep -rn 'PASSWORD\|SECRET' priv/repo/seeds.exs docker/entrypoint.sh rel/overlays/
```

my_app_gateway case: `seeds.exs` falls back to
`System.get_env("TOKENGATE_ADMIN_PASSWORD") || "my_app_gateway-admin-secret-1"`
and `docker/entrypoint.sh` runs the seed on FIRST BOOT of every deploy.
Any deploy missing the env var gets a root admin with a password committed
to the repo. Fix: `if Mix.env() == :prod, do: raise` when the env var is
absent — never fall back in prod. (Same class as the
`webhook_secret "my_app_gateway-dev-secret"` fallback in webhook_worker.ex —
dev defaults for secrets must never be reachable in prod code paths.)

### 4. Repo SSL without peer verification

```bash
grep -n 'verify_none\|verify_peer\|ssl_opts' config/runtime.exs
```

my_app_gateway case: default branch is
`[ssl: true, ssl_opts: [verify: :verify_none]]` — encrypted but MITM-able
on the network path to Postgres. There's an opt-in env var
(`ECTO_SSL_VERIFY=true` → `verify_peer` + system CAs). Rate Medium when
the DB is reached over anything but loopback/a trusted private net; note
the operator escape hatch exists but isn't the default.

### 5. Session cookie `secure` flag left to request scheme

my_app_gateway's endpoint defaults to Plug behavior (secure only when the
request itself is HTTPS) unless `SESSION_COOKIE_SECURE=true` is set. On an
HTTPS deploy behind a proxy that terminates TLS, verify `force_ssl` +
`rewrite_on: [:x_forwarded_proto]` are actually in effect, otherwise
cookies may be set without `Secure`. Info-level: recommend setting the env
var explicitly in deploy docs.

## What verified CLEAN in my_app_gateway (don't re-report)

- Session cookies: encrypted, `http_only`, `SameSite=Lax`, `renew: true`
  on every `put_session(:user_id)` (login, logout, impersonation start/stop,
  OAuth), sliding max_age, prod salts from env with `raise` on missing.
- `config :phoenix, :filter_parameters` IS configured (password, secret,
  token, api_key, client_secret, authorization).
- `prod.exs` `force_ssl` with HSTS by default at compile time (the
  Dockerfile ARG is what undermines it — finding #2 above, not prod.exs).
- `check_origin` configurable via `CHECK_ORIGINS` env; omitted by default
  (Phoenix default against configured URL).
- dev_routes (LiveDashboard + mailbox preview) compile-gated, absent in prod.
- Oban queues reasonable, Pruner plugin present, no Oban Web exposed.
- Container runs as non-root `app` user; entrypoint fails closed on
  migration error (`set -e`).

## Report-format preference (Álvaro, 2026-08)

When asked for a findings table, deliver ONE severity-ordered table with
columns: # | severity (emoji + label) | finding | file:line | fix. Follow
it with a "verified clean" table (area + why safe) and a short top-3
remediation order. Don't split findings across many sections when a table
was requested — the first pass report was prose-per-category and got the
explicit follow-up "arma una tabla con niveles de severidad".
