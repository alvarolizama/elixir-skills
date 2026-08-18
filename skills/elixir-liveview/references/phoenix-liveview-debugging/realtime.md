---
name: phoenix-liveview-realtime-ui
description: "Use when adding realtime UI to Phoenix LiveView dashboards."
version: 1.2.0
author: Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [phoenix, liveview, presence, realtime, drag-drop, dashboard, heex]
    related_skills: [phoenix-liveview-debugging, phoenix-heex-design-system, phoenix-security-audit]
---

# Phoenix LiveView Realtime UI

Use this when building live dashboard UI in Phoenix LiveView: "who's online"
indicators, in-flight request counters, alert badges in the layout topbar,
real-time tables that reload on PubSub, drag-and-drop row reordering, and
human-readable number formatting. All patterns verified in MyApp
(Phoenix 1.8, LiveView 1.x, Tailwind v4, no external JS libs).

## Phoenix.Presence — "usuarios conectados"

### The Presence module

```elixir
defmodule MyAppWeb.Presence do
  use Phoenix.Presence,
    otp_app: :MyApp,
    pubsub_server: MyApp.PubSub

  @topic "dashboard:online"
  def topic, do: @topic

  def track_user(pid, user) do
    track(pid, @topic, user.id, %{email: user.email})
  end

  def list_online do
    @topic
    |> list()
    |> Enum.map(fn {user_id, %{metas: [meta | _]}} -> %{id: user_id, email: meta.email} end)
    |> Enum.sort_by(& &1.email)
  end
end
```

Add `MyAppWeb.Presence` to the supervision tree AFTER PubSub. ⚠️ **This
requires a full server restart** — `application.ex` changes are NOT picked
up by phoenix_live_reload. Symptom: the page renders but the online count
stays 0 (tracking raises on the connected mount and the LV keeps the
disconnected render). Tell the user to restart whenever you touch
`application.ex`.

### Track GLOBALLY in on_mount, not per-LiveView

First version tracked in `LogsLive.mount` — result: the counter only worked
on /logs and read 0 everywhere else. The right place is the shared
`UserAuth.on_mount` hook so EVERY dashboard LiveView tracks:

```elixir
def on_mount(:require_authenticated, _params, session, socket) do
  user = fetch_user(session)
  socket = assign_new(socket, :current_user, fn -> user end)

  if user do
    track_presence(socket, user)
    {:cont, socket}
  else
    {:halt, Phoenix.LiveView.redirect(socket, to: "/login")}
  end
end

defp track_presence(socket, user) do
  if Phoenix.LiveView.connected?(socket) do
    {:ok, _} = MyAppWeb.Presence.track_user(self(), user)
  end

  :ok
end
```

Only the CONNECTED mount owns a websocket process worth tracking — gate on
`connected?(socket)` or the disconnected render tracks a dying process.

### Displaying online users

Subscribe to the topic and handle the diff broadcast:

```elixir
if connected?(socket) do
  Phoenix.PubSub.subscribe(MyApp.PubSub, MyAppWeb.Presence.topic())
  {:ok, assign(socket, :online_users, MyAppWeb.Presence.list_online())}
end

def handle_info(%Phoenix.Socket.Broadcast{event: "presence_diff"}, socket) do
  {:noreply, assign(socket, :online_users, MyAppWeb.Presence.list_online())}
end
```

Render as initials chips (`-space-x-2` overlap, `title={u.email}` for the
full email). Compute initials from the local part of the email split on
`[._-]`, first letters of the first two segments, upcased.

## Live ops indicators in the layout topbar

Put global counters (online users, in-flight requests, alert counts) in the
layout function component — they show on every page without per-LiveView
assigns. Compute at render time from CHEAP sources:

