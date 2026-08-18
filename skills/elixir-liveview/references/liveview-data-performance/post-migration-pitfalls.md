# Post-migration pitfalls — moving graph data off the LiveView socket (my_app, 2026-08)

Session detail behind the "Regression pitfalls" subsection of
`liveview-data-performance` (point 9). Commit `f3c48d3` shipped the
data-off-socket refactor; the review pass caught four bugs the green test
suite did not. Review method: `git show <sha> --stat`, per-file diff, then
REAL verification — scope tests (`mix test <files>`, 48 green),
`mix compile --warnings-as-errors`, and greps for dangling references.

## Pitfall 1 — Destructive assign filtering (show mode)

Before the refactor, filtering used a pristine full copy:

```elixir
# OLD (safe): filter from all_nodes/all_edges, source intact
nodes = Enum.filter(socket.assigns.all_nodes, &MapSet.member?(visible, &1.type))
```

After, the same function filtered the LIVE assign:

```elixir
# NEW (bug): filters socket.assigns.nodes, then reassigns the result
defp filter_visible(socket) do
  nodes = Enum.filter(socket.assigns.nodes, &MapSet.member?(visible, &1.type))
  visible_ids = MapSet.new(nodes, & &1.id)
  edges = Enum.filter(socket.assigns.edges, fn e ->
    MapSet.member?(visible_ids, e.source_id) and MapSet.member?(visible_ids, e.target_id)
  end)
  assign(socket, nodes: nodes, edges: edges, ...)
end
```

Symptom: in `/graph/:slug` toggle a type off → nodes gone from the assign;
toggle back on → they never return (source was overwritten). Only recovered
by navigating away or a `page_changed` reload. The old toggle off/on
restoration test covered INDEX mode and was replaced by a client-side test —
the SHOW-mode case lost coverage in the same commit. Fix: restore
`all_nodes`/`all_edges` in the socket assigns, filter always from those:

```elixir
defp filter_visible(socket) do
  visible = socket.assigns.visible_types
  nodes = Enum.filter(socket.assigns.all_nodes, &MapSet.member?(visible, &1.type))
  visible_ids = MapSet.new(nodes, & &1.id)
  edges = Enum.filter(socket.assigns.all_edges, fn e ->
    MapSet.member?(visible_ids, e.source_id) and MapSet.member?(visible_ids, e.target_id)
  end)
  assign(socket, nodes: nodes, edges: edges, ...)
end
```

Lesson: whenever a refactor deletes an assign, check every remaining reader.
`filter_visible` survived the refactor but its source-of-truth didn't.

## Pitfall 2 — `visible_types` collision between modes

When `load_show_graph` was refactored to route through `filter_visible()`,
it inherited `visible_types` from `default_visible_types()` (set in mount),
which excludes the operational layer (`todo`, `plan`) via `@hidden_by_default`.

