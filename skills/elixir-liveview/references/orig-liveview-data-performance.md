---
name: liveview-data-performance
author: Álvaro Lizama
description: Use when a LiveView freezes on large data. Payload/N+1 fix.
---

# Phoenix LiveView Performance for Large Datasets

Playbook for LiveView pages (especially data-visualization ones) that freeze when the underlying dataset grows. Verified end-to-end on a 3D graph view over hundreds of nodes / thousands of edges — full suite green (575 tests).

## Diagnose first: where is the freeze?

1. **Server query** — is the mount/handler loading unbounded rows, heavy columns (`body`, `summary`, `tags`), or computing values the client ignores (e.g. a server-side layout the JS overwrites)?
2. **Payload** — LiveView serializes every assign into the HTML/diff. A big list in `data-*` JSON multiplies DOM size and diff cost on *every* update, not just mount.
3. **Client render** — per-node/per-edge object creation (Three.js meshes, sprites, animated particles) is the usual culprit once the data arrives.

## Fixes that compound

### 1. Kill N+1 in parent/child loads

If the LiveView loads `list_relations_for_page(page.id)` and then a helper calls the same function again internally, pass the loaded data down instead:

```elixir
def build_page_subgraph(page, opts \\ []) do
  relations = Keyword.get(opts, :relations) || Brain.list_relations_for_page(page.id)
  ...
end
```

Callers that already have the relations pass `relations: relations` — one query, not two, per page.

### 2. Batch across a result set

Loading per-item relations for N results → two queries total, not 2×N. Provide a plural function (`list_relations_for_pages(ids)` → `%{id => %{outbound: ..., inbound: ...}}`), `Enum.group_by` the results, and merge with **Map-based dedup** (`Map.put_new`), never `Enum.any?` inside a reduce (O(n²)).

### 3. Cap what you render, rank the rest

Unbounded "everything connected to X" explodes on hub records. Cap with a rank that matches the visible semantics — e.g. only relations whose **both endpoints are visible** count toward degree. Report real totals (`total_nodes`, `total_edges`) alongside the capped list so the UI can say "showing 400 of 2,300".

### 4. Progressive loading: shell first, data over HTTP

For the heaviest view, don't block mount on the data query:

- Mount renders the shell with a `loading: true` assign (spinner).
- The JS hook `fetch`es a session-authenticated JSON endpoint (`/api/...`), renders immediately client-side, AND `pushEvent`s the payload back so LiveView assigns (sidebars, filters, counts) stay consistent.
- The JSON endpoint reuses the same auth plug the browser pipeline already has — don't route through the API-token pipeline.
- **Test pattern:** LiveView tests simulate the fetch with `render_hook(view, "graph_loaded", payload)` built from the same context functions the endpoint uses.

### 5. Lite payloads only

Ship exactly what the renderer reads (`id, slug, label, type, color`). Drop `summary`/`tags`/positioning fields the client recomputes. In the JS, degrade render quality by dataset size (lower geometry segments, zero particle streams, shorter physics warmup/cooldown) — one `graphScale(nodeCount, edgeCount)` function consulted at init and on every data update.

### 6. Cap edges too, not just nodes

Capping nodes (e.g. top 400 by degree) doesn't cap edges — a dense cluster of 400 hub pages can produce 4000+ edges between them, inflating the JSON payload AND the 3D render. Sort edges by weight descending and apply a hard `LIMIT`:

```elixir
# In Brain.graph_data/2: after the node_ids cap, limit edges to the strongest ones
@max_graph_edges 2500

edges =
  if Enum.empty?(node_ids) do
    []
  else
    Repo.all(
      from r in Relation,
        where: r.source_id in ^node_ids and r.target_id in ^node_ids,
        order_by: [desc: r.weight],
        limit: @max_graph_edges,
        select: %{source: r.source_id, target: r.target_id, type: r.relation_type, weight: r.weight}
    )
  end
```

Weight-priority ensures structural edges (`part_of` = 1.0) survive while weak semantic edges (0.1) drop first. The `total_edges` aggregate stays truthful — only the rendered set is capped. Pair this with the existing `graphScale()` adaptive quality tiers in JS (>2500 edges already triggers lowest-poly mode).

### 7. Push degree ranking to SQL

When capping to top-N nodes by degree, don't load ALL `(source_id, target_id)` pairs into RAM just to `Enum.frequencies()` and sort in Elixir. For 50k relations that's fine; for 500k it blocks the controller. Postgres does this natively:

```elixir
# BEFORE: loads every source-target pair into RAM
relations = Repo.all(pairs)  # 50k tuples
(Enum.map(relations, &elem(&1, 0)) ++ Enum.map(relations, &elem(&1, 1)))
|> Enum.frequencies()
|> Enum.sort_by(fn {_id, degree} -> degree end, :desc)
|> Enum.take(limit)

# AFTER: two GROUP BY queries returning only per-page degree, combined in Elixir
out_degree = from r in Relation, join: s in assoc(r, :source), ...,
  group_by: r.source_id, select: {r.source_id, count(r.id)}
in_degree  = from r in Relation, join: t in assoc(r, :target), ...,
  group_by: r.target_id, select: {r.target_id, count(r.id)}

out = Map.new(Repo.all(out_degree))
in_ = Map.new(Repo.all(in_degree))

Map.merge(out, in_, fn _k, v1, v2 -> v1 + v2 end)
|> Enum.sort_by(fn {_id, degree} -> degree end, :desc)
|> Enum.take(limit)
```

Ram cost drops from O(relations) to O(unique_pages) — ~10x reduction on typical brains. See `references/graph-query-pitfalls.md` for the full SQL-pure alternative with UNION ALL.

### 8. Filter PubSub broadcasts in :show subgraph views

A `handle_info({:page_changed, ...})` that reloads the subgraph on EVERY change (even unrelated pages) wastes queries and re-renders the 3D view unnecessarily. Only reload when the changed page is actually visible:

```elixir
def handle_info({:page_changed, _action, changed_page}, socket) do
  case socket.assigns.live_action do
    :index -> {:noreply, load_index_graph(socket)}
    :show ->
      if affected_subgraph?(socket.assigns.page, changed_page, socket) do
        {:noreply, load_show_graph(socket, socket.assigns.page)}
      else
        {:noreply, socket}
      end
  end
end

defp affected_subgraph?(center_page, changed_page, socket) do
  center_page.id == changed_page.id
  || Enum.any?(socket.assigns.nodes, &(&1.id == changed_page.id))
end
```

### 9. Keep the dataset entirely client-side; push back only counters

Point 4 pushes the full payload back to the LV so assigns stay consistent. That's still one-way (mount) — but if the LV re-serializes that data into `data-*` on every re-render, you've re-created the double round-trip. For the heaviest view, invert it: the hook owns the dataset in `this.fullData`, and the LV holds **only counters + filter state**. The socket never carries nodes/edges again.

- Hook stores the fetched/initial data in `this.fullData` (never sends it to the LV).
- `pushEvent("graph_loaded", {total_nodes, total_edges, type_counts})` — summary only.
- A separate `pushEvent("graph_counts", {node_count, edge_count})` reports the *visible* counts after the hook filters client-side, so the LV sidebar stays accurate.
- Type toggles become `push_event(socket, "set_visible_types", %{types: [...]})` → the hook filters `fullData` and re-renders, with **no socket round-trip of data**.
- The LV keeps `nodes/edges` only for the small `:show` subgraph (serialized into `data-graph`); the `:index` view renders an empty `data-graph` and lets the hook fetch + filter.
- `updated()` must skip re-reading `data-graph` in index mode (guard with a `this.progressive` flag) or it will wipe the client-held data on every LV re-render.

This is the "Wave 2" of the graph-perf work (mount-fix → data-off-socket → debounce). The hook div must ALWAYS render (no `if @nodes == []` empty-state branch) or the progressive fetch never starts — the loading overlay covers the shell.

### Regression pitfalls when moving data off the socket (verified post-ship)

The commit that shipped point 9 carried **four** bugs a code review caught — suite green, compile clean, tests did NOT catch them. All four recur any time data moves from assigns into a client hook:

1. **Destructive assign filtering.** If a smaller mode stays on the socket (e.g. the `:show` subgraph), never filter `socket.assigns.nodes` in place and reassign — toggling a type off permanently loses those nodes from the source; toggling back on can't restore them. Filter from a pristine copy (`all_nodes`/`all_edges`) and keep `visible_types` per-mode.
2. **`visible_types` collision between modes.** When `load_show_graph` is refactored to call `filter_visible()`, it inherits the global `default_visible_types()` — which hides the operational layer (todos, plans). In show mode the center node itself can BE a todo, so it gets silently filtered out. Fix: `load_show_graph` sets `visible_types` from the subgraph's own node types (`MapSet.new(nodes, & &1.type)`), not the global default. The global default only applies to index mode.
3. **pushEvent-simulating tests mask conditional-mount bugs.** `render_hook(view, "graph_loaded", ...)` fakes the client push WITHOUT checking the hook element exists. An `if @nodes == []` empty-state branch swallowed the hook div — tests stayed green while the real browser sat stuck on "No graph data". Add DOM-shape asserts: `phx-hook="Graph3D"` present, element id present, empty-state markup absent on initial render.
4. **Zombie handlers after payload diet.** A commit that strips fields from a payload (e.g. `x`/`y` coords) leaves any handler doing `%{n | x: x}` ready to KeyError the moment the event fires. Before calling it safe, grep who pushes that event (`grep -rn 'pushEvent("node_drag"' assets/`); a handler wired only to an unmounted hook is dead code — delete it (the handler in all LiveViews + the shared helper AND the pusher in the JS hook), don't leave a landmine.

