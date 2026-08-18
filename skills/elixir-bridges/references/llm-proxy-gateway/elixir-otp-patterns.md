# Elixir/OTP Patterns for LLM Proxy Gateways

Concrete patterns for building an LLM proxy in Elixir without Redis. All state lives in BEAM primitives.

## :atomics — lock-free round robin

`:atomics` provides C-level atomic operations. Created once, holds a fixed array of 64-bit signed integers.

```elixir
# Create on app start (in a GenServer init or supervisor)
atomic_ref = :atomics.new(1, [:signed])

# Increment and get atomically (lock-free, 50M+ ops/sec)
index = :atomics.add_get(atomic_ref, 1, 1)
selected = Enum.at(providers, rem(rem(index, length(providers)) + length(providers), length(providers)))
# Note: rem can be negative in Erlang for negative dividends, hence the double rem
```

**Weighted round robin:** repeat providers in the list according to weight:
```elixir
# Provider A (weight 3), Provider B (weight 1)
providers = [:a, :a, :a, :b]
index = :atomics.add_get(atomic_ref, 1, 1)
selected = Enum.at(providers, rem(index, 4))
```

## :gen_statem — circuit breaker

Per-provider state machine. Lives under a DynamicSupervisor so providers can be added/removed at runtime.

```elixir
defmodule MyApp.Routing.CircuitBreaker do
  use :gen_statem

  @failure_threshold 5
  @cooldown_ms 30_000

  defstruct [:provider_id, :failure_count, :last_failure_at]

  def start_link(provider_id) do
    :gen_statem.start_link(__MODULE__, provider_id, [])
  end

  def can_route?(pid) do
    :gen_statem.call(pid, :can_route?)
  end

  def record_success(pid) do
    :gen_statem.cast(pid, :success)
  end

  def record_failure(pid) do
    :gen_statem.cast(pid, :failure)
  end

  # --- Callbacks ---

  @impl true
  def init(provider_id) do
    {:ok, :closed, %__MODULE__{provider_id: provider_id, failure_count: 0}}
  end

  @impl true
  def handle_event(:call, :can_route?, _state, _data) do
    # Always allow in closed and half_open; reject in open
    {:keep_state, :closed, {:reply, true}}
  end

  def handle_event(:cast, :success, _old_state, data) do
    {:next_state, :closed, %__MODULE__{data | failure_count: 0}}
  end

  def handle_event(:cast, :failure, :closed, data) do
    new_count = data.failure_count + 1
    if new_count >= @failure_threshold do
      {:next_state, :open, %__MODULE__{data | failure_count: new_count},
       {{:timeout, :cooldown}, @cooldown_ms, nil}}
    else
      {:keep_state, %__MODULE__{data | failure_count: new_count}}
    end
  end

  def handle_event(:cast, :failure, :open, data) do
    # Already open, just track
    {:keep_state, data}
  end

  def handle_event({:timeout, :cooldown}, nil, :open, data) do
    {:next_state, :half_open, data}
  end

  def handle_event(:call, :can_route?, :open, _data) do
    {:keep_state, :open, {:reply, false}}
  end

  def handle_event(:call, :can_route?, :half_open, _data) do
    {:keep_state, :half_open, {:reply, true}}
  end
end
```

### DynamicSupervisor for circuit breakers

```elixir
defmodule MyApp.Routing.CircuitBreakerManager do
  use DynamicSupervisor

  def start_link(init_arg) do
    DynamicSupervisor.start_link(__MODULE__, init_arg, name: __MODULE__)
  end

  @impl true
  def init(_init_arg) do
    DynamicSupervisor.init(strategy: :one_for_one)
  end

  def start_breaker(provider_id) do
    spec = {MyApp.Routing.CircuitBreaker, provider_id}
    DynamicSupervisor.start_child(__MODULE__, spec)
  end
end
```

## ETS — rate limiting (weighted two-bucket sliding window)

A weighted sliding window is more accurate than a fixed window: it blends
the current minute's count with a decaying fraction of the previous minute's
count, so the limit doesn't artificially reset to zero at the boundary.