```elixir
defp topbar_indicators(assigns) do
  assigns =
    assigns
    |> assign(:error_count, MyApp.Providers.count_error_credentials())          # COUNT query, indexed
    |> assign(:open_breakers, MyApp.Routing.CircuitBreakerManager.count_open()) # Registry walk
    |> assign(:online, length(MyAppWeb.Presence.list_online()))                  # ETS
    |> assign(:inflight, MyApp.Limits.Manager.total_inflight())                  # ETS fold
  ~H""" ... badges ... """
end
```

Rules of thumb:
- ETS/Registry reads are free per render. ONE indexed COUNT query per
  render is acceptable for an internal admin tool; anything heavier needs a
  cache or a broadcast-driven assign.
- Alert badges: ghost style at 0, `badge-error` / `badge-warning` when > 0.
  Split distinct alert classes into separate badges (error credentials ≠
  open breakers) — users asked for this split explicitly.
- Link badges to the page where the user acts on them (alerts → alerts
  page, in-flight → logs page). Hide admin-only destinations behind the
  same role check the router uses.
- In-flight counters: read the same ETS table your rate limiter already
  maintains (`:ets.foldl(fn {_k, v}, acc -> acc + v end, 0, table)`). For
  sub-second freshness, poll with `Process.send_after(self(), :refresh, 3_000)`
  in the connected mount — do NOT broadcast per request.

## In-flight (pending) request ROWS, not just counters

When the UI needs a live "Pending" row per in-flight request (model, user,
elapsed) — not just a counter — the durable log table can't help: rows only
exist after completion. Pattern verified in MyApp (`Logs.Inflight`):

### 1. ETS registry GenServer

GenServer owns a `:public, :named_table, :set` ETS table. Public write
functions run in the CALLER process (insert/delete direct on ETS) and
broadcast; the GenServer only handles the TTL sweep. Entries carry display
metadata (model, user_email, team_name, think/effort, started_at).

```elixir
def start_request(attrs) do
  ensure_table()
  entry = Map.merge(%{id: Ecto.UUID.generate(), started_at: DateTime.utc_now() |> DateTime.truncate(:second)}, attrs)
  :ets.insert(@table, {entry.id, entry})
  Phoenix.PubSub.broadcast(@pubsub, @topic, {:inflight_started, entry})
  entry
end

def finish_request(id) do
  ensure_table()
  :ets.delete(@table, id)
  Phoenix.PubSub.broadcast(@pubsub, @topic, {:inflight_done, id})
  :ok
end
```

`ensure_table/0` in every public function (`case :ets.whereis(@table)` →
create if missing) keeps tests and crashes safe. **TTL sweep is mandatory**:
a request that dies with the provider never sends `finish_request`, so
without a sweep the Pending row is a ghost forever. Sweep interval ~60s,
TTL ~10 min, broadcast `:inflight_done` for swept ids so UIs drop them.

### 2. Register in the controller with try/after

```elixir
{conn, inflight} = register_inflight(conn, member, payload)
try do
  execute(conn, ...)
after
  Inflight.finish_request(inflight.id)   # guaranteed on error too
end
```

⚠️ **Conn is immutable** — a helper that both `assign(conn, ...)`s and
returns the entry must return `{conn, entry}` and the caller MUST rebind
conn; assigns set on a discarded conn silently vanish (classic bug: the
durable log then misses the fields you parsed).

### 3. LiveView: pending rows INSIDE the main stream (merged, highlighted)

When you want pending rows to appear **inside** the main logs table (not a separate card), convert the Inflight entry to the log shape and insert into the same stream:

```elixir
# Convert entry → log shape with __pending__ flag
defp pending_entry_to_log(entry) do
  %{
    id: "pending-#{entry.id}",
    inserted_at: entry.started_at,
    model_requested: entry.model_requested,
    team_member: %{user: %{email: entry.user_email}, team: %{name: entry.team_name}},
    # ... all other fields as nil or "—" ...
    __pending__: true
  }
end

# On start: stream_insert at top
def handle_info({:inflight_started, entry}, socket) do
  if pending_visible?(entry, socket.assigns) do
    socket =
      socket
      |> assign(:pending, [entry | socket.assigns[:pending]])
      |> assign(:api_inflight, socket.assigns[:api_inflight] + 1)
      |> stream_insert(:logs, pending_entry_to_log(entry), at: 0)

    {:noreply, socket}
  end
end

# On done: stream_delete (needs map with :id, NOT a string)
def handle_info({:inflight_done, id}, socket) do
  socket =
    socket
    |> assign(:pending, Enum.reject(socket.assigns[:pending], &(&1.id == id)))
    |> stream_delete(:logs, %{id: "pending-#{id}"})  # ← map, not "pending-#{id}"

  {:noreply, socket}
end
```

