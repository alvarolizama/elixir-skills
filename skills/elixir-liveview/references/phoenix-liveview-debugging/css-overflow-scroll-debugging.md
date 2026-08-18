# Worked Example: CSS overflow-hidden Clipping Detail Pages

## Symptom

Note detail pages (`/notes/<slug>`) and other detail pages (concepts, goals,
plans) cannot scroll to the bottom. The version history section
("Historial de cambios") and backlinks are cut off and unreachable — no
scrollbar appears. Meanwhile the kanban board (`/todos`) and dashboard (`/`)
work fine.

## Investigation

### 1. Confirm the bug with browser_console JS measurement

The app was running at `http://localhost:4000`. After logging in and navigating
to a long note detail page, measured the main content wrapper:

```js
// browser_console expression
(() => {
  const e = document.querySelector('div.flex-1.overflow-hidden.flex.flex-col.w-full');
  return JSON.stringify({
    scrollHeight: e.scrollHeight,   // 1806
    clientHeight: e.clientHeight,    // 633
    canScroll: e.scrollHeight > e.clientHeight,  // true
    overflow: getComputedStyle(e).overflow        // "hidden"
  });
})()
```

Result: `canScroll: true, overflow: "hidden"`. Content exists (1806px) but is
clipped at 633px with no way to reach it. **Bug confirmed at the layout
wrapper, not the page.**

### 2. Read the layout to find the overflow class

```
read_file lib/dran_web/components/layouts.ex
```

The `app/1` function component renders:

```heex
<div class="flex h-screen bg-base-100 text-base-content">
  <aside class="w-64 shrink-0 ...">...</aside>

  <div class="flex-1 overflow-hidden flex flex-col w-full">   <!-- THE BUG -->
    {render_slot(@inner_block)}
  </div>
  ...
</div>
```

The `h-screen` flex shell gives the wrapper a fixed viewport height.
`overflow-hidden` clips anything taller. Detail pages that don't set their
own scroll container (e.g. `note_live.ex` show action wraps `page_detail` in
a bare `<div :if={@live_action == :show}>`) are clipped.

### 3. Why the kanban survived

The kanban (`todo_live.ex`) sets its own explicit height:

```heex
<div id="kanban-board" class="flex flex-col h-[calc(100vh-4rem)] p-4">
```

`calc(100vh-4rem)` = 633 - 64 = 569px, which is **shorter** than the wrapper's
633px. So no overflow is generated on the wrapper — the kanban fits within the
clipped area and renders full-viewport. This is why the bug only hit detail
pages, not the board.

## The Fix

### Root fix: layout wrapper

```diff
- <div class="flex-1 overflow-hidden flex flex-col w-full">
+ <div class="flex-1 overflow-y-auto flex flex-col w-full">
```

One line, one file (`layouts.ex`). Every detail page that relies on the layout
for scroll is fixed at once.

### Cleanup: docs double-scroll

After the root fix, `/docs` had a **nested double-scroll**. The docs page
pre-dated the layout fix and had its own scroll container:

```heex
<div class="p-6 w-full overflow-y-auto h-full">  <!-- redundant now -->
```

With the wrapper now `overflow-y-auto`, this inner div also scrolled — two
competing scroll containers. Measured:

```js
// wrapper: canScroll false (633 === 633) — inner div stole the scroll
// docsInner: canScroll true (961 > 633), overflowY "auto"
```

Fix: remove the redundant overflow from the inner div:

```diff
- <div class="p-6 w-full overflow-y-auto h-full">
+ <div class="p-6 w-full">
```

Now docs scrolls via the single wrapper, consistent with every other page.

**How to find these**: after the root fix, grep for redundant scroll containers:

```
search_files "overflow-y-auto h-full" path=lib/dran_web
```

## Verification (browser, all against the running app)

### Note detail (the reported bug)

```js
// After fix: scroll to bottom, confirm version history visible
(() => {
  const e = document.querySelector('div.flex-1.overflow-y-auto.flex.flex-col.w-full');
  e.scrollTop = e.scrollHeight;
  const h = Array.from(document.querySelectorAll('h3'))
    .find(el => el.textContent.includes('Historial de cambios'));
  const r = h.getBoundingClientRect();
  return JSON.stringify({
    scrollHeight: e.scrollHeight,  // 1806
    clientHeight: e.clientHeight,  // 633
    scrolledToBottom: e.scrollTop >= e.scrollHeight - e.clientHeight - 1,  // true
    versionHistoryInViewport: r.top < window.innerHeight && r.bottom > 0  // true
  });
})()
```

### Kanban (must stay full-viewport, no page scroll)

```js
(() => {
  const w = document.querySelector('div.flex-1.overflow-y-auto.flex.flex-col.w-full');
  const k = document.getElementById('kanban-board');
  const cols = document.querySelectorAll('[data-kanban-status]');
  return JSON.stringify({
    wrapperCanScroll: w.scrollHeight > w.clientHeight,  // false — good
    kanbanHeight: k.offsetHeight,                       // 569 = 100vh - 4rem
    columnsEqualHeight: new Set(Array.from(cols).map(c => c.offsetHeight)).size === 1  // true
  });
})()
```

The kanban's `h-[calc(100vh-4rem)]` (569px) is shorter than the wrapper
(633px), so no page scroll is generated. All 6 columns stretch to equal
height. Feature preserved.

### Docs (single scroll, no double-scroll)

```js
// wrapper now scrolls (961 > 633), inner div overflow is "visible" (not "auto")
```

## Compile & Tests

```
mix compile --warnings-as-errors   # clean, no warnings
PORT=4444 MIX_ENV=test mix test    # 281 passed
```

## Key Lessons

1. **Measure, don't guess.** `browser_console` with a JS expression comparing
   `scrollHeight` vs `clientHeight` proves clipping in seconds. The
   `overflow` computed style confirms it's `hidden` vs `auto`.
2. **Fix at the root (layout), not per-page.** One `overflow-hidden` →
   `overflow-y-auto` change fixes every detail page. Per-page scroll
   containers would be 10+ edits and drift.
3. **Check for nested double-scroll after the root fix.** Pages that had
   their own `overflow-y-auto h-full` now compete with the wrapper. Grep
   for them and simplify to rely on the wrapper.
4. **Verify fullscreen pages survive.** Kanban/dashboard pages with explicit
   heights (`h-[calc(100vh-4rem)]`) stay full-viewport because they're shorter
   than the wrapper — confirm `wrapperCanScroll: false` after the fix.
5. **The `fluid` attr pattern.** The layout declared `attr :fluid, :boolean`
   and `todo_live.ex` passed `fluid={@live_action == :index}`, but the
   template never consumed `@fluid`. An unused attr is harmless (preserves
   API) — the kanban works via its own height calc, not via `fluid`. Don't
   remove it (breaks callers), don't rely on it (does nothing).
