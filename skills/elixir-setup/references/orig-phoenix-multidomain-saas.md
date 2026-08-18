---
name: phoenix-multidomain-saas
description: "Architect multi-domain SaaS on an Elixir/Phoenix umbrella."
version: 1.0.0
author: chaos manager
license: MIT
metadata:
  hermes:
    tags: [elixir, phoenix, umbrella, multi-tenant, multi-host, saas, architecture, MyApp]
    related_skills: [elixir-umbrella-feature-build, phoenix-release-deploy, ecto-query-pitfalls, liveview-data-performance]
---

# Phoenix Multi-Domain SaaS Architecture

Use when designing or scaffolding a SaaS platform that serves MULTIPLE domains
(customer domains, satellite domains, subdomains) on one Elixir/Phoenix
codebase — the "one umbrella, many storefronts" pattern. Covers the app
layout, the multi-host resolution plug, the two-layer tenant model, and the
security/performance principles that must be baked in from day 1 (not
patched later).

## When to use

- User wants to build a platform where each customer (or each satellite
  brand) gets its own domain/host served by the same system.
- Designing an umbrella before writing schemas: decide the app boundaries
  FIRST, so later features build on a stable skeleton.
- Reviewing an existing multi-domain app for tenant isolation or hot-path
  problems.

## Reference umbrella layout (validated pattern)

Separate the app into: one pure-domain app, zero-or-more OTP apps (no HTTP),
and one web endpoint per front. Rule of gold: **`core` depends on nothing;
every other app depends on `core` only.**

```
MyApp/  (umbrella)
├── core/          ← domain pure: schemas, contexts, Repo, migrations (NO web)
├── harness/       ← OTP app (no port): agents, GenServers, orchestration, queues
├── channels/      ← OTP app (no port): persistent messaging connections (WhatsApp, Telegram)
├── portal/        ← 4000 — marketing + customer control center (the platform's own client area)
├── communities/   ← 4001 — product A: membership/community sites (Skool-like), multi-host
├── landings/      ← 4002 — product B: landing/funnel builder + multi-host publication
└── api/           ← 4003 — machine frontier: integrations, bots, webhooks, agent
```

Decisions that shaped this layout (keep them when adapting):

1. **Two-layer SaaS model**: the platform sells to its customers, who deliver
   products to THEIR end users. The platform's own customer area (control
   center: configure products, own courses/mentorships, billing) lives in the
   portal app; the products the platform's customers deliver (communities,
   landings) live in their own apps, multi-host, on the customer's domains.
2. **Naming**: name apps for the PRODUCT they serve, not the role of the
   consumer. `communities` (not `members`) — because `member` is the end-user
   role, `communities` is the product. Distinct names, distinct meanings.
3. **Separate the builder from its publication runtime**: the landing/website
   builder UI is a LiveView inside the member/dashboard app; the multi-host
   runtime that SERVES published pages is its own endpoint (or a mode of the
   product app). The machine API (integrations, bots) is a separate app with
   its own auth (API keys), rate limits, and lifecycle — never share the
   browser session pipeline with it.
4. **OTP apps without ports are legitimate members of the umbrella.** Agents
   (harness) and persistent connections (channels) are long-lived processes
   with their own supervision trees and failure modes. They get their own
   apps so a WhatsApp reconnect storm doesn't restart the orchestration, and
   hot-reload can't touch them.
5. **Migrate in exactly one place** (core). Web apps share one Repo; only one
   deploy step runs migrations.

## Multi-host resolution pattern

One endpoint serves N hosts. The `Host` header (or `x-forwarded-host` behind
a proxy) is the tenant key. A plug resolves host → tenant → branding, once
per request, cached in ETS.

```elixir
defmodule LandingsWeb.Plugs.Site do
  import Plug.Conn

  def call(conn, _opts) do
    case Sites.resolve(conn.host) do
      {:ok, site} -> conn |> assign(:site, site) |> assign(:site_host, conn.host)
      :error -> conn |> put_status(:not_found) |> halt()
    end
  end
end
```

Resolution supports two kinds of tenants on the same endpoint:

```elixir
def resolve(host) do
  case Repo.get_by(Site, host: host, status: :active) do
    nil ->
      # not a fixed brand site → is it a customer-published landing?
      case Repo.get_by(Landing, domain: host, status: :published) do
        nil -> :error
        landing -> {:ok, %{type: :client_landing, landing: landing}}
      end
    site -> {:ok, %{type: :site, site: site}}
  end
end
```

Then render branding/layout from `conn.assigns.site` (layout id, colors,
GA4, meta). LiveView: same single LiveView, reads `socket.assigns.site`.

**Cache rule (inherited from my_app_gateway):** resolve via ETS with short TTL
(~60s), `:public` + `read_concurrency: true`, invalidate explicitly on
publish/unpublish, NEVER cache invalid/missing keys (anti brute-force table
growth), and degrade gracefully if the ETS table is absent (`whereis` guard +
`rescue ArgumentError`) — cache is an optimization, never a hard dependency.
Named ETS tables of new GenServers do NOT exist on already-running nodes
(hot-reload doesn't restart the supervision tree); code touching them must
survive their absence.

## Deploy topology (Coolify and similar)

- **One container, many ports** (start): one resource/build; the release
  boots all web apps on the same BEAM node, each on its port (4000-4003);
  map domains → ports in the proxy. One build, one migration step, one log
  surface.
- **One resource per app** (when a front grows alone): per-app `mix release`
  (`MIX_ENV=prod mix release <app>`), per-app Coolify resource/domain.
  Extraction is free because the umbrella is already partitioned.
- The proxy (Traefik/Caddy) terminates TLS and forwards `x-forwarded-host`;
  configure `trusted_proxies` so Phoenix honors it, and `force_ssl` per app
  in `prod.exs` (compile-time).

## Security & performance principles — from day 1

Full distilled bank (commits that paid for these lessons): see
`references/security-performance-principles.md`. The non-negotiables:

- **Fail closed**: nil/error/unknown → denied. Never default-open in
  multi-tenant lookups, auth, or context resolution.
- **Rate limit auth** (login per IP, API keys per token) with ETS
  fixed-window; clear counter on success.
- **Sessions**: sliding expiration (`renew: true`), short max_age (~4h),
  secure+httpOnly+SameSite; token/API-key values NEVER in the DOM (prefix +
  `push_event` copy); mask credentials for non-admins; filter sensitive
  params from logs.
- **Web hardening**: CSP without `unsafe-inline`, body caps in Plug.Parsers,
  CSV formula-injection neutralization, audit log for sensitive admin
  actions, `mix_audit` in precommit.
- **Hot path**: ETS auth cache (60s TTL, invalidate on rotation), batch
  queries (`WHERE id IN (...) GROUP BY` → map), iodata accumulation, no
  decode on fast-path, composite indexes `(foreign_key, inserted_at DESC)`,
  atomic counters for metrics, debounce with ETS `insert_new` mark.
- **N+1**: helpers receive DATA not structs (change the signature, don't add
  preloads); batch per-item loops into one aggregate query. See the
  `n-plus-one-cookbook` concept in MyApp and `ecto-query-pitfalls` /
  `liveview-data-performance` skills.
- **Resilience**: circuit breaker on every external integration (GHL,
  Systeme.io, WhatsApp, LLM); kill stream tasks on first-token timeout.

## Pitfalls

- **`core` depending on a web app** — bidirectional deps defeat the purpose;
  the Qi flows one way: core → everyone.
- **Creating schemas/tables in the foundation plan** — the skeleton plan
  (apps + config + conventions) must stay schema-free so features arrive in
  later plans on a stable base.
- **One port per domain** — wrong mental model. Ports belong to ENDPOINTS;
  domains map to ports via the proxy. One endpoint can serve many domains.
- **Builder UI in the wrong app** — the editor is a dashboard feature; the
  publication runtime is multi-host. Don't fuse them into a "funnels app"
  unless the builder IS the product with its own deploy cycle.
- **Membership confusion** — the end-user role is `member`; the product app
  is `communities`. Keep names distinct or the codebase gets ambiguous.
- **Updating plan/project pages in MyApp with meta+body together** — strips
  mermaid blocks; pass body only.

## References

- `references/security-performance-principles.md` — distilled lessons from
  the my_app_gateway and MyApp repositories (security audit, hot-path perf,
  hardening), with commit references.