**Template**: one `<tbody id="logs" phx-update="stream">`, branch on `Map.get(log, :__pending__)` for the row class (`bg-warning/20`) and cell rendering (badge "En vuelo" instead of status code, dashes for missing metrics).

**Pitfall**: `stream_delete/3` expects a struct or map with `:id` key — passing a plain string like `"pending-123"` raises `ArgumentError`. Always pass `%{id: "pending-#{id}"}`.

**Filter changes**: when the user changes filters, reset the stream AND re-insert pending rows at top (`load_logs_with_pending/1` pattern).

### 4. Preload associations in BOTH paths

Rows rendered from the list query AND rows arriving via broadcast must
carry the same preloads or live rows show "—" where initial rows show data:
add `preload(team_member: [:user, :team])` to the list query AND
`Repo.preload(struct, ...)` after insert before broadcasting.

### 5. Test pitfalls (LiveViewTest)

- `render_change` on a `<select>` REQUIRES the value to be one of the
  rendered options — the test must create real option rows (e.g. model
  aliases) first, then filter by that name.
- Broadcast-driven rows: call the registry/broadcast from the test, then
  `render(view)` to flush the message before asserting.
- ⚠️ **Function components with `attr` are called `<.badge value={x} />`,
  NOT `{badge(x)}`** — passing the value as the assigns arg compiles but
  renders wrong (or raises on missing attr). Plain string helpers are fine
  for unstyled output; anything with markup/classes wants the component.

### 6. KPI card counter MUST share the same filter as the rows

When a dashboard shows the in-flight count BOTH as a KPI card ("En vuelo: 3")
AND as a row list ("En vuelo ahora · 3 rows"), they must agree. The
recurring bug: the card reads `Inflight.count/0` (the **raw** ETS size,
no filter) while the rows read `visible_pending(assigns)` (filtered by
scope + agent + model + team + date range). User sees "En vuelo: 5" and
"En vuelo ahora: 3" and reports it as "se duplica" — the two numbers
disagree because one ignores the user's filters.

Fix:

```elixir
# Single source of truth: same filter the rows use.
defp visible_inflight_count(assigns), do: visible_pending(assigns) |> length()

# Initial mount + the 3s reconciler tick both read it:
|> assign(:api_inflight, visible_inflight_count(socket.assigns))

# Inflight events update the card counter IMMEDIATELY (don't wait for the
# 3s tick) — but only when the entry actually passes the filter:
def handle_info({:inflight_started, entry}, socket) do
  if pending_visible?(entry, socket.assigns) do
    socket =
      socket
      |> assign(:pending, [entry | socket.assigns[:pending]])
      |> assign(:api_inflight, socket.assigns[:api_inflight] + 1)

    {:noreply, socket}
  else
    {:noreply, socket}
  end
end

def handle_info({:inflight_done, id}, socket) do
  pending_before = socket.assigns[:pending]
  removed? = Enum.any?(pending_before, &(&1.id == id))

  socket =
    socket
    |> assign(:pending, Enum.reject(pending_before, &(&1.id == id)))
    |> update(:api_inflight, fn n -> if removed?, do: max(n - 1, 0), else: n end)

  {:noreply, socket}
end
```

Two non-obvious details:

- **Decrement with `max(n - 1, 0)`** — a `:inflight_done` for an entry
  the user already filtered out (or one added in a different LiveView
  process) MUST NOT push the counter negative. Only decrement when the
  row was actually present in `@pending` (the `removed?` check).