```elixir
defmodule MyApp.Limits.Manager do
  use GenServer

  @rpm_table :my_app_rpm_buckets
  @sweep_interval_ms 60_000
  @bucket_retention_minutes 2

  @doc """
  Weighted two-bucket sliding window: current bucket + previous bucket
  weighted by the fraction of the previous minute that still bleeds into
  the current window.
  """
  def check_rate(api_key_id, nil), do: :ok

  def check_rate(api_key_id, rpm_limit) when is_integer(rpm_limit) do
    now = System.system_time(:second)
    current_bucket = div(now, 60)
    key = {api_key_id, current_bucket}

    # lookup_element/4 returns the default (0) if the key is absent —
    # no need to pattern-match on lookup/2 results.
    prev_count = :ets.lookup_element(@rpm_table, {api_key_id, current_bucket - 1}, 2, 0)
    cur_count  = :ets.lookup_element(@rpm_table, key, 2, 0)

    elapsed = rem(now, 60)
    weighted_prev = div(prev_count * (60 - elapsed), 60)
    weighted_count = weighted_prev + cur_count

    if weighted_count < rpm_limit do
      # update_counter/4 with {key, 0} default inserts the key if absent
      :ets.update_counter(@rpm_table, key, 1, {key, 0})
      :ok
    else
      {:error, :rate_limited, retry_after_ms(now)}
    end
  end

  # --- GenServer: table creation + periodic sweep ---

  @impl true
  def init(_opts) do
    if :ets.whereis(@rpm_table) == :undefined do
      :ets.new(@rpm_table, [
        :set, :public, :named_table,
        read_concurrency: true, write_concurrency: true
      ])
    end
    schedule_sweep()
    {:ok, %{}}
  end

  @impl true
  def handle_info(:sweep, state) do
    sweep_old_buckets()
    schedule_sweep()
    {:noreply, state}
  end

  defp sweep_old_buckets do
    now = System.system_time(:second)
    cutoff = div(now, 60) - @bucket_retention_minutes

    # select_delete/2 with a match spec is O(matching) not O(n) —
    # much better than tab2list + Enum.each for high-cardinality tables.
    # The match spec captures the bucket number ($1) and deletes if < cutoff.
    match_spec = [{{{:_, :"$1"}, :_}, [{:<, :"$1", cutoff}], [true]}]
    :ets.select_delete(@rpm_table, match_spec)
  end

  defp schedule_sweep, do: Process.send_after(self(), :sweep, @sweep_interval_ms)

  defp retry_after_ms(now) do
    elapsed = rem(now, 60)
    # Approximate: ms remaining in current minute, floored at 1000
    max((60 - elapsed) * 1000, 1000)
  end
end
```

### Key ETS techniques used

- **`lookup_element/4` with default** — `:ets.lookup_element(table, key, pos, default)` returns `default` if the key is absent. Eliminates the `case :ets.lookup(...)` pattern match boilerplate.
- **`update_counter/4` with default object** — `:ets.update_counter(table, key, {pos, incr}, {key, 0})` inserts `{key, 0}` if the key doesn't exist, then increments. Atomic insert-or-increment in one call.
- **`select_delete/2` with match spec** — `:ets.select_delete(table, match_spec)` deletes all matching entries in one atomic pass. Far more efficient than `tab2list` + `Enum.each` + `delete` for cleanup. The match spec `{{{:_, :"$1"}, :_}, [{:<, :"$1", cutoff}], [true]}` matches any key tuple where the second element (bucket number) is less than `cutoff`.

## ETS — subscription round-robin rotation

Per-provider round-robin among active subscriptions. Unlike the global
`:atomics` counter (which is a single fixed-size array), subscription
rotation needs **per-provider** counters keyed by dynamic `provider_id`s —
ETS is the right primitive because it supports arbitrary keys.

The GenServer creates two public named tables in `init/1` and never touches
them again. All public functions run in the **caller's process** (including
the DB read), avoiding a GenServer bottleneck on the hot path.

