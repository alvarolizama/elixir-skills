# Per-Provider Retry Fallback Pattern

## Problem

In a multi-provider LLM proxy with sticky routing + circuit breakers, naive retry
logic wastes attempts on the same failed provider because:

1. The first retry doesn't exclude the failed credential (to avoid "burning the pool").
2. The sticky tracker re-selects the same provider (breaker still closed, under threshold).
3. Result: 2 out of 3 attempts hit the same provider; the third moves on.

## Solution: Per-provider retry counter

Thread a `provider_retries` counter through the execute/retry function chain:

```
execute(conn, route, payload, member, attempts_left, exclude)
→ execute(conn, route, payload, member, attempts_left, exclude, provider_retries=0)

retry_with_fallback(..., provider_retries) do
  {exclude, provider_retries} =
    if provider_retries < @max_retries_per_provider do
      {exclude, provider_retries + 1}          # retry same provider
    else
      {[route.credential.id | exclude], 0}     # move to next, reset counter
    end

  case Router.route(..., exclude: exclude) do
    {:ok, new_route} → execute(..., provider_retries)
  end
end
```

## Configuration

- `@max_retries_per_provider = 3` — each provider gets 3 attempts before moving on.
- `@max_attempts = 9` — total budget across all providers (3 providers × 3 retries).
- `breaker_threshold = 5` — breaker opens after 5 consecutive failures (cross-request).

With 3 retries per provider and a 5-failure breaker threshold, the breaker never
opens during a single request's retries (3 < 5). It opens across multiple requests,
which is correct: one transient failure shouldn't block the provider for future requests.

## Key interactions

| Component | Effect on retry |
|-----------|----------------|
| **Sticky tracker** | Re-selects same provider when not excluded. Correct for "retry same provider" path; wrong if you accidentally don't exclude after exhausting retries. |
| **Circuit breaker** | Records each failure via `record_outcome`. Opens after threshold → future requests skip this provider. Per-request retries don't reach the threshold (3 < 5). |
| **auth_error** | Disables credential in DB (async). Even without exclude, router filters it out (status != "active"). Per-provider retry counter is irrelevant for auth_error — next route picks a different provider automatically. |
| **exclude_credential_ids** | The explicit exclude list. Updated only when `provider_retries >= @max_retries_per_provider`. |

## Pitfall: don't conflate "retry same provider" with "circuit breaker healing"

The circuit breaker handles **cross-request** healing (provider recovered → breaker
closes). Per-provider retries handle **within-request** resilience (transient blip).
Don't rely on the breaker to do per-request retries — the threshold is too high
(default 5) and the cooldown is too long (60s). They're complementary, not redundant.

## All three execution paths need the same change

- `execute` → `retry_with_fallback` (chat completions, non-streaming)
- `execute_stream` → `retry_stream_with_fallback` (chat completions, streaming)
- `execute_simple` → `retry_simple_with_fallback` (embeddings, rerank)

Each path must thread `provider_retries` independently since they're separate
request flows.