- **Reconcile in the periodic tick** — the periodic `:refresh_inflight`
  tick re-runs `visible_inflight_count/1` so any drift (TTL sweep,
  missed broadcast, race, session restart) self-heals within seconds.
  Without it, a counter that went negative stays negative forever.

The general rule: any time the same number appears in two UI surfaces
(KPI card + table, badge + list, summary + detail), both must read
from the SAME filtered source. If the source is cheap (ETS, in-memory
list) this is trivially correct. If the source is a DB query, define
a `count_X/1` helper that takes the same filter args as the list query
and call it from both places.

### 7. Adding a new metadata column — full enrichment pipeline

When you need to show a NEW piece of metadata in both the pending
(in-flight) table AND the completed-logs table (e.g. `api_key_prefix`,
`provider_name`, `think`, `effort`), you must thread it through FOUR
layers — missing any one produces "—" in the UI:

```
proxy_controller.ex        inflight.ex          write_worker.ex       logs_live.ex
register_inflight/4   →    entry map       →    args["field"]    →    template cell
enqueue_log                start_request       perform/1             <td>
```

**Step 1 — Schema + migration.** Add the column to `request_logs` and
`@permitted` in the changeset. The field is nullable (existing rows
pre-date it).

**Step 2 — Inflight entry type.** Add the field to the `@type entry`
map and to the `start_request/1` attrs `Map.get` block. ETS stores
maps, so no migration — but old entries (in-flight at deploy) will have
`nil` for the new field, which the template must handle with `|| "—"`.

**Step 3 — Proxy `register_inflight`.** Pass the data at registration
time. If the new field comes from the `route` (e.g. `provider_name`)
or `member` (e.g. `api_key_prefix`), the function signature grows
(`/3` → `/4`) — call sites that still call `/3` will fail at compile
time (good). The `try/after` block calling `finish_request` is unaffected.

**Step 4 — Proxy `enqueue_log`.** Add the field to the Oban args map.
The WriteWorker picks it up from `args["field"]` and passes it to the
changeset. ⚠️ Decimal fields must be `Decimal.to_string/2` before
enqueueing — Oban serializes to JSON.

**Step 5 — WriteWorker `perform/1`.** Add `field: args["field"]` to the
attrs map passed to `Logs.log_request/1`.

**Step 6 — LiveView template.** Add `<th>` + `<td>` in BOTH tables
(pending + completed). Update the empty-row `colspan` — off-by-one
causes the empty state to render misaligned.

**Step 7 — Tests.** Update `member_with_log` helper (completed logs)
and `Inflight.start_request(%{...})` calls (pending) to include the
new field, otherwise tests pass but don't verify the new column.

### 7. Top-N "last minute" KPI cards (Postgres, not ETS)

When a dashboard needs "Top 3 models/users in the last minute" cards, do NOT use the in-flight ETS registry (it only knows CURRENT in-flight, not recent history). Query Postgres with the same filter pipeline as the list view:

```elixir
def top_models_last_minutes(minutes \\ 1, limit \\ 3, filters \\ %{}) do
  cutoff = DateTime.add(DateTime.utc_now(), -minutes * 60, :second)

  RequestLog
  |> where([rl], rl.inserted_at >= ^cutoff)
  |> where([rl], not is_nil(rl.model_requested))
  |> apply_log_filters(filters)        # ← SAME filters as list_logs/1
  |> group_by([rl], rl.model_requested)
  |> order_by([rl], desc: count(rl.id))
  |> limit(^limit)
  |> select([rl], %{model: rl.model_requested, count: count(rl.id)})
  |> Repo.all()
end
```

Key rules:
- **Pass the same filter map** the list view uses (scope_member_ids, agent_type, model_search, team_id, streaming, error_reason). Missing this leaks rows the table would hide — the test failure mode is "filter says hide X but the card still shows it".
- **Refresh on the same tick** as the summary cards (e.g. `:timer.send_interval(3_000, :refresh_inflight)`), not per-request.
- **Empty state**: render "—" when `[]`, same as other KPI cards.

