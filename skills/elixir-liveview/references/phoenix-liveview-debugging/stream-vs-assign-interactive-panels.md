# LiveView Stream vs Assign: Interactive Sub-Panels

## The Problem

When using `stream(:items, items, reset: true)` for a list of items, and each
item contains an interactive sub-panel (search form, inline edit, expandable
section) driven by a **global assign** (e.g. `search_open_for_id`), the panel
**never re-renders** when the assign changes.

**Symptom**: The `handle_event` fires, the assign updates, but the DOM stays
stale — the search input never appears after clicking "Add".

**Root cause**: LiveView streams only diff the item if the item's own data
changes. They do NOT re-render when unrelated global assigns change.

## The Fix

Use plain `assign` + `:for` over the list for any collection whose items
contain interactive sub-components:

```elixir
# WRONG for interactive items
|> stream(:services, services, reset: true)

# RIGHT for interactive items
|> assign(:services, services)
```

```heex
<%# WRONG %>
<div :for={{id, service} <- @streams.services} id={id}>
  <div :if={@search_open_for_id == service.id}>...</div>
</div>

<%# RIGHT %>
<div :for={service <- @services} id={"service-#{service.id}"}>
  <div :if={@search_open_for_id == service.id}>...</div>
</div>
```

## When to Use Each

| Pattern | Use when |
|---------|----------|
| `stream` | Append-only, read-only lists (logs, audit feeds) |
| `assign` + `:for` | Interactive items with forms, toggles, inline edits |

## Session Example: ServicesLive Supervisor Search

**Symptom**: Clicking "Agregar supervisor" on a service card never showed the
search input. The `toggle_supervisor_form` event fired and updated the assign,
but the `<input>` never appeared in the DOM.

**Root cause**: `services_live.ex` used `stream(:services, services,
reset: true)`. The supervisor search form (driven by
`supervisor_search_service_id`) was inside a stream item, and streams don't
re-render on global assign changes.

**Fix applied**: Replaced `stream` with `assign(:services, services)` and
`:for={service <- @services}` in the template. The form now appears correctly.

**Commit**: `047a833` — "fix: services_live replace stream with assign for
services list"
