# Feature-Toggle UI Filtering (disabled page types)

Pattern for making a per-context feature toggle (e.g. my_app's
`disabled_page_types`) actually hide every UI surface tied to the disabled
type — not just the sidebar link.

Real-world case: my_app commit `91bef12` ("hide tabs, filters and badges for
disabled page types").

## The trap: data layer filters, UI doesn't

In my_app, `Brain.list_pages/1` already excluded disabled types at the data
layer (`maybe_exclude_disabled_types`). But the UI kept rendering:

- Detail-view tabs (`{"todos", "Tareas"}` in Goal/Plan/Project LiveViews)
- Kanban filter dropdowns (Project/Goal/Plan)
- Kanban quick-add `<select>` for goal
- Kanban todo-card badges reading `meta.goal_slug` / `meta.project_slug` / `meta.plan_slug`

Disabling a type only hid the sidebar link. Everything else kept showing the
type.

**Lesson**: when you add a feature toggle, grep for every place the feature's
*keys* appear in templates and module attributes — not just where its *data*
is queried.

## Key mismatch: tab keys are plural, page types singular

my_app's `disabled_page_types` stores page types (`"todo"`, `"goal"`, `"plan"`).
But UI tab keys are plural (`"todos"`, `"goals"`, `"plans"`). Comparing the
tab key directly against the disabled list silently never matches:

```elixir
# WRONG — "todos" not in ["todo"], tab never hidden
Enum.reject(tabs, fn {key, _} -> key in disabled end)
```

Fix — explicit mapping, same as the sidebar already does:

```elixir
@tab_key_page_types %{
  "todos" => "todo",
  "goals" => "goal",
  "plans" => "plan",
  "projects" => "project"
}

def visible_tabs(tabs, context) do
  disabled = context.disabled_page_types || []
  Enum.reject(tabs, fn {key, _} ->
    page_type = Map.get(@tab_key_page_types, key)
    page_type && page_type in disabled
  end)
end
```

Keys absent from the map (e.g. `"graph"`, `"overview"`) are never filtered.

Check the app's existing mapping first — my_app's sidebar had
`@nav_key_page_types %{"kanban" => "todo", "todos" => "todo", ...}` which is
the canonical key→type source. Mirror it, don't invent a second one.

## Checklist: surfaces to filter per disabled type

For each disabled type, walk this list:

| Surface | Where | How |
|---|---|---|
| Sidebar nav item | layouts | usually already done — verify |
| Detail-view tabs | `@page_type_tabs` module attr in `*_live.ex` | `visible_tabs(@tabs, context)` at mount |
| Kanban/list filter dropdowns | `<.filter_select>` in board LiveView | `:if={@type_enabled}` on the component |
| Quick-add `<select>` for the type | form in board LiveView | `:if={@type_enabled}` on wrapper div |
| "Clear filters" button condition | same template | include `@type_enabled and` in the `:if` |
| Badges/chips on cards reading `meta.<type>_slug` | `all_badges/1`-style helpers | pass context, filter disabled types (see below) |
| Create/update endpoints | context module / MCP controller | reject creation of disabled type |

## Badges: pass the context down

Badge helpers usually take only the item. To filter disabled types they need
the context:

```elixir
# Before
defp all_badges(todo) do
  []
  |> maybe_add_badge("project", meta_get(todo.meta, "project_slug"))
  |> maybe_add_badge("goal", meta_get(todo.meta, "goal_slug"))
end

# After — context threads through; disabled types skipped
defp all_badges(todo, context) do
  disabled = (context && context.disabled_page_types) || []

  []
  |> maybe_add_badge("project", meta_get(todo.meta, "project_slug"), disabled)
  |> maybe_add_badge("goal", meta_get(todo.meta, "goal_slug"), disabled)
end

defp maybe_add_badge(list, _type, nil, _disabled), do: list
defp maybe_add_badge(list, _type, "", _disabled), do: list

defp maybe_add_badge(list, type, slug, disabled) do
  if type in disabled do
    list
  else
    [%{type: type, slug: slug, label: String.slice(slug, 0, 12)} | list]
  end
end
```

Remember the overflow counter (`+N`) and its tooltip must use the same
filtered list — pass `context` to `extra_badge_count/2` and
`extra_badge_titles/2` too, or the `+N` leaks hidden badges.

Note the `if type in disabled` body check — `when type in disabled` in a
guard does NOT compile (`in` needs a compile-time list in guards). See the
`elixir-functional-purity-patterns` skill, Pitfall 5.

## Mount assigns for the template

Compute enabled flags once at mount and assign them:

```elixir
assign(socket,
  project_enabled: Brain.page_type_enabled?(context, "project"),
  goal_enabled: Brain.page_type_enabled?(context, "goal"),
  plan_enabled: Brain.page_type_enabled?(context, "plan")
)
```

Then the template uses `:if={@goal_enabled}` on each conditional element.
The tab list itself is filtered at mount (`visible_tabs`) rather than with
`:if` per button — keeps the template cleaner.

## Toggle UI: show impact before disabling

In the settings toggle, add a per-type hint so the user knows what will
disappear:

```elixir
defp page_type_impact("todo"), do: gettext("Kanban, tasks, todos list")
defp page_type_impact("goal"), do: gettext("Goals, goal filters, goal badges")
# ...
```

Render it as muted helper text next to the toggle — prevents "I disabled X
and now I can't manage the relations I already had" surprises.

## Data stays, UI hides

Disabled types only affect presentation. Existing pages and their
`meta.*_slug` relations are NOT deleted — if the type is re-enabled,
everything comes back intact. Don't add any data-layer cascade when
implementing the toggle.
