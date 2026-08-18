# Async data loading in LiveViews (start_async / assign_async)

Pattern that emerged from the MyApp StatsLive refactor (2026-08-07):
a dashboard LiveView running ~12 Ecto queries per `set_period` click went
from 3-5 s blocking loads to an instantly-responsive page by going fully
async. This is the canonical shape for any LiveView whose mount/params
handler runs multiple independent queries.

## Which API for what

| Need | API |
|---|---|
| One value the template renders via `<.async_result :let={val} assign={@key}>` | `assign_async/3` |
| Run N queries/tasks, then **bulk-apply many assigns** in one diff | `start_async/3` + `handle_async/3` |
| Fire-and-forget side effect (no assigns from result) | `start_async/3`, ignore in `handle_async` |

## The `assign_async` return-contract trap

`assign_async(socket, :key, fn -> {:ok, result} end)` requires `result`
to be a **map whose keys are the assign names to merge** — and it wraps
`:key` itself in `%Phoenix.LiveView.AsyncResult{}`.

- `{:ok, %{data: m}}` → ArgumentError: "expected assign_async to return
  map of assigns for all keys in [:stats_data]" (the returned map's keys
  must include the async assign's own name).
- `{:ok, %{stats_data: m}}` → works mechanically, but the template's
  `@stats_data` is an `AsyncResult` struct, not `m`. Every plain assign
  consumers expect (`@breakdown_model`, `@metrics`, …) stays empty unless
  the template unwraps via `<.async_result>`.

If the end goal is "fill a dozen existing plain assigns", `assign_async`
fights you. Use `start_async` instead — it delivers the raw return value
to `handle_async/3` where you `assign/2` whatever you want.

## Canonical shape

```elixir
def mount(_, _, socket) do
  {:ok,
   socket
   |> assign(:stats_loading, true)
   |> assign(empty_data_assigns())   # first paint = empty states
end

def handle_params(params, _uri, socket) do
  {:noreply, socket |> assign_filters(params) |> start_data_load()}
end

defp start_data_load(socket) do
  a = socket.assigns
  params = %{user: a.current_user, period: a.period, action: a.live_action,
             sort_field: a.sort_field, sort_direction: a.sort_direction}

  socket
  |> assign(:stats_loading, true)
  |> start_async(:stats_data, fn -> compute_data_assigns(params) end)
end

@impl true
def handle_async(:stats_data, {:ok, data}, socket) do
  {:noreply,
   socket
   |> assign(:stats_loading, false)
   |> assign(empty_data_assigns())   # drop keys the new action doesn't produce
   |> assign(data)}                  # one diff with all fresh data
end

def handle_async(:stats_data, {:exit, reason}, socket) do
  require Logger
  Logger.warning("data load failed: #{inspect(reason)}")
  {:noreply, assign(socket, :stats_loading, false)}
end
```

Key rules:

- **Capture assigns into plain values BEFORE the async fn.** The fn runs
  in a separate task; reading `socket.assigns` inside it is a stale-copy
  bug. Build a `%{}` of everything it needs first.
- **Fan out independent queries inside the task** with
  `Task.async_stream(funs, fn f -> f.() end, timeout: :infinity)`. Each
  returns `{assign_key, rows}`; merge with `Map.new/1`. Repo pool size
  bounds real parallelism — 12 queries on a pool of 10 land in ~2 rounds
  instead of 12 sequential ones.
- **Reset to empty defaults before applying results** when the loaded
  key set varies by `live_action` — otherwise switching views leaves
  stale keys (e.g. `member_usage_tiers` from :index) rendered on the
  new view.
- Re-triggering `start_data_load` while a previous one is in flight
  automatically kills the old task (LiveView owns task lifetime) — rapid
  period-clicking needs no debounce logic.
- Sorting/filtering that was previously re-run synchronously after the
  queries moves INTO the task (`apply_sorting(data, params)`), driven by
  captured sort assigns.

## UX: keep content mounted, show inline loading

Do NOT swap the whole content area for a full-page spinner
(`if @loading do ... else ... end`) — the unmount/remount flash makes
the page feel slower than the queries are. Instead:

```heex
<span :if={@stats_loading} class="loading loading-spinner loading-sm" id="stats-loading"></span>
...
<div class={["transition-opacity duration-200",
             @stats_loading && "opacity-50 pointer-events-none"]} id="stats-content">
  ...always-mounted content...
</div>
```

First mount renders empty states behind the spinner; subsequent reloads
show the previous data dimmed until the new diff lands.

## Testing

`live(conn, url)` returns before the async task finishes — sync with
`:sys.get_state(view.pid)` and poll the loading flag. Full recipe in
`references/testing.md` ("Testing LiveViews that load data via
start_async / assign_async").
