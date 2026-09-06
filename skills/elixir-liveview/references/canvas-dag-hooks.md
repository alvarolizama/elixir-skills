# Canvas / DAG / 3D Hooks — Client-State Re-assertion

**Symptom:** an absolutely-positioned canvas or DAG surface (SVG edges +
cards in a pan/zoom stage, or a 3D force graph) slowly corrupts as the
server patches: edges cross-wire between wrong nodes, pan/zoom resets,
wires are drawn at stale offsets, or the whole stage freezes after a
re-render.

Same underlying class as `client-dom-vs-morphdom.md` — state that lives
only in the client DOM/content — with its own victims and fixes.

## Mechanism: morphdom syncs unkeyed children by index

When a connect/remove reorders edges, morphdom matches unkeyed SVG paths
by index and `d` attributes swap between paths. Cards are absolutely
positioned via inline `style.left/top`; the server renders them without
the client-owned pan/zoom transform (`stage.style.transform` + hook state
`this.tx/ty/scale`), so any re-render big enough to recreate children
strips the transform while hook state stays — rect math computed before
re-asserting it uses a *phantom* transform, drawing wires at stale
offsets.

## Fixes

### Keyed edge paths + client `redrawEdges()`

- Put `data-edge-key={prereq <> "|" <> dependent}` on every SVG path —
  and on its HTML overlay buttons — so morphdom matches by key, not
  index.
- A client `redrawEdges()` selects `path[data-edge-key]` and re-derives
  `d` from live port rects.
- Card drag recomputes `style.left/top` AND edge paths in the same
  pointermove frame (server only learns on drop); the hook `updated()`
  re-runs `redrawEdges()` after EVERY patch to absorb the server's
  stale server-rendered `d`. Never wait for the round-trip to animate —
  the patch that lands later just confirms it.
- Optimistic dropped edge: on connection drop, freeze the ghost path at
  the drop point and set a `pendingEdge` flag; `updated()` clears it and
  reveals the real server edge from that same patch — no flicker between
  drop and round-trip.

### Pan-guard rot when cards lose `phx-click`

A pan hook that guards with `closest('[phx-click]')` silently stops
protecting cards the moment cards become drag-first (click removed).
Add the explicit card-class guard in the pan `_onDown` — otherwise pan +
card drag run simultaneously.

### Re-assert the stage transform before any rect math

In `updated()` call the pan hook's `_apply()` (re-assert transform; make
it re-query the stage node if `!isConnected`) BEFORE `redrawEdges()`.

### Edge anchors must glide with the cards

Cards carry `transition-all duration-300`; server-rendered port
`left/top` (inline style) needs its own mirrored transition — same
duration AND same easing (`cubic-bezier(0.4,0,0.2,1)`), else ports jump
on frame 1 and edges redrawn from live rects trail behind. Kill the port
transition during manual drag (sibling selector, e.g.
`.card-dragging ~ span[data-port]`) so ports hug the cursor
frame-by-frame.

### One `updated()` redraw isn't enough mid-transition

Live rects during the glide are still pre-patch values; a single redraw
freezes the wires behind the cards. Loop: in `updated()`, if any card or
port has a running `CSSTransition` (`getAnimations()`; exclude infinite
keyframe pulses), redraw edges+menus every rAF until transitions end
(bounded ~500ms deadline), then one final redraw.

## 3D force-graph hooks

Where a 3D canvas is driven by a `phx-hook` that owns `this.fullData`,
the LiveView holds only counters + filter state and pushes data over a
single channel — see `liveview-data-performance` notes in the SKILL.

## Fixture-based testing (no app login)

Serve a static fixture dir (`python3 -m http.server`) replicating the
DOM, then mount the real hook manually:

- Bundle hook files into ONE classic script (strip `import`/`export`;
  `file://` blocks ES modules, absolute imports break).
- `Object.create(Hook)`, stub `pushEvent` into `window.__events`, call
  `mounted()`.
- Drive with synthetic `PointerEvent` sequences (dispatch is
  synchronous).

Caveats: MutationObserver callbacks are microtasks — assert after
`setTimeout(0)`; removing a node directly does NOT trigger the observer,
mutate the observed parent's childList instead. The fixture proves hook
math; it CANNOT catch server-patch interactions (morphdom strips) —
those need the real app.

## Real-app E2E for canvas patches

playwright-core against the dev server; login via the real form;
materialize the layout (one card drag, persist `meta.pos`); wait out all
CSSTransitions (`getAnimations()`); trigger the repack button; sample
`path.getPointAtLength(0/len)` + `getScreenCTM()` (bbox lies for
beziers) every 100ms and assert both wire endpoints sit within ~12px of
their port centers for every sample. Verify the served bundle actually
contains the fix before trusting a pass.