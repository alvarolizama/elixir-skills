---
name: llm-proxy-gateway
description: "Design and build an LLM proxy/gateway: OpenAI-compatible API passthrough, multi-provider routing (priority fallback, circuit breakers, sticky routing for prompt caching), budgets, rate limiting, and OTLP observability webhooks. Elixir/OTP primary stack."
version: 1.2.0
author: Álvaro Lizama
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [llm, proxy, gateway, elixir, otp, phoenix, openai, observability, otel]
    related_skills: [phoenix-umbrella-project-setup, elixir-umbrella-feature-build, plan]
---

# LLM Proxy Gateway

Use when designing or building an LLM proxy/gateway — a middleware between AI agents and LLM providers that is drop-in compatible with the OpenAI API.

Covers: architecture patterns, provider abstraction, routing strategies (priority fallback with sticky routing, circuit breakers), rate limiting, budgets, OTLP observability webhooks (OpenRouter-compatible), and real-time dashboards.

Primary stack: Elixir + Phoenix LiveView + Postgres (no Redis needed). Patterns are transferable to Go/Rust with adapted primitives.

## When to use

- User wants to build an LLM proxy, gateway, or middleware between agents and providers
- User wants OpenAI-compatible API passthrough with multi-provider routing
- User wants OpenRouter-style observability webhooks (OTLP traces)
- User asks about round robin, fallback, circuit breakers, or sticky routing for prompt caching
- User needs rate limiting, budgets, or cost tracking across providers

## Quick navigation

