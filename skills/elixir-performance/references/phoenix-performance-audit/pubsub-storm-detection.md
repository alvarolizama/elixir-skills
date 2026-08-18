# PubSub storm detection — Phoenix/Elixir

How to identify a PubSub storm and prove it. A "storm" is when a
PubSub topic is broadcast per-request (or per-event at high rate)
and at least one subscriber runs a DB query per message.

## The two sides to inspect

### Broadcaster side

Find every `Phoenix.PubSub.broadcast/3` call in the codebase. Each
broadcast defines a topic; the rate at which the broadcaster fires
is the rate at which subscribers receive messages.

```bash
grep -rn 'Phoenix.PubSub.broadcast\|Phoenix.PubSub.local_broadcast' \
  lib/<app> lib/<app>_web
```

For each call, classify the rate:

| Source                                            | Rate |
|---------------------------------------------------|------|
| `Metrics.Collector.record_request/1` per proxied req | per-request |
| `Logs.WriteWorker.perform/1` `broadcast_new_log/1` | per-request |
| Webhook worker (per Oban job)                     | per-request |
| `Budgets.Manager.record_spend/2`                 | per-request (counted, not broadcast by default) |
| Admin action (toggle, delete, …)                 | low (manual) |
| Module reloaded in dev                           | per-recompile (dev only) |

Anything in the per-request column is a candidate for storming.

### Subscriber side

Find every `Phoenix.PubSub.subscribe` in LiveView modules. For each,
classify what the matching `handle_info` does:

```bash
grep -rn 'Phoenix.PubSub.subscribe' lib/<app>_web/live
```

For each subscriber, look at the matched `handle_info` clauses:

```elixir
def handle_info({:metrics_updated, _}, socket) do
  # ?  read ETS (cheap) -> OK
  # ?  read ETS + run aggregate SQL query (storm)
  if socket.assigns[:reload_scheduled] do
    {:noreply, socket}
  else
    Process.send_after(self(), :reload_metrics, 2_000)
    {:noreply, assign(socket, :reload_scheduled, true)}
  end
end
```

Coalescing via `Process.send_after` is the *minimum* good practice.
Even with coalescing at 1s, the inner `load_X/1` can still issue
dozens of DB queries — and at 1 RPS that's still a sustained
storm on a growing table.

## The compound storm pattern (the worst case)

Most dangerous when ALL of these hold:

1. Topic broadcast per-request (`"logs:new"` from `Logs.WriteWorker`).
2. Multiple LiveViews subscribe to the same topic
   (`credits_live`, `alerts_live`, `logs_live` all subscribe to
   `"logs:new"`).
3. The handler runs a DB query (`load_X/1`) that issues N+1 queries
   over a growing table.

Under sustained proxy traffic:

- N connected LiveViews × per-message query cost = N × cost.
- Coalescing helps but only amortizes — the inner query is still
  the bottleneck.
- DB query that loads ALL members of a system (e.g.
  `list_member_budgets`) is the worst: cost grows with member count.

The MyApp audit found this exact pattern in `credits_live` and
`alerts_live` (findings PS-01 and PS-02).

## Severity decision tree

```
broadcaster rate  =  per-request?
subscriber count  =  >1?
handler reads DB =  yes?
  -> storm severity = high
  + if handler does cascade N+1 over system-wide data -> escalate to critical

broadcaster rate  =  per-request?
handler reads ETS =  yes?
coalescing        =  present?
  -> acceptable pattern (dashboard_live is the reference implementation)

broadcaster rate  =  low / manual?
subscriber reads DB = yes?
  -> low severity (admin action storm)
```

## Detection recipe (concrete commands)

```bash
# 1. List all broadcasters
grep -rn 'Phoenix.PubSub\.broadcast\|Phoenix.PubSub\.local_broadcast' \
  lib/<app> lib/<app>_web

# 2. List all subscribers
grep -rn 'Phoenix.PubSub\.subscribe' lib/<app>_web

# 3. For each subscriber, dump the handle_info clauses that match
#    broadcaster messages (read the surrounding handle_info)

# 4. Inside each handle_info, grep for DB-shaped calls:
grep -nE 'Repo\.|Budgets\.|Logs\.|MyApp\.[A-Z][a-z]+\.' <live>.ex
# Mark any that appear inside a handle_info clause.

# 5. Cross-check: does the handler call a function that contains
#    Enum.map(... Context.helper(...))? Trace through.
```

## Fix patterns (in priority order)

1. **Move to ETS for hot counters.** If the handler reads
   `Budgets.Manager.spend/1` (ETS) instead of running an aggregate
   query, the storm evaporates. The `Manager` cache is updated
   synchronously by `record_spend/2` on the proxy hot path, so ETS
   is the source of truth for the most-recently-changed values.
2. **Stream inserts from the broadcaster.** For per-row events
   (`{:new_log, log}`), the handler can `stream_insert` the new log
   into a `Phoenix.LiveView.stream` (no DB read), and aggregate
   counters update lazily from a buffer or ETS snapshot.
3. **Cap subscribers.** If multiple LiveViews subscribe to the same
   storm topic, consolidate into a single LiveView that fans the
   data out (or push it to a single Presence/Registry instead).
4. **Increase the coalescing window** as a stopgap (not a fix).
   Going from 1s to 5s reduces DB load 5× but doesn't change the
   worst case.

## Already-good coalescing pattern (reference)

`dashboard_live.ex:88-108`:

```elixir
def handle_info({:metrics_updated, _lite}, socket) do
  if socket.assigns[:reload_scheduled] do
    {:noreply, socket}
  else
    Process.send_after(self(), :reload_metrics, 2_000)
    {:noreply, assign(socket, :reload_scheduled, true)}
  end
end

def handle_info(:reload_metrics, socket) do
  user = socket.assigns[:current_user]
  {:noreply,
   socket
   |> assign(:reload_scheduled, false)
   |> load_metrics(user)}
end
```

The handler that schedules the reload is cheap (ETS snapshot).
The handler that does the heavy work runs at most once per 2s.
This is the right pattern — but the heavy work itself (the
`load_metrics` body) still must be cheap or read from ETS.