## Debounced PubSub reloads (storm protection)

Never run a DB query per broadcast per connected LiveView. Coalesce with a
scheduled reload (full pattern + rationale lives in the
`phoenix-security-audit` skill, Category 5c): `reload_scheduled` assign +
`Process.send_after(self(), :reload, 2_000)`. The UI stays ≤2s behind live
while DB load becomes independent of traffic.

## Drag-and-drop sortable table rows

Native HTML5 DnD — no external libs (respects the "only app.js bundle" rule
in phx.new projects). Three pieces:

### 1. The JS hook (app.js, registered in the hooks object)

```js
const SortableRows = {
  mounted() {
    this.dragged = null

    this.el.addEventListener("dragstart", e => {
      const row = e.target.closest("tr[data-id]")
      if (!row) return
      this.dragged = row
      e.dataTransfer.effectAllowed = "move"
      try { e.dataTransfer.setData("text/plain", row.dataset.id) } catch (_) {}
      row.classList.add("opacity-40")
    })

    this.el.addEventListener("dragend", () => {
      if (this.dragged) this.dragged.classList.remove("opacity-40")
      this.dragged = null
      this.clearIndicators()
    })

    this.el.addEventListener("dragover", e => {
      if (!this.dragged) return
      e.preventDefault()                      // REQUIRED or drop never fires
      e.dataTransfer.dropEffect = "move"
      const row = e.target.closest("tr[data-id]")
      this.clearIndicators()
      if (!row || row === this.dragged) return
      row.classList.add("bg-primary/10")
    })

    this.el.addEventListener("drop", e => {
      if (!this.dragged) return
      e.preventDefault()
      const row = e.target.closest("tr[data-id]")
      this.clearIndicators()
      if (!row || row === this.dragged) return

      const rect = row.getBoundingClientRect()
      const after = (e.clientY - rect.top) > rect.height / 2
      this.el.insertBefore(this.dragged, after ? row.nextSibling : row)  // optimistic

      const ids = Array.from(this.el.querySelectorAll("tr[data-id]")).map(r => r.dataset.id)
      this.pushEvent("reorder_rows", {parent_id: this.el.dataset.parentId, ids})
    })
  },

  clearIndicators() {
    this.el.querySelectorAll("tr[data-id]").forEach(r => r.classList.remove("bg-primary/10"))
  }
}

// hooks: {...colocatedHooks, SortableRows}
```

Tailwind class caveat: any class added via `classList.add` must already
exist in the compiled CSS — Tailwind v4 scans source files, so reuse a
class that appears in your templates (`bg-primary/10`, `opacity-40`), don't
invent JS-only ones.

### 2. The markup

```heex
<tbody id={"sortable-#{parent.id}"} phx-hook="SortableRows" data-parent-id={parent.id}>
  <tr :for={row <- sorted_rows(parent)} id={"row-#{row.id}"} data-id={row.id}
      draggable="true" class="cursor-grab active:cursor-grabbing">
    <td class="w-8 text-base-content/30"><.icon name="hero-bars-3" class="w-4 h-4" /></td>
    ...
```

Only make rows draggable for users allowed to reorder (`draggable={to_string(@is_admin)}`,
hide the handle column otherwise). Display order must follow the sortable
field: `Enum.sort_by(rows, fn r -> {is_nil(r.priority), r.priority || 0} end)`
(nil priority sorts last).

### 3. The server event — validate ownership, normalize positions