```elixir
defmodule MyApp.Providers.SubscriptionManager do
  use GenServer

  @rotation_table :my_app_sub_rotation
  @usage_table :my_app_sub_usage

  # Counter starts at 0 (default object). update_counter returns the NEW
  # value, so first call returns 1. Subtract 1 for 0-based indexing:
  # counter 1 → index 0, counter 2 → index 1, etc.
  def pick_subscription(provider_id) do
    subs = provider_id |> active_subscriptions() |> Enum.sort_by(& &1.inserted_at, DateTime)

    case subs do
      [] ->
        {:error, :no_active_subscription}

      [_ | _] ->
        count = length(subs)
        idx = :ets.update_counter(@rotation_table, provider_id, {2, 1}, {provider_id, 0})
        sub = Enum.at(subs, rem(idx - 1, count))
        {:ok, sub}
    end
  end

  # Per-sub usage counter — atomic increment, no GenServer round-trip.
  def record_usage(subscription_id) do
    :ets.update_counter(@usage_table, subscription_id, {2, 1}, {subscription_id, 0})
    :ok
  end

  # Reads with lookup_element/4 default (0 if key absent).
  defp read_usage_counter(subscription_id) do
    :ets.lookup_element(@usage_table, subscription_id, 2, 0)
  end

  # GenServer only creates tables, never reads/writes them.
  @impl true
  def init(_opts) do
    ensure_table(@rotation_table)
    ensure_table(@usage_table)
    {:ok, %{}}
  end

  defp ensure_table(name) do
    if :ets.whereis(name) == :undefined do
      :ets.new(name, [:set, :public, :named_table, write_concurrency: true])
    end
  end
end
```

### Key patterns

- **`rem(idx - 1, count)` indexing** — `update_counter/4` returns the NEW
  value (1 on first call). Without subtracting 1, the first pick skips
  index 0 and starts at index 1. This is the #1 off-by-one trap in ETS
  round-robin.
- **`ensure_table/1` guard** — `if :ets.whereis(name) == :undefined` before
  `:ets.new/2` prevents the `ArgumentError` when the named table already
  exists (e.g. app-tree GenServer + test `start_supervised!` sharing the name).
- **Caller-process DB read** — `Providers.active_subscriptions/1` runs in
  the caller's process, not the GenServer. Routing the DB read through the
  GenServer would serialize all provider selections on one process.
- **`Enum.sort_by(& &1.inserted_at, DateTime)`** — the DB query doesn't
  order by `inserted_at`, so sort in-process to guarantee deterministic
  round-robin ordering.

### Exhaust marking + PubSub broadcast

```elixir
def exhaust(subscription_id) do
  case Providers.get_subscription(subscription_id) do
    nil -> {:error, :not_found}
    sub ->
      {:ok, updated} = Providers.update_subscription(sub, %{status: "exhausted"})
      Phoenix.PubSub.broadcast(@pubsub, "subscriptions", {:subscription_exhausted, subscription_id})
      {:ok, updated}
  end
end
```

Exhausted subscriptions drop out of `active_subscriptions/1` (which filters
`status == "active"`), so subsequent `pick_subscription/1` calls skip them
automatically — no ETS invalidation needed.

### Testing patterns

- `async: false` — named ETS tables are singletons.
- `Process.whereis(Manager) || start_supervised!(Manager)` to reuse app-tree instance.
- Clear tables in setup: `:ets.delete_all_objects/1` if `:ets.whereis/1 != :undefined`.
- **Second-precision timestamp trap:** `timestamps(type: :utc_datetime)` has
  second precision — back-to-back inserts share the same `inserted_at`. For
  deterministic ordering tests, set distinct timestamps explicitly:
  ```elixir
  defp timed_subscription(provider, name, offset_seconds) do
    sub = subscription_fixture(provider, %{name: name})
    time = DateTime.utc_now() |> DateTime.add(offset_seconds) |> DateTime.truncate(:second)
    {:ok, _} = sub |> Ecto.Changeset.change(%{inserted_at: time}) |> Repo.update()
    %{sub | inserted_at: time}
  end
  ```
- **Pin syntax in `assert_receive`:** `^provider.id` is invalid — pin
  expects a variable, not an expression. Bind first: `provider_id = provider.id`
  then `assert_receive {:event, ^provider_id, _}`.

## ETS — in-flight concurrency gate

Race-free concurrency limiting using optimistic increment-then-check.
No locks, no transactions — just atomic counter ops with rollback.