In show mode (`/graph/:slug`), the center node itself can BE a todo — so it
gets silently filtered out. The existing test ("show view includes the
operational layer") caught it immediately:

```
Assertion with in failed
  code:  assert "todo" in types
  left:  "todo"
  right: ["goal", "note"]
```

Fix: `load_show_graph` sets `visible_types` from the subgraph's own node
types, not the global default:

```elixir
defp load_show_graph(socket, page) do
  %{nodes: nodes, edges: edges} = GraphHelpers.build_page_subgraph(page)

  # Show mode: all types visible (including the operational layer — the
  # subgraph is local context, not the global filtered view).
  visible_types = MapSet.new(nodes, & &1.type)

  socket
  |> assign(
    all_nodes: nodes,
    all_edges: edges,
    visible_types: visible_types,
    type_counts: count_types(nodes)
  )
  |> filter_visible()
end
```

The global `default_visible_types()` only applies to index mode (where the
operational layer is excluded by design).

Lesson: when two modes share a filter function, the filter state must be
set per-mode, not inherited globally. A shared `filter_visible/1` is fine —
its INPUT (`visible_types`) must reflect the mode's semantics.

## Pitfall 3 — pushEvent-simulating tests mask conditional-mount bugs

The component rendered the hook div only when non-empty:

```heex
<%= if @nodes == [] do %>
  <div>No graph data</div>          ← mounts instead of the hook div
<% else %>
  <div id={@id} phx-hook="Graph3D" data-graph={@graph_json} />
<% end %>
```

Index mode starts with `nodes: []` and depends on the hook's HTTP fetch —
which never mounts, so the page sits on the loading spinner forever. Tests
never caught it because the progressive flow was simulated:

```elixir
render_hook(view, "graph_loaded", payload)   # fakes the client push,
                                             # never checks the div exists
```

Detection came from READING the component, not from running tests. Fix +
regression test shape:

```heex
<!-- always mount the hook div; the LV loading overlay covers the wait -->
<div id={@id} phx-hook="Graph3D" data-graph={@graph_json}
     data-visible-types={@visible_types_json} />
```

```elixir
test "mounts the hook div even when the graph starts empty", %{conn: conn} do
  {:ok, _view, html} = live(conn, ~p"/graph")
  assert html =~ ~s(phx-hook="Graph3D")
  assert html =~ ~s(id="graph-3d")
  refute html =~ "No graph data"
  assert html =~ ~s(data-visible-types=)
end
```

## Pitfall 4 — Zombie handlers after a payload diet

The refactor stripped layout coords from subgraph nodes/edges (`x`, `y`,
`radius`, `x1`, `y1`, `x2`, `y2`) — the 3D force layout ignores them. But
two handlers still assumed them:

```elixir
# graph_live.ex — %{n | x: x} KeyErrors now that nodes have no :x
def handle_event("node_drag", %{"id" => id, "x" => x, "y" => y}, socket) do
  nodes = Enum.map(socket.assigns.nodes, fn n ->
    if n.id == id, do: %{n | x: x, y: y}, else: n
  end)
  ...
```

Same pattern in `graph_events.ex` (`node_drag/4`) used by 9 page LiveViews.

### Is it live? Grep the pusher

```bash
grep -rn 'pushEvent("node_drag"' assets/ lib/
# only hit: assets/js/app.js GraphPanZoom hook — the OLD 2D SVG hook,
# which no template mounts anymore (grep 'phx-hook=' confirms)
```

Dead code wired to an unmounted hook: safe today, a KeyError landmine the
day someone remounts it.

### Fix (this session): delete the full chain

The cleanup touched **12 files** — the handler in `graph_live.ex`, the
shared helper `node_drag/4` in `graph_events.ex`, and the delegating
`handle_event` clauses in 9 page LiveViews (entity, goal, note, concept,
plan, project, query, todo, reference). The JS pusher (`GraphPanZoom` in
`app.js`) was NOT deleted yet — it's ~170 lines of dead SVG-2D code still
registered in the hooks object but never mounted. Recommended future cleanup:
extract and remove it (and its `svg-pan-zoom.min.js` vendor import) in a
separate commit.

## Fix for toggle off-on in show mode (regression test)

```elixir
test "toggle_type off and on in show mode is non-destructive", %{conn: conn, todo: todo} do
  {:ok, view, _html} = live(conn, ~p"/graph/#{todo.slug}")

  graph = graph_from_view(view)
  initial_count = length(graph["nodes"])

  # Toggle "goal" off
  view |> render_hook("toggle_type", %{"type" => "goal"})
  graph_hidden = graph_from_view(view)
  refute graph_hidden["nodes"] |> Enum.any?(&(&1["type"] == "goal"))

  # Toggle "goal" back on — all original nodes must return
  view |> render_hook("toggle_type", %{"type" => "goal"})
  graph_restored = graph_from_view(view)

  assert length(graph_restored["nodes"]) == initial_count,
         "toggle off-on must restore all original nodes (non-destructive)"
end
```

## Review checklist for this class of refactor

- [ ] Scope tests pass (`mix test <relevant files>`)
- [ ] `mix compile --warnings-as-errors --force` clean
- [ ] grep for removed symbols (`circular_layout`, stripped field names) —
      no dangling references in lib/ or test/
- [ ] Every assign the refactor deleted: grep its old readers
- [ ] Every handler that reads payload fields: grep who pushes the event,
      confirm the pusher is actually mounted
- [ ] DOM-shape asserts for hook elements the progressive flow depends on
- [ ] `visible_types` set per-mode, not inherited globally — show mode must
      include ALL subgraph types (including the operational layer)
- [ ] Debounce timers: cancel-before-schedule reads clean
      (`Process.cancel_timer(old)` before `Process.send_after(...)`)