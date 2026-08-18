# ETS Rolling-Window for Realtime Sparklines

Pattern proven in MyApp's `MyApp.Metrics.Window` (Aug 2026) —
avoids hitting Postgres every 5s for a live 60-minute sparkline.

## Module structure

```elixir
defmodule MyApp.Metrics.Window do
  use GenServer

  @table :my_metrics_window
  @window_minutes 60
  @pubsub MyApp.PubSub
  @topic "metrics:window"
  @sweep_interval_ms 60_000
```

## Key design decisions

### Minute index = integer, not :minute

`System.system_time(:minute)` **does NOT exist** — Elixir only supports
`:second`, `:millisecond`, `:microsecond`, `:nanosecond`. Use:

```elixir
minute = div(System.system_time(:second), 60)
```

This gives a monotonic integer-minute offset from Unix epoch. Use it
EVERYWHERE: `record_request/1`, `snapshot/0`, `rotate/0`. If you miss
one, the GenServer crashes on `:sweep` 60s later.

### Caller-process writes (no GenServer bottleneck)

Same pattern as `Collector`:

```elixir
def record_request(attrs) do
  model_alias_id = Map.get(attrs, :model_alias_id)
  unless is_nil(model_alias_id) do
    minute = div(System.system_time(:second), 60)
    :ets.update_counter(@table, {model_alias_id, minute}, {2, 1},
      {{model_alias_id, minute}, 0})
  end
  :ok
end
```

### Snapshot with zero-fill

```elixir
def snapshot do
  now_minute = div(System.system_time(:second), 60)
  start_minute = now_minute - @window_minutes + 1

  all = @table |> :ets.tab2list() |> Enum.reject(fn {{_id, min}, _} ->
    min < start_minute
  end)

  models = all |> Enum.map(fn {{id, _}, _} -> id end) |> Enum.uniq()

  Map.new(models, fn alias_id ->
    counts = for minute <- start_minute..now_minute do
      case :ets.lookup(@table, {alias_id, minute}) do
        [{_key, count}] -> count
        [] -> 0
      end
    end
    {alias_id, counts}
  end)
end
```

### Backfill on boot — use try/catch, NOT try/rescue

```elixir
@impl true
def init(_opts) do
  ensure_table()
  try do
    backfill()   # calls Rollup.minute_series_by_model/1 → Repo
  catch
    _, _ -> :ok   # trap :noproc EXITs too, not just exceptions
  end
  schedule_sweep()
  {:ok, %{}}
end
```

**Why `catch` not `rescue`:** when the GenServer calls `Repo` in `init/1`
during tests (Ecto sandbox), the sandbox process may not be alive for
this GenServer's process. The crash is an `:noproc` EXIT — `rescue` only
catches exceptions raised within the `try` block, not linked-process
EXITs. The `catch _, _ ->` form traps both.

### Rotation (GenServer sweep)

```elixir
defp rotate do
  ensure_table()
  cutoff = div(System.system_time(:second), 60) - @window_minutes
  @table
  |> :ets.select([{{{:"$1", :"$2"}, :_}, [{:<, :"$2", cutoff}], [{{:"$1", :"$2"}}]}])
  |> Enum.each(fn key -> :ets.delete(@table, key) end)
end
```

The select returns full `{alias_id, minute}` key tuples that can be
passed directly to `:ets.delete/2`.

## Hooking into the existing Collector

One line added to `Collector.record_request/1`:

```elixir
# In record_request, after push_latency(latency_ms):
MyApp.Metrics.Window.record_request(attrs)
```

No broadcast needed — the LiveView polls on its 5s refresh cycle.

## Registration

Add to the metrics supervisor's children:

```elixir
children = [
  MyApp.Metrics.Collector,
  MyApp.Metrics.Window        # new
]
```

## Sparkline SVG helper functions

```elixir
def sparkline_points(counts) do
  max_val = Enum.max(counts, fn -> 1 end)
  step = 120 / 60   # svg width / bucket count

  counts
  |> Enum.with_index()
  |> Enum.map(fn {count, i} ->
    x = Float.round(i * step, 2)
    y = Float.round(30 - count / max_val * 30, 2)
    "#{x},#{y}"
  end)
  |> Enum.join(" ")
end

def sparkline_area_path(counts) do
  "M0,30 L#{sparkline_points(counts)} L120,30 Z"
end
```

HEEx usage:

```html
<svg viewBox="0 0 120 30" class="w-full h-8" preserveAspectRatio="none">
  <path d={sparkline_area_path(ticket.sparkline)} class="fill-primary/10">
  </path>
  <polyline points={sparkline_points(ticket.sparkline)}
    fill="none" class="stroke-primary"
    stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round">
  </polyline>
</svg>
```

## Trading-terminal LiveView layout

### Indices strip (top)

5 cards in a responsive grid:

```html
<div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
  <.index_card label="Requests / s" value={format_number(@indices[:rps])}
    icon="hero-bolt" color="text-primary" />
  ...
</div>
```

### Watchlist rows (clickable for drill-down)

```html
<button phx-click="toggle-expand" phx-value-model-id={ticket.alias_id}
  class={["grid ...", @expanded_model == ticket.alias_id && "bg-base-200/50"]}>
  ...sparkline, RPM, volume, total, in-flight badge...
</button>
```

### Drill-down panel (inline, per-credential)

When `@expanded_model == ticket.alias_id`:

```html
<.credential_drilldown rows={@credential_rows} />
```

Shows: credential_name, provider, req_count, p95, error_rate %, cost, status.
Status dot: green=active, gray=disabled, red=error. Joined from
`provider_credentials` table by name.

## Float.round pitfall in templates

`Float.round((@indices[:error_rate] || 0) * 100, 1)` crashes — `|| 0`
produces an **integer**, and `Float.round/2` requires a float. Fix:

```html
value={"#{Float.round((@indices[:error_rate] || 0.0) * 100, 1)}%"}
```

Always use `|| 0.0` (float default) in HEEx when the value feeds into
`Float.round/2`.