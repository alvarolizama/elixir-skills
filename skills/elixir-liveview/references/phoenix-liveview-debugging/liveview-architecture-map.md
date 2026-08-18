# my_app LiveView Architecture Map

Quick-reference map of the my_app web layer (`lib/dran_web/`) for sessions that
need to add or modify a LiveView page type, a sidebar entry, a dashboard
shortcut, or the command palette. Built while adding the `project` page type
to a plan — these are the real file locations and patterns to clone, not
guessed structure.

Use this **before** writing a plan or patch that touches my_app's UI wiring.
Reading these files first prevents inventing plausible-but-wrong code.

## File locations (the canonical wiring points)

| Concern | File | Anchor |
| --- | --- | --- |
| Page types registry (`@page_types` list, `@types` map) | `lib/my_app/brain/page.ex:70` (list) + `lib/dran_web/page_types.ex` (map with `path`/`label`/`icon`/`plural`) | `@types` map is the source of truth for URL path, icon, labels |
| Meta fields per type + validation | `lib/my_app/brain/page_meta.ex` | `meta_fields_for/1` (form), `validate_meta_for_type/2` (changeset) |
| Sidebar nav (grouped, collapsible `<details>`) | `lib/dran_web/components/layouts.ex` → `sidebar_nav/1` | Groups list literal starts ~line 178; `compute_counts/1` ~line 124 |
| Dashboard quick-access grid + nav groups | `lib/dran_web/live/dashboard_live.ex` → `@nav_groups` ~line 14 | `sort_by_type/1` ~line 555 (hardcoded type order) |
| Command palette quick actions | `lib/dran_web/components/command_palette.ex` → `@quick_actions` ~line 15 | `navigate_action/2` resolves by index; `do_search/2` already returns any `page_type` |
| Empty state per page type | `lib/dran_web/components/page_list_components.ex` → `empty_state/1` (private) ~line 15 | Falls back to generic "No pages yet" |
| Router live blocks | `lib/dran_web/router.ex` ~line 100-135 | Pattern: `live "/<plural>", <Type>Live, :index` + `/new` + `/:slug` |
| Context/brain relations sync | `lib/my_app/brain.ex` → `sync_planning_relations/2` ~line 809 | Pattern-matches on `page_type`; extends for new `*_slug` meta fields |

## Adding a new page type — the 8-point wiring checklist

When a plan introduces a new `page_type` (e.g. `project`), **all eight** of
these need to be touched. Missing any one produces a half-wired feature:

1. **`page.ex`** — add the type string to `@page_types`.
2. **`page_meta.ex`** — add `meta_fields_for("<type>")` (form fields) and
   `validate_meta_for_type/2` clause (changeset validation). Add any new
   common `*_slug` field to `all_fields/0` and the common-fields list.
3. **`brain.ex`** — extend `sync_planning_relations/2` with a clause for the
   new type if it participates in the planning hierarchy (reads/writes
   `*_slug` meta and materializes `part_of` relations).
4. **`page_types.ex`** — add the `%{path:, label:, icon:, plural:}` entry.
5. **`router.ex`** — add 3 routes: index, new (via `PageNewLive`), show.
6. **`<type>_live.ex`** — new LiveView module (see "Cloning a LiveView" below).
7. **`layouts.ex`** — sidebar entry + `compute_counts/1` key.
8. **`dashboard_live.ex`** — `@nav_groups` entry + `sort_by_type/1` order.
   Optionally `command_palette.ex` `@quick_actions` entry.
9. **`page_list_components.ex`** — `empty_state("<type>")` clause.

## Cloning a LiveView (GoalLive → ProjectLive pattern)

When the new page type's detail page should mirror an existing one (e.g.
project mirrors goal — both are "containers" with tabs + a todos kanban),
clone the source LiveView and apply these consistent renames:

### Rename (resource prefix)

- `@page_type` literal: `"goal"` → `"project"`
- Module attr `@goal_tabs` → `@project_tabs` (and trim the tab list — don't
  blindly copy all 9 tabs; pick the minimum that serves the new type)
- Assigns: `goal_todos`, `goal_goals`, `goal_notes` → `project_todos`,
  `project_goals`, etc.
- Private helpers: `goal_column_items/2` → `project_column_items/2`,
  `goal_priority_class/1` → `project_priority_class/1`, etc. Prefixing
  avoids clashes if you later extract a shared `KanbanBoard` module.
- JS hook name in the `<script :type={Phoenix.LiveView.ColocatedHook}>`:
  `.GoalKanban` → `.ProjectKanban`. The hook body can be **byte-identical**
  — only the name attribute changes. The `phx-hook=".ProjectKanban"` on the
  board div must match.
- Board element id: `goal-kanban-<slug>` → `project-kanban-<slug>`.
- Editor id: `goal-editor` → `project-editor`.
- `push_navigate` targets: Back button → `/projects` (not `/goals`);
  `show_page` event → `/todos/:slug` (kanban cards always open the todo,
  regardless of which container's board they're on).

