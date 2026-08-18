# Idempotency-Key for Safe Retries (Replay Deduplication)

Companion to `MyApp-per-provider-retry-pattern.md`. The retry policy answers
*when* to retry; this pattern answers *how to make retries safe*.

## Problem

Retries without deduplication are not safe. When a provider processed a request
but the response was lost (network drop mid-response, gateway timeout after the
upstream committed, LB reset), the retry executes the request a **second time**:
double completion, double billing — and nothing in the logs reveals it, because
both attempts look like fresh requests.

## Pattern: one key per client request, reused by every upstream attempt

Generate ONE idempotency key at the gateway entrypoint and send the SAME key on
every upstream attempt — same-provider retries AND cross-provider fallbacks.
The key identifies the logical client request, not the attempt.

```elixir
# 1. Entrypoints — one key per client request (chat, embeddings, rerank)
conn = assign(conn, :idempotency_key, Ecto.UUID.generate())

# 2. Single injection point shared by every execution path
defp extract_forwarded_headers(conn) do
  forwarded = ... # whitelisted client headers (user-agent, http-referer, x-title)
  Map.put(forwarded, "idempotency-key", conn.assigns.idempotency_key)
end

# 3. Adapter forwards it like any whitelisted header
@forwarded_header_keys ~w(user-agent http-referer x-title idempotency-key)
```

## Key points

- **Generate at the entrypoint, never per attempt.** `Ecto.UUID.generate()`
  needs no extra dependency (Ecto is already present).
- **Inject at the single header-forwarding chokepoint**
  (`extract_forwarded_headers`): streaming, non-streaming, and simple
  (embeddings/rerank) paths all pick it up automatically. Both
  `chat_completions/2` and `simple_proxy/5` must assign it.
- **Same key to the fallback provider too.** Providers share no state, so
  cross-provider replay is harmless; the header still gives every provider the
  logical-request identity. Providers that don't honor the header ignore it.
- **Client-sent Idempotency-Key:** honoring a key the client SDK already sends
  (instead of generating) is the natural extension — same injection point,
  prefer the client's value when present.

## Testing (Bandit mock provider)

The test plug sends headers next to the body:

```elixir
send(pid, {:provider_request, Jason.decode!(body)})
send(pid, {:provider_request_headers, conn.req_headers})
```

Drain the headers mailbox with the same `receive ... after 0` loop the retry
hit-count tests use, then assert:

- every attempt carries a binary `idempotency-key` header matching a UUID regex;
- `Enum.uniq(keys) |> length() == 1` across all attempts (retries + fallback);
- the fallback scenario asserts `length(keys) >= 2` so the stability claim is
  actually exercised over multiple attempts.

Verified in my_app_gateway: 3 tests (happy path, multi-provider fallback, embeddings)
on top of the existing retry suite — `mix precommit` green (865 tests).
