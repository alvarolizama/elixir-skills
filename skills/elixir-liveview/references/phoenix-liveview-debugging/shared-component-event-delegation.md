# Shared Component Event Delegation — The Missing Handler Pitfall

## The bug
A shared component renders `phx-click="some_event"`, but the consuming LiveView has no `handle_event("some_event", ...)`. Result: button click does **nothing** — no error, no flash, no log.

## Why it happens
- Shared components emit events via `phx-click`
- Each consuming LiveView must **either** handle the event itself **or** delegate to the shared module
- If even ONE LiveView forgets the delegation, that page silently breaks
- Phoenix compiles fine — there is no compile-time warning for a missing event handler

## Prevention pattern
When a shared component adds ANY new `phx-click` event:

1. **Audit every consumer** — `grep -l "use_the_component" lib/dran_web/live/*_live.ex`
2. **Add delegation** to ALL consumers in the same commit as the component change:
   ```elixir
   # In every LiveView that uses the component:
   def handle_event("the_event", params, socket),
     do: SharedModule.handle_event("the_event", params, socket)
   ```
3. **Verify with grep** — `grep -c "the_event" lib/dran_web/live/*_live.ex` must show non-zero for every consumer
4. **Compile + smoke test** — a missing handler compiles fine; only a runtime click test proves it works

## Detection heuristic
When a button "doesn't work" with no error:
1. Check the LiveView for the `handle_event` clause matching the button's `phx-click`
2. If missing → the shared component emits an event the LiveView doesn't handle
3. Check the shared module (e.g. `PageEdit`) for the implementation
4. Add delegation

## Real-world example (my_app 2025-08)
`page_detail` component rendered `phx-click="toggle_pinned"` but ZERO out of 10 consuming LiveViews had the handler. The `PageEdit` module had the full implementation (toggle boolean, update via Brain, flash message). Fix: add one-liner delegation to all 10 LiveViews:

```elixir
def handle_event("toggle_pinned", params, socket),
  do: PageEdit.handle_event("toggle_pinned", params, socket)
```

All 10 LiveViews affected: concept, entity, goal, note, plan, project, query, reference, report, todo.