```elixir
def acquire_concurrency(api_key_id, limit) when is_integer(limit) do
  key = api_key_id
  # Increment unconditionally; update_counter/4 inserts {key, 0} if absent
  new_value = :ets.update_counter(@inflight_table, key, {2, 1}, {key, 0})

  if new_value <= limit do
    :ok
  else
    # Over limit — roll back the increment
    :ets.update_counter(@inflight_table, key, {2, -1})
    {:error, :concurrency_exceeded}
  end
end

def acquire_concurrency(api_key_id, nil) do
  # nil limit = unlimited, but still track the count for observability
  :ets.update_counter(@inflight_table, api_key_id, {2, 1}, {api_key_id, 0})
  :ok
end
```

### Atomic floor-at-0 release (never goes negative)

The `{position, increment, threshold, setval}` form of `update_counter/4`
atomically prevents the counter from going below `threshold` — if the
result would be below `threshold`, it's set to `setval` instead.

```elixir
def release_concurrency(api_key_id) do
  # {2, -1, 0, 0}: decrement position 2 by 1; if result < 0, set to 0
  :ets.update_counter(@inflight_table, api_key_id, {2, -1, 0, 0}, {api_key_id, 0})
  :ok
end
```

This is race-free: two concurrent releases on a count of 1 will not produce
-1, because each decrement is atomic and the threshold guard prevents
undershoot in the same operation.

### Testing ETS-backed limit managers

- Use `async: false` — named ETS tables are singletons; concurrent tests
  would clobber each other's counters.
- Use `start_supervised!/1` + `_ = :sys.get_state(pid)` to ensure the
  GenServer has created its tables before assertions.
- Use unique keys per test (`"key-#{System.unique_integer([:positive])}"`)
  to avoid inter-test contamination even within the serial run.
- For the sweep/cleanup path, insert fake old buckets, send `:sweep` to the
  GenServer, then `:sys.get_state(pid)` to synchronize before asserting.

## ETS — metrics ring buffer

```elixir
defmodule MyApp.Metrics.Collector do
  use GenServer

  @buffer_size 3600  # 1 hour at 1 entry/sec

  def start_link(opts) do
    GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  end

  def record_request(metrics) do
    GenServer.cast(__MODULE__, {:record, metrics})
  end

  def get_recent(seconds \\ 60) do
    GenServer.call(__MODULE__, {:get_recent, seconds})
  end

  @impl true
  def init(_opts) do
    table = :ets.new(:metrics_buffer, [:set, :public, :named_table])
    {:ok, %{table: table, index: 0}}
  end

  @impl true
  def handle_cast({:record, metrics}, state) do
    idx = state.index
    :ets.insert(:metrics_buffer, {idx, metrics})
    {:noreply, %{state | index: rem(idx + 1, @buffer_size)}}
  end

  @impl true
  def handle_call({:get_recent, seconds}, _from, state) do
    count = min(seconds, @buffer_size)
    start_idx = rem(state.index - count + @buffer_size, @buffer_size)
    entries = for i <- 0..(count - 1) do
      idx = rem(start_idx + i, @buffer_size)
      case :ets.lookup(:metrics_buffer, idx) do
        [{_, m}] -> m
        [] -> nil
      end
    end |> Enum.reject(&is_nil/1)
    {:reply, entries, state}
  end
end
```

## Phoenix.PubSub — real-time dashboard updates

```elixir
# In the proxy handler, after request completes:
Phoenix.PubSub.broadcast(
  MyApp.PubSub,
  "metrics:realtime",
  {:request_completed, %{
    provider: provider_name,
    model: model_name,
    latency_ms: latency,
    tokens: total_tokens,
    cost_usd: cost,
    status: status_code
  }}
)

# In the LiveView:
def mount(_params, _session, socket) do
  if connected?(socket) do
    Phoenix.PubSub.subscribe(MyApp.PubSub, "metrics:realtime")
  end
  {:ok, assign(socket, metrics: [])}
end

def handle_info({:request_completed, data}, socket) do
  {:noreply, update(socket, :metrics, &[data | &1])}
end
```

## Finch — provider connection pooling

