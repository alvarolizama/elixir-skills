# Circuit Breaker & Provider Fallback — Runtime Flow

Concrete runtime analysis of MyApp's circuit breaker, provider fallback,
and sticky routing system, traced from the source code (`proxy_controller.ex`,
`router.ex`, `circuit_breaker.ex`, `circuit_breaker_manager.ex`,
`provider_adapter.ex`, `openai_adapter.ex`, `sticky_tracker.ex`).

## 1. Configuration (current production defaults)

```elixir
# config/config.exs
config :MyApp, :circuit_breaker,
  cooldown_ms: 60_000,          # 1 minute
  threshold: 5,                  # 5 consecutive failures to trip
  rate_limit_cooldown_ms: 10_000 # 10 seconds

config :MyApp, :first_token_timeout_ms, 15_000
```

Hardcoded defaults in `circuit_breaker.ex` match the config.
Default `receive_timeout` in `openai_adapter.ex` and `Credential` schema: **180_000ms** (3 minutes).

Rationale: LLM providers frequently take 20s–2min to respond. A threshold of 1
and a 30-minute cooldown made the system discard providers after a single
transient timeout. The new settings tolerate bursts while still protecting
against sustained outages.

## 2. Architecture: one breaker per credential_id

```
CircuitBreakerManager (DynamicSupervisor)
└── one :gen_statem per credential_id
    registered via {:via, Registry, {CircuitBreakerRegistry, credential_id}}
    lazily started on first contact (ensure_started/1)
```

Each API key from a provider gets its own breaker. Two OpenAI keys at
different priorities have independent failure tracking and cooldown.

## 3. Circuit breaker state machine

```
       success (resets counter to 0)
    ┌──────────────────────────────┐
    │                              ▼
┌───┴────┐  N consecutive failures  ┌──────┐  cooldown (1min or 10s) ┌───────────┐
│ closed │ ──────────────────────► │ open │ ───────────────────────► │ half_open │
└────────┘   (threshold = 5)        └──────┘                          └───────────┘
    ▲                              ▲ │                               │
    │                              │ │ probe success → :closed          │
    └──────────────────────────────┘ │                                │
              late success = no-op   │ probe failure → :open (fresh cd)│
                                     │                                │
                                     │ late failure while open         │
                                     │ → refreshes cooldown timer      │
                                     └────────────────────────┘
```

### Two cooldown values

| Cooldown | Default | When used |
|----------|---------|-----------|
| `cooldown_ms` | **60,000ms (1 min)** | last failure was `:server_error` or `:timeout` |
| `rate_limit_cooldown_ms` | **10,000ms (10 s)** | last failure was `:rate_limited` (429/529) |

Selected by `cooldown_for(reason, data)`.

### Failure reasons and their effects

| Reason | Counts toward breaker? | Cooldown if tripped | Credential effect |
|--------|----------------------|---------------------|-------------------|
| `:server_error` (5xx) | ✅ (threshold=5) | 1 min | — |
| `:timeout` | ✅ (threshold=5) | 1 min | — |
| `:rate_limited` (429/529) | ✅ (threshold=5) | 10 s | — |
| `:auth_error` (401/402/403) | ❌ (not in @counting_reasons) | N/A | **Permanent DB deactivation** |
| `:client_error` (other 4xx) | ❌ never | — | — |

`:auth_error` does not trip the breaker because the credential is permanently
disabled in the DB instead.

### half_open probe semantics

Only ONE probe request is allowed through (`probe_in_flight?: true`). While the
probe is in flight, all other `allow?/1` calls return `false`, preventing a
thundering herd on recovery.

## 4. Error classification chain

```
Upstream HTTP response
        │
        ▼
ProviderAdapter.classify_status(status)
  401, 402, 403  → :auth_error       ← permanent deactivation, fallback
  429, 529       → :rate_limited     ← 10-s cooldown, fallback
  4xx (other)    → :client_error     ← caller's fault, no fallback
  5xx            → :server_error     ← 1-min cooldown, fallback
        │
ProviderAdapter.classify_error(transport_error)
  timeout reasons → :timeout
  other transport → :connection_error → :server_error (via breaker_reason)
        │
        ▼
proxy_controller: breaker_reason/1
  :timeout          → :timeout
  :rate_limited     → :rate_limited
  :auth_error       → :auth_error
  :connection_error → :server_error
  _                 → :server_error
        │
        ▼
Router.record_outcome(route, {:failure, reason})
  → CircuitBreaker.record_failure(credential_id, reason)
```

## 5. Fallback execution flow (proxy_controller.ex)

`@max_attempts` is **5**.