```elixir
def handle_event("reorder_rows", %{"parent_id" => parent_id, "ids" => ids}, socket) do
  valid_ids =
    from(r in Row, where: r.parent_id == ^parent_id, select: r.id)
    |> Repo.all()
    |> MapSet.new()

  # NEVER trust client-sent ids: every id must belong to the parent, or a
  # crafted event rewrites another parent's rows (IDOR via reorder).
  if is_list(ids) and ids != [] and Enum.all?(ids, &MapSet.member?(valid_ids, &1)) do
    {:ok, _} =
      Repo.transaction(fn ->
        ids
        |> Enum.with_index(1)
        |> Enum.each(fn {id, pos} ->
          from(r in Row, where: r.id == ^id)
          |> Repo.update_all(set: [position: pos, updated_at: DateTime.truncate(DateTime.utc_now(), :second)])
        end)
      end)

    {:noreply, load_rows(socket)}
  else
    {:noreply, put_flash(socket, :error, "Orden inválido.")}
  end
end
```

No success flash — drag-drop is high-frequency; a flash per drop is noise.
Test with `render_hook(view, "reorder_rows", %{...})` plus a foreign-id
rejection case (IDs from another parent must not change).

## Number formatting: K/M/B compact + thousands separators

Users want `32,711` or `32.7K`, never raw `32711`. Two helpers per LiveView
module (no shared helper module needed for 2-3 call sites):

```elixir
def format_number(n) when is_integer(n) do
  digits = Integer.to_string(abs(n))

  grouped =
    digits
    |> String.reverse()
    |> String.replace(~r/(\d{3})(?=\d)/, "\\1,")
    |> String.reverse()

  if n < 0, do: "-" <> grouped, else: grouped
end

def format_compact(n) when is_integer(n) and n >= 1_000_000_000, do: "#{Float.round(n / 1_000_000_000, 1)}B"
def format_compact(n) when is_integer(n) and n >= 1_000_000,     do: "#{Float.round(n / 1_000_000, 1)}M"
def format_compact(n) when is_integer(n) and n >= 1_000,         do: "#{Float.round(n / 1_000, 1)}K"
def format_compact(n) when is_integer(n),                        do: Integer.to_string(n)
def format_compact(n) when is_float(n),                          do: format_compact(trunc(n))
def format_compact(_),                                           do: "0"
```

Where each goes (user-validated):
- **KPI cards** (big token/request totals): `format_compact` with the exact
  value in `title={format_number(n)}` so hover shows `32,711`.
- **Table cells**: `format_number` (commas) — compact loses precision where
  rows get compared.
- **CSV exports**: RAW integers/decimals, always. Exports are
  machine-readable; never route CSV through display formatters.

## Stats cards in entity card lists (services, teams, models)

When a list of entity cards needs real usage stats displayed as KPI cards:

### Query pattern

```elixir
# NOTE: query filters by service.id, but request_logs.team_member_id has
# a FK to team_members (NOT services). In production this query returns
# zero rows for services — see MyApp quirk note in `MyApp-cost-accounting`.
# Kept here for the UI shape; the empty-stats branch is the realistic render path.
thirty_days_ago = DateTime.utc_now() |> DateTime.add(-30 * 86_400, :second)

stats =
  from(l in RequestLog,
    where: l.team_member_id in ^service_ids and l.inserted_at >= ^thirty_days_ago,
    group_by: l.team_member_id,
    select: %{
      service_id: l.team_member_id,
      total_cost: sum(l.provider_cost_usd),
      total_requests: count(l.id),
      total_input_tokens: sum(l.prompt_tokens),
      total_output_tokens: sum(l.completion_tokens)
    }
  )
  |> Repo.all()
  |> Map.new(&{&1.service_id, &1})
```

### Template pattern — always render cards, default to zero

