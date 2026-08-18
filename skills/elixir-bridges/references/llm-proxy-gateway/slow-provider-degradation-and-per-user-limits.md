# Slow-Provider Degradation & Per-User Concurrency Limits

How to handle providers that are **slow but not dead** — the failure mode a
plain circuit breaker misses — and how to cap concurrency **per user inside a
shared provider API key**. Distilled from a MyApp session (2026-07) where
clients were stuck on a degraded priority-1 provider.

## The core problem: slow ≠ dead

A circuit breaker only trips on **failures** (`:server_error`, `:timeout`,
`:rate_limited`). A provider that responds in 120s *successfully* counts as a
success, resets the failure counter to 0, and never trips the breaker. Under
priority + sticky routing, all traffic stays pinned to that degraded provider
until it fully saturates (concurrency limit hit) — clients pile up waiting on
the full `receive_timeout` for every request.

**Symptom:** "clients get stuck on the first provider, never reach the second."
Root cause is almost always this combo:

1. **Huge upstream `receive_timeout`** (e.g. 180s default) — each stuck request
   burns a concurrency slot for minutes.
2. **Success resets the breaker** — slow-but-alive providers never degrade.
3. **Priority+sticky has no health dimension** — everyone stays glued to the
   degraded provider.

## Fix pattern (three coordinated pieces)

### 1. Timeouts in config, not the web UI

Operator-facing tunables that change often (or need a quick prod tweak) belong
in application config; only business-meaningful numbers go in the admin UI.

```elixir
config :MyApp, :proxy,
  receive_timeout_ms: 60_000,     # NOT 180s — this alone un-sticks most cases
  first_token_timeout_ms: ***

config :MyApp, :circuit_breaker,
  threshold: 3,                   # was 5 — open faster on real failures
  cooldown_ms: 60_000,
  rate_limit_cooldown_ms: 10_000
```

Keep a per-credential DB column (`receive_timeout_ms`) as an **override**;
the config value is the default when the column is NULL.

### 2. Latency-based health: degrade without tripping

Track "slow success" separately from the breaker, e.g. an ETS table
`{credential_id => last_slow_at}` (a `CredentialHealth` module with
`mark_slow/1`, `mark_healthy/1`, `degraded?/1`).

- Success with `latency_ms > slow_threshold_ms` (e.g. 30s) → `mark_slow/1`.
- Fast success → `mark_healthy/1` (clears the mark).
- The router orders candidates with **degraded providers demoted to the back
  of their tier** — it does NOT remove them (that's the breaker's job).
- Optionally: a slow success does **not** reset the breaker's failure counter
  to 0 (so a chronically slow provider eventually trips anyway).

```elixir
config :MyApp, :routing,
  slow_threshold_ms: 30_000,
  slow_penalty_ms: 120_000        # degrade for 2 min, then retry as primary
```

This gives self-healing: a slow subscription steps aside on its own and comes
back on its own, no manual intervention.

### 3. Tiered routing: paid-for capacity first

When the operator's mental model is "use the flat-rate subscriptions until
they degrade, then spill to pay-per-use", encode it as tiers in the selection
strategy instead of raw priority. **The tier order matters — get it wrong and
a slow subscription still beats a fast paid provider.** The correct order:

1. `billing_mode = "included"` (subscriptions), **healthy** — priority order.
2. `pay_per_token`, **healthy** — priority order.
3. `included`, **degraded** (slow subscription = last resort, not second place).
4. `pay_per_token`, degraded.