```
chat_completions/2
  │
  ├── execute(conn, route, payload, member, attempts_left=5, exclude=[])
  │     │
  │     ├── {:ok, body, latency} → record_success, finalize → DONE
  │     │
  │     ├── {:error, :auth_error, status, error_message}
  │     │     → disable_credential_async(credential, "auth_error_#{status}", error_message)
  │     │     → record_failure(:auth_error)  ← doesn't count, but logged
  │     │     → fallback if attempts_left > 1, else render error
  │     │
  │     ├── {:error, :client_error, status}
  │     │     → record_failure(:client_error)  ← doesn't count
  │     │     → render upstream_client_error → DONE (no fallback)
  │     │
  │     └── {:error, reason, status, _error_message}  (server_error, timeout, rate_limited)
  │           → record_failure(breaker_reason(reason))  ← counts toward breaker
  │           │
  │           ├── attempts_left > 1?
  │           │     ├── YES → retry_with_fallback:
  │           │     │     On the FIRST failure, the failed credential is NOT excluded;
  │           │     │     let the breaker/strategy decide. Only exclude on subsequent
  │           │     │     retries so a transient failure does not drain the whole pool.
  │           │     │     Router.route(model, member, %{exclude_credential_ids: exclude})
  │           │     │     ├── {:ok, new_route} → execute(..., attempts_left-1, exclude)
  │           │     │     └── {:error, :no_available_provider} → 503 all_providers_down
  │           │     │
  │           │     └── NO → render upstream_error → DONE
```

### Streaming path

Same fallback logic as non-streaming, but only **before** committing to a 200.
Once `send_chunked(200)` is sent, mid-stream failures call `finish_stream/3`
and no fallback is possible.

`await_first_chunk/2` waits up to `first_token_timeout_ms` (default 15s):

| Event | Action |
|-------|--------|
| `{:sse_chunk, chunk}` | commit 200, start streaming, record success |
| `{:sse_done}` | empty stream → record failure, fallback if attempts left |
| `{:sse_error, reason}` | kill stream, disable cred if auth_error, record failure, fallback |
| `{:DOWN, ref, :process, pid, reason}` | kill stream, record failure, fallback |
| timeout (15s) | kill stream, record failure, fallback |

## 6. Sticky routing

`StickyTracker` stores `{api_key_hash, model_alias_id} → {model_provider_id, inserted_at}`.

- **TTL:** 30 minutes (lazy expiry on read + periodic sweep every 5 min).
- On fallback, sticky keeps the API key on the fallback provider to preserve
  prompt cache.
- If the stuck provider is unavailable, the sticky entry is cleared and the next
  available provider is selected.

### Manual sticky reset

Admins can force a team member to re-route on the next request via the
"Quitar sticky" button in the team member UI. This calls
`Accounts.clear_team_member_sticky_routes/1`, which reads the member's API key
hash and calls `StickyTracker.clear_all_for_api_key_hash/1`.

## 7. Credential reactivation

`Providers.reactivate_credential/1` sets `status = "active"`, clears
`error_reason`/`error_message`/`error_at`, and resets the breaker via
`CircuitBreakerManager.reset/1`.

## 8. Key files

| File | Role |
|------|------|
| `lib/MyApp/routing/circuit_breaker.ex` | `:gen_statem` state machine |
| `lib/MyApp/routing/circuit_breaker_manager.ex` | DynamicSupervisor + Registry |
| `lib/MyApp/routing/router.ex` | Alias resolution, candidate filter, `Priority.select` |
| `lib/MyApp/routing/priority.ex` | Priority sort + sticky routing |
| `lib/MyApp/routing/sticky_tracker.ex` | ETS sticky table with TTL |
| `lib/MyApp/proxy/provider_adapter.ex` | HTTP status/error classification |
| `lib/MyApp/proxy/openai_adapter.ex` | Finch transport, 180s receive timeout |
| `lib/my_app_web/controllers/proxy_controller.ex` | `execute/6`, `execute_stream/6`, fallback |
| `lib/MyApp/providers/credential.ex` | Schema + status fields |
| `lib/MyApp/providers.ex` | `reactivate_credential/1` |
| `lib/MyApp/accounts.ex` | `clear_team_member_sticky_routes/1` |
| `lib/my_app_web/live/team_members_live.ex` | "Quitar sticky" button |
| `config/config.exs` | Breaker + first-token timeout config |

## 9. Tuning checklist

When providers are being blocked too aggressively:

1. Check `circuit_breaker.threshold` — should be > 1 for real upstreams.
2. Check `circuit_breaker.cooldown_ms` — 30 min is excessive for transient errors.
3. Check `circuit_breaker.rate_limit_cooldown_ms` — providers recover from 429s in seconds, not minutes.
4. Check `receive_timeout_ms` on credentials — must be >= the p99 upstream latency.
5. Check `@max_attempts` in `ProxyController` — more attempts help when many providers are configured.
6. Verify the fallback does not exclude credentials on the first failure — let the breaker decide.
7. Confirm `StickyTracker` TTL is appropriate for cache affinity vs. recovery speed.
8. Provide a manual "clear sticky" control per team member for ops intervention.
