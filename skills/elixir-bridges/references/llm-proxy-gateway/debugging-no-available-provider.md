# Debugging `no_available_provider` 503s (routing layer rejects everything)

Session: 2026-07-27. Symptom: `POST /v1/chat/completions` returns
`503 {"error":{"code":"no_available_provider","message":"All providers are currently unavailable"}}`
in ~15ms, while `GET /v1/models` with the same API key returns 200.

## Diagnostic chain (in order)

1. **Split auth from routing.** `GET /v1/models` uses the same `ApiAuth` plug
   but no routing/breaker logic. If `/v1/models` is 200, the API key and team
   grants are fine — the problem is downstream (candidates filter or breaker).
2. **Check the DB candidate set** (all must be true for a candidate to survive
   `Router.route_alias/6` filters):
   ```sql
   SELECT ma.name, mp.provider_model, mp.enabled, pc.status, pc.error_reason, p.status
   FROM model_providers mp
   JOIN model_aliases ma ON ma.id = mp.model_alias_id
   JOIN provider_credentials pc ON pc.id = mp.credential_id
   JOIN providers p ON p.id = pc.provider_id;
   ```
   Also verify the team grant exists (`team_model_aliases` row for the team)
   — note `/v1/models` proves this already.
3. **Suspect the in-memory circuit breaker when the 503 is instant.** With
   `threshold: 1` and `cooldown_ms: 1_800_000`, ONE transient failure
   (timeout, 5xx) opens the breaker for 30 minutes and every later request
   fails fast with `no_available_provider` — without touching the upstream.
   Breaker state is in-memory (`:gen_statem` per credential), so **restarting
   the dev server is the decisive experiment**: if requests route again after
   restart, the breaker was open. Note: `:auth_error` and `:client_error`
   (4xx) never trip the breaker; only `:server_error`/`:timeout` (30 min) and
   `:rate_limited` (10 min) do.
4. **Reproduce the upstream call directly with the stored credential** to
   isolate proxy-side mutation bugs from provider-side problems:
   ```bash
   KEY=$(psql ... -tA -c "SELECT api_key_encrypted FROM provider_credentials LIMIT 1;")
   curl -s https://openrouter.ai/api/v1/chat/completions \
     -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
     -d '{"model":"<provider_model from DB>","messages":[...]}'
   ```
   MyApp stores provider keys as-is (column named `api_key_encrypted` but
   no encryption yet) — use it in a shell variable, never print it.
   Then repeat with the client's alias name as `model` — if the provider
   rejects the alias (`400 "... is not a valid model ID"`) but accepts the
   provider_model id, the gateway is forwarding the alias verbatim (bug #1
   below). OpenRouter's public `/api/v1/models` list (no auth) confirms
   whether a model id exists at all.

## Bug #1 found: alias never rewritten to provider_model before forwarding

The router resolves the client's alias (`deepseek-4-flash`) to a route whose
`model_responded` holds the upstream id (`deepseek/deepseek-v4-flash`), but
`model_responded` was only used for **logging** — the payload went to the
adapter with the alias still in `"model"`. Every upstream call got 400.

Fix in `proxy_controller.execute/6` and `execute_stream/6`:
```elixir
payload = Map.put(payload, "model", route.model_responded)
```

**Regression trap:** the retry helpers (`retry_with_fallback`,
`retry_stream_with_fallback`) re-route with `Router.route(payload["model"], ...)`.
After the rewrite, `payload["model"]` is the provider id, not an alias, so
retries 404 with `model_not_found`. Re-route with the ORIGINAL alias:
`Router.route(route.model_alias.name, member, request_context)`. Each
`execute` re-applies the rewrite for its own route, so per-provider ids stay
correct across fallbacks.

## Bug #2 (observability gap): failures never reach request_logs

`WriteWorker` is only enqueued from `finalize_success` — every failed request
(4xx/5xx/breaker rejections) leaves ZERO trace in `request_logs`. That's why
the DB showed 0 rows despite the outage. When auditing "did this key ever
work?", an empty `request_logs` means "no successes", not "no traffic".
Fix direction: enqueue a failure log (with `status_code`) on the error paths
too, or log breaker rejections at minimum.

## Operational note

With threshold=1 + 30-min cooldown, a single hiccup = a 30-minute model
outage that is invisible in the DB and only fixable by waiting or restarting.
Consider: admin "reset breaker" action in the dashboard
(`CircuitBreakerManager.reset/1` already exists), and/or a lower default
`cooldown_ms` for dev.
