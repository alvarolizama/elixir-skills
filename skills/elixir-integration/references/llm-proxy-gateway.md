# LLM Proxy Gateway

Operating an LLM proxy in Elixir: the hot path, retry/fallback, circuit
breaking, idempotency, provider dialects, observability, and access control.
Every pattern is symptom → mechanism → fix → verification.

## Hot path discipline

**Symptom.** p99 latency is hundreds of ms before the first upstream byte;
Postgres is the top wait event under load.

**Mechanism.** Per-request work (auth, limits, routing, budget checks) is
hitting Postgres synchronously. Streaming proxy throughput collapses
because every token-carrying request pays DB round-trips.

**Fix.** The hot path reads ETS/`:atomics` ONLY: credentials, limits,
budgets, breaker states are cached there and refreshed by Oban jobs.
Postgres writes (request logs, webhooks, rollups) go through Oban, async.
No DB query per request on the hot path — no exceptions for "just one
lookup".

**Verification.** Load test with DB query tracing: zero synchronous queries
from the proxy plug pipeline.

## Three throttle gates

All three must pass before forwarding — they protect different resources:

1. **Team limits** — client-side abuse (requests/min, tokens/day).
2. **Credential limits** — upstream rate limits per API credential.
3. **Per-user concurrency** — inside shared subscriptions; one user's 20
   parallel streams starve a whole team otherwise.

Skipping gate 3 is invisible until one power user's batch job 429s everyone
on the same credential.

## Circuit breaker per credential

**Symptom.** One expired credential burns every request's timeout budget;
or one 429 storm trips the whole provider for healthy credentials.

**Mechanism.** Breaker keyed too broadly (per provider) or too narrowly
(per request); thresholds of 1 trip on transient errors.

**Fix.** One `:gen_statem` per credential. Threshold > 1 (use 5). Short
cooldowns: 60s for server/timeout errors, 10s for rate limits. Only one
half-open probe in flight. `:auth_error` NEVER trips the breaker — auth
failures permanently deactivate the credential in the DB (retrying a 401
never helps).

**Verification.** Test: 5 timeouts → breaker opens; next request gets
immediate fallback (assert on timing, not just status); 401s deactivate
the credential instead of opening the breaker.

## Fallback and retry policy

**Symptom.** Upstream blips produce user-visible errors, or a working
provider is excluded after a single failure.

**Mechanism.** Timeouts and fast errors need different handling, and
exclusion on first attempt throws away healthy capacity.

**Fix.**

- Timeouts: fall back immediately (the caller is already paying the wait).
- Fast errors (connection refused, 5xx): retry the SAME provider up to N
  times with a per-provider retry counter, THEN exclude it for this
  request.
- Never exclude on the first attempt.
- **Streaming:** all fallback decisions happen BEFORE
  `send_chunked(200)` — after headers are sent, no fallback exists. Gate
  the commit on the first-token timeout.

**Verification.** `mix test test/my_app_web/proxy --trace`:

- timeout → immediate fallback (timing assertion);
- fast 500 → same provider retried, then excluded (hit-count assertion);
- streaming request whose upstream never sends a first token → falls back
  before any bytes reach the client.

## Never stack retries

**Symptom.** Latency p99 explodes under provider degradation; request logs
show attempt counts of 9+.

**Mechanism.** The agent loop owns retries (backoff, error classification,
per-step timeouts) AND the HTTP client (`Req`, default `retry: :safe`
transient) retries too. Client × engine retries compound exponentially.

**Fix.** One layer owns retries. If the agent loop does, set the HTTP
client's `retry: false`. If the client owns them, the loop treats a
response as final. Document which layer owns it for every call site.

**Verification.** `grep -rn "retry:" lib/` — every outbound LLM call site
states its retry ownership explicitly.

## Idempotency keys

**Symptom.** A retry after a network blip charges the client twice, or
completes two upstream generations for one user action.

**Mechanism.** The key is regenerated per attempt (per retry, per
fallback) instead of per client request, or it is set in some call paths
and not others.

**Fix.** ONE key per client request: generate a UUID at the entrypoint,
inject at the SINGLE header-forwarding chokepoint, reuse across every
retry AND fallback. Deduplicate upstream-side by the key.

**Verification.** Test: simulated timeout + fallback produces exactly one
upstream record with the SAME idempotency key on both attempts.

## Provider dialects: data-driven translation

**Symptom.** Every new provider adds an adapter module; the modules drift
(e.g. one forgets the embeddings dimension field) and double the test
matrix.

**Mechanism.** Per-provider modules copy-paste encode/decode logic; the
OpenAI shape is the de-facto lingua franca but is re-implemented each time.

**Fix.** Keep the OpenAI-compatible shape (and the rerank shape) as the
internal format; translate with a data-driven `{encode, decode}` function
registry resolved from provider metadata (a map in config, not a module
per provider). `base_url` in provider config must include the FULL API
base path; the adapter appends only the endpoint (e.g. `/chat/completions`)
— half-paths produce 404s that look like auth failures.

**Verification.** Adding a provider = adding a config entry + encode/decode
pair + fixtures; no new module files. `base_url` fixtures end with the
version segment (`/v1`).

## Observability

- OTLP with GenAI semantic conventions for spans/metrics (token usage,
  model, request duration).
- Fallback chains: one trace, multiple spans — each attempt is a span
  sharing the `traceId`, so a "failed then succeeded" request reads as a
  chain, not as unrelated requests.
- Webhooks for usage events in an OpenRouter-compatible format.

## Access control layers

In order of strength (use the strongest that fits):

1. Router `live_session :admin` + `on_mount` guard — admin-only pages.
2. Mount-level guard — data-dependent checks (manager of THIS team).
3. Template `@is_admin` assigns — COSMETIC ONLY, never a control.

A template-only check is not access control: the socket still fires
events. Every mutating `handle_event` re-checks on the server.

## Carry the upstream error message

**Symptom.** "Upstream server error" in logs/admin UI; debugging requires
correlating timestamps with provider status pages.

**Mechanism.** Only the reason atom survives; the upstream message body is
dropped at the adapter boundary.

**Fix.** Carry `{status, message}` end-to-end — breaker decisions, request
logs, admin UI all show the message. Redact secrets in messages before
persistence (a leaked key in a provider error message must not land in the
log).
