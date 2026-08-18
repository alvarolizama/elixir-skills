# ETS TTL Cache for Dashboard Query Bundles

Pattern proven in MyApp's `MyApp.Metrics.DashboardCache` (Aug 2026) —
eliminates redundant Postgres queries when multiple connected LiveViews
receive the same PubSub broadcast and re-query the same period-scoped data.

**Distinct from the rolling-window ETS** (`Metrics.Window`): the rolling
window keeps incremental per-minute counts for sparklines (write-once,
read-many, rotate every 60s). This cache stores **the full result bundle
of a multi-query Postgres load** with a TTL, so N connected dashboards
for the same user share 1 query set instead of N × 8+ queries.

## When to use this pattern

- A LiveView subscribes to a PubSub topic that fires on every domain
  event (e.g. `metrics:updated` broadcasts on every proxied request).
- The LiveView debounces broadcasts (e.g. `Process.send_after` 2s), but
  even debounced, N connected dashboards → N Postgres query sets per
  debounce window.
- The data is **period-scoped** (today, 7d, 30d) — the existing ETS
  collectors (Collector, Window) are lifetime/incremental and cannot
  answer "how much in the last 24h?".
- The data can tolerate a few seconds of staleness (it's a metrics
  overview, not a trading order book).

## Module structure

```elixir
defmodule MyApp.Metrics.DashboardCache do
  use GenServer

  @table :myapp_dashboard_cache
  @default_ttl_ms 5_000

  def start_link(opts \\ []), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @spec build_key(term(), String.t(), String.t()) :: {term(), String.t(), String.t()}
  def build_key(user_id, period, timezone), do: {user_id, period, timezone}

  @spec fetch_or_compute(term(), (-> map())) :: map()
  def fetch_or_compute(key, compute_fn) do
    case read(key) do
      {:ok, data} -> data
      :miss ->
        data = compute_fn.()
        put(key, data)
        data
    end
  end

  def put(key, data) do
    :ets.insert(@table, {key, data, System.monotonic_time(:millisecond)})
    :ok
  end

  def invalidate(key), do: :ets.delete(@table, key); :ok
  def invalidate_all, do: :ets.delete_all_objects(@table); :ok
  def ttl_ms, do: Application.get_env(:MyApp, :dashboard_cache_ttl_ms, @default_ttl_ms)

  @impl true
  def init(_opts) do
    ensure_table()
    {:ok, %{}}
  end

  defp ensure_table do
    if :ets.whereis(@table) == :undefined do
      :ets.new(@table, [:set, :public, :named_table, write_concurrency: true])
    end
    :ok
  end

  defp read(key) do
    case :ets.lookup(@table, key) do
      [{^key, data, ts}] ->
        if System.monotonic_time(:millisecond) - ts < ttl_ms() do
          {:ok, data}
        else
          :miss
        end
      [] -> :miss
    end
  end
end
```

## Key design decisions

### TTL expiry, NOT PubSub invalidation

The `metrics:updated` broadcast still triggers the LiveView's reload
cycle (debounced to 2s), but the reload reads from cache first. If the
entry is within TTL, it's a hit — no Postgres query. This means the
dashboard may show data up to `ttl_ms` stale, which is acceptable for a
metrics overview.

With a 5s TTL and 2s debounce, a single dashboard hits Postgres every
~5-6s instead of every ~2s — a ~60% reduction. Multiple dashboards for
the same user share one cache entry.

If you need more aggressive freshness, call `DashboardCache.invalidate/1`
from the PubSub handler — but the TTL-only approach is simpler and
sufficient for most dashboards.

### `write_concurrency: true`, NOT `read_concurrency: true`

Unlike a read-heavy graph cache (where `read_concurrency: true` is
correct), this cache is written to on every miss. `write_concurrency:
true` optimizes for the concurrent-miss case — multiple LiveView
processes may miss simultaneously and all try to populate the cache.
Worst case: one extra compute, last-write-wins. No correctness issue.

### GenServer only owns the table

Same pattern as `Collector` and `Window`: the GenServer creates the ETS
table in `init/1` and never touches it again. `fetch_or_compute/2`,
`put/2`, `invalidate/1` all run in the caller's process. No GenServer
bottleneck on the read path.

### Cache key = `{user_id, period, timezone}`

- `user_id` — each user sees their own scoped data.
- `period` — "today", "7d", "30d", "90d" produce different query bounds.
- `timezone` — hour-bucketing is timezone-aware, so the same period in
  different timezones produces different chart series.

