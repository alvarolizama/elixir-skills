# Multi-domain SaaS on one Phoenix umbrella

Architecture pattern for serving MULTIPLE customer domains on one
Elixir/Phoenix codebase — "one umbrella, many storefronts". Decide the app
boundaries BEFORE writing schemas so later features build on a stable split.

## Reference umbrella layout

```
MyApp/  (umbrella)
├── core/          ← domain pure: schemas, contexts, Repo, migrations (NO web)
├── harness/       ← OTP app (no port): agents, GenServers, orchestration, queues
├── channels/      ← OTP app (no port): persistent connections (WhatsApp, Telegram)
├── portal/        ← 4000 — platform's own customer control center
├── communities/   ← 4001 — product A: membership/community sites, multi-host
├── landings/      ← 4002 — product B: landing/funnel builder, multi-host
└── api/           ← 4003 — machine frontier: integrations, bots, webhooks
```

Rules that shaped it (keep them):

1. **Two-layer SaaS**: the platform sells to customers who deliver products to
   THEIR end users. Platform's own area = portal; customer-delivered products
   = their own multi-host apps.
2. **Naming**: name apps for the PRODUCT they serve, not the consumer role —
   `communities`, not `members` (`member` is the end-user role). Distinct
   names, distinct meanings.
3. **Separate the builder from its publication runtime**: the landing-page
   builder UI lives in the dashboard app; the multi-host runtime that SERVES
   published pages is its own endpoint. The machine API (bots/webhooks) is a
   separate app with its own auth (API keys), rate limits, and lifecycle —
   never share the browser-session pipeline with it.
4. **OTP apps without ports are legitimate umbrella members**: harness and
   channels get their own supervision trees, so a WhatsApp reconnect storm
   doesn't restart orchestration and hot-reload can't touch them.
5. **Migrate in exactly one place** (`core`). All web apps share one Repo;
   one deploy step runs migrations.

Rule of gold: **`core` depends on nothing; every other app depends on `core`
only.**

## Multi-host resolution pattern

One endpoint serves N hosts. The `Host` header (or `x-forwarded-host` behind
a proxy) is the tenant key. A plug resolves host → tenant once per request,
cached in ETS:

```elixir
defmodule MyAppWeb.Plugs.Site do
  import Plug.Conn

  def call(conn, _opts) do
    case Sites.resolve(conn.host) do
      {:ok, site} -> conn |> assign(:site, site) |> assign(:site_host, conn.host)
      :error -> conn |> put_status(:not_found) |> halt()
    end
  end
end
```

Two tenant kinds share one endpoint:

```elixir
def resolve(host) do
  case Repo.get_by(Site, host: host, status: :active) do
    nil ->
      case Repo.get_by(Landing, domain: host, status: :published) do
        nil -> :error
        landing -> {:ok, %{type: :client_landing, landing: landing}}
      end
    site -> {:ok, %{type: :site, site: site}}
  end
end
```

Branding/layout renders from `conn.assigns.site` (layout id, colors, GA4,
meta). LiveView: one LiveView reads `socket.assigns.site`.

**Cache rule.** Resolve via ETS with short TTL (~60s), `:public` +
`read_concurrency: true`, invalidate explicitly on publish/unpublish, NEVER
cache invalid/missing keys (anti brute-force table growth), and degrade
gracefully if the table is absent (`whereis` guard + `rescue ArgumentError`).
Named ETS tables of NEW GenServers do NOT exist on already-running nodes —
hot-reload does not restart the supervision tree. The cache is an
optimization, never a hard dependency; an unguarded cache has taken down a
whole proxy.

## Deploy topology

- **One container, many ports** (start): one build; the release boots all web
  apps on one BEAM node, each on its port (4000–4003); map domains → ports in
  the proxy. One build, one migration step, one log surface.
- **One resource per app** (when a front grows alone): per-app
  `MIX_ENV=prod mix release <app>`, per-app Coolify resource/domain.
  Extraction is free because the umbrella is already partitioned.
- The proxy (Traefik/Caddy) terminates TLS and forwards `x-forwarded-host`;
  configure `trusted_proxies` so Phoenix honors it, and set `force_ssl` per
  app in `prod.exs` (compile-time — see
  `runtime-config-overrides.md`).

## Security & performance non-negotiables (bake in day 1)

- **Fail closed**: nil/error/unknown → denied, never default-open in
  multi-tenant lookups, auth, or context resolution.
- **Rate limit auth** (login per IP, API keys per token hash) with ETS
  fixed-window; clear the counter on success; never cache invalid/missing
  keys long.
- **Sessions**: sliding expiration (`renew: true`), short max_age (~4h),
  secure + httpOnly + SameSite. Token/API-key values NEVER in the DOM
  (prefix-only + `push_event` copy); mask credentials for non-admins; filter
  sensitive params from logs.
- **Web hardening**: CSP without `unsafe-inline`, body caps in `Plug.Parsers`
  (10MB length / 1MB read_length), CSV formula-injection neutralization
  (prefix `'` on values starting `= + - @`), audit log for sensitive admin
  actions, `mix_audit` in precommit (catches transitive CVEs).
- **Hot path**: ETS auth cache (60s TTL, invalidate on rotation/revocation),
  batch queries (`WHERE id IN (...) GROUP BY` → map lookup), iodata
  accumulation (never `binary <> acc`), `compress: true` on the endpoint,
  composite indexes `(foreign_key, inserted_at DESC)`.
- **N+1**: change the helper SIGNATURE to receive data, not structs; use
  `maybe_preload` with `Ecto.assoc_loaded?/1`; push the search excerpt into
  the main query select. Caps as defense: hard per-list limits.
- **Resilience**: circuit breaker on every external integration
  (closed → open after N consecutive failures → half-open probe); kill
  stream tasks on first-token timeout (fd-leak prevention).

## Pitfalls

- **`core` depending on a web app** — bidirectional deps defeat the split; the
  dependency flow is one way: core → everyone.
- **Creating schemas/tables in the foundation plan** — the skeleton plan
  (apps + config + conventions) stays schema-free so features arrive on a
  stable base.
- **One port per domain** — wrong mental model: ports belong to ENDPOINTS;
  domains map to ports via the proxy. One endpoint serves many domains.
- **Builder UI in the wrong app** — the editor is a dashboard feature; the
  publication runtime is multi-host. Don't fuse them into a "funnels app"
  unless the builder IS the product with its own deploy cycle.
- **Membership confusion** — the end-user role is `member`; the product app
  is `communities`. Keep the names distinct.

## Verification

```bash
mix compile --warnings-as-errors && mix test        # after wiring each app
# resolution is fail-closed:
curl -s -o /dev/null -w "%{http_code}" -H "Host: unknown.example.com" http://localhost:4000/   # 404
curl -s -o /dev/null -w "%{http_code}" -H "Host: site-a.example.com"   http://localhost:4000/   # 200
```