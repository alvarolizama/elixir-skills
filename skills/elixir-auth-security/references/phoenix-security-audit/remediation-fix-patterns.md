# Remediation patterns — Phoenix security/performance fixes

Concrete, verified fix patterns for the most common findings from the
`phoenix-security-audit` and `phoenix-performance-audit` skills. Each
pattern was applied and verified (compile + full suite + ad-hoc check)
in MyApp, August 2026.

Use these when the user asks to FIX an audit finding (remediation mode),
not just report it. Audit-side detection lives in the SKILL.md bodies.

## 1. Sliding session expiration (Plug.Session `renew: true`)

**Finding:** fixed `max_age` session cookie — stolen cookie valid for the
full window, active users logged out mid-work.

**Fix:** add `renew: true` to `@session_options` in `endpoint.ex`. Every
request that writes the session re-issues the cookie with a fresh
`max_age` — sliding expiration for free:

```elixir
@session_options [
  store: :cookie,
  key: "_app_key",
  signing_salt: System.get_env("SESSION_SIGNING_SALT", "..."),
  encryption_salt: System.get_env("SESSION_ENCRYPTION_SALT", "..."),
  same_site: "Lax",
  http_only: true,
  renew: true,
  max_age: String.to_integer(System.get_env("SESSION_MAX_AGE_SECONDS", "14400"))
]
```

Pair with a shorter default (4h, not 8h). No controller changes needed —
login/OAuth/impersonation keep their explicit `configure_session(renew: true)`.

## 2. Prefix-only search + minimum length (autocomplete hardening)

**Finding:** `ilike` substring search (`"%foo%"`) lets any authenticated
user enumerate the directory one char at a time.

**Fix:** drop the leading `%`, require ≥3 chars:

```elixir
def search_users(query, limit \\ 10)
def search_users(query, _limit) when byte_size(query) < 3, do: []
def search_users(query, limit) when is_binary(query) do
  escaped =
    query
    |> String.replace("\\", "\\\\")
    |> String.replace("%", "\\%")
    |> String.replace("_", "\\_")

  pattern = "#{String.downcase(escaped)}%"   # prefix only — no leading %

  Repo.all(
    from u in User,
      where: ilike(u.email, ^pattern) or ilike(u.name, ^pattern),
      order_by: [asc: u.email],
      limit: ^limit
  )
end
```

**Test contract:** mid-string term must NOT match; 1-2 char queries → `[]`;
literal-prefix row (`"50% off"`) still matches `"50%"`. Existing substring
tests fail on exactly those assertions — update them to assert the NEW
contract, don't revert the fix.

## 3. Streaming upstream-kill ordering (first-token timeout)

**Finding:** when the SSE first-token timeout fires, the provider's Finch
stream Task holds a real HTTP connection open until the full
`receive_timeout` — leaking connections and the credential's concurrency
slot while the fallback is already running.

**Fix ordering in the controller's error clause:** kill the pid AND
demonitor BEFORE any fallback work:

```elixir
{:error, reason, status} ->
  # Kill the upstream stream FIRST — before any fallback work. The
  # Finch.stream_while task holds a real HTTP connection open; killing
  # closes the socket immediately and frees the concurrency slot.
  Process.exit(pid, :kill)
  Process.demonitor(ref, [:flush])

  if reason == :auth_error do
    disable_credential_async(route.credential, "auth_error_stream")
  end
  # ... fallback
```

The `[:flush]` option on demonitor drains any already-delivered `:DOWN`
message so it can't leak into the next receive block.

## 4. ETS routing cache (model_providers per scope)

**Finding:** router calls `list_model_providers_for_member` (multi-join
query) on EVERY proxied request; the data changes only on admin edits.

**Fix shape:** singleton GenServer owns a public ETS table; reads are
lock-free `:ets.lookup` in the caller process; the GenServer only creates
the table. Cache key `{:model_providers, alias_id, team_id || :global}`,
TTL 60s, plus a separate `:disabled_credentials` MapSet refreshed the
same way.

**Invalidation-on-write beats TTL:** every context write that touches
providers/credentials/model_providers calls `Cache.invalidate_all()` (or
`invalidate(:disabled_credentials)`) on success. Wire it in the CONTEXT
functions (`create_/update_/delete_`), not the LiveViews — admin edits
through LiveView, seeds, or future API all hit the same path.

**Pitfall — cache key granularity vs member exclusives:** when the cached
list is keyed by `(alias_id, team_id)`, the raw list may contain a provider
exclusive to a DIFFERENT member of the same team. Filter per-member in the
candidate filter after the cache read:

```elixir
defp visible_to_member?(mp, team_member) do
  case mp.exclusive_to_team_member_id do
    nil -> true
    member_id -> team_member != nil and team_member.id == member_id
  end
end
```

**Pitfall — fixtures bypass invalidation:** test fixtures that
`Repo.insert` directly (not via the context function) won't invalidate.
Clear the cache in the test module's `setup` block
(`Cache.invalidate_all()`), or fixtures from one test leak into the next
through the TTL.

