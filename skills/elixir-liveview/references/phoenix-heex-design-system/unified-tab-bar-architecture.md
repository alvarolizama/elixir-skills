# Unified Tab Bar Architecture (slot-based)

When a Phoenix app has a shared `page_detail` component that renders Content +
Graph tabs client-side (via `switch_detail_tab` JS commands), but individual
LiveViews (Project, Goal, Plan) also have their own server-side tabs
(Kanban, Todos, Notes, etc. via `switch_tab` event), you get **two stacked tab
bars** — confusing UX. This pattern unifies them into one bar.

## Slot-based injection

Add two slots to the shared component (`page_detail` / `page_components.ex`):

```elixir
slot :extra_tabs, doc: "extra server-side tabs rendered alongside Content + Graph"
slot :extra_content, doc: "server-side tab content rendered outside the content panel"
```

Render the extra tab buttons **between** Content and Graph in the nav:

```heex
<button id="detail-tab-content" ...>Content</button>
{render_slot(@extra_tabs)}
<button id="detail-tab-graph" ...>Graph</button>
```

Render the extra content and the Graph panel **inside the main content column**,
after the `detail-panel-content` div:

```heex
<div class="flex-1 min-w-0 space-y-6">
  <div id="detail-panel-content" data-detail-panel class={[\"space-y-6\", @content_hidden && \"hidden\"]}>
    {render_slot(@tabs)}
    <!-- fallback rendered_body -->
  </div>

  {render_slot(@extra_content)}

  <div id="detail-panel-graph" data-detail-panel class={[\"hidden\", ...]}>
    {render_slot(@graph)}
  </div>
</div>
```

**Key:** The Graph panel must live INSIDE the main content column
(`flex-1 min-w-0`), NOT after the sidebar `</aside>`. If it's after the
two-column layout div, the graph renders below the sidebar — wrong.

## Coordinating client-side and server-side tabs

Add attrs to the shared component:

```elixir
attr :content_hidden, :boolean, default: false
attr :graph_active, :boolean, default: false
attr :content_tab_value, :string, default: "overview"
```

The Content tab switches behavior based on `content_hidden`:

```heex
phx-click={if @content_hidden, do: "switch_tab", else: switch_detail_tab("content")}
phx-value-tab={@content_tab_value}
```

- **Páginas normales** (notes, concepts): `content_hidden=false` (default).
  Content/Graph use client-side `switch_detail_tab` — no server round-trip.
- **Project/Goal/Plan**: pass `content_hidden={@active_tab not in ["overview", "graph"]}`.
  When a server-side tab is active, `content_hidden=true`, so Content fires
  `switch_tab` with `phx-value-tab` = the LiveView's content tab name.

`content_tab_value` handles LiveViews that use "content" as their default tab
(Plan, Note, Concept) vs "overview" (Project, Goal). Pass it from each LiveView:

```elixir
# project_live.ex — default tab is "overview"
content_hidden={@active_tab not in ["overview", "graph"]}
content_tab_value="overview"

# plan_live.ex — default tab is "content"
content_hidden={@active_tab not in ["content", "graph"]}
content_tab_value="content"
```

## LiveView usage pattern

Each LiveView that has extra tabs uses `:extra_tabs` for buttons and
`:extra_content` for the content divs:

```heex
<.page_detail
  page={@page}
  content_hidden={@active_tab not in ["overview", "graph"]}
  graph_active={@active_tab == "graph"}
  editing={@editing}>

  <:extra_tabs>
    <button
      :for={{tab, label} <- @project_tabs}
      phx-click="switch_tab"
      phx-value-tab={tab}
      class={[
        "px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors duration-150",
        @active_tab == tab && "border-primary text-primary",
        @active_tab != tab && "border-transparent text-base-content/60 hover:text-base-content hover:border-base-content/20"
      ]}
    >
      {label}
    </button>
  </:extra_tabs>

  <:tabs>
    <!-- overview/content goes here, inside detail-panel-content -->
    <div :if={@active_tab == "overview"}>
      <!-- dashboard content -->
    </div>
  </:tabs>

  <:extra_content>
    <div :if={@active_tab == "kanban"}>
      <!-- kanban board -->
    </div>
    <div :if={@active_tab == "graph"} class="space-y-4">
      <.page_graph id="project-page-graph" nodes={@graph_nodes} edges={@graph_edges} />
    </div>
  </:extra_content>
</.page_detail>
```

