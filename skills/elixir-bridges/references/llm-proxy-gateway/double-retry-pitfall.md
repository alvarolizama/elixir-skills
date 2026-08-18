# Double-Retry Pitfall: Req + Agent Engine (2026-08-03)

When an HTTP client (Req) has `retry: :transient` AND the calling agent/engine also has its own retry logic, retries compound exponentially.

## Example from my_app

**Req** (`inference/client.ex`): `retry: :transient` → retries HTTP 500/502/503/504 automatically (3 attempts, exponential backoff).

**Agent.Engine** (`agent/engine.ex`): Retries on `{:http_error, status, _}` for same status codes (2 more attempts, exponential backoff).

With a slow or erroring backend:
- Req retries: 3 × 30s timeout = 90s per Inference.chat() call
- Engine retries: 2 × 90s = 270s total for one step
- `per_step_timeout`: 120s → step times out

## Fix

Disable HTTP client retry when the agent/engine handles retries:

```elixir
# client.ex
req_opts = [
  ...
  retry: false  # Agent.Engine.call_llm handles retries
]
```

## General rule

When building an agent that calls an HTTP API:
1. Decide WHO owns retries: the HTTP client or the agent loop
2. If the agent has retry logic (backoff, error classification, step timeout), disable the HTTP client's retry
3. If the HTTP client has retry, the agent should NOT also retry on the same error codes

Never stack retries at both layers — it causes unpredictable timeouts and makes debugging harder.
