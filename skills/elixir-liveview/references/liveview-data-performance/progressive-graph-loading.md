# Progressive graph loading — full recipe (my_app, 2026-03)

Session detail behind the `liveview-data-performance` skill. The 3D knowledge-graph view froze with hundreds of nodes / thousands of relations; two commits (`b3ed4da`, `59b8209`) fixed it. Full suite green: 575 tests.

## Architecture that shipped

```
GET /graph (LiveView)
  mount: shell only, loading: true          ← instant, no data query
  render: spinner overlay + <.graph_3d> with empty data-graph
       │
       ▼
Graph3D JS hook (mounted)
  data-graph empty → fetch("/api/graph-json")     ← session auth
  ├─ render client-side immediately (no LV roundtrip wait)
  └─ pushEvent("graph_loaded", payload)            ← sidebar/counts/filter state
       │
       ▼
LiveView handle_event("graph_loaded")
  assign all_nodes/all_edges/totals, loading: false, filter_visible()
```

Key decisions:

- **New controller, browser pipeline.** `GET /api/graph-json` lives in the `:browser, :auth` scope (session cookie), NOT the `:api, :api_auth` scope (bearer token) — the fetch comes from the page's own JS with the session cookie. Context resolution uses the same `Auth.current_context(conn)` helper other controllers use.
- **Hook renders before LiveView ack.** `graph.graphData(...)` runs right after fetch resolves; `pushEvent` only syncs LV assigns for sidebar counts and type filters. User sees the graph ~1 roundtrip sooner.
- **Server-side cap by degree.** `Brain.graph_data(ctx, exclude_types: ~w(todo plan), max_nodes: 400)` — hidden types filtered in SQL; when over the cap, top N pages by total degree, counting ONLY relations whose both endpoints survive the exclusion (the ad-hoc script caught the first version ranking by invisible edges). Real totals always returned for the "showing X of Y" banner.
- **Subgraphs capped too.** `build_page_subgraph(page, relations: rels, max_neighbors: 200)` — sorts neighbors by relation weight desc before taking. All 9 page LiveViews pass their already-loaded `relations` (kills the double query).
- **Adaptive JS quality.** `graphScale(nodes, edges)`: >700 nodes or >2500 edges → 8-segment spheres, 0 particles, 15 warmup ticks / 500ms cooldown; >250/>800 → medium; else full polish. Re-evaluated on every `updated()`.

## Test pattern for progressive LiveViews

```elixir
defp push_graph_loaded(view, context) do
  %{nodes: nodes, edges: edges, total_nodes: tn, total_edges: te} =
    Brain.graph_data(context.id, exclude_types: ~w(todo plan), max_nodes: 400)

  render_hook(view, "graph_loaded", %{
    "nodes" => Enum.map(nodes, &%{"id" => &1.id, "slug" => &1.slug, "label" => &1.title,
                                  "type" => &1.type, "color" => "#60A5FA"}),
    "edges" => Enum.map(edges, &%{"source_id" => &1.source, "target_id" => &1.target,
                                  "color" => "#94A3B8"}),
    "total_nodes" => tn, "total_edges" => te,
    "type_counts" => Brain.graph_type_counts(context.id, ~w(todo plan))
  })
end
```

Tests call `live(conn, ~p"/graph")` (shell), then `push_graph_loaded/2`, then assert on the rendered `data-graph` JSON — same assertions as before, one extra line.

## Numbers to expect (hundreds of nodes, thousands of edges)

| Stage | Before | After |
|-------|--------|-------|
| Initial HTML | 2-8s (data query + fat payload) | <100ms (shell) |
| Data fetch | — | 100-300ms |
| JS render (capped 400, adaptive quality) | 2-5s freeze | 0.5-1.5s, spinner visible |
| Page-show subgraph | 2 queries, unbounded | 1 query, ≤200 neighbors |
| Search graph mode (20 results) | 40+ queries, O(n²) dedup | 2 queries, O(n) dedup |

## Next bottleneck found (2026-06 audit) — SHIPPED in `f3c48d3` (2026-08)

STATUS: implemented. The audit below shipped as commit `f3c48d3`
("fix hook mount, keep graph data client-side, debounce broadcasts"):
Wave 1 = items on hook-mount (see point 9 in SKILL.md), Wave 2 = items 1+4
(data off the socket, client-side filtering), Wave 3 = items 2+3 (debounced
`graph_refetch` via `Process.send_after` 1.5s, coords stripped from
`build_page_subgraph`). Review of that commit found three regressions —
see `references/post-migration-pitfalls.md` and the "Regression pitfalls"
subsection in SKILL.md before repeating this refactor.

After fixes 1-8 shipped, a follow-up read-only audit of the same graph
pipeline (`GraphLive` + `graph_json_controller` + `graph_3d.js`) found the
remaining cost is NOT the query — it's the data path around the socket:

1. **Double-crossing the wire (high).** The hook fetches `/api/graph-json`
   and renders client-side (good), but ALSO `pushEvent("graph_loaded", ...)`
   with the FULL node/edge set. The LV stores it in `all_nodes`/`all_edges`,
   filters, re-assigns `nodes`/`edges`, and the template re-serializes the
   same data into the `data-graph` DOM attribute, which the hook re-reads in
   `updated()`. The dataset crosses the wire twice AND lives duplicated in
   the DOM. End-state fix: the LV keeps only small assigns (`type_counts`,
   totals, `visible_types`); type-toggle filtering moves client-side via a
   `pushEvent` down to the hook; the hook is the single owner of the dataset.
2. **Broadcast-driven full reload (high).** In `:index` mode every
   `handle_info({:page_changed})` runs `load_index_graph` → full re-query +
   re-serialize of up to 400 nodes / 2500 edges, even though the client
   already holds the data. Fix direction: push a light "graph stale" event;
   the hook debounce-refetches over HTTP (~1-2s window) on its own schedule.
3. **Dead payload fields (medium).** `:show` subgraph payloads carry
   circular-layout `x, y, x1, y1, x2, y2` that the force-directed 3D
   renderer ignores entirely — dead bytes in `data-graph` on every diff.
4. **Hook `updated()` re-init (medium).** Any assign re-set of graph data
   restarts the force simulation (visible jump + CPU spike). Guard with a
   data-identity check: skip `graphData(...)` when the payload is unchanged.

Order of attack when implementing: 1+2 together (same surgery — getting the
dataset out of the socket), then 3 as a drive-by. 1+2 eliminates the
per-page-edit re-serialization that compounds as the brain grows.
