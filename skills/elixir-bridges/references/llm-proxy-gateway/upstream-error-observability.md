# Upstream error observability: surfacing WHY a provider failed

How MyApp carries the upstream provider's error *message* (not just the
classified reason atom) end-to-end: from the adapter into the circuit breaker
state, the durable request log, and both admin UI surfaces. Use when an admin
says "the logs say 200 / the breaker says 'server error' but nobody can tell me
what actually happened."

## The original gap

The adapter already extracts the provider's error body
(`OpenAIAdapter.extract_error_message/1` — scrubs API-key fragments, truncates
at 500 chars) and returns it as the 4th element of the error tuple. But every
caller threw it away:

- `proxy_controller` matched `{:error, reason, status, _error_message}` —
  message dropped on the floor.
- The circuit breaker only stored `last_reason` (atom), so the admin UI could
  only render "Error servidor" with no detail.
- `log_fallback_attempt` persisted `provider_status_code` + a generic
  `error_reason` string ("provider_error_500"), but not the real message —
  invisible unless you noticed `provider_status_code` in a far-right column of
  a wide table.

Result: operators see a 200 (the fallback succeeded!) with no visible trace of
why the first provider failed, and a breaker alert that says "server error"
with no message.

## The plumbing pattern (message flows with the reason, everywhere)

1. **Breaker state gets `last_error_message`.** `record_failure/3` with
   `error_message \\ nil` (backwards compatible). Every state's `details/1`
   reply gains the key; resets and half-open successes clear it; late failures
   while open keep the freshest message (`error_message || data.last_error_message`).
2. **Manager passthrough.** `CircuitBreakerManager.record_failure/3`, and the
   default `details/1` map for unknown credentials includes
   `last_error_message: nil` so consumers never hit a missing key.
3. **Router.record_outcome accepts a 3-tuple.** `{:failure, reason, error_message}`
   alongside the existing `{:failure, reason}` — old call sites untouched.
4. **Controller binds `_error_message` → `error_message`** and passes it to
   both `Router.record_outcome` and the log enqueue opts.
5. **Durable log column.** `request_logs.error_message` (string), threaded:
   `enqueue_error_log` opts → Oban job args → `WriteWorker` → changeset
   `@permitted` → schema field.

## Fallback-attempt logging (the "200 but failed" rows)

`log_fallback_attempt/5` runs BEFORE every re-route: writes a request log with
`status_code: 200` (the client eventually got an answer), the real
`provider_status_code`, a human `error_reason` per status (429 →
"provider_rate_limited", 503 → "provider_overloaded", 500 →
"provider_internal_error", nil → "provider_error", other →
"provider_error_<status>"), and now the real `error_message`.

**Streaming path pitfall:** the SSE adapter used to send
`{:sse_error, {reason, status}}` and `await_first_chunk` collapsed it to just
the atom, losing the status. Make `await_first_chunk` return
`{:error, reason, status}` so the stream fallback can also log
`provider_status_code`, and the final-exhausted render passes the real status
to `{:upstream_error, reason, status}` instead of hardcoded `nil`.

## Gate-error rows: the invisible stats drill-down

Gate-level failures — the ones that happen BEFORE routing succeeds
(`provider_concurrency_exceeded`, team `rate_limited`, `budget_exceeded`,
`no_available_provider` after concurrency fallback) — were logged by
`enqueue_gate_error_log` WITHOUT `model_alias_id` (only the `model_requested`
name string). Consequence: every per-model query that filters by
`model_alias_id` (`cost_summary`, `Rollup.breakdown_by_provider_for_model`,
`breakdown_by_member_for_model`, `breakdown_by_team_for_model`) silently
excluded them, so `/dashboard/stats/models?model_id=...` showed "Sin datos"
during exactly the saturation bursts the admin opened the page to inspect.
The logs table still showed them because its model filter matches on the
`model_requested` string — that asymmetry is the tell.

**Fix pattern:** alias names are globally unique (`unique_index(:model_aliases, [:name])`),
so resolve the id with one indexed lookup on the cold error path:

```elixir
defp alias_id_for_name(nil), do: nil
defp alias_id_for_name(name) when is_binary(name) do
  Repo.one(from ma in ModelAlias, where: ma.name == ^name, select: ma.id)
end
```

and put `"model_alias_id" => alias_id_for_name(model)` into the gate log's
Oban args. This is a deliberate exception to the "no DB on the hot path" rule:
the gate path only runs when the request already failed, and one indexed
lookup is cheaper than the Oban insert that follows it anyway. Never do this
on the success path.

Note the breakdown row for gate logs groups under `model_provider_id == nil`
(left joins → provider_name falls back to "—") — correct, since no provider was
ever contacted.

## UI surfaces

- **Logs table:** when `status_code == 200 && error_reason`, render a warning
  "fallback" badge next to the status so recovered requests are visibly
  distinct from clean 200s. Under the error_reason badge, render
  `error_message` truncated with the full text in `title=`.
- **Open breakers table:** a "Detalle" column showing
  `details.last_error_message` (truncated, full text in `title=`) next to the
  "Razón" column.

## Verification

- Breaker unit tests: message stored, survives trip-to-open, nil with 2-arity
  call, cleared on reset.
- End-to-end proxy test (Bandit mock returning
  `500 {"error":{"message":"provider exploded"}}`): after fallback to a healthy
  provider, `Oban.drain_queue(queue: :logs)` shows **4 jobs, not 2** — the down
  provider gets `@max_retries_per_provider` (3) attempts before exclusion, each
  logging a fallback row, plus the final success. Assert every fallback row has
  `status_code == 200`, `provider_status_code == 500`, and the real
  `error_message`.
- Gate-error test: saturate the only credential's concurrency
  (`Limits.acquire(cred.id, %{concurrency_limit: 1})` before the request),
  assert 429, drain the logs queue, and assert the persisted row's
  `model_alias_id == model_alias.id` — this is the regression guard for the
  stats-invisibility bug.

That drain-count point is the test-authoring pitfall: when asserting log
counts around fallback, remember fast errors retry the same provider 3 times
before excluding it — the fallback log count is `retries + 1 success`, not 2.