```heex
<% has_activity = Map.get(@service_stats, service.id) != nil %>
<% stats = Map.get(@service_stats, service.id, %{
  total_cost: Decimal.new(0),
  total_requests: 0,
  total_input_tokens: 0,
  total_output_tokens: 0
}) %>
<div class="mt-3 grid grid-cols-4 gap-3 w-full">
  <!-- 4 stat cards: cost, requests, tokens in, tokens out -->
  <div class="card bg-base-100 border border-base-300 shadow-sm">
    <div class="card-body p-4">
      <div class="flex items-center justify-between">
        <span class="text-xs font-medium text-base-content/60 uppercase tracking-wide">Gasto real</span>
        <span class="flex items-center justify-center w-8 h-8 rounded-lg bg-success/10">
          <.icon name="hero-currency-dollar" class="w-4 h-4 text-success" />
        </span>
      </div>
      <p class="mt-1.5 text-lg font-bold">${format_decimal(stats.total_cost || 0)}</p>
      <p class="text-xs text-base-content/40">30 días</p>
    </div>
  </div>
  <!-- ... repeat for requests, tokens in, tokens out -->
</div>
<%= if !has_activity do %>
  <p class="text-xs text-base-content/40 mt-2">Sin actividad en los últimos 30 días</p>
<% end %>
```

### Rules

- **Always render the cards** — don't hide them behind `if stats != %{}`. The user
  expects the card structure even when values are 0.
- **Full-width 4 columns** — `grid-cols-4 gap-3 w-full`, not `grid-cols-2 sm:grid-cols-4`.
- **Semantic colors** — success=green for cost, primary=blue for requests,
  accent=cyan for tokens in, warning=orange for tokens out.
- **Icons** — currency-dollar, bolt, arrow-down-tray, arrow-up-tray.

## Read-only LiveViews (defense-in-depth via `attach_hook`)

When a LiveView shows data the user CAN view but must NOT mutate (e.g.
a supervisor viewing services they don't own, a viewer role, an audit
log), the right pattern is NOT a `handle_event/3` fallback that returns
`{:halt, socket}` — `handle_event` callbacks must return `{:noreply, socket}`
or `{:reply, [], socket}`. Returning `{:halt, socket}` from a real
callback crashes the LiveView process:

```
** (ArgumentError) invalid return from MyAppWeb.SomeLive.handle_event/3
   callback. Expected: {:noreply, %Socket{}} | {:reply, map, %Socket{}}
   Got: {:halt, %Socket{}}
```

The correct pattern uses `attach_hook`, which DOES accept `{:cont, socket}`
/ `{:halt, socket}` — and that's the same primitive `ServicesLive` uses
for `require_admin_hook`:

```elixir
defmodule MyAppWeb.SupervisedThingLive do
  use MyAppWeb, :live_view

  def mount(_params, _session, socket) do
    socket =
      socket
      |> assign(:page_title, "…")
      |> attach_read_only_hook()
      |> load_data()

    {:ok, socket}
  end

  # No `handle_event/3` callbacks defined at all — the view is pure display.
  # The hook below catches any event a hostile client fires at the WebSocket.

  defp attach_read_only_hook(socket) do
    attach_hook(socket, :read_only, :handle_event, fn _event, _params, socket ->
      {:halt, put_flash(socket, :error, "Esta vista es de solo lectura.")}
    end)
  end
end
```

### UI cues — make the read-only nature explicit

A user who lands on a read-only view must know it can't be edited:

- A topbar badge ("Vista de solo lectura") permanently rendered in the
  page header (id like `#view-readonly-badge` so tests can assert it).
- Per-card "Solo lectura" chips so the user sees the constraint per row,
  not just at the page level.
- The ESLint rule for live admin views: if a control would be a
  `<button phx-click="…">` in the editable view, REMOVE it here. Don't
  just `disabled` it — disabled buttons still imply the action exists
  and tempt the user to click. The DOM must not contain the mutation
  surface at all.

### Test the read-only contract

Four must-have assertions in the test file:

1. **Unauthenticated** → redirect to `/login`.
2. **Empty state** (user has nothing to view) → friendly message,
   "read-only" badge still visible.
3. **Happy path** → card renders the data (name, status badge, stats,
   aliases, etc.).
4. **Zero mutating buttons** → refute every `phx-click="…"` event the
   editable view uses, plus the form selectors (e.g.
   `refute html =~ "phx-click=\"edit_service\""`).
5. **Hostile event blocked** → `render_click(view, "delete_anything", %{})`
   still hits the hook; the DB is unchanged and the response contains
   the flash.

