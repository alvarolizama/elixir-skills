# 3D Force Graph Hook Pitfalls (three-forcegraph / 3d-force-graph)

Lessons from debugging the my_app 3D knowledge graph (`assets/js/hooks/graph_3d.js`).

## 1. `graph.refresh()` flushes all Three.js objects — causes visible jump on zoom

`refresh()` in `three-forcegraph` sets `_flushObjects = true` and calls
`_rerender()`. This forces a full reconstruction of all Three.js scene objects
(spheres, links, particles). When zoomed in and hovering a node, the
reconstruction causes a visible jump/flicker — nodes appear to "move away."

**Fix:** remove `refresh()` calls from `selectNode` and `clearSelection`. The
link accessors (`linkColor`, `linkWidth`, `linkDirectionalParticles`) are
evaluated every render frame, and direct `material.opacity` /
`emissiveIntensity` / `scale.setScalar` changes on `n.__sphere` are visible
without a flush.

```js
// BAD — causes jump when zoomed + hovering
selectNode(node) {
  // ... dim/glow spheres ...
  this.graph.refresh()  // ← remove this
}

// GOOD — accessors re-evaluate every frame; material changes are immediate
selectNode(node) {
  // ... dim/glow spheres ...
  // no refresh() needed
}
```

Verified by removing both `refresh()` calls and confirming highlight/dim still
works without the zoom-jump.

## 2. SpriteText labels clutter the 3D view — DOM overlay is cleaner

`three-spritetext` creates text sprites that float above nodes in 3D space. They
work but: (a) they require a dependency, (b) they need manual disposal in
cleanup, (c) they clutter the view at scale, (d) they need raycast handling for
click-through.

**Alternative:** a DOM overlay div injected by the hook into `this.el` (the
hook container) — positioned top-right, showing the hovered node's title + type
+ a link to open the page. No Three.js dependency, fades in/out with CSS
transition, removed on hover-out + cleanup.

Key implementation details:
- `this.el` (the hook container div) already has `position: relative` from the
  component wrapper. The overlay uses `position: absolute` inside it.
- Inject the overlay in `selectNode(node)` when `node.label` exists.
- Remove in `clearSelection()` via `hideHoverOverlay()` — fade out then
  `removeChild` after 200ms.
- Also call `hideHoverOverlay()` at the start of `cleanup()`.
- The overlay builds the page URL from `node.type` + `node.slug` via a
  typePlurals map (`{note: "notes", concept: "concepts", ...}`).

## 3. Node data shape from the server

The graph JSON from `/api/graph-json` (or `data-graph` attribute in show mode)
provides nodes as `{id, slug, label, type, color}` and edges as
`{source_id, target_id, color}`. The hook transforms these:
- `id` → `String(n.id)` for consistent Set/Map lookups
- `links` → `source`/`target` become node-object references after force-graph
  processes them; keep original String IDs for adjacency computation
- `label` — the page title, used for the DOM overlay
- `type` — the page_type, used to build the page URL

## 4. Hover debounce + expiry pattern

300ms debounce before highlighting (avoid flicker when sweeping the cursor
across nodes), then 3s expiry after cursor leaves (highlight persists briefly
before auto-clearing). Implementation:

```js
handleNodeHover(node, prevNode) {
  if (this.labelExpiryTimer) clearTimeout(this.labelExpiryTimer)
  if (node) {
    if (this.hoveredNode !== node) {
      this.hoveredNode = node
      if (this.hoverTimer) clearTimeout(this.hoverTimer)
      this.hoverTimer = setTimeout(() => {
        this.hoverTimer = null
        if (this.hoveredNode === node) this.selectNode(node)
      }, 300)
    }
  } else if (prevNode) {
    if (this.hoverTimer) clearTimeout(this.hoverTimer)
    this.hoveredNode = null
    this.labelExpiryTimer = setTimeout(() => {
      this.clearSelection()
      this.labelExpiryTimer = null
    }, 3000)
  }
}
```