**Pitfall — degraded-included must sink BELOW healthy-pay.** An earlier draft
ordered tiers as `included-healthy → included-degraded → pay-healthy`, which
made a *slow* subscription outrank a *fast* paid provider — the exact opposite
of the intent ("a slow 'free' provider is worse than a fast paid one; the
whole point of preferring the subscription is that it serves traffic well").
Sort by `{tier, priority}` with the tier map above, so any healthy provider
beats any degraded one, and among healthy ones the subscription wins.

Sticky routing stays **within the tier** — degrade → drop tier; recover →
return to the subscription (and to its prompt cache). Concretely: a degraded
stuck provider must RELEASE the stick (clear + re-stick to a healthy
candidate) so the user flows to the healthy tier instead of staying glued to
a slow one just because the breaker still says "available".

## Per-user concurrency inside a shared provider key

Three distinct limits that look alike but protect different things — keep them
separate:

| Limit | Key | Protects |
|-------|-----|----------|
| `max_rpm` | `credential.id` | The subscription/key **quota**. Local gate → instant 0ms fallback when the minute's quota is spent. |
| `max_concurrent` | `credential.id` | **Global saturation** of the upstream key in real time. |
| `max_concurrent_per_user` | `{credential.id, user_api_key_id}` | One client hogging the shared subscription's slots. |

Implementation notes:

- A generic ETS limiter already keyed by an opaque `api_key_id` accepts a
  **composite tuple** `{credential_id, key_id}` as the key — no new table
  needed. Just a second `acquire_concurrency/2` call after the global one.
- When the per-user gate trips, **fall back to the next provider for that
  user** (add credential.id to `exclude` and re-route) — do not block them.
  The heavy user spills to pay-per-use; the rest of the team keeps the
  subscription.
- Release **both** keys symmetrically in the `after` block (global + composite),
  on every exit path (success, error, timeout, client disconnect).
- `nil` = unlimited (backwards-compatible default).

### What stays in the web UI

Only the two business numbers per credential: `max_rpm` and
`max_concurrent_per_user` (plus the pre-existing `max_concurrent`). Timeouts,
thresholds, slow-penalty windows: config. This was an explicit operator
preference — "config de la web" only for per-key business limits.

## RPM: still worth it?

Yes, when subscriptions are quota-metered (RPM flat plans). The local RPM gate
is what triggers a **clean instant fallback** when the minute's quota is spent
— without it you learn about the limit via an upstream 429 (a wasted
round-trip + a breaker failure mark). For self-hosted/local providers
(GPU-bound), leave `max_rpm` nil — concurrency is the only meaningful knob
there. TPM is the theoretically-purer metric but requires pre-estimation; RPM
is the pragmatic proxy.

## Verification checklist

- Per-user gate: two users have independent counters; the one who trips falls
  back, the other is unaffected.
- Releases symmetric: no counters leak after error/timeout/disconnect.
- Slow-success marks degraded; fast success clears; mark expires after
  `slow_penalty_ms`.
- Tier order: healthy `included` beats any `pay_per_token`; degraded provider
  sinks within/across tiers; sticky respects tier boundaries.

## Implementation pitfalls (learned the hard way)

- **Ecto schema `default:` kills config fallback.** When a schema field has
  `field :x, :integer, default: 180_000`, Ecto sets that value on every
  struct load — the DB column is never NULL. So `credential.receive_timeout_ms
  || config_default` always sees the 180_000 and never falls back to config.
  **Fix:** (1) remove the `default:` from the schema, (2) write a migration
  that NULLs out rows carrying the old default, (3) drop the DB column default
  so new rows are born with NULL:

  ```elixir
  # Migration
  def up do
    execute("UPDATE credentials SET timeout_ms = NULL WHERE timeout_ms = 180000")
    alter table(:credentials) do
      modify(:timeout_ms, :integer, null: true, default: nil, from: {:integer, default: 180_000})
    end
  end
  ```

  **Rule of thumb:** if a field's "real" default lives in application config
  (env var / runtime.exs), the schema must NOT have `default:` — it will mask
  the config fallback silently. `nil` is the correct schema default when config
  is the source of truth.

- **Make `tier/1` defensive about unloaded credentials.** The selection
  strategy's tier function reads `mp.credential.id` for the health check, but
  `ModelProvider` structs built by hand in tests (or any candidate whose
  `credential` assoc isn't preloaded) will raise `KeyError` /
  `Ecto.Association.NotLoaded`. Pattern-match the credential and treat
  `nil` / `NotLoaded` as **healthy**, falling back to billing_mode + priority:

  ```elixir
  defp degraded?(%{credential: %Ecto.Association.NotLoaded{}}), do: false
  defp degraded?(%{credential: nil}), do: false
  defp degraded?(%{credential: %{id: id}}), do: CredentialHealth.degraded?(id)
  ```

- **Record slow-success latency inside `record_outcome`, not at every call
  site.** The proxy has several success paths (non-streaming, streaming
  first-token, embeddings/rerank). Instead of calling `mark_slow` in each,
  extend the breaker-recording function to accept `opts[:latency_ms]` and do
  the health update there — every current and future caller gets it for free:

  ```elixir
  Router.record_outcome(route, :success, latency_ms: ttft_ms)
  ```

- **Two ETS tables, not one.** Keep the hard breaker (gen_statem, per
  credential) and the soft health mark (plain ETS map) separate. The breaker
  owns "is it alive" (availability — removes the candidate); the health table
  owns "is it fast enough to be primary" (ordering — demotes within the
  sorted list). Don't bolt ordering onto the breaker state machine.