| Topic | Reference |
|-------|-----------|
| **Core architecture & request lifecycle** | this file (below) |
| **Elixir/OTP primitives** (atomics RR, gen_statem breaker, ETS rate limits, concurrency gate, budget sync, SSE passthrough) | `references/elixir-otp-patterns.md` |
| **Circuit breaker & fallback runtime flow** (state machine, cooldowns, error classification chain, sticky routing, tuning checklist) | `references/circuit-breaker-fallback-flow.md` |
| **Upstream error observability** (carrying the provider's error *message* end-to-end: breaker `last_error_message`, `request_logs.error_message`, fallback-attempt rows with status 200, "fallback" badge + "Detalle" column in admin UI, streaming status preservation pitfall) | `references/upstream-error-observability.md` |
| **Gate-error stats invisibility** (pre-routing failures missing `model_alias_id` leave the per-model stats drill-down empty during exactly the bursts that matter; resolve alias by name on the cold error path) | `references/upstream-error-observability.md` (§ Gate-error rows) |
| **Per-provider retry pattern** (timeout vs fast-error policy, adapter tuple-shape pitfall, test recipes) | `references/MyApp-per-provider-retry-pattern.md` |
| **Slow-provider degradation & per-user concurrency** (slow≠dead, latency-health tiers, `{credential_id, key_id}` composite gate, config-vs-web split) | `references/slow-provider-degradation-and-per-user-limits.md` |
| **Live system monitor** (OTP VM + DB health cards in a LiveView ops dashboard — RAM/CPU/processes/DB/IO/uptime, `:erlang.memory()` keyword-list pitfall, honest CPU & DB approximations) | `references/live-system-monitor.md` |
| **Double-retry pitfall** (HTTP client retry × agent engine retry compounding) | `references/double-retry-pitfall.md` |
| **Embeddings & rerank endpoints** (Cohere/Jina normalization, usage estimation) | `references/embeddings-rerank-endpoints.md`, `references/embeddings-rerank-formats.md` |
| **Provider dialect abstraction** (DashScope native rerank, RerankDialect registry, build_url absolute-vs-relative, Ecto changeset get_change vs get_field pitfall) | `references/provider-rerank-dialects.md` |
| **DashScope regions & region-scoped keys** (China vs intl hosts, 401 InvalidApiKey on region mismatch, native endpoint shapes) | `references/dashscope-regions.md` |
| **Access control & auth** | `references/access-control-and-auth.md` |
| **Budget models** | `references/budget-models.md` |
| **OTLP observability** (OpenRouter-compatible webhooks, GenAI semantic conventions) | `references/otlp-implementation-patterns.md`, `references/otlp-genai-semantic-conventions.md` |
| **Provider benchmarks (SSE streaming measurement with Finch — TTFT, TPS, latency, token count; Enum.zip arity pitfall, return type chaining)** | `references/provider-benchmarks-sse-measurement.md` |
| **Cost accounting ops manual** (cost model, throttling, RBAC, stats, audit recipes) | see `MyApp-cost-accounting` skill |

## Core architecture

The proxy sits between agents and providers, speaking the OpenAI API shape on both sides.

```
Client (agent) ──OpenAI API──> Proxy ──OpenAI API──> Provider
                                 │
                                 ├─ auth (API key → team member)
                                 ├─ two-gate throttle (team limits + credential limits)
                                 ├─ routing (priority + sticky + circuit breaker)
                                 ├─ budgets (pre-check + post-record)
                                 └─ observability (OTLP webhooks, request logs, metrics)
```

### Request lifecycle (hot path discipline)

1. **Auth** — resolve API key → team member (ETS-cached).
2. **Team limits gate** — RPM + concurrency per API key (ETS/atomics only).
3. **Route** — alias → model_provider → credential. Priority sort + sticky + breaker availability filter.
4. **Budget pre-check** — has the member exhausted their monthly cap? (ETS spend counter.)
5. **Credential limits gate** — `max_rpm` / `max_concurrent` per credential (ETS). Saturated credential → exclude and re-route instantly, zero latency.
6. **Execute** — forward payload verbatim to the provider (Finch). On failure, apply the retry/fallback policy (see per-provider retry reference).
7. **Post-record** — usage → cost → budget spend (ETS), request log + OTLP webhook via Oban (async, off the hot path).

**Hot path rule:** auth, limits, budgets, and routing read from ETS/atomics only. Postgres is touched asynchronously via Oban. Never run a DB query per request on the hot path.

### Two-gate throttling (now three gates)

Requests pass through two independent throttle layers, with a third gate
added per-user inside a shared credential:

1. **Team limits** — protects the proxy from abusive users (client-side). Derived from team defaults + member overrides, keyed by API key.
2. **Credential limits** — protects the provider API key from upstream rate limits (provider-side). Configured per credential (`max_rpm`, `max_concurrent`), keyed by `credential.id`.
3. **Per-user concurrency** — stops a single heavy user from swallowing every slot of a shared subscription. Keyed by `{credential.id, user_api_key_id}` against `max_concurrent_per_user`. When it trips, only that user falls back; the rest keep the subscription. `nil` = unlimited.

All three gates must pass. Team limits acquired first; credential limits acquired after routing succeeds; per-user gate is checked inside credential acquire (rolled back if it fails so the global slot doesn't leak). See `references/slow-provider-degradation-and-per-user-limits.md` for the full three-gate design and tier-based routing details.

## Provider abstraction

A single `ProviderAdapter` behaviour with one implementation (`OpenAIAdapter`) covering every OpenAI-compatible endpoint. The adapter is a thin transport layer: it forwards the payload exactly as received, classifies HTTP/transport errors into a small `failure_reason()` atom set (`:timeout`, `:server_error`, `:rate_limited`, `:client_error`, `:connection_error`, `:auth_error`), and exposes `chat_completion/4`, `stream_chat_completion/4`, `embeddings/4`, `rerank/4`, `health_check/2`, `list_models/2`.

**Contract pitfall:** keep ONE error tuple arity across the whole adapter contract and assert it in the adapter's own test. See the tuple-shape pitfall in `references/MyApp-per-provider-retry-pattern.md` — a 3-tuple vs 4-tuple drift caused a latent `CaseClauseError` on the exact provider-timeout path, plus a dead `client_error` clause that retried 4xx against other providers.

### Provider dialects (non-Cohere rerank)

Not every provider speaks the Cohere lingua franca for rerank. DashScope uses a nested `input`/`parameters` format at a completely different base URL. **Do NOT create a new adapter module per dialect** — use a data-driven `RerankDialect` registry that resolves from `provider.rerank_dialect` in the DB. The adapter calls `dialect_for(provider)` and gets `:passthrough` (Cohere) or `{encode_fn, decode_fn}` (translate before send / after receive). This keeps the transport layer shared and adding a new dialect to one module + one entry. See `references/provider-rerank-dialects.md` for the full pattern, the `build_url` absolute-URL helper, and the Ecto changeset `get_change` vs `get_field` default-value pitfall.

## Routing strategy

Default: **tiered priority-based selection with sticky routing**. Candidates are sorted by `{tier, priority}` — healthy subscription (`billing_mode == "included"`) providers form the top tier, followed by healthy pay-per-token, then degraded subscriptions, then degraded pay-per-token. Within a tier, priority ASC decides (exclusive providers injected at priority -1). The `CredentialHealth` module (`mark_slow/mark_healthy/degraded?`) provides the health signal; a credential is "degraded" when it answered a request but slower than `slow_threshold_ms`. See `references/slow-provider-degradation-and-per-user-limits.md` for the tier table and the pitfall of getting the order wrong.

If an `api_key_hash` is present, look up the sticky entry; if the stuck provider is among the candidates **and** is available **and** not degraded, return it. Otherwise pick the first available candidate in tier+priority order and stick to it (per-entry TTL, default 15 min). A degraded stuck provider releases the stick so the user flows to a healthy tier.

Providers can be scoped: **global**, **member-exclusive**, or **team-exclusive**. Exclusive providers are injected at the front for the matching scope; if they fail, the normal pool takes over.

Callers pass `:exclude_credential_ids` to drop credentials from the candidate set — the mechanism behind retry-after-failure fallback. The retry POLICY (when to exclude, when to retry the same provider) lives in `references/MyApp-per-provider-retry-pattern.md`: **timeouts fall back immediately, fast errors retry the same provider up to 3 times.**

## Streaming

SSE passthrough with first-token fallback: nothing is sent to the client until the provider's first chunk arrives. If it never does (timeout or error), record the failure and fall back BEFORE committing to a 200. Once `send_chunked(200)` is sent, mid-stream failures close the stream and no fallback is possible.

`first_token_timeout_ms` default is **30s** (was 15s — too aggressive, killed slow-but-alive providers on cold prompt). On a first-token timeout, fall back immediately — do not retry the same provider (see timeout policy in the retry reference).

`stream_options: {include_usage: true}` is the single sanctioned payload mutation — it makes the provider report real usage for cost accounting.

## Cost accounting

Trust the upstream to report what it charged via `usage.cost` / `usage.cost_usd`. The proxy normalizes provider-specific usage shapes, computes `cost_usd` (provider price) and `estimated_cost_usd` (market price), injects them into the response `usage` object, and sets `X-MyApp-Cost` / `X-MyApp-Savings` headers. When the upstream omits usage, fall back to a chars/4 estimator. See the `MyApp-cost-accounting` skill for the full ops manual.

## Verification checklist

- `mix compile --warnings-as-errors` clean
- Full test suite green (`mix test`), including proxy end-to-end tests through a live Bandit mock
- Retry policy covered: timeout falls back immediately (timing assertion), fast 500 retries same provider (hit-count assertion), streaming first-token fallback
- No DB queries on the hot path (auth/limits/routing all ETS)

## Key stack decisions

- **No Redis** — all state (rate limits, sticky routes, budgets, metrics, in-flight) lives in BEAM primitives (ETS, atomics, gen_statem). Simpler ops, lower latency, no external dependency.
- **Oban for async writes** — request logs, webhook delivery, rollups. Keeps Postgres off the hot path.
- **Bandit mock for tests** — a real HTTP provider plug lets proxy tests exercise the full fallback matrix end-to-end through the endpoint.