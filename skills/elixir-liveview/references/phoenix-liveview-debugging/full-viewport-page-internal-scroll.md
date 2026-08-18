# Full-Viewport Page with Internal Column Scroll

## The scenario (inverse of the clipping bug)

The sibling doc `css-overflow-scroll-debugging.md` covers the case where the
layout wrapper has `overflow-hidden` and **clips** detail pages — the fix is to
switch the wrapper to `overflow-y-auto` so every page can scroll.

This doc covers the **inverse**: a page that should fill the entire content
area with **no page-level scroll at all**, scrolly happening *inside* its own
sub-elements (e.g. each kanban column scrolls independently). The wrapper is
already `flex-1 overflow-y-auto flex flex-col w-full` (the "good" state from
the sibling fix). The challenge: make ONE page opt out of the wrapper's scroll
without touching `layouts.ex` and without breaking the other pages that rely
on it.

## Why `h-full` does NOT work here

The wrapper is a flex column that scrolls:

```heex
<!-- layouts.ex — the shared wrapper -->
<div class="flex-1 overflow-y-auto flex flex-col w-full">
  {render_slot(@inner_block)}
</div>
```

A child with `h-full` resolves against the parent's **content height**, which
in a scrolling flex column is `auto` (= the child's own height). So `h-full`
on the kanban root is a no-op — the child grows with its content, and the
wrapper scrolls. Exactly the behavior we want to suppress.

`min-h-full` is the same trap: it sets a floor but no ceiling, so tall content
still pushes the wrapper into scroll mode.

## The working pattern: `h-screen` + `overflow-hidden` + the `min-h-0` chain

```heex
<!-- kanban_live.ex — root of the LiveView template -->
<div class="flex h-screen flex-col overflow-hidden">
  <div class="... shrink-0">  <!-- header: fixed height, never compresses -->
  <div class="... shrink-0">  <!-- filters: fixed height, never compresses -->

  <!-- Board: consumes the remaining height. min-h-0 is CRITICAL. -->
  <div class="flex gap-4 overflow-x-auto px-4 pb-4 flex-1 min-h-0"
       id="kanban-board" phx-hook="KanbanDragDrop">

    <!-- Each column fills the board's height. min-h-0 again, h-full. -->
    <div class="w-72 shrink-0 flex flex-col min-h-0 h-full ...">
      <div class="... shrink-0">  <!-- column header -->

      <!-- The scroll region. flex-1 + min-h-0 + overflow-y-auto. -->
      <div class="p-2 space-y-2 min-h-0 flex-1 overflow-y-auto">
        <!-- cards -->
      </div>
    </div>
  </div>
</div>
```

### Why each class is necessary

| Class | Without it |
|---|---|
| Root `h-screen` | Child has no height baseline; wrapper's `overflow-y-auto` engages and the page scrolls. `h-screen` matches the visible wrapper exactly (the shell is `flex h-screen`). |
| Root `overflow-hidden` | Tall content overflows the root and pushes the wrapper into scroll mode anyway. |
| Root `flex flex-col` | Children can't use `flex-1` to split the viewport. |
| Header/filters `shrink-0` | Flex compresses them when the board is tall, squashing the controls. |
| Board `flex-1` | Board collapses to content height; no room for columns to stretch. |
| Board `min-h-0` | **The #1 silent failure.** Flex items default to `min-height: auto`, which prevents children from scrolling — `overflow-y-auto` on a child has nothing to clip against because the parent grew to fit. Adding `min-h-0` lets the board shrink below its content so the child scrollbars engage. |
| Column `h-full` + `min-h-0` | Columns don't fill the board's height; the inner scroll region has no bounded height. |
| Inner list `flex-1 min-h-0 overflow-y-auto` | Either no scroll (no `flex-1`) or no clipping boundary (no `min-h-0`). |

### Why `h-screen` is correct (not `h-[calc(100vh-Npx)]`)

The layout shell is `flex h-screen` (sidebar + content side by side, both
100vh). The content wrapper is `flex-1`, so its rendered height is **exactly
`100vh`** — there is no header above it to subtract. So `h-screen` on the
kanban root is the precise value. No `calc()` needed.

The older pattern `h-[calc(100vh-4rem)]` (seen in the sibling doc) works only
when there's a 4rem header **inside** the wrapper above the board. It is
fragile: change the header height and the calc drifts, leaving a gap or a
scrollbar. Prefer `h-screen` + `flex-1` for the remaining-height split.

### The `min-h-[200px]` trap

A common instinct on the scroll region is `min-h-[200px] flex-1 overflow-y-auto`
— "give it at least 200px so empty columns are visible." This **backfires**:
when the board is shorter than 200px (small viewport, many columns), the
`min-height: 200px` forces the region taller than its flex parent, which
pushes the wrapper into scroll mode. Use `min-h-0` instead. Empty columns are
still visible — they just show their "Empty" placeholder at natural height.

## Decision: touch `layouts.ex` or not?

Two options were evaluated for this task:

**Option A — wrapper change:** flip the wrapper's `overflow-y-auto` to
`overflow-hidden` for the kanban page (via a layout attr or a conditional
class). Rejected: every other page depends on the wrapper scrolling. The
blast radius is the entire app.

**Option C (chosen) — page-local only:** leave `layouts.ex` untouched. The
kanban root uses `h-screen overflow-hidden` to create its own bounded box that
the wrapper never needs to scroll. Other pages are 100% unaffected because
the wrapper's classes never changed.

**Rule:** when one page needs to opt out of a shared scroll container,
encapsulate the opt-out in that page's root element. Do not parameterize the
layout. The blast radius of a layout change is the whole app; the blast
radius of a page change is one file.

## Verifying it works (browser_console)

```js
// The wrapper must NOT scroll (kanban owns the viewport)
(() => {
  const w = document.querySelector('div.flex-1.overflow-y-auto.flex.flex-col.w-full');
  const k = document.getElementById('kanban-board');
  const cols = document.querySelectorAll('[data-kanban-status]');
  return JSON.stringify({
    wrapperCanScroll: w.scrollHeight > w.clientHeight,   // false = good
    wrapperOverflow: getComputedStyle(w).overflowY,       // "auto" (unchanged)
    kanbanRootOverflow: getComputedStyle(k.parentElement).overflow,  // "hidden"
    columnsEqualHeight: new Set(Array.from(cols).map(c => c.offsetHeight)).size === 1,
    innerListsScroll: Array.from(document.querySelectorAll('[data-kanban-status] > div:last-child'))
      .every(d => d.scrollHeight > d.clientHeight === false || d.scrollHeight > d.clientHeight)
  });
})()
```

The key signals:
- `wrapperCanScroll: false` — the kanban did NOT push the wrapper into scroll.
- `wrapperOverflow: "auto"` — we did NOT touch the wrapper; other pages still scroll.
- `columnsEqualHeight: true` — the `h-full` + `min-h-0` chain stretched columns.
- `innerListsScroll` — at least one column has more content than its height.

## Verifying other pages still scroll

After the change, grep the wrapper selector on a normal page (e.g. `/notes`):

```js
(() => {
  const w = document.querySelector('div.flex-1.overflow-y-auto.flex.flex-col.w-full');
  return JSON.stringify({
    wrapperOverflowY: getComputedStyle(w).overflowY,  // "auto" — still scrolls
    wrapperCanScroll: w.scrollHeight > w.clientHeight  // true on long pages — good
  });
})()
```

If `wrapperOverflowY` is anything other than `"auto"`, the layout was
accidentally modified — revert `layouts.ex` and keep the change page-local.

## When to use this pattern

- Kanban / sprint boards with independent column scroll.
- Multi-pane dashboards (fixed header + scrollable table + fixed footer).
- Chat UIs (message list scrolls, composer is pinned).
- Any LiveView where the page itself should not scroll but inner regions must.

**Do NOT use this for:** form pages, settings, article/docs views, or any
content the user reads top-to-bottom. Those rely on the wrapper scroll and
should stay as `w-full p-6` (no `h-screen`, no `overflow-hidden`).

## The before/after diff (my_app kanban)

| Element | Before | After |
|---|---|---|
| Root | `px-4 py-3` | `flex h-screen flex-col overflow-hidden` |
| Header row | `flex items-center justify-between mb-4` | `flex items-center justify-between px-4 pt-3 pb-2 shrink-0` |
| Filters | `flex flex-wrap gap-3 mb-4 p-3 ...` | `flex flex-wrap gap-3 mx-4 mb-3 p-3 ... shrink-0` |
| Board | `flex gap-4 overflow-x-auto pb-4` | `flex gap-4 overflow-x-auto px-4 pb-4 flex-1 min-h-0` |
| Column | `w-72 shrink-0 flex flex-col ...` | `w-72 shrink-0 flex flex-col min-h-0 h-full ...` |
| Column header | `flex items-center justify-between px-3 py-2 border-b ...` | `... shrink-0` appended |
| Inner list | `p-2 space-y-2 min-h-[200px] flex-1 overflow-y-auto` | `p-2 space-y-2 min-h-0 flex-1 overflow-y-auto` |

Two things to call out:
1. **Padding moved from root to children.** The root can't have `px-4 py-3`
   anymore because `overflow-hidden` would clip content at the root's padding
   edge — but more importantly, the root needs to be a pure flex container
   with no padding so `h-screen` is exact. Each child carries its own `px-*` /
   `pt-*` / `pb-*` / `mx-*` instead.
2. **`min-h-[200px]` → `min-h-0`** on the scroll region. This is the subtlest
   change and the one most likely to be "helpfully" reverted by a future
   contributor. The 200px floor sounds reasonable but breaks the flex chain
   on short viewports.
