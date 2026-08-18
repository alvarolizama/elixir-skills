# LiveView stream vs assign: the global-assign trap

## Symptom

A `stream(:items, items)` list where each item contains a dynamic sub-panel
(search form, inline edit, expandable section) driven by a global assign
(e.g. `search_open_for_id`). The `handle_event` fires, the assign updates,
but the sub-panel **never appears in the DOM**.

## Root cause

LiveView streams optimize for append-only, read-heavy lists (logs, audit
feeds, chat messages). They diff at the item level: an item re-renders only
when its own data changes. A global assign change (e.g. "open the search
form for item X") does NOT mark the item as changed, so the stream skips
re-rendering it entirely.

## Fix

Use plain `assign` + `:for` for any collection whose items contain
interactive sub-components:

```elixir
# BAD — stream won't re-render the search form when supervisor_search_service_id changes
|> stream(:services, services, reset: true)

# GOOD — assign re-renders the full list on any assign change
|> assign(:services, services)
```

```heex
<%!-- BAD --%>
<div :for={{id, service} <- @streams.services} id={id}>
  ...
  <div :if={@supervisor_search_service_id == service.id}>
    <input name="query" />
  </div>
</div>

<%!-- GOOD --%>
<div :for={service <- @services} id={"service-#{service.id}"}>
  ...
  <div :if={@supervisor_search_service_id == service.id}>
    <input name="query" />
  </div>
</div>
```

## When stream IS appropriate

- Truly append-only lists (logs, activity feeds)
- Read-only items with no per-item interactive UI
- Lists large enough that full re-render is a perf concern

## Observed

2026-08-01 — MyApp `services_live.ex` used `stream(:services, ...)`.
The per-service supervisor search form (driven by `supervisor_search_service_id`)
never appeared after `toggle_supervisor_form`. Switching to `assign` fixed it.