### Keep verbatim (clone-don't-reinvent)

- `@kanban_columns` literal — the 6 `{status, label, badge_class}` tuples are
  the kanban's visual contract. Copy as-is.
- The drag-and-drop `<script>` hook body — `dragstart`/`dragover`/`drop`/
  `dragend` listeners, `data-kanban-slug` / `data-kanban-status` data
  attributes. Identical behavior.
- `mount/3` boilerplate — `Auth.assign_to_socket/2`, `allow_upload/3` with the
  same accept list and `handle_progress/3` delegate.
- `handle_event` delegation lines for `toggle_edit`/`cancel_edit`/
  `validate_page`/`save_page`/`body_change`/`field_change`/`request_upload`/
  `upload_complete` → `PageEdit.handle_event(...)`. Copy the 8 one-liners
  verbatim; they're the LiveView's editing contract.
- `handle_params` for `:show` — the `Brain.get_page_by_slug` → load relations
  → load versions → load logs → `GraphHelpers.build_page_subgraph` →
  `render_markdown` shape. Only the sub-page list loads differ (which
  `page_type` to list and which `meta.*_slug` to filter on).
- `handle_event("move_todo", ...)` — updates `kanban_status` in meta, then
  reloads the filtered todos list. Body identical; only the filter key and
  the re-query filter change.

### The filter key change (the one substantive edit)

GoalLive filters todos by `meta.goal_slug == page.slug`. ProjectLive filters
by `meta.project_slug == page.slug`. This is the core semantic difference —
everything else is renaming. The filter appears in:

- `handle_params` `:show` — the `Enum.filter(fn p -> meta_get(p.meta, "<type>_slug") == page.slug end)` after `Brain.list_pages(...)`
- `handle_event("move_todo", ...)` — the same `Enum.filter` when reloading
  after a status change

### Document the duplication in the plan's Risks section

The clone produces ~400 lines of near-duplicated code (hook JS, kanban
helpers, mount boilerplate). Don't extract a shared component during the
initial feature — it's YAGNI until a third container type appears. Write
the trade-off into the plan's Risks section so a future reviewer knows the
duplication is intentional and where the extraction point would be.

## Sidebar + dashboard count wiring (the two-map consistency rule)

When adding a sidebar entry, **both** the sidebar's `compute_counts/1`
return map and the dashboard's `@nav_groups` must use the **same key name**
for the badge count. Mismatched keys silently produce `nil` badges:

```elixir
# layouts.ex compute_counts/1 — add the key here:
%{
  ...
  projects: by_type["project"] || 0,   # <- this key
  goals: by_type["goal"] || 0,
  ...
}

# layouts.ex sidebar_nav/1 — referenced here:
%{key: "projects", ..., badge: counts[:projects]}   # <- must match

# dashboard_live.ex @nav_groups — independent list, also needs the entry:
%{key: "project", label: gettext("Projects"), icon: "hero-rocket-launch", path: "/projects"}
```

Note the sidebar uses plural key (`projects`), dashboard uses singular
(`project`) — both are local conventions in their respective files. Match
the existing pattern in each file; don't normalize.

## `sort_by_type/1` is hardcoded — update it

`dashboard_live.ex` `sort_by_type/1` has a literal `type_order` list that
controls the "Pages by Type" bar chart order. A new page type not in this
list falls to index 99 (sorts last). Add the new type in its hierarchy
position (e.g. `project` before `goal`, since project is the parent
container):

```elixir
type_order = ~w(note concept entity reference project goal plan todo artifact comparison)
```

## Inspecting before rewriting a plan section

When a user asks to **revise a section of an existing plan** (especially one
with concrete Elixir/HEEx code), read the actual source files the plan
references before writing new plan content. A plan that says "modify
`goal_live.ex:125`" is only trustworthy if line 125 still contains what the
plan claims. Workflow:

1. `read_file` the existing plan fully (use `offset`/`limit` for >500 lines).
2. `search_files` (content mode) for the real definitions the plan touches:
   `@nav_groups`, `empty_state`, `sidebar_nav`, `@quick_actions`,
   `@project_tabs`, router `live` blocks, etc.
3. `read_file` each relevant source file — don't infer from search snippets.
4. Ground every code snippet in real file contents. Copy the actual patterns
   (the exact hook JS structure, the `handle_event` delegation lines, the
   `@kanban_columns` literal) rather than inventing plausible-looking code.
5. `patch` the section in place; then re-search the file for the new
   headings (`^### 3\.\d`) to confirm structure landed correctly.

A patch that reports success but landed in the wrong place is a silent
failure — always verify post-patch with a search for the expected
section markers and key terms.

## Concurrency warning on plan patches

If a sibling subagent or parallel process edits the plan file between your
`read_file` and your `patch`, the patch tool warns
("modified by sibling subagent"). The patch may still have landed — re-read
the file and verify the final structure before assuming success.
