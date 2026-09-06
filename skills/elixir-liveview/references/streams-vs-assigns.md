# Streams vs Assigns — When Each Pattern Renders

**Symptom:** a `handle_event` fires, a socket assign updates correctly,
but the UI never re-renders — an inline form, search box, or expanded
panel inside a list item simply does not appear in the DOM.
`render_click` in tests returns HTML without the expected element.

## Mechanism

`stream(:items, items)` tells LiveView to manage the list as a **stream**
— items are appended/prepended/deleted individually, and LiveView diffs
at the ITEM level: an item re-renders only when the item's own data
changes. A **global assign** change (e.g. "open the search form for item
X") does NOT mark that item as changed, so the stream skips it entirely.
Stream items are opaque units keyed by DOM id; the item template is NOT
re-evaluated for unrelated assign changes.

## The decision rule

| Use `stream` when… | Use `assign` when… |
|---|---|
| List is large (100+ items), mostly read-only | List is small (<50 items) |
| Items are independent — no global state affects them | Items have interactive sub-panels driven by global assigns |
| You only append/prepend/delete (chat, logs, feeds) | You need inline forms, toggles, or conditional sections per item |
| Performance matters (avoid full re-render) | Correctness matters (content must reflect current assigns) |

## The fix

```elixir
# BROKEN — stream won't re-render on global assign changes
|> stream(:services, services, reset: true)

# WORKS — full re-render on every assign change
|> assign(:services, services)
```

```heex
<%!-- BROKEN --%>
<div id="services" phx-update="stream">
  <div :for={{id, service} <- @streams.services} id={id}>
    <div :if={@search_open_for_id == service.id}>
      <input name="query" />
    </div>
  </div>
</div>

<%!-- WORKS --%>
<div id="services">
  <div :for={service <- @services} id={"service-#{service.id}"}>
    <div :if={@search_open_for_id == service.id}>
      <input name="query" />
    </div>
  </div>
</div>
```

## Debugging recipe

1. `IO.inspect` in the `handle_event` to confirm the assign updates.
2. Check the `render_click` output for the expected element.
3. If the assign updates but the element is missing, check if the
   container uses `phx-update="stream"`.
4. If yes, switch to `assign` + `:for` and retest.

## Client-side visible toggles — no server state at all

For a pure show/hide toggle inside a stream item, don't keep state in
the socket. Drive it in the DOM with `JS.toggle` / `JS.toggle_class`:

```elixir
def toggle_providers_js(id) do
  JS.toggle(to: "#alias-providers-#{id}", display: "block")
  |> JS.toggle_class("rotate-90", to: "#alias-chevron-#{id}")
end
```

- `JS.toggle/2` toggles **inline `display`** (the `:display` option is
  the value used when *showing*, default `"block"`). Mark the section
  initially hidden with `style="display: none"`, NOT a `hidden`
  attribute and NOT a `:if` (a `:if` removes it from the DOM and — per
  the trap above — won't come back on an assign change anyway).
- Content stays in the DOM (just `display:none`), so LiveView tests can
  `has_element?` the inner buttons without simulating the expand click.
  If you switch to server-side `:if`, every existing test that clicks
  inner buttons starts failing because the nodes aren't rendered.
- Chevron rotation needs a stable span `id` + `transition-transform`.
- Give the collapsible container a per-item `id` so the `JS.toggle`
  selector targets exactly one card — never a shared class across all
  stream items.
- If collapse state must persist across reconnects, keep it ON the
  stream item (a struct field) or re-`stream_insert` the affected item —
  don't key `:if` off a side `MapSet` assign.

## Fusing pending/in-flight pseudo-entries into one stream

A real-time table can show completed rows (Postgres-backed) AND
in-flight rows (ETS-backed) in ONE stream:

```elixir
def handle_info({:inflight_started, entry}, socket) do
  socket
  |> assign(:pending, [entry | socket.assigns[:pending]])
  |> stream_insert(:logs, pending_entry_to_log(entry), at: 0)
end

def handle_info({:inflight_done, id}, socket) do
  socket
  |> assign(:pending, Enum.reject(socket.assigns[:pending], &(&1.id == id)))
  |> stream_delete(:logs, %{id: "pending-#{id}"})
end

defp pending_entry_to_log(entry) do
  %{
    id: "pending-#{entry.id}",
    inserted_at: entry.started_at,
    # ... all fields the template expects ...
    __pending__: true
  }
end
```

Template: `class={if Map.get(log, :__pending__), do: "bg-warning/20"}`
plus a "In flight" badge (`Map.get`, not `log.__pending__` — synthetic
rows are maps).

**Pitfall:** `stream_delete/2` expects a struct or map with `:id` —
passing a raw string like `"pending-abc"` crashes with
`ArgumentError: expected stream :logs to be a struct or map with :id
key`.

**Re-insert after filter reset:** when filters change →
`stream(..., reset: true)` wipes the stream; after the reset, re-insert
the pending entries from the `:pending` assign (`Enum.reduce` +
`stream_insert(acc, :logs, pending_entry_to_log(entry), at: 0)`).