## The refactor: compute bundle + apply bundle

The key insight: separate the **query logic** (pure, no socket) from the
**assign logic** (socket only). This makes the query result cacheable.

### Before (every PubSub reload re-queries Postgres)

```elixir
defp load_metrics(socket, user) do
  opts = [...]
  socket
  |> load_summary_metrics(user, opts)      # Postgres query
  |> load_chart_series(user, opts, ...)     # Postgres query
  |> load_breakdowns(user, opts)            # Postgres query
  |> load_model_usage_stats(user)           # 4 Postgres queries
  |> assign(:loading, false)
end
```

### After (cache miss → compute bundle; cache hit → apply bundle)

```elixir
defp load_metrics(socket, user) do
  period = socket.assigns[:period] || "today"
  timezone = socket.assigns[:timezone] || "Etc/UTC"
  cache_key = DashboardCache.build_key(user.id, period, timezone)

  bundle = DashboardCache.fetch_or_compute(cache_key, fn ->
    compute_metrics_bundle(user, period, timezone, socket.assigns)
  end)

  apply_metrics_bundle(socket, bundle)
end

# Pure: no socket, returns a plain map. Called only on cache miss.
defp compute_metrics_bundle(user, period, timezone, assigns) do
  # ... all the Postgres queries ...
  %{metrics: ..., cost_series: ..., breakdown_model: ..., ...}
end

# Cheap: no Postgres, just applies the bundle to socket assigns.
defp apply_metrics_bundle(socket, bundle) do
  socket
  |> assign(:metrics, bundle.metrics)
  |> assign(:cost_series, bundle.cost_series)
  # ...
  |> assign(:loading, false)
end
```

**Critical:** `load_model_catalog` must run in `mount/3` BEFORE
`load_metrics`, because `compute_metrics_bundle` reads
`assigns[:model_catalog]` to build model_ids. If it runs inside
`load_metrics`, a cache hit skips it and `model_catalog` stays empty.

## Registration

Add to the metrics supervisor's children:

```elixir
children = [
  MyApp.Metrics.Collector,
  MyApp.Metrics.Window,
  MyApp.Metrics.DashboardCache    # new
]
```

## Testing

### Unit tests for the cache module

```elixir
use ExUnit.Case, async: false  # named ETS table = singleton

setup do
  pid = Process.whereis(DashboardCache) || start_supervised!(DashboardCache)
  _ = :sys.get_state(pid)
  DashboardCache.invalidate_all()
  :ok
end

test "cache hit does not recompute" do
  key = DashboardCache.build_key("user-1", "today", "Etc/UTC")
  call_count = :counters.new(1, [:atomics])

  compute = fn ->
    :counters.add(call_count, 1, 1)
    %{data: :ok}
  end

  _ = DashboardCache.fetch_or_compute(key, compute)
  _ = DashboardCache.fetch_or_compute(key, compute)

  assert :counters.get(call_count, 1) == 1  # computed once
end
```

### TTL expiry test — use monotonic_time, NOT hardcoded 0

```elixir
test "entry expires after TTL and recomputes" do
  key = DashboardCache.build_key("user-ttl", "today", "Etc/UTC")
  # ... compute once ...

  # Age the entry past TTL. monotonic_time is relative to BEAM boot,
  # so compute the expired timestamp dynamically:
  expired_ts = System.monotonic_time(:millisecond) - DashboardCache.ttl_ms() - 1
  :ets.insert(:myapp_dashboard_cache, {key, %{v: :stale}, expired_ts})

  result = DashboardCache.fetch_or_compute(key, fn -> %{v: :fresh} end)
  assert result == %{v: :fresh}
end
```

**Pitfall:** `System.monotonic_time(:millisecond)` on the BEAM is
relative to VM boot, NOT Unix epoch. On a freshly started VM, the value
may be small (a few thousand ms). Using `0` as an "old" timestamp does
NOT guarantee expiry because `0` may be within `ttl_ms` of the current
monotonic time. Always compute the expired timestamp as
`current_monotonic - ttl - 1`.

### Integration tests

The existing LiveView tests (e.g. `dashboard_live_test.exs`) should pass
unchanged — the cache is transparent to the LiveView's behavior. Run
them alongside the cache unit tests to confirm the refactor didn't break
render, event handlers, or period switching.
