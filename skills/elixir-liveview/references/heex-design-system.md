# HEEx Design System — Custom CSS Layer + daisyUI

**Symptom:** a Phoenix app styled with Tailwind + daisyUI shows
inconsistent surfaces, hardcoded gray/blue/amber/green/red palette
classes that break in dark mode, hover effects that silently do nothing,
and repeated UI markup drifting across pages.

## Core concept

Apply a custom CSS layer (`.text-title`, `.surface-2`, `.lift`, etc.)
alongside Tailwind v4 + daisyUI semantic colors. Custom classes encode
reusable look-and-feel; daisyUI tokens carry color semantics so UI
adapts to light/dark mode.

### Typography mapping

| Element | Class | Replaces |
|---|---|---|
| Page h1 | `.text-title` | `text-2xl font-bold` |
| Section h2 | `.text-heading` | `text-lg font-semibold` |
| Body text | `.text-body` | `text-sm` |
| Captions | `.text-caption` | `text-xs text-base-content/50 uppercase` |
| Display (hero) | `.text-display` | `text-4xl font-extrabold` |

### Surface / elevation

| Class | Purpose |
|---|---|
| `.surface-1` | Subtle background (base-200) + thin border |
| `.surface-2` | Card surface + subtle shadow |
| `.surface-3` | Elevated card + deeper shadow |
| `.lift` | Hover micro-interaction: translateY + shadow upgrade |

### daisyUI semantic color migration — replace the hardcoded palette

| Hardcoded | daisyUI token | Use case |
|---|---|---|
| `bg-gray-100 text-gray-600` | `bg-base-300 text-base-content/70` | Neutral |
| `bg-blue-100 text-blue-700` | `bg-info/15 text-info` | Informational |
| `bg-amber-100 text-amber-700` | `bg-warning/15 text-warning` | Caution |
| `bg-green-100 text-green-700` | `bg-success/15 text-success` | Positive |
| `bg-red-100 text-red-700` | `bg-error/15 text-error` | Destructive |

### CRITICAL pitfall: custom CSS cannot take Tailwind variant prefixes

`hover:surface-3` does **nothing** — custom classes are not Tailwind
utilities.

| You want to… | Use |
|---|---|
| Hover-elevate a surface | `.lift` (self-contained `:hover`) |
| Hover-change background | `hover:bg-base-200` (Tailwind utility) |
| Hover-change border | `hover:border-primary/30` (Tailwind utility) |

Nested `.surface-2` inside a hovered container is invisible: it does not
elevate on parent hover. Use `hover:bg-base-200` for nested items.

### Prop-to-tint helper

```elixir
defp bg_for_color("text-primary"), do: "bg-primary/10"
defp bg_for_color("text-success"), do: "bg-success/10"
defp bg_for_color("text-error"),   do: "bg-error/10"
defp bg_for_color(_),              do: "bg-base-content/10"
```

### Component redesign checklist

1. Replace `card bg-base-100 border` → `.surface-2`
2. Add `.lift` for interactive cards
3. Icon: `size-10 rounded-lg bg-{color}/10`
4. Value: `text-2xl font-bold tabular-nums`
5. Label: `.text-caption`

## CSS percentage-height pitfall

`height: 100%` resolves against the parent's *content* box; a bar chart
or progress fill whose parent has `height: 0` (or only padding) renders
a zero-height child — the bar disappears. Fix: put `height: 100%` +
`position: relative` on the bar's immediate wrapper so it anchors to a
real height, and give the wrapper an explicit height from the layout.
Rule: `%` heights climb the ancestor chain — every intermediate box must
have a resolvable height.

## Icon-only toggle buttons

An icon-only toggle must encode the ACTION, not the state, in
`icon + title`: a chevron pointing down says "Collapse" (action), not
"Expanded" (state). When a toggle isn't the right control (one of two
exclusive modes), use two explicit buttons or a segmented control
instead.

## Micro-interaction audit checklist

Per interactive element:

1. Transition class on state change (`transition-transform`,
   `transition-colors`, `transition-all` where safe).
2. Visible hover state (`.lift`, `hover:bg-*`, `hover:border-*`).
3. Focus-visible ring for keyboard navigation (`focus-visible:ring-2
   ring-primary` or equivalent).

Audited element types: cards, nav items, icon buttons, table rows with
actions, toggle buttons, sidebar groups.

## Collapsible sidebar panels (details/summary)

Use native `<details>`/`<summary>` for collapsible groups — no JS, no
state, keyboard accessible. Convert plain div panels by moving the
toggle target into `<details>`; flatten nested `<details>` inside
`<summary>` (nested interactive elements break the click target).

## Table column grouping

Wide tables: two-row `<thead>` — group header row + column header row;
body rows mirror the separators; update the empty-state `colspan` to the
full column count. Grouping strategy: group by domain, order by
cardinality (fixed sets first), keep group labels short.

## Bulk component extraction (N files → 1 shared component)

1. Locate every occurrence: `grep -rl '<form id="the-form">' lib/`.
2. Read ALL target files before patching.
3. Patch each file independently; confirm each file gets exactly 1
   occurrence of the new component.
4. Verify per file: exactly 1 occurrence of the new component, zero
   occurrences of the old literal inside a `.form` tag, structure
   (`if/else/end`) intact, then compile to catch attr mismatches.

## Verification

```bash
mix format --check-formatted lib/my_app_web/live/<target>.ex
mix compile --warnings-as-errors
mix test test/my_app_web/live/
```

Update tests that assert on old markup — prefer structural asserts over
text: element id, the new class, or the navigate destination:

```elixir
assert has_element?(view, ~s(a[href="/notes/1"]))
assert has_element?(view, ~s(.surface-2))
```