## Service supervisors (read-only role for non-admin users)

Pattern for a "supervisor" role: a non-admin user who can view specific
services but not edit them. Validated on MyApp (2026-08-01):

1. **Migration + schema**: `service_supervisors` join table (`service_id`,
   `user_id`, unique pair, both FK `on_delete: :delete_all`).
2. **Context functions** (idempotent): `add_service_supervisor/2`,
   `remove_service_supervisor/2`, `services_for_supervisor/1`,
   `service_supervisor_ids/1`, `service_supervisors/1`.
3. **Route**: `live_session :service_viewer` with `require_authenticated`
   (NOT `require_admin`) — any logged-in user can access it.
4. **Read-only LiveView**: zero `handle_event/3` callbacks, `attach_hook`
   halts all events. Cards show 30d stats, api_key status, model aliases.
5. **Admin panel in ServicesLive**: per-service supervisor management
   (search users, add/remove badges). Uses `Accounts.search_users/2` for
   the autocomplete.
6. **Dashboard shortcut**: card on `/dashboard` when
   `supervised_services_count > 0`, linking to `/dashboard/services/supervised`.

⚠️ **Stream pitfall**: if the admin panel uses `stream(:services, ...)`,
the supervisor search form (a dynamic sub-panel per service) will NOT
re-render when the global `search_service_id` assign changes. Use plain
`assign` + `:for` for any list with interactive per-item UI. See the
stream pitfall in `riel-delegate` for the full debugging path.

**Complementary remedy — `stream_insert` the affected items**: when the
list legitimately STAYS a stream (CRUD + performance) but an external
datum it displays changes via PubSub (e.g. a live spend counter rendered
inside each streamed row), updating the assign alone does nothing — the
DOM rows are stream-managed. In `handle_info`, update the assign AND
re-insert the items that show the datum:

```elixir
def handle_info({:counter_updated, scope_id}, socket) do
  items = items_for_scope(scope_id)  # re-query with same preload/order as initial load

  socket =
    socket
    |> assign(:counters, Map.put(socket.assigns.counters, scope_id, read_counter(scope_id)))
    |> then(fn s -> Enum.reduce(items, s, &stream_insert(&2, :items, &1)) end)

  {:noreply, socket}
end
```

`stream_insert/3` on an existing stream id updates the row in place (position
kept). Refactor the initial load query into a shared helper
(`items_query/0` + a scoped `items_for_scope/1`) so the re-inserted struct
carries the exact same preloads as the first render. ⚠️ When scoping that
query, do NOT reach for `distinct: true` over an ORDER BY with a fragment
(CASE, etc.) — Postgres rejects it with `42P10: for SELECT DISTINCT, ORDER
BY expressions must appear in select list`. Filter by id subquery instead:
`from(i in items_query(), where: i.id in subquery(ids_query))`.

## Guard rails: per-model system prompt injection

When a model alias needs custom instructions prepended to every system prompt:

1. **Schema**: `guard_rails` (`:text`, nullable) on `model_aliases`.
2. **Modal**: separate from edit-alias modal, textarea input, own form assign
   (`@guard_rails_form`) and events (`edit_guard_rails`, `save_guard_rails`).
3. **Injection** in proxy controller before calling provider adapter:

```elixir
defp inject_guard_rails(payload, model_alias) do
  case model_alias.guard_rails do
    nil -> payload
    "" -> payload
    guard_rails ->
      messages = Map.get(payload, "messages", [])
      case messages do
        [%{"role" => "system", "content" => content} | rest] ->
          Map.put(payload, "messages", [
            %{"role" => "system", "content" => guard_rails <> "\n\n" <> content} | rest
          ])
        _ ->
          Map.put(payload, "messages", [
            %{"role" => "system", "content" => guard_rails} | messages
          ])
      end
  end
end
```

Call in both `execute/6` (non-streaming) and `execute_stream/6` after
`Map.put(payload, "model", route.model_responded)`.
