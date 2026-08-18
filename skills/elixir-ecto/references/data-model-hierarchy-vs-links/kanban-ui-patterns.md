# Kanban UI Patterns

## Badge Design

Cards in a global kanban show linked containers as badges:

```
┌─────────────────┐
│ [proj:MVP] [goal:70kg]  ← máximo 2 visibles
│ Título del todo
│ Due: mañana     Priority: high
└─────────────────┘
```

- **Color coding**: blue=project, green=goal, purple=plan
- **Max 2 badges**: rest shown as "+2 more" with tooltip on hover
- **Click badge**: filters kanban by that link
- **Text**: short name (3-8 chars), not full slug

## Filter UX

```
┌─────────────────────────────────────────┐
│ [All] [Inbox] [Proj: X▾] [Goal: Y▾]    │
│ [Plan: Z▾] [+ Add filter]               │
├─────────┬─────────┬─────────┬──────────┤
│ Backlog │ Today   │ In Prog │ Done     │
│ [todo]  │ [todo]  │ [todo]  │ [todo]   │
│ (inbox) │ (projX) │ (goalY) │ (planZ)  │
└─────────┴─────────┴─────────┴──────────┘
```

**Combinable filters:**
- `project:X AND goal:Y` — todos of project X that also serve goal Y
- `project:X AND inbox` — todos of project X with no goal/plan
- `inbox` — completely unlinked todos

**Implementation:**
```elixir
# In LiveView
def handle_event("filter", %{"project" => slug}, socket) do
  filters = Map.put(socket.assigns.filters, :project, slug)
  {:noreply, assign(socket, filters: filters) |> load_todos()}
end

# Query builder
defp apply_filters(query, filters) do
  query
  |> maybe_filter(:project, filters[:project])
  |> maybe_filter(:goal, filters[:goal])
  |> maybe_filter(:plan, filters[:plan])
  |> maybe_filter_inbox(filters[:inbox])
end

defp maybe_filter(query, _field, nil), do: query
defp maybe_filter(query, field, slug) do
  from q in query, where: fragment("meta->>? = ?", ^"#{field}_slug", ^slug)
end

defp maybe_filter_inbox(query, true) do
  from q in query,
    where: fragment("meta->>'project_slug' IS NULL") and
           fragment("meta->>'goal_slug' IS NULL") and
           fragment("meta->>'plan_slug' IS NULL")
end
defp maybe_filter_inbox(query, _), do: query
```

## Drag-Drop

```javascript
// Same pattern as goal_live kanban, but global
// phx-hook="KanbanBoard"

Hooks.KanbanBoard = {
  mounted() {
    this.el.addEventListener("dragstart", e => {
      e.dataTransfer.setData("todo_slug", e.target.dataset.slug)
    })
    
    this.el.addEventListener("dragover", e => e.preventDefault())
    
    this.el.addEventListener("drop", e => {
      e.preventDefault()
      const slug = e.dataTransfer.getData("todo_slug")
      const newStatus = e.target.closest("[data-status]").dataset.status
      this.pushEvent("move_todo", {slug, kanban_status: newStatus})
    })
  }
}
```

```elixir
# In LiveView
def handle_event("move_todo", %{"slug" => slug, "kanban_status" => status}, socket) do
  todo = Brain.get_page!(slug)
  {:ok, _} = Brain.update_page(todo, %{meta: Map.put(todo.meta, "kanban_status", status)})
  {:noreply, load_todos(socket)}
end
```

## Common Pitfalls

1. **Don't embed kanban in container pages.** A project page with kanban is 600+ lines duplicated. Show a list and link to global kanban with filter preset.

2. **Don't show all badges.** 3+ badges make cards unreadable. Max 2, rest in tooltip.

3. **Don't forget the inbox.** Users need to see unlinked todos. Make it a first-class filter, not an afterthought.

4. **Don't use JOINs for filters.** JSONB `meta->>'field' = ?` is simpler and faster with a GIN index.

5. **Don't auto-hide done.** Some users want to see completed work. Add a "Show done" toggle instead of filtering it out automatically.