Full code excerpts and verification recipes: `references/post-migration-pitfalls.md`.

### 10. esbuild gotcha: `handleEvent("x", cb)` shorthand needs the Phoenix plugin

The `handleEvent("set_visible_types", ({...}) => {...})` shorthand at the top level of a hook object is a **Phoenix esbuild plugin** feature. With plain esbuild (no plugin in `config :esbuild`), that syntax is a JS SyntaxError. Register the listener inside `mounted()` instead:

```js
mounted() {
  this.handleEvent("set_visible_types", ({ types }) => { ... })
  this.init()
}
```

Check `config/config.exs` → `config :esbuild` for a plugin before using the shorthand. The node linter flags it immediately (`Unexpected string`), which is the tell.

### 10. ETS-backed graph cache (3 tables, read-concurrent)

When the progressive-loading JSON endpoint (`/api/graph-json`) runs an expensive query (graph_data + type_counts + degree ranking), every page reload re-executes it. An ETS-backed GenServer cache eliminates repeat DB work **without serializing reads** — reads hit ETS directly, only the first miss goes through the GenServer to build.

```elixir
defmodule MyApp.GraphCache do
  use GenServer

  @graph_table :myapp_graph_cache
  @subgraph_table :myapp_subgraph_cache
  @page_table :myapp_page_cache

  def start_link(_), do: GenServer.start_link(__MODULE__, %{}, name: __MODULE__)

  # Reads go to ETS — no GenServer call, no bottleneck
  def get(context_id) do
    case :ets.lookup(@graph_table, context_id) do
      [{^context_id, json}] -> %{json: json, cached: true}
      [] -> GenServer.call(__MODULE__, {:build_graph, context_id})
    end
  end

  def get_subgraph(page_id, context_id) do
    key = {page_id, context_id}
    case :ets.lookup(@subgraph_table, key) do
      [{^key, sub}] -> %{nodes: sub.nodes, edges: sub.edges, cached: true}
      [] -> GenServer.call(__MODULE__, {:build_subgraph, page_id, context_id})
    end
  end

  def get_page(slug, context_id) do
    key = {slug, context_id}
    case :ets.lookup(@page_table, key) do
      [{^key, :not_found}] -> nil
      [{^key, page}] -> page
      [] -> GenServer.call(__MODULE__, {:fetch_page, slug, context_id})
    end
  end

  # Invalidations hit ETS directly too
  def invalidate_context(context_id), do: :ets.delete(@graph_table, context_id)
  def invalidate_page(page_id, context_id) do
    :ets.delete(@subgraph_table, {page_id, context_id})
    :ets.delete(@graph_table, context_id)  # any page change affects the global graph
  end
  def invalidate_page_slug(slug, context_id), do: :ets.delete(@page_table, {slug, context_id})

  @impl true
  def init(_) do
    # GenServer OWNS the tables. read_concurrency enables lock-free
    # concurrent reads from ANY process.
    :ets.new(@graph_table, [:set, :named_table, :public, {:read_concurrency, true}])
    :ets.new(@subgraph_table, [:set, :named_table, :public, {:read_concurrency, true}])
    :ets.new(@page_table, [:set, :named_table, :public, {:read_concurrency, true}])
    {:ok, %{}}
  end

  # Writes/builds go through the GenServer (serialized, but rare — only on miss)
  @impl true
  def handle_call({:build_graph, context_id}, _from, state) do
    case :ets.lookup(@graph_table, context_id) do
      [{^context_id, json}] -> {:reply, %{json: json, cached: true}, state}
      [] ->
        json = build_graph_json(context_id)
        :ets.insert(@graph_table, {context_id, json})
        {:reply, %{json: json, cached: false}, state}
    end
  end

  @impl true
  def handle_info(_msg, state), do: {:noreply, state}
end
```

- Add to `application.ex` children: `MyApp.GraphCache`.
- Controller: `GraphCache.get(context.id)` → `send_resp(200, cached.json)`. The JSON is already encoded — use `send_resp`, not `json/2` (that re-encodes).
- **Invalidation:** call the granular invalidation functions directly from the broadcaster (`broadcast_page_change/3`), NOT via a PubSub subscription inside the cache. Direct calls are simpler, no races. The old single `invalidate/1` that nuked the whole context is replaced by:
  - `invalidate_page_slug(slug, context_id)` — page cache entry
  - `invalidate_page(page_id, context_id)` — subgraph + global graph
  - `invalidate_context(context_id)` — global graph only (for bulk ops)