## Cleanup: removing `tabs_bar` from many LiveViews at once

When migrating to the unified tab bar, all LiveViews that had `<.tabs_bar>`
inside `<:tabs>` need cleanup. The mechanical pattern (removing `tabs_bar`,
`@tabs` module attribute, `tabs: @tabs` assign, and `:if={@active_tab == "content"}`
wrapper divs) can be done with a Python script via `execute_code`:

```python
import re

files = ['note_live.ex', 'concept_live.ex', 'entity_live.ex', ...]
for f in files:
    path = f'/path/to/lib/dran_web/live/{f}'
    with open(path, 'r') as fh:
        content = fh.read()
    # Remove tabs_bar line
    content = re.sub(r'\s*<\.tabs_bar[^/]*/>\s*\n', '\n', content)
    # Remove @tabs definition
    content = re.sub(r'  @tabs \[\s*\n.*?\n\s*\]\s*\n', '\n', content, flags=re.DOTALL)
    # Remove tabs: @tabs, from assigns
    content = re.sub(r'\s*tabs: @tabs,\n', '\n', content)
    # Fix orphaned </div> from removed :if wrapper
    content = re.sub(r'(<% end %>)\s*</div>\s*(</:tabs>)', r'\1\n          \2', content)
    with open(path, 'w') as fh:
        fh.write(content)
```

**Pitfall:** removing `<div :if={@active_tab == "content"}>` leaves its closing
`</div>` orphaned. The regex fix above catches the `<% end %>` + `</div>` +
`</:tabs>` pattern. For LiveViews with multiple tabs (like Plan with
"content" + "todos"), handle manually — the "todos" tab becomes an `:extra_tabs`
button and its content moves to `:extra_content`.

## Tab ordering convention

Álvaro's preference for tab order: **Content → [type-specific tabs] → Graph**

- Graph always goes LAST.
- "Overview" is removed as a tab name — the dashboard content lives under the
  "Content" tab.
- Relations are NOT shown as a tab — they live in the collapsible "Links"
  panel in the sidebar.

## Removing a tab entirely (e.g. Related, Relations, Versions)

When removing a tab that was part of the shared `page_detail` component:

1. **Remove the tab button** from the nav bar in `page_components.ex`.
2. **Remove the panel div** (e.g. `detail-panel-related`) from the template.
3. **Remove the attr** (e.g. `related_active`) from the component's attr list.
4. **Remove the attr pass** from all LiveViews that set it (grep for the attr name).
5. **Update `content_hidden` lists** — remove the tab name from the `not in [...]` list.
6. **Remove any `:extra_content` blocks** in LiveViews that rendered content for that tab.
7. **Remove the handler** if the tab had its own `handle_event` clause (e.g. `toggle_view_mode`).

**Pitfall:** the `content_hidden` expression lists which tabs should NOT hide
the content panel. When removing a tab, its name must also be removed from
these lists or the content panel will stay visible when it shouldn't.

## Removing a view mode toggle (2D/3D)

When simplifying to a single view mode (e.g. removing 2D graph, keeping only 3D):

1. Delete the toggle button group from the sidebar.
2. Delete the `handle_event("toggle_view_mode", ...)` clause.
3. Delete the `view_mode` assign from `mount`.
4. Delete the `<%= if @view_mode == "2d" do %>` conditional branch and its SVG.
5. Leave the `else` branch (3D) as the only path — remove the `if/else` wrapper.
6. Hardcode the dark background: `style="background: #0a0e27;"` on the container
   and `this.scene.background = new THREE.Color("#0a0e27")` in the JS hook.