```elixir
# In application.ex children:
{Finch, name: MyApp.Finch, pools: %{
  "https://api.openai.com" => [size: 50, count: 5],
  "https://api.anthropic.com" => [size: 50, count: 5]
}}

# Usage:
Finch.build(:post, "https://api.openai.com/v1/chat/completions", headers, body)
|> Finch.stream(MyApp.Finch, nil, fn
  {:status, status}, acc -> {status, acc}
  {:headers, headers}, acc -> {headers, acc}
  {:data, data}, acc -> # forward SSE chunk to client
end)
```

## Oban — async webhook delivery

```elixir
defmodule MyApp.Observability.WebhookWorker do
  use Oban.Worker, queue: :webhooks, max_attempts: 5

  @impl true
  def perform(%Oban.Job{args: args, attempt: attempt}) do
    url = args["url"]
    payload = args["payload"]
    headers = args["headers"]

    case Finch.build(:post, url, headers, payload)
         |> Finch.request(MyApp.Finch) do
      {:ok, %{status: status}} when status in 200..299 ->
        :ok
      {:ok, %{status: status}} ->
        {:error, "webhook returned #{status}"}
      {:error, reason} ->
        {:error, reason}
    end
  end
end

# Enqueue:
%{url: dest.url, payload: otlp_json, headers: headers}
|> Oban.insert(MyApp.Observability.WebhookWorker.new(%{...}))
```

## Budget tracking — ETS + periodic Postgres sync

```elixir
defmodule MyApp.Budgets.Manager do
  use GenServer

  @sync_interval_ms 5_000  # sync to Postgres every 5s

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  def add_spend(api_key_id, amount_usd) do
    # Called from hot path — ETS only, no GenServer call
    :ets.update_counter(:budget_counters, api_key_id, {2, amount_usd})
  rescue
    ArgumentError -> :ets.insert(:budget_counters, {api_key_id, amount_usd})
  end

  def get_spend(api_key_id) do
    case :ets.lookup(:budget_counters, api_key_id) do
      [{_, spend}] -> spend
      [] -> Decimal.new("0")
    end
  end

  @impl true
  def init(_opts) do
    :ets.new(:budget_counters, [:set, :public, :named_table, read_concurrency: true])
    schedule_sync()
    {:ok, %{}}
  end

  @impl true
  def handle_info(:sync, state) do
    # Read all counters, batch update Postgres, reset
    counters = :ets.tab2list(:budget_counters)
    # TODO: batch upsert to Postgres
    schedule_sync()
    {:noreply, state}
  end

  defp schedule_sync, do: Process.send_after(self(), :sync, @sync_interval_ms)
end
```

## Streaming SSE passthrough

```elixir
defmodule MyApp.Proxy.Streaming do
  import Plug.Conn

  def stream_to_client(conn, provider_stream) do
    conn = conn
    |> put_resp_header("content-type", "text/event-stream")
    |> put_resp_header("cache-control", "no-cache")
    |> send_chunked(200)

    Enum.reduce_while(provider_stream, conn, fn chunk, conn ->
      case chunk(conn, "data: #{chunk}\n\n") do
        {:ok, conn} -> {:cont, conn}
        {:error, :closed} -> {:halt, conn}
      end
    end)
  end
end
```

## Hot path isolation — what touches what

| Component | ETS | :atomics | :gen_statem | Postgres | Oban |
|-----------|-----|----------|-------------|----------|------|
| Rate limit check | ✅ read+write | — | — | ❌ | — |
| Round robin select | — | ✅ read+write | — | ❌ | — |
| Circuit breaker check | — | — | ✅ call | ❌ | — |
| Provider request | — | — | — | ❌ | — |
| Metrics record | ✅ write | — | — | ❌ | — |
| Budget increment | ✅ write | — | — | ❌ | — |
| Request log | — | — | — | ✅ async | ✅ enqueue |
| Webhook delivery | — | — | — | ✅ async | ✅ enqueue |
| Budget sync | — | — | — | ✅ periodic | — |
| Metrics rollup | — | — | — | ✅ periodic | ✅ enqueue |

## File descriptors

```bash
# Check current limit
ulimit -n

# Set higher (systemd service)
[Service]
LimitNOFILE=1000000

# Or in /etc/security/limits.conf
* soft nofile 65535
* hard nofile 65535
```