- **Why ETS, not a GenServer Map:** a GenServer serializes ALL reads through one process inbox. Under concurrent page loads, this becomes a bottleneck. ETS with `read_concurrency: true` allows lock-free concurrent reads from any process — the GenServer only handles the rare write-on-miss.
- **Cache `nil` results too:** `get_page` stores `:not_found` for nil pages so repeated misses are cheap (no GenServer call, no DB query).

### 11. Labels/sprites: create only what the user will see (click-selection model)

**2026-08 update:** the MyApp graph moved from hover-based to **click-based selection** (Álvaro: "Quita el hover"). The current model: zero labels by default; **single click** a node → `selectNode()` creates `SpriteText` labels for the clicked node + its direct neighbors only (BFS depth 1), dims the rest; **double-click** navigates; background click clears. So the labels-are-waste lesson is: **create labels lazily on selection, not at init**. The original "remove labels entirely" advice is now WRONG for this app — labels are the primary interaction affordance. What still holds:

- Do NOT create 400 `SpriteText` objects at init (each allocates canvas + texture + material). Create them in `selectNode()` for the small selected set, dispose them in `clearSelection()` (remove from parent, `material.map.dispose()`, `material.dispose()`).
- Do NOT keep a `scheduleLabelRefresh` polling loop — the click-selection model doesn't need per-frame label visibility tracking.
- The BFS `computeNeighborhood` for highlight (dim/scale) is kept — it drives which nodes get labels.
- Verify: `grep -c "SpriteText" assets/js/hooks/graph_3d.js` should show the lazy creation pattern, NOT init-time creation.

### 12. Multi-level BFS subgraphs with batch queries

A subgraph showing only direct neighbors (1 level) is shallow. Expanding to 3 levels via BFS gives richer context. The key: use the **batch** relation loader per BFS frontier, not per-node:

```elixir
def build_page_subgraph(page, opts \\ []) do
  depth = Keyword.get(opts, :depth, 3)
  max_nodes = Keyword.get(opts, :max_nodes, 200)
  # Level 1: list_relations_for_page (or preloaded)
  # Levels 2-N: list_relations_for_pages(frontier_ids) — 2 SQL queries per level
  # After BFS: one query for all neighbor metadata (slug, title, page_type)
end
```

- Cap at `max_nodes` (default 200) to prevent unbounded expansion on hubs.
- Each BFS level is 2 SQL queries total, not 2×N.
- Dedup via `MapSet` visited set in the BFS, not `Enum.uniq_by` on a growing list.
- `import Ecto.Query` and `alias MyApp.Brain.Page` needed in the helper module.

### Regression: removing module attributes triggers `--warnings-as-errors`

When you delete a feature that had a module attribute (e.g. `@max_graph_nodes 400`), the attribute becomes "set but never used". Before deleting: `grep -rn '@attr_name' lib/` to find readers. Same for unused aliases after a refactor.

### 13. Debounce PubSub broadcasts with `Process.send_after`

When a `page_changed` broadcast triggers a full graph reload, debounce it: cancel any pending timer, then schedule a single `send_after`. When the timer fires, push an event to the hook to re-fetch over HTTP — the full graph never re-serializes over the socket per broadcast:

```elixir
def handle_info({:page_changed, _action, _changed_page}, socket) do
  case socket.assigns.live_action do
    :index ->
      if socket.assigns.refetch_timer, do: Process.cancel_timer(socket.assigns.refetch_timer)
      timer = Process.send_after(self(), :graph_refetch, 1500)
      {:noreply, assign(socket, refetch_timer: timer)}
    :show -> ...
  end
end

def handle_info(:graph_refetch, socket) do
  {:noreply, assign(socket, refetch_timer: nil) |> push_event("graph_refetch", %{})}
end
```

The hook listens for `graph_refetch` via `this.handleEvent("graph_refetch", () => this.fetchGraphData())` in `mounted()`.

## Verification

Add ExUnit coverage for the cap/rank/totals semantics AND a throwaway ad-hoc script (`MIX_ENV=test mix run /tmp/verify.exs`, own context, cascade cleanup) that exercises the new paths against real rows. The ad-hoc script catches semantic bugs (like the "relations to excluded nodes counted toward degree" one) that isolated unit tests with tiny fixtures miss. See `references/progressive-graph-loading.md` for the full implementation recipe and `references/graph-query-pitfalls.md` for the detailed code comparisons behind fixes 6-8.
