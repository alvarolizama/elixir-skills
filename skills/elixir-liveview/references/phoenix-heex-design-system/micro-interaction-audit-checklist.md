# Micro-interaction Audit Checklist

Reusable checklist for auditing transition/hover/focus-visible completeness
across Phoenix HEEx component files. Derived from the my_app app audit session.

## Per-element checklist

For each interactive element in each in-scope file, check all three:

### 1. Transition class
- [ ] Has `transition-colors`, `transition-transform`, or `transition-all`
- [ ] Has `duration-150` or `duration-200` (not longer than 200ms for UI feedback)
- [ ] If element has scale on active (e.g. `active:scale-95`), uses bare `transition`

### 2. Visible hover state
- [ ] Nav links: `hover:bg-base-200` (or `hover:bg-base-300` for buttons)
- [ ] Icon-only links: `hover:opacity-80` or `hover:opacity-100` if starting dim
- [ ] Cards/clickable rows: `hover:shadow-md` or `hover:bg-base-200` (no layout shift)
- [ ] Active nav indicator: `border-l-2 border-primary` or `bg-primary/10 text-primary`

### 3. Focus-visible ring (keyboard navigation)
- [ ] Has `focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none`
- [ ] Has `rounded` or `rounded-lg` so the ring has a shape (if not already present)
- [ ] Uses `focus-visible` NOT `focus` (so ring doesn't appear on mouse click)
- [ ] Form inputs: upgrade from `focus:ring-1` to `focus-visible:ring-2`

## Element types to audit

| Element | Where found | Notes |
|---|---|---|
| `<a href>` | nav links, logo, "view all" links | Most common — often missing focus-visible |
| `<button>` | toolbar buttons, toggle buttons, submit buttons | Check `btn` daisyUI classes too |
| `<select>` | context selectors, filter dropdowns | Often missing transition + focus-visible |
| `<input>` | search boxes, form fields | Usually has `focus:ring-1` — upgrade to `focus-visible:ring-2` |
| `<summary>` | collapsible `<details>` sections | Often missing transition + focus-visible |
| `<div phx-click>` | clickable cards/rows | Needs `cursor-pointer` + transition + hover + focus-visible |
| `<g phx-click>` (SVG) | graph nodes | Skip focus-visible (needs tabindex); add `transition-transform` + `hover:opacity-80` |

## Scope boundary checks

Before editing, verify:
- [ ] Read ALL in-scope files first (don't edit blind)
- [ ] Search for modals/dialogs: `phx-remove`, `phx-mounted`, `JS.hide`, `JS.show`, `modal`, `dialog`
- [ ] If modals found: add smooth open/close transitions via `JS.transition`
- [ ] If no modals in scope: note explicitly, don't invent them
- [ ] Honor file exclusions (e.g. "do NOT touch core_components.ex")
- [ ] Verify with `mix compile --warnings-as-errors`

## my_app app specific notes (reference, not generic)

The my_app app at `/Users/alvaro/Repos/my_app` has these component files:

- `lib/dran_web/components/layouts.ex` — sidebar nav, topbar, theme toggle, context selector
- `lib/dran_web/components/markdown_editor_components.ex` — TipTap editor toolbar buttons, meta fields
- `lib/dran_web/live/graph_live.ex` — graph canvas, view mode toggle (2D/3D), SVG nodes
- `lib/dran_web/components/core_components.ex` — EXCLUDED (done in wave 1)
- `lib/dran_web/components/page_list_components.ex` — EXCLUDED (done in wave 1)
- `lib/dran_web/components/chat_widget.ex` — EXCLUDED (done in wave 1)
- `lib/dran_web/components/command_palette.ex` — EXCLUDED (done in wave 1)

No modal/dialog components exist in the in-scope files (only in excluded files).
The `nav_link` component already had transition + hover + active state — only
needed focus-visible ring added.
