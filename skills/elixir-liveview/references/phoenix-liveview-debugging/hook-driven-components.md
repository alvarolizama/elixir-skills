# Reusable HEEx function components that drive a JS hook

Pattern captured from replacing an old SVG-2D `<.page_graph>` (GraphPanZoom hook)
with a reusable `<.graph_3d>` (forces `3d-force-graph`) across 9 LiveViews in my_app.

## The component pattern (function component → JSON payload → JS hook)

A LiveView component that renders a container wired to a JS hook needs the data
serialized server-side and handed to the DOM as a `data-` attribute:

```elixir
attr :id,    :string, default: "graph-3d"
attr :nodes, :list,   required: true
attr :edges, :list,   required: true
attr :class, :string, default: ""
attr :style, :string, default: ""

def graph_3d(assigns) do
  graph_data = %{nodes: assigns.nodes, edges: assigns.edges}
  assigns = assign(assigns, :graph_json, Jason.encode!(graph_data))

  ~H"""
  <div class={["relative overflow-hidden", @class]}
       style={"background: #0a0e27; #{@style}"}>
    <%= if @nodes == [] do %>
      <div class="...">No graph data</div>
    <% else %>
      <div id={@id} phx-hook="Graph3D" data-graph={@graph_json}
           style="width: 100%; height: 100%; min-height: 300px;" />
    <% end %>
  </div>
  """
end
```

- Build the payload as a plain map and `Jason.encode!` it in the function head,
  then `assign` it into a `:graph_json` attr used as `data-graph={@graph_json}`.
  **Jason needs no import** — it's a direct dependency in nearly every Phoenix
  project, so `Jason.encode!/1` resolves without aliasing.
- `attr :nodes, :list, default: []` guards the render: branch on `@nodes == []`
  rather than calling the hook with empty data.
- Keep the `<.icon>` / `<.empty_state>` empty-state in the component so callers
  get it for free; `<.icon>` is already imported via the component file's
  `import DranWeb.CoreComponents, only: [icon: 1]`.

## PITFALL: same component, different parent slots across LiveViews

When replacing a component across *all* LiveViews that use it, do NOT assume the
call site shape is uniform. Screen every file. In my_app's `page_detail` layout:

- **7 LiveViews** render the graph in the **`:graph` slot** (`<:graph>` … `</:graph>`):
  note, concept, entity, reference, query, plan, todo.
- **2 LiveViews** (project, goal) render it inside a `<div :if={@active_tab == "graph"} class="space-y-4">` block in the **`:extra_content` slot** instead.

So `page_graph`→`graph_3d` replacement needed two different indentation/context
shapes. A blanket search-and-replace of `<.page_graph … />` still worked because the
tag itself was uniform, but the *surrounding* markup differed. Grep for the tag
across `lib/dran_web/live/*_live.ex`, read each call site's enclosing slot, then
patch per-context.

## Full-height bleed from the page_detail panel

The `:graph` panel sits inside padded content, so a full-bleed graph needs
negative margins on the panel container:

```heex
class={["-m-6 -mt-4", not @graph_active && "hidden"]}
```

`-m-6` cancels the left/right padding, `-mt-4` the top padding, letting the graph
fill the tab width.

## Verification recipe (Liveroom / any LiveView refactor)

Authoritative pass/fail check — do NOT trust `mix test … | tail` alone; a passing
run can still end with a leftover trace from an earlier retried test in the window:

```bash
mix compile --warnings-as-errors   # zero warnings = the gate the guidelines enforce
mix format --check-formatted       # run `mix format <files>` first, then check
mix test --no-deps-check 2>&1 | grep -E "^Result:"   # → "Result: 515 passed" is the real summary
```

After a multi-file HEEx change, run `mix format <changed files>` before
`--check-formatted` — long single-line component tags like
`<.graph_3d id="…" nodes={…} …/>` get auto-wrapped by the formatter and will fail
the check otherwise.
