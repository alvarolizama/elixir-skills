# LiveView streams vs assigns for dynamic content

## Symptom

A `handle_event` receives the event, updates an assign correctly, but the UI never re-renders. The updated content (a form, a panel, a search box) simply does not appear in the DOM. `render_click` in tests returns HTML without the expected element.

## Root cause

`stream(:items, items)` tells LiveView to manage the list as a **stream** — items are appended/prepended/deleted individually, and LiveView does NOT re-render an item's inner content when a global assign changes. The stream item is treated as an opaque unit keyed by its DOM id.

When your UI depends on a **global assign** (e.g. `supervisor_search_service_id`) to show/hide content INSIDE a stream item, the stream never re-renders that item because the item itself (the struct) didn't change — only the global assign did.

## The fix

Replace `stream` with `assign` when the list items contain interactive, assign-dependent content:

```elixir
# BROKEN — stream won't re-render on global assign changes
|> stream(:services, services, reset: true)

# WORKS — full re-render on every assign change
|> assign(:services, services)
```

And in the template:

```heex
<%!-- BROKEN --%>
<div id="services" phx-update="stream">
  <div :for={{id, service} <- @streams.services} id={id}>

<%!-- WORKS --%>
<div id="services">
  <div :for={service <- @services} id={"service-#{service.id}"}>
```

## When to use stream vs assign

| Use stream when… | Use assign when… |
|---|---|
| The list is large (100+ items) and mostly read-only | The list is small (<50 items) |
| Items are independent — no global state affects them | Items contain interactive sub-panels driven by global assigns |
| You only append/prepend/delete (chat messages, log entries) | You need inline forms, toggles, or conditional sections inside items |
| Performance matters (avoid full re-render) | Correctness matters (content must reflect current assigns) |

## Debugging recipe

1. Add `IO.inspect` in the `handle_event` to confirm the assign updates.
2. Check the `render_click` output for the expected element.
3. If the assign updates but the element is missing, check if the container uses `phx-update="stream"`.
4. If yes, switch to `assign` and retest.

## Real-world example (MyApp ServicesLive)

The `services_live.ex` used `stream(:services, services, reset: true)` for the services list. Each service card had a "Supervisores" section with a toggle button that opened an inline search form driven by `@supervisor_search_service_id`. The event fired, the assign updated, but the form never appeared because the stream didn't re-render the service card.

Fix: `|> assign(:services, services)` + removed `phx-update="stream"` from the container.

**Commit**: `047a833` — "fix: services_live replace stream with assign for services list"