## 5. Atomic latency histogram (no ETS read-modify-write)

**Finding:** prepend-and-trim list in one ETS key — two concurrent writers
lose each other's samples, and the lost ones are the high-latency outliers
(exactly the ones p95 needs).

**Fix:** fixed-bucket histogram, atomic increments only:

```elixir
@latency_buckets [50, 100, 250, 500, 1_000, 2_500, 5_000, 10_000, 30_000, :infinity]

defp record_latency(latency_ms) when is_integer(latency_ms) and latency_ms >= 0 do
  add({:latency, :sum}, latency_ms)        # exact avg: sum/count
  incr({:latency, :count})
  incr({:latency, {:bucket, latency_bucket(latency_ms)}})
end
```

p95 at read time: nearest-rank over cumulative bucket counts, linear
interpolation within the winning bucket's width; `:infinity` bucket falls
back to the previous finite bound. avg stays exact (`sum/count`), count is
unbounded (no 200-sample cap). Same snapshot shape for the UI
(`%{count, avg_ms, p95_ms}`) so templates don't change.

**Test updates:** the old "trims at 200" tests become "counts every
sample"; exact-value p95 assertions become range assertions
(`> 50 and <= 100`) because interpolation inside a bucket is approximate.

## 6. Debounced Oban enqueue (one job per burst, not per request)

**Finding:** every successful request enqueues a drift-correction job —
1k RPM = 1k jobs/min for work that batches trivially.

**Fix:** ETS `insert_new` flag as the dedup gate; the worker clears the
flag at the START of `perform/1`:

```elixir
# record_spend/2 (hot path):
defp maybe_enqueue_sync(member_id) do
  if :ets.insert_new(@table, {{:sync_pending, member_id}, true}) do
    %{member_id: member_id} |> SyncWorker.new() |> Oban.insert()
  end
  :ok
end

# SyncWorker.perform/1 — clear BEFORE recomputing:
def perform(%Oban.Job{args: %{"member_id" => member_id}}) do
  Manager.clear_sync_pending(member_id)   # spend after this re-enqueues
  # ... recompute + set_from_db
end
```

Clearing BEFORE the recompute is load-bearing: clearing after creates a
window where a concurrent `record_spend` sets the flag between your clear
and your write, then never fires a new job. Oban's own
`unique: [period: 60, keys: [:member_id]]` stacks on top as a second layer.

## 7. ETS projection instead of tab2list (per-dimension aggregates)

**Finding:** dashboard `count_by_model`/`count_by_user` copies the whole
in-flight table per LiveView render.

**Fix:** match-spec projection returning just the fields you group by:

```elixir
@table
|> :ets.select([
  {{:"$1", %{model_requested: :"$2", credential_name: :"$3", provider_key_suffix: :"$4"}, :"$5"},
   [], [{{:"$2", :"$3", :"$4"}}]}
])
|> Enum.group_by(fn {model, _cred, _suffix} -> model end)
```

Same result shape, no full-map copies. (The next iteration up — per-dimension
counters bumped on insert/delete — makes reads O(1); projection is the
cheap first step that keeps the code shape.)

## 8. Composite indexes on partitioned tables — the CONCURRENTLY trap

Postgres raises `ERROR 0A000 (feature_not_supported) cannot create index
on partitioned table ... concurrently` — fires in `mix test` migrations
too. On a partitioned parent use plain `CREATE INDEX IF NOT EXISTS`
(propagates to partitions automatically, blocking on large prod tables —
schedule a window). CONCURRENTLY only works on regular tables or on
individual partitions one by one.

Keep `@disable_ddl_transaction true` + `@disable_migration_lock true` in
the migration module either way.

## 9. CSP + Permissions-Policy via put_secure_browser_headers

`plug :put_secure_browser_headers` with a map replaces/extends the default
header set — one plug, no custom code:

```elixir
plug :put_secure_browser_headers, %{
  "content-security-policy" =>
    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data:; connect-src 'self' wss: ws:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
  "permissions-policy" =>
    "camera=(), microphone=(), geolocation=(), payment=(), usb=(), magnetometer=(), gyroscope=(), accelerometer=()"
}
```

LiveView needs `'unsafe-inline'` on script-src/style-src for its injected
runtime bits; `connect-src` needs `wss:`/`ws:` for the socket. Tightening
beyond that (nonces) is a bigger project — don't half-do it.

## 10. mix_audit in the precommit gate

```elixir
# mix.exs deps:
{:mix_audit, "~> 2.1", only: [:dev, :test], runtime: false}

# aliases:
precommit: [
  "compile --warnings-as-errors",
  "deps.unlock --unused",
  "deps.audit",
  "format",
  "test"
]
```

Expect the first run to flag transitive deps you can't immediately bump
(e.g. `hackney` pinned by `swoosh`/`tzdata` to a pre-patch range).
Decision: document the advisory + why it's low-risk for your usage
(hackney only fetches the tz database; the app uses Req/Finch for its own
HTTP), and keep the gate on so NEW advisories fail the build. Don't
silence the gate to make it green.
