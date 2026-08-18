# LiveView Streams vs Assigns — Rendering Pitfall

## Symptom

A LiveView page renders a list of items via `stream(:items, items)` and
each item contains interactive UI (buttons, forms, toggles). Clicking a
button inside a stream item fires the `handle_event` correctly and the
socket assign updates, but the UI **never shows the new content** — the
form, search results, or expanded panel simply doesn't appear in the DOM.

## Root Cause

`stream/3` optimizes for large append-only lists. Items are rendered as
morphdom patches keyed by DOM id. When a **global** assign changes
(e.g. `search_form_open`, `editing_id`, `results`), LiveView's diff
engine skips stream items because the stream itself hasn't changed —
only the parent's assigns have. The stream item's template is NOT
re-evaluated.

## Reproduction Recipe

```elixir
# mount
|> stream(:services, services)

# template
<div :for={{id, service} <- @streams.services} id={id}>
  <button phx-click="toggle_form" phx-value-id={service.id}>
    Open form
  </button>
  <div :if={@editing_id == service.id}>
    <input name="query" />
  </div>
</div>

# handle_event
def handle_event("toggle_form", %{"id" => id}, socket) do
  {:noreply, assign(socket, :editing_id, id)}
end
```

The assign updates but the `:if` block never renders.

## Fix

Replace `stream` with plain `assign` when the list is small and items
contain interactive UI that depends on global assigns:

```elixir
# mount
|> assign(:services, services)

# template
<div :for={service <- @services} id={"service-#{service.id}"}>
  ...
</div>
```

## When Streams Are OK

- True append-only lists (chat messages, log entries, activity feeds)
- No per-item interactive state that depends on parent assigns
- Items are read-only or self-contained (each item has its own LiveComponent)

## When to Switch to Assign

- < 50 items
- Each item has buttons/forms/toggles that mutate parent assigns
- You need `phx-change` / `phx-keyup` inside items
- You use `:if` with a parent assign inside the item template
