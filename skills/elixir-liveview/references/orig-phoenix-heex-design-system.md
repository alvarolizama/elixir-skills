---
name: phoenix-heex-design-system
description: "Refactor Phoenix LiveView HEEx templates to apply a custom design-system CSS layer (typography, surfaces, elevation) alongside Tailwind v4 + daisyUI semantic colors. Covers class migration, the custom-vs-utility pitfall, prop-to-tint helpers, and HEEx-only verification."
version: 1.0.0
author: Álvaro Lizama
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [elixir, phoenix, liveview, heex, tailwind, daisyui, design-system, css, ui-refactor]
    related_skills: [software-development/phoenix-wizard-forms, creative/popular-web-designs]
---

# Phoenix HEEx Design System Refactoring

Use when refactoring HEEx templates to apply a custom design-system CSS layer
(`.text-title`, `.surface-2`, `.lift`, etc. in `app.css`) alongside Tailwind v4
+ daisyUI semantic colors. Also covers **UI consolidation** (merging duplicate
sections that share the same data) and the **propose-then-implement** workflow
Álvaro prefers for UI refactors — see
`references/ui-consolidation-and-propose-workflow.md`.
color tokens.

## Common triggers

- "Pulir el Dashboard / LiveView usando las clases del design system"
- "Migrate hardcoded Tailwind palette colors to daisyUI semantic tokens"
- "Apply `.surface-2`, `.lift`, `.text-heading` to existing LiveView"
- "Make components work in both light and dark themes"
- User references specific custom CSS classes that exist in app.css

## Workflow

1. **Read both files first** — the target `.ex` LiveView file AND `assets/css/app.css`.
   You need to know which custom classes exist (`.surface-2`, `.lift`,
   `.text-title`, `.text-heading`, `.text-caption`, `.text-body`, `.text-display`,
   `.surface-1`, `.surface-3`, `.skeleton`, `.focus-ring`) and what they do
   before touching the template.
2. **Read AGENTS.md** — the project may have UI/UX guidelines (e.g. "never use
   `@apply`", "always use `<.icon>` component", HEEx class list syntax rules).
3. **Plan the migration** per component: identify hardcoded palette classes
   (`bg-gray-100`, `text-blue-700`, `bg-purple-100`) and map them to daisyUI
   semantic tokens.
4. **Edit only the target file** — the user often constrains changes to one
   `.ex` file. Do not edit CSS, layouts, or other LiveViews unless explicitly
   allowed. Test files may be updated if they assert on changed markup.
5. **Re-read after concurrent modification** — when working alongside parallel
   subagents (e.g. via `dynamic-workflow`), the `patch` tool may fail with
   "modified by sibling subagent." Re-read the file with `read_file` before
   retrying; the other agent may have already applied part or all of the
   design-system changes, leaving only cleanup or verification. After
   re-reading, review what was done and clean up artifacts (see pitfalls).
6. **Verify** with `mix compile --warnings-as-errors` and the relevant test
   directory. See the Verification section below.

## Typography class mapping

Custom design-system CSS layers typically define a typographic scale. Use the
right class for the right element:

| Element | Class | Typical CSS |
|---|---|---|
| Page h1 (main title) | `.text-title` | 1.5rem, 700, -0.01em tracking |
| Section h2 headers | `.text-heading` | 1.125rem, 600 |
| Body text / labels | `.text-body` | 0.875rem, 400 |
| Captions / metadata | `.text-caption` | 0.75rem, 500, 55% base-content |
| Display (hero) | `.text-display` | 2.25rem, 800, -0.02em |

When refactoring, replace ad-hoc Tailwind (`text-2xl font-bold`,
`text-sm text-base-content/50`, `text-lg font-semibold`) with the
corresponding design-system class.

## Surface / elevation classes

| Class | Purpose |
|---|---|
| `.surface-1` | Subtle background (base-200), thin border |
| `.surface-2` | Card surface (base-100) + subtle shadow |
| `.surface-3` | Elevated card (base-100) + deeper shadow |
| `.lift` | Hover micro-interaction: translateY + shadow upgrade |
| `.skeleton` | Loading placeholder with shimmer animation |

Use `.surface-2 .lift` on interactive cards (metric cards, quick-access tiles)
for a subtle hover effect. Use `.surface-2` alone for static section containers.

## daisyUI semantic color migration

Replace hardcoded Tailwind palette classes with daisyUI semantic tokens so
colors adapt to both light and dark themes automatically:

| Old (hardcoded) | New (semantic) | Use case |
|---|---|---|
| `bg-gray-100 text-gray-600` | `bg-base-300 text-base-content/70` | Neutral / backlog |
| `bg-blue-100 text-blue-700` | `bg-info/15 text-info` | Informational |
| `bg-amber-100 text-amber-700` | `bg-warning/15 text-warning` | Caution / today |
| `bg-purple-100 text-purple-700` | `bg-accent/15 text-accent` | Highlight / in-progress |
| `bg-green-100 text-green-700` | `bg-success/15 text-success` | Positive / done |
| `bg-red-100 text-red-700` | `bg-error/15 text-error` | Destructive / cancelled |

The `/15` opacity variant creates a subtle tinted background that works in
both themes. Pair with `text-{semantic}` for the foreground.

## CRITICAL PITFALL: Custom CSS classes cannot take Tailwind variant prefixes

This is the #1 mistake when working with a custom design-system CSS layer.

**Custom classes defined as plain CSS in `app.css` (e.g. `.surface-2`,
`.lift`, `.text-caption`) are NOT Tailwind utilities.** Tailwind's variant
system (`hover:`, `focus:`, `md:`, `dark:`) only works on classes that
Tailwind generates. Writing `hover:surface-3` in a HEEx class attribute
produces **nothing** — the class is silently ignored.

### Wrong (does nothing)

```heex
<.link class="surface-2 hover:surface-3 transition ...">
```

### Right — use Tailwind utilities for hover states

```heex
<.link class="rounded-lg hover:bg-base-200 transition ...">
```

### Right — use `.lift` for the hover-elevation pattern

The `.lift` class already encapsulates `transition` + `:hover` in its CSS
definition, so it works without a `hover:` prefix:

```css
/* In app.css — .lift handles its own :hover */
.lift { transition: all 150ms ease; }
.lift:hover { transform: translateY(-0.5px); box-shadow: var(--shadow-surface-3); }
```

```heex
<!-- Correct: .lift is self-contained -->
<div class="surface-2 lift p-5">...</div>
```

### Rule of thumb

| You want to... | Use |
|---|---|
| Hover-elevate a surface | `.lift` (self-contained `:hover`) |
| Hover-change background color | `hover:bg-base-200` (Tailwind utility) |
| Hover-change border color | `hover:border-primary/30` (Tailwind utility) |
| Apply a custom surface class on hover | **Cannot** — restructure instead |

## Prop-to-tint helper pattern

When a component receives a `color` prop like `"text-primary"` and you need
the matching tinted background `bg-primary/10`, use a function head with
pattern-matched clauses:

```elixir
attr :color, :string, default: "text-base-content"

defp metric_card(assigns) do
  ~H"""
  <div class="surface-2 lift p-5 flex items-center gap-3">
    <div class={[
      "shrink-0 size-10 rounded-lg flex items-center justify-center",
      bg_for_color(@color)
    ]}>
      <.icon name={@icon} class={["size-5", @color]} />
    </div>
    <div class="min-w-0">
      <div class="text-2xl font-bold tabular-nums">{@value}</div>
      <div class="text-caption">{@label}</div>
    </div>
  </div>
  """
end

defp bg_for_color("text-primary"), do: "bg-primary/10"
defp bg_for_color("text-secondary"), do: "bg-secondary/10"
defp bg_for_color("text-accent"), do: "bg-accent/10"
defp bg_for_color("text-info"), do: "bg-info/10"
defp bg_for_color("text-success"), do: "bg-success/10"
defp bg_for_color("text-warning"), do: "bg-warning/10"
defp bg_for_color("text-error"), do: "bg-error/10"
defp bg_for_color(_), do: "bg-base-content/10"
```

This keeps the color prop as the single source of truth and derives the
background tint from it. The fallback clause ensures unknown colors still
get a visible tint.

## Status badge → semantic pill with dot

daisyUI's `badge badge-success` / `badge badge-ghost` classes render as flat
colored rectangles. For a more professional "status pill" look (Notion / Linear
style), rewrite them as a rounded-full tinted background + a small colored dot
+ label text:

```elixir
attr :active, :boolean, required: true

defp status_badge(assigns) do
  ~H"""
  <span class={[
    "inline-flex items-center gap-1.5 px-2 py-0.5 text-xs font-medium rounded-full",
    @active && "bg-success/15 text-success",
    !@active && "bg-base-200 text-base-content/50"
  ]}>
    <span class={[
      "size-1.5 rounded-full",
      @active && "bg-success",
      !@active && "bg-base-content/30"
    ]} />
    {if @active, do: gettext("Enabled"), else: gettext("Disabled")}
  </span>
  """
end
```

Conventions:
- Container: `rounded-full` (pill, not `rounded-md`), `px-2 py-0.5 text-xs
  font-medium`, tinted background `bg-{semantic}/15` for active or
  `bg-base-200` for neutral/inactive.
- Dot: `size-1.5 rounded-full` (≈6px) using the solid semantic color
  (`bg-success`, `bg-error`, `bg-base-content/30` for inactive). The solid
  color — not a tint — gives the dot enough contrast to read as a status
  indicator against the tinted background.
- This replaces `badge badge-sm badge-success` / `badge badge-ghost` wholesale;
  the `@active` prop semantics are preserved.

Use this pattern on settings/config rows (Enabled/Disabled), API status
indicators, and any binary state that currently uses daisyUI `badge-*` classes.

## HEEx class list syntax

Per AGENTS.md conventions, when a class attribute has multiple values or
conditional logic, **always use list `[...]` syntax**:

```heex
<!-- Correct: list syntax -->
<div class={[
  "shrink-0 size-10 rounded-lg flex items-center justify-center",
  bg_for_color(@color)
]}>
```

```heex
<!-- Correct: string interpolation for dynamic badge classes -->
<span class={"px-2.5 py-1 text-xs rounded-lg #{badge}"}>{label}</span>
```

Both forms are valid. Use list syntax when composing multiple dynamic parts;
use string interpolation when a single dynamic value is appended to a static
prefix.

## Component redesign checklist

When refactoring a card-based component (metric_card, quick_card, etc.):

1. Replace `card bg-base-100 border border-base-300` → `.surface-2`
2. Replace `card-body p-5` → `p-5` (drop the daisyUI card wrapper)
3. Add `.lift` if the card is interactive (clickable, hoverable)
4. Icon: wrap in `size-10 rounded-lg flex items-center justify-center` +
   `bg-{color}/10` tint
5. Value: `text-2xl font-bold tabular-nums` (tabular-nums for aligned digits)
6. Label: `.text-caption` (replaces `text-xs text-base-content/50 uppercase tracking-wider`)
7. Layout: `flex items-center gap-3` (icon left, text stacked right)

## Section structure pattern

Organize dashboard/overview pages with consistent section headers:

```heex
<div class="surface-2 p-5">
  <div class="flex items-center justify-between">
    <h2 class="text-heading">{gettext("Section Title")}</h2>
    <.link navigate={~p"/related"} class="text-sm text-primary hover:underline">
      {gettext("View all")}
    </.link>
  </div>
  <div class="space-y-2 mt-4">
    <!-- items -->
  </div>
</div>
```

Key conventions:
- Section containers: `.surface-2 p-5` (not `card` + `card-body`)
- Section title: `.text-heading` (not `card-title text-lg font-semibold`)
- "View all" link: `text-sm text-primary hover:underline` (not `btn btn-ghost`)
- Spacing between sections: `space-y-8` (not `space-y-4`)
- Spacing inside sections (title → content): `mt-4` (not `mt-2`)

## Greeting-style dashboard header pattern

When polishing a dashboard / home LiveView to read like a personal-management
app (Notion, Linear, Reflect), replace a static `"Dashboard"` title with a
time-of-day greeting. Elixir has no `if/else if` — use `cond`:

```elixir
# Private helper in the LiveView module
defp greeting do
  hour = DateTime.utc_now().hour

  cond do
    hour < 6 -> gettext("Good night")
    hour < 12 -> gettext("Good morning")
    hour < 20 -> gettext("Good afternoon")
    true -> gettext("Good evening")
  end
end

defp format_today do
  Calendar.strftime(Date.utc_today(), "%A, %B %d, %Y")
end
```

```heex
<div class="space-y-1">
  <h1 class="text-title">{greeting()}</h1>
  <p class="text-caption">
    {format_today()} ·
    {if @context, do: @context.name, else: gettext("No context")} · {@stats[:total_pages] || 0} {gettext("pages")}
  </p>
</div>
```

Conventions:
- Greeting boundaries: <6 night, <12 morning, <20 afternoon, else evening.
- Always `gettext()` each greeting string — they're user-visible and need PO entries (es: "Buenos días", "Buenas tardes", etc.).
- `Calendar.strftime/2` with `%A, %B %d, %Y` gives "Sunday, July 19, 2026" — locale-aware via the gettext backend's default locale. No extra dependency.
- The greeting replaces the title in the header only; keep `page_title: gettext("Dashboard")` in `mount/3` for the browser tab.
- `DateTime.utc_now()` is fine for the greeting even if the app is timezone-aware — the bucket boundaries are wide enough that UTC offset rarely crosses a greeting threshold. If precision matters, use the configured local timezone.

## Verification

After editing only the target `.ex` file:

```bash
# Check formatting first — catches HEEx class-attribute line-wrapping issues
# that mix compile won't report but the formatter will reformat on next run
mix format --check-formatted lib/dran_web/live/<target>.ex
# If it diffs, run mix format on the file(s) to apply the formatter's fixes
# (formatting only — no logic change):
mix format lib/dran_web/live/<target>.ex

# Compile with warnings as errors
mix compile --warnings-as-errors

# Run the relevant test directory
mix test test/dran_web/    # or test/dran_web/live/ if dashboard_live_test.exs exists
```

`mix format --check-formatted` is a fast pre-compile gate: it surfaces HEEx
class-attribute wrapping (long `class={[...]}` lists that fit on one line get
split by the formatter) before you pay for a full compile. If it diffs, run
`mix format <file>` (no arguments beyond paths) to auto-fix formatting — this
only reformats whitespace/line-wrapping, never logic. The skill authoring
convention is: formatter output is the canonical form; do not hand-format.

If tests assert on old markup (class names, text content that changed), update
them using `has_element?/2` with robust selectors (element IDs, semantic
classes) rather than text content. See `references/verification-recipes.md`
for detailed patterns, pre-existing warning handling, the daisyUI semantic
color quick-reference table, and the custom class quick-reference table. For
the micro-interaction audit checklist (transition/hover/focus-visible per
element type), see `references/micro-interaction-audit-checklist.md`.

## Categorical documentation card-grid

When a docs/guide page needs to list a fixed set of entities (agent types, page
types, API categories) where each item has rich metadata (icon, trigger type,
description, limits), use a 2-column card grid driven by a **data-list helper**
rather than a flat `<ul>` or a `<table>`. This is the richer cousin of the "Next
steps" card grid — each card carries more structured information and a badge.

### Data-list helper pattern

Define a private function returning a list of maps with all card fields. This
keeps the template clean and makes the data easy to maintain:

```elixir
defp agents_data do
  [
    %{
      label: "Research",
      icon: "hero-magnifying-glass-circle",
      color: "text-blue-500 dark:text-blue-400",
      trigger: :manual,        # or :scheduled
      schedule: nil,           # "Daily 06:00", "Sun 08:00" for scheduled
      description: "Explores a topic...",
      limits: "Max 10 sources, 10 pages..."
    },
    # ...
  ]
end
```

### Card grid template

```heex
<div class="not-prose grid grid-cols-1 md:grid-cols-2 gap-4 my-4">
  <%= for agent <- agents_data() do %>
    <div class="surface-1 lift rounded-lg p-4 border border-base-300/60 transition">
      <div class="flex items-start justify-between gap-3 mb-2">
        <div class="flex items-center gap-2.5">
          <.icon name={agent.icon} class={["w-7 h-7", agent.color]} />
          <h3 class="font-semibold text-base-content">{agent.label}</h3>
        </div>
        <%= if agent.trigger == :manual do %>
          <span class="shrink-0 inline-flex items-center gap-1 rounded-full bg-primary/10 text-primary text-xs font-medium px-2.5 py-0.5 border border-primary/20">
            <.icon name="hero-hand-raised" class="w-3 h-3" />Manual
          </span>
        <% else %>
          <span class="shrink-0 inline-flex items-center gap-1 rounded-full bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 text-xs font-medium px-2.5 py-0.5 border border-emerald-500/20">
            <.icon name="hero-clock" class="w-3 h-3" />{agent.schedule}
          </span>
        <% end %>
      </div>
      <p class="text-sm text-base-content/70 leading-relaxed mb-3">
        {agent.description}
      </p>
      <p class="text-xs text-base-content/50 flex items-center gap-1.5">
        <.icon name="hero-adjustments-horizontal" class="w-3.5 h-3.5" />
        {agent.limits}
      </p>
    </div>
  <% end %>
</div>
```

### Key conventions

- **Grid:** `not-prose grid grid-cols-1 md:grid-cols-2 gap-4` (escape prose for
  full control; 2 columns on desktop, 1 on mobile).
- **Card surface:** `.surface-1 .lift rounded-lg p-4 border border-base-300/60`
  — `.surface-1` + explicit border gives a subtle card; `.lift` adds hover.
- **Distinct icon colors per item:** when items are categorical (not status),
  assign each a distinct palette color (`text-blue-500`, `text-violet-500`,
  `text-amber-500`, etc.) rather than daisyUI semantic tokens. Categorical
  distinction benefits from visual variety; semantic status should use tokens.
- **Data-driven `<%= for %>`** with a helper list — never hardcode 6 cards inline.
  The helper is the single source of truth; the template is pure rendering.
- **Metadata line at bottom:** `text-xs text-base-content/50 flex items-center
  gap-1.5` with a small `hero-adjustments-horizontal` icon prefix for limits/config.

### Badge pill variants

Three badge pill styles by purpose:

| Purpose | Pattern | Example |
|---|---|---|
| **Status badge** (semantic) | `bg-{semantic}/15 text-{semantic}` (no border) | `bg-success/15 text-success` |
| **Categorical badge with border** | `rounded-full bg-{color}/10 text-{color} border border-{color}/20 px-2.5 py-0.5` + inline `w-3 h-3` icon | Manual / Scheduled |
| **Required-field marker** | `bg-red-500/20 text-red-700 text-xs px-1.5 py-0.5 rounded` (no icon) | `yes` / `no` in param tables |

The **border variant** (`rounded-full ... border border-{color}/20`) gives a more
distinct "pill" look than the bare tint — use it when badges need to stand out
as metadata tags alongside rich card content. Pair with an inline `w-3 h-3` hero
icon and `text-xs font-medium` for a compact, scannable badge.

## Segmented control pattern

For mode/strategy selectors (search strategy, filter tabs, view toggles),
use the segmented control pattern instead of bordered buttons:

```heex
<div role="group" class="inline-flex rounded-lg bg-base-200 p-1">
  <button
    :for={{mode, label} <- @modes}
    type="button"
    phx-click="set_mode"
    phx-value-mode={mode}
    class={[
      "px-3 py-1.5 text-sm transition-colors rounded-md",
      if @search_mode == mode,
        do: "bg-base-100 shadow-sm font-medium",
        else: "text-base-content/60 hover:text-base-content"
    ]}
  >
    {label}
  </button>
</div>
```

Key conventions:
- Container: `inline-flex rounded-lg bg-base-200 p-1` (not border + overflow-hidden)
- Active item: `bg-base-100 shadow-sm font-medium` (lifts out of the track)
- Inactive item: `text-base-content/60 hover:text-base-content`
- Each item: `rounded-md` (rounds inside the container's `rounded-lg`)
- Refactor repeated mode buttons into a `@modes` list to avoid duplication

## Icon-in-tinted-square pattern

Two sizes depending on context:

| Context | Size | Classes |
|---|---|---|
| Dashboard metric cards | `size-10` | `size-10 rounded-lg flex items-center justify-center bg-{color}/10` |
| List items / search results | `size-8` | `size-8 rounded-md flex items-center justify-center bg-primary/10` |

The `size-8 rounded-md` compact variant is for dense lists (search results,
kanban cards) where the larger `size-10` would dominate. Icon inside is
`size-4` (compact) or `size-5` (standard).

## Empty state convention

Empty states come in three levels of richness depending on context.

### Level 1 — Inline empty (within a column/list)

```heex
<p class="text-caption text-center py-8">{gettext("No items")}</p>
```

- `py-8` for inline empty states (within a list column)
- Text: always `.text-caption` (never raw `text-xs text-base-content/30`)

### Level 2 — Full-section empty with icon (search results, dashboard)

```heex
<div class="text-center py-16">
  <.icon name="hero-face-frown" class="size-10 mx-auto text-base-content/30" />
  <p class="text-caption mt-3">{gettext("No results found")}</p>
</div>
```

- `py-16` for full-section empty states
- Icon: `size-10 mx-auto text-base-content/30` when present
- Text: always `.text-caption`

### Level 3 — Rich empty state with CTA (index pages, collection lists)

When the empty state is on a top-level index/list page where the user's next
action is clear (create the first item), use a full CTA pattern — icon, title,
help text, and a button:

```heex
<div :if={@collections == []} class="text-center py-16">
  <.icon name="hero-folder-plus" class="w-16 h-16 mx-auto mb-4 text-base-content/30" />
  <h2 class="text-lg font-semibold text-base-content/70">
    {gettext("No smart collections yet.")}
  </h2>
  <p class="text-sm text-base-content/50 mt-1 max-w-sm mx-auto">
    {gettext("Save a set of filters from search or any page list to create one.")}
  </p>
  <.link navigate={~p"/collections/new"} class="btn btn-primary btn-sm mt-4">
    <.icon name="hero-plus" class="w-4 h-4" />
    {gettext("Create your first collection")}
  </.link>
</div>
```

Key conventions:
- Icon: `w-16 h-16` (larger than the search empty state's `size-10`)
- Title: `text-lg font-semibold text-base-content/70` (not `.text-heading` —
  this is a standalone empty state, not a section header)
- Help text: `text-sm text-base-content/50 mt-1 max-w-sm mx-auto` — constrain
  width so it doesn't sprawl on wide screens
- CTA: `btn btn-primary btn-sm mt-4` with a `hero-plus` icon
- All strings wrapped in `gettext()`

**When NOT to add a CTA:** if the creation form is already visible on the
same page (e.g. the context_live form sits above the list), the empty state
should only say "create one above" with an icon — no button. The form IS the
CTA.

### Empty state icon selection

Pick a heroicon that semantically matches the entity:

| Entity type | Icon |
|---|---|
| Collections / saved queries | `hero-folder-plus` |
| Pages / search results | `hero-document-magnifying-glass` |
| Tags | `hero-tag` |
| Contexts / workspaces | `hero-square-3-stack-3d` |
| Generic "nothing found" | `hero-face-frown` |

## Browser tool form submission pitfall

The Hermes `browser_tool` (browser_navigate + browser_click) does NOT reliably
submit HTML `<form method="post">` elements. The click may appear to succeed
but the POST never fires, leaving the page on the same URL. This is a known
limitation of the tool's DOM interaction layer — it works for LiveView
`phx-submit` forms (which use JS interception) but not for classic HTML forms.

**Workaround for authenticated screenshots:**
1. Read the auth module for default credentials (`auth.ex` module attributes)
2. Use `curl` to perform the login POST and capture the session cookie
3. Use `curl` with the cookie to verify pages load correctly
4. For actual screenshots, use Playwright with a script that fills the form
   and submits it (or use the `page.evaluate` approach to bypass the form
   and set the session cookie directly)

See `references/browser-tool-form-submit-pitfall.md` for the full reproduction
and the Playwright cookie-injection workaround.

## Progressive disclosure form + smart defaults

> **SUPERSEDED for MyApp (jul 2026):** Álvaro rejected the "Más opciones" collapsible he had previously requested — creation/edit forms now use a 2-column layout: title+editor left, always-visible attributes sidebar right (`aside class="w-80 shrink-0 space-y-4 surface-2 rounded-2xl p-5 sticky top-6"` with an "Atributos" header containing summary + tag_input + meta_fields). Do NOT propose `<details>` progressive disclosure for his create/edit forms; default to the sidebar. The pattern below remains valid generically — just not for MyApp.

## Tag input with badge chips (colocated hook, zero deps)

When the user wants "etiquetas como badges en el input": replace the comma-separated text input with a chip editor that keeps the hidden-input contract so NO server code changes.

### Component shape (`tag_input/1` in the shared editor-components module)

Attrs: `id`, `name` (form field name, e.g. `"page[tags]"`), `value` (comma-separated string OR list), `label`, `placeholder`, `suggestions` (existing tags for datalist autocomplete).

Renders: chip row (`rounded-full bg-primary/10 text-primary text-xs px-2.5 py-1`, tag text + × button) + inline text input + `<datalist>` + **hidden input carrying `attr :name`** with the canonical comma-separated value. Plain form submit sends exactly what the old text input sent.

### Colocated hook behavior (all DOM-only, no server round-trips)

- Enter/comma keydown → `preventDefault`, add chip (trim, strip trailing commas, dedupe), clear field.
- Backspace on EMPTY input → pop last chip.
- Click on `[data-tag-remove]` (delegated on root) → remove that chip.
- `sync(next)` rebuilds hidden value + re-renders chips (removes all `[data-tag-chip]`, inserts new before the field). Source of truth = the hidden input re-parsed on each event — no JS-side state to drift.
- Placeholder: show only when 0 chips (store original in `field.dataset.placeholder`).

### Server-side pieces

- Suggestions: ONE bulk query helper (e.g. `Brain.list_tags(context_id)` → distinct sorted tags), not per-item.
- Wiring into N pages: put the component in the shared form component and lazy-load suggestions there when the caller omits them (`case assigns.tag_suggestions do nil -> load from context_id; list -> list end`) — avoids touching 11 LiveView mounts.
- Ecto `{:array, :string}` fields render CONCATENATED in a plain text input (Phoenix.HTML doesn't comma-join lists) — the tag input normalizes both string and list values, fixing that rendering bug for free.

### Test pattern

`render_component/3`: assert one `[data-tag-chip="x"]` per tag, hidden input canonical value (`value="uno,dos"`), datalist options render. NOTE: colocated hooks render with the FULLY-QUALIFIED module name outside a LiveView — assert `phx-hook="MyAppWeb.Components.TagInput"` in component tests, not the short `.TagInput` name.

## Web-configurable settings page conventions (MyApp direction)

Álvaro's settings-page rule: **web-editable values FIRST (with plain-language explanation per attribute), env-var values AFTER as read-only.** Structure:

1. Editable sections at the top (DB-backed `Settings` overrides), each attribute with a `text-caption` explaining WHAT it does and its EFFECT (not just the name).
2. Read-only env sections grouped under one header (e.g. "Entorno") with caption "Solo lectura — cargado de variables de entorno al arrancar."
3. Fix the page header caption — "Values are read from environment variables at startup" becomes misleading once web-editable settings exist.

**Model selectors from a live inference server:** when the API server exposes `GET /models`, populate per-purpose selects (chat, embedding, rerank, etc.) from it; first option `value=""` labeled "Por defecto (env)" — the empty option removes the override so config falls back to the env var. Read precedence in the config module: DB override first, env second, module default last. On `/models` fetch error, degrade to a note + manual input (don't hide the section). **Annotate the env-default option with " (env)"** so the user always sees what they'll fall back to — this requires parallel env-only getters in the config module (`env_chat_model/0` etc.) that bypass the DB override, because the main getters return the override once set.

**Section order (MyApp, jul 2026):** Brain tuning (editable) → Modelos (editable, API-populated selects) → Entorno (read-only env sections grouped under one header with caption "Solo lectura — cargado de variables de entorno al arrancar."). The old standalone info-note about env vars gets absorbed into the Entorno caption.

When refactoring a creation/edit form (e.g. `page_new_live.ex`) to surface
only primary fields by default and hide secondary fields behind a
collapsible section, use the native `<details>` element with the same
hero-chevron idiom as the backlinks section in `page_components.ex`:

```heex
<details class="group">
  <summary class="flex items-center gap-2 cursor-pointer select-none mb-3">
    <.icon
      name="hero-chevron-right"
      class="size-4 shrink-0 text-base-content/40 transition-transform duration-150 group-open:rotate-90"
    />
    <span class="text-sm font-semibold text-base-content/60 uppercase tracking-wider">
      {gettext("Más opciones")}
    </span>
  </summary>

  <div class="space-y-4 ml-6">
    <!-- secondary fields: summary input, <.meta_fields>, etc. -->
  </div>
</details>
```

Conventions:
- **`class="group"` on `<details>`** enables the `group-open:` variant so the
  chevron rotates 90° on expand.
- **No `open` attribute** → collapsed by default. Add `open={@show_advanced}`
  only if you want conditional expansion.
- **`ml-6` on the body** indents secondary fields under the chevron.
- Primary fields (Title, Tags, Content) stay outside the `<details>`.

### Smart defaults: prefill meta per type on `:new`

On `handle_params` for `:new`, compute a type-specific default meta map and
pass it into `<.meta_fields meta={@meta} context_id={@context_id} />` instead
of `%{}`. Carry defaults through `validate_page` by merging form-submitted
meta on top (user edits win), filtering out empty-string submissions:

```elixir
defp default_meta_for("note"), do: %{"kind" => "thought", "date" => Date.utc_today() |> Date.to_string()}
defp default_meta_for("todo"), do: %{"kanban_status" => "backlog", "priority" => "medium"}
defp default_meta_for(type) when type in ["project", "plan"], do: %{"status" => "draft"}
defp default_meta_for("goal"), do: %{"health_source" => "derived"}
defp default_meta_for(_), do: %{}

# validate_page — operator-precedence pitfall: bind base_meta FIRST
base_meta = socket.assigns[:meta] || %{}
meta = Map.merge(base_meta, meta_from_params(page_params))

defp meta_from_params(%{"meta" => form_meta}) when is_map(form_meta) do
  form_meta |> Enum.reject(fn {_k, v} -> v in ["", nil] end) |> Map.new()
end
defp meta_from_params(_), do: %{}
```

`socket.assigns[:meta] || %{} |> Map.merge(...)` parses as
`socket.assigns[:meta] || (%{} |> Map.merge(...))` — the `|>` binds tighter
than `||`, so the defaults are dropped when `@meta` is nil. Always bind the
base to a variable first.

### Arity-2 with default arg: adding a mode without breaking callers

When a function (e.g. `PageMeta.meta_fields_for/1`) is called by a component
you do NOT own (a concurrent agent is editing it), add the new parameter with
a default so existing arity-1 calls keep working:

```elixir
def meta_fields_for(type, mode \\ :edit)
def meta_fields_for(type, :edit), do: meta_fields_edit(type)
def meta_fields_for("goal", :new) do
  # capture-only fields: health, current_value, progress excluded
  [...]
end
def meta_fields_for(type, :new), do: meta_fields_edit(type)
```

The `:new` filtering activates only once the component gains a `:mode` attr
and forwards it. Until then, the component's arity-1 call hits the default
`:edit` and returns the full list. Document this in the function's `@doc`.

### Testing pitfall: `selected=""` attribute order

Phoenix's HTML renderer emits boolean attributes as `attr=""` and may order
them differently than you'd write by hand. A selected `<option>` renders as
`<option selected="" value="thought">`, NOT `value="thought" selected`.
Tests asserting `~s(value="thought" selected)` will fail. Assert the value
and `selected=""` separately, or just assert the value is present:

```elixir
assert html =~ ~s(value="thought")
assert html =~ ~s(selected="")
```

See `references/progressive-form-and-smart-defaults.md` for the full worked
example (auto-slug removal via `Brain.ensure_title_and_slug/1`, the
one-step `mix gettext.extract --merge` workflow, and the arity-delegation
coordination note for concurrent agents).

## Loading state convention (phx-disable-with)

Submit buttons in LiveView forms should use `phx-disable-with` to show a
loading state while the server processes the event. This is standard
LiveView — no custom JS needed:

```heex
<button type="submit" class="btn btn-primary btn-sm" phx-disable-with={gettext("Creating…")}>
  <.icon name="hero-plus" class="size-4" /> {gettext("Create")}
</button>
```

Conventions:
- Use an ellipsis `…` (U+2026), not three dots `...`
- The loading text should be a participle of the action: "Creating…",
  "Saving…", "Deleting…"
- Always wrap the `phx-disable-with` value in `gettext()` — it's user-visible
  text that will be extracted
- Apply to ALL submit buttons that trigger a server round-trip, not just
  the primary CTA

## Gettext batch workflow

When adding multiple `gettext()` wrappers to several files in one pass:

1. **Verify before wrapping** — use `search_files` to check which strings are
   already wrapped. In mature codebases, many strings may already be in
   `gettext()`. Wrapping an already-wrapped string is a no-op; missing one
   that should be wrapped leaves it untranslated.

2. **Check for prior waves** — if this is a follow-up wave (e.g., wave 2 of
   an i18n pass), check `git log` and `git diff HEAD~1 --stat` to see which
   files were already wrapped. Don't re-wrap files that were done in a
   previous wave — focus on the remaining ones.

3. **Extract new strings:**
   ```bash
   mix gettext.extract
   ```
   This updates `priv/gettext/default.pot` (the template) with all new
   `gettext()` calls found in source files.

4. **Merge into locale files:**
   ```bash
   mix gettext.merge priv/gettext
   ```
   This updates ALL `.po` files (es, en) — adding new msgids with empty
   `msgstr ""`, marking reworded source strings as `#, fuzzy`, and removing
   obsolete entries.

5. **Fill msgstr entries** — open `priv/gettext/es/LC_MESSAGES/default.po`
   and fill every `msgstr ""` with the Spanish translation. A Python script
   is the fastest way to do this in bulk when there are 50+ entries — see
   `scripts/fill_po.py` for a reusable template.

6. **Fix fuzzy entries** — entries marked `#, fuzzy` have a pre-existing
   translation that may be wrong because the source string changed. Review
   each one, correct the `msgstr`, and the `fuzzy` flag will be removed
   automatically on the next `gettext.merge` if the msgstr is non-empty.
   You can also manually strip `, fuzzy` from the `#,` comment line.

7. **Re-run merge to verify:**
   ```bash
   mix gettext.merge priv/gettext
   ```
   Output should show `0 new messages, 0 removed, N unchanged, 0 reworded
   (fuzzy)`. If it shows new or fuzzy entries, you missed some.

8. **Compile to verify:**
   ```bash
   mix compile --warnings-as-errors
   ```

9. **Grep-verify completeness** — after wrapping, confirm NO unwrapped
   English UI strings remain. This is the step that catches missed strings,
   which is the #1 failure mode in batch gettext passes. Run these checks
   across all modified files:

   ```bash
   # Bare placeholders (not wrapped in gettext)
   grep -n 'placeholder="[^{]' lib/dran_web/live/*.ex

   # Bare labels (not wrapped in gettext)
   grep -n 'label="[^{]' lib/dran_web/live/*.ex

   # Bare button/visible text (>Word< not wrapped in {gettext(...)})
   grep -nE '>[A-Z][a-z]+[^<{]*<' lib/dran_web/live/*.ex | grep -v gettext

   # Bare flash messages
   grep -n 'put_flash.*"' lib/dran_web/live/*.ex | grep -v gettext

   # Bare page_title assignments
   grep -n 'page_title: "' lib/dran_web/live/*.ex | grep -v gettext
   ```

   Each grep should return nothing (or only non-UI strings). If any line
   appears, that string was missed — wrap it and re-run. See
   `references/gettext-wrapping-patterns.md` for the exact syntax to use
   for each string type (module attrs, HEEx text, attributes, flash,
   page_title, interpolated strings) and what NOT to wrap.

### Pitfall: gettext.merge resets empty msgstr

If you run `mix gettext.merge` AFTER filling translations, it preserves
non-empty msgstr values. But if you run it and then edit source files and
run it AGAIN, new entries will have empty msgstr. Always fill translations
as the LAST step before compiling.

## Split-renderer component refactor (meta_fields-style)

When a per-type field renderer (e.g. `<.meta_fields>` rendering tuples
`{type, key, label, opts}`) grows per-type branches inside one big `case`,
split it in two stages — this is also how you get visual GROUPING for free:

1. **Split the field list before rendering**: `Enum.split_with/2` on the
   normalized tuples (e.g. link-type fields vs plain fields), assign both
   lists, render the link group under its own section header
   ("Vincular a…" with a `hero-link` icon) and the plain group in the
   standard grid. Grouping by field TYPE costs one line and removes the
   "where do I link this to?" hunt in long forms.
2. **Extract a `meta_field_input/1` private component** (attrs: `type`,
   `key`, `label`, `opts`, `value`, `context_id`) holding the
   `case @type do ... end` — the parent loops call it uniformly. Adding a
   new field type afterwards is one new clause in one place, not an edit
   inside a 60-line template.

Related gotcha: when adding a renderer clause for a previously-unhandled
field type (e.g. `:number` defined in the schema but never rendered), the
symptom is a field that silently doesn't appear — no error. Test by
creating the entity and asserting the input exists.

### Pitfall: subagents write daisyUI form classes into custom-Tailwind apps

When delegating UI work on an app where daisyUI is FORBIDDEN (MyApp rule),
explicitly put "no `class="input ..."` / `class="select ..."`" in the
subagent brief — they reach for daisyUI form classes by default. Sweep
afterwards regardless:

```bash
grep -rn 'class="input \|class="select ' lib/<app>_web/live/
```

Replace with the app's standard field classes:
`w-full px-3 py-2 text-sm rounded-lg border border-base-300 bg-base-100 transition-colors duration-150 focus:outline-none focus:ring-1 focus:ring-primary`.

Also diff-check gettext sweeps from subagents: one "translated" an existing
Spanish msgid into English in the SOURCE (`gettext("Más opciones")` →
`gettext("More options")`) instead of adding a msgstr. Revert the source;
never let a sweep change an existing Spanish msgid.

See `references/kanban-consolidation-and-gettext-fill.md` for the full
recipes: board/list consolidation (dead-code sweep after removing a board,
PubSub dual-list reload), slug de-duplication extraction, bulk po-fill
delegation rules, settings-slimming pattern, and the Three.js theme-aware
background probe.

## Bulk HEEx component extraction (N files → 1 shared component)

When a duplicated inline block (e.g. a `<.form>...</.form>` edit form) is
copy-pasted across many LiveView files with per-type variations, extract it
into one shared function component and replace each occurrence with a call.
This is the N-file cousin of the single-file split-renderer refactor above —
same goal (DRY), different workflow: locate every occurrence with grep, read
all targets in parallel, patch each independently preserving its
`editor_id="<type>-editor"` prop, intentionally drop fields the shared
component now owns (slug, suggest buttons), and verify with
`grep -c` per file + zero residual literal markers. See
`references/bulk-component-extraction.md` for the full worked example
(11 MyApp page-type LiveViews → `<.page_edit_form>`), the per-file structural
preservation rules (todo's status-buttons row, goal/project `overview` tab
wrapper), the intentional-field-dropping checklist, and the concurrent-sibling
`git diff --stat` scope-leak audit.

## Two-column detail page layout (main content + sidebar)

When a `page_detail` shared component has content + backlinks + changelog all
stacked vertically in a single column, restructure to a two-column layout:
main content on the left, backlinks + changelog in a sidebar on the right.

### Structure

```heex
<.detail_tabs_bar />

<div class="flex flex-col lg:flex-row gap-6">
  <%!-- Main column: tabs content ── % --%>
  <div class="flex-1 min-w-0 space-y-6">
    <div id="detail-panel-content" data-detail-panel class="space-y-6" phx-hook="Mermaid">
      {render_slot(@tabs)}
      <!-- rendered_body, compare_version, etc. -->
    </div>
  </div>

  <%!-- Sidebar: backlinks + changelog (hidden in edit mode) ──────── --%>
  <aside :if={not @editing} class="lg:w-72 xl:w-80 shrink-0 space-y-4">
    <div class="surface-2 rounded-lg p-4">
      <.backlinks_section relations={@relations} />
    </div>

    <div class="surface-2 rounded-lg p-4">
      <h3 class="text-caption font-semibold ...">{gettext("Changelog")}</h3>
      <!-- versions list -->
    </div>
  </aside>
</div>
```

Key conventions:
- **`flex-col lg:flex-row`** — stacks on mobile, side-by-side on desktop.
- **`flex-1 min-w-0`** on the main column — `min-w-0` prevents flex overflow
  with long content (code blocks, wide tables).
- **`lg:w-72 xl:w-80 shrink-0`** on the sidebar — fixed width, doesn't shrink.
- **Both backlinks AND changelog go in the sidebar** — each in its own
  `surface-2 rounded-lg p-4` container. Changelog below backlinks.
- **Hide sidebar in edit mode** — `:if={not @editing}` on the `<aside>`. The
  `page_edit_form` component has its own attributes sidebar (`w-80`), so showing
  both sidebars creates visual clutter. Pass `editing={@editing}` from each
  LiveView to `page_detail`.

### Adding the `editing` attr to `page_detail`

The shared `page_detail` component needs an `editing` attr (default `false`)
to conditionally hide the sidebar:

```elixir
attr :editing, :boolean, default: false
```

Each LiveView that uses `page_detail` must pass `editing={@editing}`:

```heex
<.page_detail
  page={@page}
  relations={@relations}
  versions={@versions}
  editing={@editing}
  ...
>
```

When 10+ LiveViews need this attr added, use `execute_code` with a Python
regex script to batch-add it — same principle as the bulk changelog removal
script below.

### Bulk duplicate removal across N LiveViews (Python regex script)

When a shared component (`page_detail`) starts rendering something that was
previously duplicated inline across many LiveViews (changelog, backlinks,
metadata), you need to remove the duplicates. For 9+ files with the same
HTML block pattern, use `execute_code` with a Python regex script instead
of patching each file individually:

```python
import re

files = [
    "lib/dran_web/live/note_live.ex",
    "lib/dran_web/live/todo_live.ex",
    # ... 9 files total
]

changelog_pattern = re.compile(
    r'\n\s*<div class="border-t border-base-300 pt-4">\s*'
    r'<h3 class="text-sm font-semibold text-base-content/60 mb-2">\s*'
    r'\{gettext\("Changelog"\)\}\s*'
    r'</h3>\s*'
    r'<div class="space-y-1">\s*'
    r'(?:<div[^>]*>.*?\</div>\s*)*'
    r'<p :if=\{@versions == \[\]\}[^>]*>\s*\{gettext\("No version history yet\."\)\}\s*</p>\s*'
    r'</div>\s*'
    r'</div>',
    re.DOTALL
)

for f in files:
    with open(f, "r") as fh:
        content = fh.read()
    new_content = changelog_pattern.sub('', content)
    with open(f, "w") as fh:
        fh.write(new_content)
```

The regex matches the entire changelog `<div>` block including the version
list and empty-state paragraph. `re.DOTALL` lets `.*?` span newlines. This
is the same principle as the codebase-wide rename script pattern (see
memory), but for prose removal instead of symbol replacement.

### Batch-adding an attr to N LiveView calls

When a shared component (`page_detail`) gains a new attr (`editing`), every
LiveView that calls it needs to pass it. For 10+ files, use `execute_code`
with a Python regex script:

```python
import re, glob

for f in glob.glob("lib/dran_web/live/*_live.ex"):
    with open(f) as fh:
        content = fh.read()
    if "page_detail" not in content or "@editing" not in content:
        continue
    # Add editing={@editing} before the closing > of the <.page_detail tag
    pattern = r'(<\.page_detail\b[^>]*?)(/?>)'
    def add_attr(m):
        if 'editing=' in m.group(1):
            return m.group(0)
        return m.group(1) + '\n          editing={@editing}' + m.group(2)
    new_content = re.sub(pattern, add_attr, content, count=1, flags=re.DOTALL)
    if new_content != content:
        with open(f, 'w') as fh:
            fh.write(new_content)
```

The `count=1` ensures only the first `<.page_detail` tag in each file is
patched. The `if 'editing=' in m.group(1)` guard makes it idempotent.

### When to use this layout

- **Detail pages with backlinks** — the sidebar pattern works when the page
  has metadata that's useful but not the primary focus (relations, changelog).
- **Hide the sidebar in edit mode** — `page_edit_form` has its own attributes
  sidebar. Pass `editing={@editing}` to `page_detail` and use
  `:if={not @editing}` on the `<aside>`.
- **NOT for forms** — edit forms should use the sidebar for attributes, not
  for backlinks. See the "Progressive disclosure form + smart defaults"
  section above.
- **NOT when the sidebar would be empty** — if there are no relations AND
  no versions, the sidebar adds dead space. Consider hiding the `<aside>` with
  `:if={@relations.outbound != [] or @relations.inbound != [] or @versions != []}`.

## Integrating JS rendering libraries into the TipTap markdown editor (Mermaid, MathJax, etc.)

When adding client-side rendered content (Mermaid diagrams, MathJax, syntax
highlighters) to the MyApp markdown editor, the integration spans 5 files:
a new LiveView hook (lazy-loads the library from CDN), `app.js` hook
registration, a toolbar button in `markdown_editor_components.ex`, a TipTap
command in `markdown_editor.js`, and `phx-hook` attachment on the read-mode
content container in `page_components.ex`. Also covers removing the
`max-width: 65ch` constraint from the `.tiptap` CSS class for full-width
editing. Full pattern in `references/markdown-editor-js-rendering.md`.

## data-testid convention

When the user asks for testability hooks, add `data-testid` attributes
to key containers — not on every element, only on semantic boundaries:

```heex
<div data-testid="todo-board" phx-hook=".KanbanBoard" class="p-6">
  ...
</div>

<div data-testid="search-results" class="space-y-2">
  ...
</div>
```

These are stable selectors for integration tests and Playwright/browser
automation, independent of CSS class changes.

## Drag-and-drop visual feedback via JS hook

When a LiveView uses HTML5 drag & drop with a colocated JS hook, add
visual feedback by toggling Tailwind classes on the drop target columns.
The classes are added on `dragenter`, removed on `dragleave`/`drop`/`dragend`:

```javascript
const dropClasses = ["ring-2", "ring-primary/30", "border-dashed"];

board.addEventListener("dragenter", (e) => {
  const col = e.target.closest("[data-kanban-status]");
  if (col) col.classList.add(...dropClasses);
});

board.addEventListener("dragleave", (e) => {
  const col = e.target.closest("[data-kanban-status]");
  if (col && !col.contains(e.relatedTarget)) col.classList.remove(...dropClasses);
});

board.addEventListener("drop", (e) => {
  const col = e.target.closest("[data-kanban-status]");
  if (col) col.classList.remove(...dropClasses);
  // ... existing drop logic
});

board.addEventListener("dragend", () => {
  // Cleanup: remove classes from all columns in case dragleave didn't fire
  board.querySelectorAll("[data-kanban-status]").forEach((col) => {
    col.classList.remove(...dropClasses);
  });
});
```

The `dragend` cleanup is essential — if the drop happens outside any
column, `dragleave` may not fire on the last entered column. The
`!col.contains(e.relatedTarget)` check prevents premature removal when
moving between child elements within the same column.

Do NOT change the `phx-hook` name, `phx-value-*` attributes, or the
`pushEvent` call — only add visual class toggling around the existing
event logic.

## line-clamp for multi-line truncation

Tailwind v4 includes `line-clamp-2` / `line-clamp-3` by default (no
plugin needed). Use it for excerpts, summaries, and previews:

```heex
<div class="text-sm text-base-content/60 line-clamp-2">
  {raw(sanitize(result.excerpt))}
</div>
```

This replaces manual truncation with CSS `display: -webkit-box` +
`-webkit-line-clamp`.

## Tab-to-collapsible demotion (moving a tab panel into an inline `<details>`)

When a tab panel doesn't justify a full tab slot (low content, always-relevant
context, or the user wants it visible alongside the main content), demote it
from a JS-command tab to a collapsible `<details>` section. This is a common
refactor when the detail page has too many tabs and some are lightweight.

### When to demote vs keep as a tab

| Keep as a tab | Demote to collapsible |
|---|---|
| Heavy content that benefits from its own scroll surface | Light metadata table, activity log |
| Rarely viewed (user clicks in deliberately) | Contextually relevant alongside content |
| Expensive to render (graph, big query) — lazy via server-side tab | Already-rendered, cheap DOM |
| Has interactivity (compare buttons, version diff) | Read-only display |

### The recipe (3 steps)

1. **Remove the tab entry** from the `tabs` list in `detail_tabs_bar/1`:
   ```elixir
   # Before:
   tabs = [
     {"content", gettext("Content")},
     {"metadata", gettext("Metadata")},   # ← remove this
     {"relations", gettext("Relations")},
     {"versions", gettext("Versions")},
     {"activity", gettext("Activity")},   # ← and this
     {"graph", gettext("Graph")}
   ]
   # After:
   tabs = [
     {"content", gettext("Content")},
     {"relations", gettext("Relations")},
     {"versions", gettext("Versions")},
     {"graph", gettext("Graph")}
   ]
   ```

2. **Delete the old `data-detail-panel` div** for the demoted tab — the
   `switch_detail_tab` JS command and `id="detail-panel-<tab>"` are no longer
   needed.

3. **Add a `<details>` collapsible** in the target column using the existing
   chevron idiom. For the **main content column**, place it below the content
   panel. For the **sidebar**, place it after the last `surface-2` card:

   ```heex
   <%!-- Main column: collapsible below content --%>
   <details :if={not @editing} class="group" open>
     <summary class="flex items-center gap-2 cursor-pointer select-none mb-3">
       <.icon name="hero-chevron-right"
         class="size-4 shrink-0 text-base-content/40 transition-transform duration-150 group-open:rotate-90" />
       <h3 class="text-caption font-semibold text-base-content/60 uppercase tracking-wider">
         {gettext("Metadata")}
       </h3>
     </summary>
     <div class="surface-2 rounded-lg overflow-hidden ml-6">
       <!-- content from the old tab panel goes here -->
     </div>
   </details>
   ```

   ```heex
   <%!-- Sidebar: collapsible with surface-2 styling to match Changelog --%>
   <details class="group surface-2 rounded-lg p-4" open>
     <summary class="flex items-center gap-2 cursor-pointer select-none">
       <.icon name="hero-chevron-right"
         class="size-4 shrink-0 text-base-content/40 transition-transform duration-150 group-open:rotate-90" />
       <h3 class="text-caption font-semibold text-base-content/60 uppercase tracking-wider">
         {gettext("Activity")}
       </h3>
     </summary>
     <div class="space-y-1 mt-2">
       <!-- content from the old tab panel -->
     </div>
   </details>
   ```

### Style conventions for demoted collapsibles

- **Main column collapsible**: `class="group" open` (open by default), body
  indented with `ml-6` to align under the chevron. Wrap content in
  `surface-2 rounded-lg` for visual containment.
- **Sidebar collapsible**: `class="group surface-2 rounded-lg p-4" open` —
  matches the Changelog/backlinks cards visually. No `ml-6` indentation (the
  `p-4` padding handles it). Content uses `mt-2` to separate from the summary.
- **`open` by default**: demoted sections are context the user wants to see
  without an extra click. If the section is long or rarely needed, omit `open`.
- **No `data-detail-panel` / `data-detail-tab`**: these are NOT tabs anymore —
  the JS tab switcher should have zero references to them.

### The JS switch_detail_tab needs NO changes

`switch_detail_tab/1` is generic — it does `JS.show(to: "#detail-panel-#{tab}")`.
With fewer tabs in the list, fewer tab buttons render, but the JS command
itself doesn't reference any tab name statically. No code change needed in the
switch function.

### Verify after demotion

```bash
# 1. Compile clean
mix compile --warnings-as-errors

# 2. Confirm no orphaned panel IDs remain
grep -rn 'detail-panel-metadata\|detail-panel-activity' lib/  # should be empty

# 3. Confirm the tab bar only renders the remaining tabs (dev_browser_eval):
# document.querySelectorAll('[data-detail-tab-key]')
#   .forEach(t => console.log(t.dataset.detailTabKey))
# Expected: content, relations, versions, graph (no metadata, no activity)

# 4. Confirm collapsibles exist with the right content (dev_browser_eval):
# document.querySelectorAll('details > summary').map(s => s.textContent.trim())
# Should include "Metadatos" and "Actividad"
```

## Client-side sub-tabs with JS commands (no server round-trip)

When a detail page needs to switch between panels (Content / Relations / Versions / Graph), use **Phoenix.LiveView.JS commands** for the tab switch instead of a `handle_event` + assign round-trip. The panels all render on first paint; clicking a tab just hides/shows them client-side.

### Why client-side

- **Zero latency** — no server round-trip, no diff patch, instant switch.
- **No router changes** — no need for `handle_params` or `?tab=` query plumbing.
- **No assign state** — works inside a shared function component (e.g. `page_detail` used by 10+ LiveViews) without requiring every caller to add an `active_tab` assign and a `switch_tab` handler.

### The pattern

```elixir
# In the shared component module (e.g. DranWeb.PageComponents):

def detail_tabs_bar(assigns) do
  tabs = [
    {"content", gettext("Content")},
    {"metadata", gettext("Metadata")},
    {"relations", gettext("Relations")},
    {"versions", gettext("Versions")},
    {"activity", gettext("Activity")}
  ]
  assigns = assign(assigns, :tabs, tabs)

  ~H"""
  <div class="border-b border-base-300">
    <nav class="flex gap-1" role="tablist" aria-label={gettext("Page sections")}>
      <button
        :for={{tab, label} <- @tabs}
        id={"detail-tab-#{tab}"}
        data-detail-tab
        data-detail-tab-key={tab}
        phx-click={switch_detail_tab(tab)}
        role="tab"
        aria-selected={tab == "content"}
        data-testid={"detail-tab-#{tab}"}
        class={[
          "px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors duration-150",
          tab == "content" && "border-primary text-primary",
          tab != "content" && "border-transparent text-base-content/60 hover:text-base-content hover:border-base-content/20"
        ]}
      >
        {label}
      </button>
    </nav>
  </div>
  """
end

# The JS command — pure client-side DOM manipulation:
def switch_detail_tab(js \\ %JS{}, tab) do
  js
  |> JS.hide(to: "[data-detail-panel]")
  |> JS.remove_class("border-primary text-primary", to: "[data-detail-tab]")
  |> JS.add_class("border-transparent text-base-content/60", to: "[data-detail-tab]")
  |> JS.show(to: "#detail-panel-#{tab}")
  |> JS.remove_class("border-transparent text-base-content/60", to: "#detail-tab-#{tab}")
  |> JS.add_class("border-primary text-primary", to: "#detail-tab-#{tab}")
end
```

Panels in the template — all rendered, only the default visible:

```heex
<div id="detail-panel-content" data-detail-panel class="space-y-6">
  <!-- main content -->
</div>
<div id="detail-panel-metadata" data-detail-panel class="hidden space-y-3">
  <!-- metadata table -->
</div>
<!-- ... more panels, all class="hidden ..." except the default -->
```

### Key conventions

- **Tab bar indicator:** `border-b-2 -mb-px` on buttons over a `border-b` container — the active tab's `border-primary` replaces the container border visually.
- **All panels rendered:** every panel is in the DOM from first paint; non-default ones get `class="hidden ..."`. This is what makes the switch instant and keeps LiveView diffs simple.
- **`data-detail-panel` / `data-detail-tab` markers:** used as JS command selectors — more robust than Tailwind classes (which the LiveView CSS selector engine can't always handle, e.g. `#id.h-[calc(...)]`).
- **`data-testid` on every tab:** `data-testid={"detail-tab-#{tab}"}` so tests do `element(view, "[data-testid=detail-tab-metadata]") |> render_click()`.
- **`role="tablist"` / `role="tab"` / `aria-selected`:** keep the ARIA roles — they're free accessibility and the `aria-selected` initial state must match the visible default panel.
- **When to use server-side tabs instead:** if each tab loads expensive data (a graph, a big query), use the ProjectLive pattern (`@active_tab` assign + `switch_tab` handle_event + render only the active panel) so you don't pay for all panels on mount. Client-side is for cheap, already-loaded content.

### Pitfall: string-keyed maps in tab data

If the tab list or panel data comes from a string-keyed map (`%{"method" => m}`), dot access in the template (`item.method`) crashes LiveView **on tab switch re-render** (not first paint) with `KeyError` at `Phoenix.LiveView.Diff.process_keyed/5`. Convert to atom keys before rendering. This slips past `mix compile` — test with `render_click` on the tab, not just `live/2`.

## Unified tab bar: mixing client-side JS tabs with server-side tabs

When a shared `page_detail` component has client-side JS tabs (Content, Graph,
Related via `switch_detail_tab`) but individual LiveViews (project_live,
goal_live) have their OWN server-side tabs (Kanban, Todos, Notes, etc. via
`switch_tab` + `@active_tab`), you end up with TWO tab bars stacked vertically.
To unify them into ONE bar, use a **hybrid slot architecture** with three new
slots and attrs on the shared component.

### The three slots + three attrs

| Slot / Attr | Purpose |
|---|---|
| `:extra_tabs` slot | Buttons rendered BETWEEN Content and Related/Graph — for LiveView-specific server tabs (Kanban, Todos, Notes, etc.) |
| `:extra_content` slot | Server-side tab content rendered OUTSIDE `detail-panel-content` — so it stays visible when the content panel is hidden |
| `:graph` slot | Still used for pages without server-side tabs (notes, concepts) — renders inside `detail-panel-graph` for client-side switching |
| `content_hidden` attr (bool) | When true, adds `hidden` class to `detail-panel-content` and `detail-panel-graph` |
| `graph_active` attr (bool) | When true, Graph tab shows active styling |
| `related_active` attr (bool) | When true, Related tab shows active styling (and `detail-panel-related` is hidden because content comes from `:extra_content`) |

### Tab bar order

```
Content | [extra_tabs...] | Related | Graph
```

Graph ALWAYS goes last. Related is global (appears on ALL page types). Extra
tabs are LiveView-specific.

### The hybrid click handler

For Content, Graph, and Related tabs, the `phx-click` must work BOTH for
pages with server-side tabs AND pages without them:

```heex
phx-click={if @content_hidden, do: "switch_tab", else: switch_detail_tab("graph")}
phx-value-tab="graph"
```

When `@content_hidden` is true (a server-side tab system is active), the click
fires `switch_tab` (server round-trip). When false (normal page), it fires the
client-side JS command for instant switching.

### CRITICAL: server-side tab content must go in `:extra_content`, NOT `:tabs`

The `:tabs` slot renders INSIDE `detail-panel-content`. When `content_hidden`
is true, that panel gets `class="hidden"` — so anything in `:tabs` disappears
too. The `:extra_content` slot renders OUTSIDE the panel, so it stays visible:

```heex
<div id="detail-panel-content" data-detail-panel class={["space-y-6", @content_hidden && "hidden"]}>
  {render_slot(@tabs)}
</div>

{render_slot(@extra_content)}  <!-- ← server-side tab content goes here -->
```

In the LiveView, split the content:
- `<:tabs>` gets only the "overview" (the dashboard/default view)
- `<:extra_content>` gets all other server-side tabs (kanban, todos, goals, plans, related, graph)

### Per-LiveView wiring

```heex
<.page_detail
  page={@page}
  content_hidden={@active_tab not in ["overview", "graph", "related"]}
  graph_active={@active_tab == "graph"}
  related_active={@active_tab == "related"}
  ...
>
  <:extra_tabs>
    <button :for={{tab, label} <- @project_tabs}
      phx-click="switch_tab"
      phx-value-tab={tab}
      class={[
        "px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors duration-150",
        @active_tab == tab && "border-primary text-primary",
        @active_tab != tab && "border-transparent text-base-content/60 hover:text-base-content hover:border-base-content/20"
      ]}>
      {label}
    </button>
  </:extra_tabs>

  <:tabs>
    <div :if={@active_tab == "overview"}>...</div>
  </:tabs>

  <:extra_content>
    <div :if={@active_tab == "kanban"}>...</div>
    <div :if={@active_tab == "todos"}>...</div>
    <div :if={@active_tab == "graph"}>...</div>
  </:extra_content>
</.page_detail>
```

### The `detail-panel-related` visibility trick

Related is global — it appears on ALL pages. For normal pages (notes, concepts),
it works client-side: `switch_detail_tab("related")` shows `#detail-panel-related`
which contains the page's inbound/outbound relations. For pages with server-side
tabs (project, goal), the Related content comes from `:extra_content`, so the
`detail-panel-related` must be HIDDEN to avoid showing an empty panel:

```heex
<div id="detail-panel-related" data-detail-panel
  class={["hidden", (@content_hidden || @related_active) && "hidden"]}>
```

- Normal page, Related tab clicked: `related_active` is false (no server tabs),
  `content_hidden` is false → JS shows the panel. ✅
- Project page, Related tab clicked: `related_active` is true → panel stays
  hidden, content comes from `:extra_content`. ✅
- Project page, Kanban tab active: `content_hidden` is true → panel hidden. ✅

### Removing "Overview" from the tab list

When unifying, "Overview" is no longer a tab — it becomes the Content tab's
default state. The LiveView's `@active_tab` defaults to `"overview"` and the
Content tab's `phx-value-tab="overview"` maps to it. Remove `{"overview",
"Overview"}` from the LiveView's `@project_tabs` / `@goal_tabs` list.

### Removing "Related" from per-LiveView tab lists

Since Related is now global (rendered by `page_detail` itself), remove
`{"related", "Related"}` from each LiveView's tab list. The LiveView still
handles `@active_tab == "related"` in `:extra_content` for custom rendering
(e.g. project shows notes/concepts/entities/references in a grid).

## Full-width and full-height layout patterns

When a LiveView should fill the available viewport (dashboards, activity feeds, graphs, kanban boards), avoid these common constraints:

### Width: remove `max-w-*` constraints

```heex
<!-- Wrong: artificially limits content width -->
<div class="w-full max-w-4xl mx-auto p-6">

<!-- Right: uses full available width -->
<div class="w-full p-6">
```

**When to keep `max-w-*`**: Form pages (new/edit), settings panels, and narrow content (articles, documentation) benefit from a centered max-width for readability. Apply it selectively, not globally.

**Álvaro's rule (MyApp):** "todas las páginas deben ocupar todo el ancho" — list pages, dashboards, activity feeds, detail views, and docs indexes go full-width. The exceptions he explicitly accepts: centered forms (login, new/edit page) and long-form reading `prose` bodies when a max-width serves legibility. When he says "full width", audit shared components too (`page_components.ex`, `page_list_components.ex`, empty states) — page detail containers (`max-w-5xl mx-auto`, `max-w-3xl mx-auto` panels) are the usual offenders, and they live in the shared component, not in each LiveView.

### Full-height kanban/board inside a scrolling layout wrapper

When the layout wrapper already scrolls (`flex-1 overflow-y-auto flex flex-col`), a board that must fill the viewport with internal-only scroll opts out **locally** — do NOT touch `layouts.ex`:

```heex
<div class="flex h-screen flex-col overflow-hidden">   <!-- page root: own bounded box -->
  <div class="... shrink-0">header + filters</div>      <!-- fixed -->
  <div class="flex gap-4 px-4 pb-4 flex-1 min-h-0">     <!-- board: min-h-0 CRITICAL -->
    <div class="w-72 shrink-0 flex flex-col min-h-0 h-full">  <!-- column -->
      <div class="... shrink-0">column header</div>
      <div class="p-2 space-y-2 min-h-0 flex-1 overflow-y-auto">  <!-- scroll region -->
        <!-- cards -->
      </div>
    </div>
  </div>
</div>
```

- `h-screen` works because the shell is `flex h-screen` with no header above the content area — nothing to subtract. `h-full` does NOT work (parent's height is `auto` in a scrolling flex column).
- Every flex item between root and scroll region needs `min-h-0` — flex items default to `min-height: auto` which prevents descendant scrollbars from engaging.
- Do NOT put `min-h-[200px]` on the scroll region "so empty columns show" — it re-engages the wrapper scroll on short viewports. Use `min-h-0`.
- Verify other pages still scroll: the wrapper keeps `overflow-y-auto`, so only this page's root changed. Blast radius: one file vs the whole app.
- Full worked example + browser_console verification snippets: `references/full-viewport-page-internal-scroll.md` in the `phoenix-liveview-debugging` skill.

### Variant: nested board inside `page_detail` (header + tab bar above)

When the kanban board is NOT at the page root — it's a tab inside a `page_detail`
component that renders a metadata header + a tab bar above the board — `h-screen`
overflows because it doesn't subtract the header/tab-bar chrome. Use
`h-[calc(100vh-Nrem)]` instead, where `N` accounts for: the `page_detail`
header (title, metadata bar, tags), the project sub-tab bar, and the board's
own header row. A typical value is `16rem` (256px) for a MyApp-style project
detail page; adjust by inspecting the rendered page.

```heex
<%!-- Kanban tab inside page_detail — board fills remaining viewport height --%>
<div :if={@active_tab == "kanban"} class="flex flex-col h-[calc(100vh-16rem)] min-h-0">
  <div class="flex items-center justify-between mb-3 shrink-0">
    <span class="text-sm text-base-content/60">{length(@project_todos)} {gettext("todos in this project")}</span>
    <.link navigate={~p"/todos/new"} class="btn btn-primary btn-xs">
      <.icon name="hero-plus" class="size-3.5" /> {gettext("New Todo")}
    </.link>
  </div>
  <div
    class="flex gap-4 overflow-x-auto pb-4 flex-1 min-h-0"
    phx-hook="KanbanDragDrop"
    id="project-kanban-board"
  >
    <div
      :for={{status, label, badge_class} <- @kanban_columns}
      data-kanban-status={status}
      class="w-72 shrink-0 flex-1 max-w-sm flex flex-col min-h-0 h-full rounded-2xl bg-base-200/40 border border-base-300 overflow-hidden"
    >
      <div class="flex items-center justify-between px-3 py-2.5 border-b border-base-300 shrink-0">
        <div class="flex items-center gap-2">
          <span class={"size-2 rounded-full shrink-0 " <> kanban_accent_dot(status)}></span>
          <span class="text-sm font-semibold">{label}</span>
        </div>
        <span class={"px-2 py-0.5 text-xs rounded-full " <> badge_class}>
          {count_kanban(@project_todos, status)}
        </span>
      </div>
      <div class="p-2 space-y-2 min-h-0 flex-1 overflow-y-auto">
        <!-- cards -->
      </div>
    </div>
  </div>
</div>
```

Key differences from the page-root variant:
- **Root height:** `h-[calc(100vh-16rem)]` (not `h-screen`) — subtracts the
  `page_detail` header + tab bar. The `16rem` is an estimate; inspect the
  rendered page and tune. The `min-h-0` on the root is still required.
- **Board row:** `flex-1 min-h-0` (same as page-root variant) + keeps
  `overflow-x-auto pb-4` for narrow screens.
- **Column width growth:** `w-72 shrink-0 flex-1 max-w-sm` — the `flex-1
  max-w-sm` pair makes columns GROW to fill available width (up to 24rem each)
  instead of staying fixed at `w-72`. Without `flex-1`, columns stay at 18rem
  and the board leaves dead space on wide screens. Without `max-w-sm`, columns
  stretch too wide on ultrawide screens. This is the "professional PM tool" look.
- **Column visuals:** `rounded-2xl ... overflow-hidden` (not `rounded-lg`) —
  the `overflow-hidden` is essential so the rounded corners clip the header
  border and the scroll region. Without it, the header's `border-b` pokes out
  of the rounded corners.
- **Status accent dot:** a `size-2 rounded-full` dot next to the column label,
  colored per status via a helper. See the pattern below.

### Status accent dot helper

For column headers that need a colored status indicator (kanban, status
boards), add a small dot next to the label using a private helper that maps
status atoms/strings to Tailwind color classes:

```elixir
defp kanban_accent_dot(status) do
  case status do
    "backlog" -> "bg-base-300"
    "this_week" -> "bg-blue-500"
    "today" -> "bg-amber-500"
    "in_progress" -> "bg-purple-500"
    "done" -> "bg-green-500"
    "cancelled" -> "bg-red-500"
    _ -> "bg-base-300"
  end
end
```

```heex
<div class="flex items-center gap-2">
  <span class={"size-2 rounded-full shrink-0 " <> kanban_accent_dot(status)}></span>
  <span class="text-sm font-semibold">{label}</span>
</div>
```

Use the solid `-500` color (not `/15` tint) for the dot — it's a small accent
that should read as a distinct color chip, not a tinted background. The
backlog/neutral state uses `bg-base-300` (not a semantic color) to match the
"neutral = base-300" rule for kanban columns.

### Height: use viewport-relative sizing

```heex
<!-- Wrong: fixed pixel height crops on tall screens -->
<svg height="600">

<!-- Right: fills available space -->
<svg height="100%" style="min-height: calc(100vh - 180px);">
```

The `calc(100vh - Npx)` pattern subtracts header/sidebar chrome. Adjust `N` based on your layout's fixed heights (e.g., `180px` for a 64px header + 48px breadcrumb + 68px padding).

### Flex column for full-height layouts

When the parent uses `flex flex-col h-screen`, children must use `flex-1` to consume remaining space:

```heex
<div class="flex h-screen">
  <aside class="w-64 shrink-0">...</aside>
  <div class="flex-1 overflow-hidden flex flex-col">
    <!-- LiveView content goes here -->
    <div class="flex-1 overflow-y-auto">  <!-- fills remaining height -->
      <div class="w-full p-6">...</div>     <!-- fills width -->
    </div>
  </div>
</div>
```

## Entity dashboard pattern (detail page as executive dashboard)

When the user says a detail page should open on "un dashboard para ver el status" of the entity (project, goal, etc.) — not a prose body — restructure the default tab into a dashboard and demote the body to a conditional section.

### Structure (top to bottom)

1. **Status header** — one flex row of pill badges: health (semantic tinted), status, priority, target_date with calendar icon. Derived-vs-manual source as a small muted label next to health.
2. **Stat cards** — `grid grid-cols-2 md:grid-cols-4 gap-3`, each `.surface-2 rounded-xl p-4` with a big `text-2xl font-semibold` number, a `text-xs text-base-content/60` label, and a third line of secondary detail (breakdown counts, health badges, progress bar). For a count-with-completion card, add a thin progress bar: `mt-2 h-1.5 rounded-full bg-base-300 overflow-hidden` wrapping a `h-full bg-green-500` div with inline `style={"width: #{pct}%"}`.
3. **Entity body** — only `:if={@page.body not in [nil, ""]}`, so blank bodies don't leave a gap.
4. **Compact linked-item lists** — `grid grid-cols-1 md:grid-cols-2 gap-6`, each section an uppercase `text-caption` header (`Goals (3)`) + rows of `flex items-center justify-between py-1.5 text-sm` (link left, status badge right), capped with `Enum.take(list, 5)`, with a muted one-line empty state per section.

### Scoped kanban tab (board filtered to one entity)

When the entity needs "un tab con un kanban para los items de ese proyecto nada mas":

- Add a `{"kanban", "Kanban"}` entry to the tabs list and a `@kanban_columns` module attribute (copy the 6-column list from the global KanbanLive).
- The board reuses the global kanban's visual pattern (column `w-72 shrink-0 flex flex-col rounded-lg bg-base-200/40 border`, header `shrink-0`, card list `min-h-0 flex-1 overflow-y-auto`) but filters items in memory: `kanban_items(@entity_todos, status)` where `@entity_todos` was loaded with the entity's slug filter (`Brain.list_pages(..., project_slug: page.slug)`).
- **Drag-drop needs its own colocated hook** — copy the `<script :type={Phoenix.LiveView.ColocatedHook} name=".KanbanDragDrop">` block into the tab (a LiveView template can carry its own colocated hook; it pushes `move_todo` to THIS LiveView, not the global one).
- Add a `handle_event("move_todo", ...)` clause in the entity LiveView that updates `kanban_status` via the context and patches the in-memory list (`Enum.map` replace by id) — do NOT reload all pages, the list is small and scoped.
- Card click uses the shared `show_page` event — make sure the LiveView has that handler (see the FunctionClauseError pitfall in `phoenix-liveview-debugging`).

### Key decision: dashboard vs body-first

Default to the dashboard when the entity is a *container* (project, goal with children, plan with todos). Keep body-first when the entity is *content* (note, concept, reference). If the user asks for a dashboard on a container, don't keep the body as the hero — it drops to a conditional section below the stat cards.

## Micro-interaction completeness audit

When asked to "audit and complete micro-interactions" or "add transitions and
focus states" across a set of HEEx component files, work file-by-file and
element-by-element. The goal is that EVERY interactive element has: a transition
class, a visible hover state, and a focus-visible ring for keyboard navigation.

### Standard interaction class bundles by element type

| Element type | Transition | Hover | Focus-visible |
|---|---|---|---|
| Nav links / `<a>` | `transition-colors duration-150` | `hover:bg-base-200` (or `hover:opacity-80` for icon-only) | `focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none` |
| Buttons (`<button>`) | `transition-colors duration-150` (or `transition` if also scaling) | `hover:bg-base-300` / `hover:opacity-100` | same ring pattern |
| Icon-only buttons | `transition-colors duration-150` | `hover:bg-base-300 hover:text-base-content` | same ring pattern + `rounded` |
| Cards / clickable rows | `transition-all duration-200` | `hover:shadow-md` or `hover:bg-base-200` | same ring pattern |
| Form inputs / selects | `transition-colors duration-150` | (native hover) | `focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none` (upgrade from `focus:ring-1`) |
| `<details>` summary | `transition-colors duration-150` | `hover:text-base-content/70` | same ring pattern + `rounded` |
| SVG interactive `<g>` | `transition-transform duration-150` | `hover:opacity-80` or `hover:scale-110` | N/A (SVG focus needs `tabindex` — skip unless explicitly requested) |

### The focus-visible ring pattern

Always use `focus-visible` (not `focus`) so the ring only appears for keyboard
users, not on mouse click:

```
focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none
```

Add `rounded` (or `rounded-lg`) if the element doesn't already have it, so the
ring has a shape to follow. For elements inside a `rounded-lg` container that
already has rounding, the ring inherits the shape.

### Audit workflow

1. **Read all in-scope files first** — read every target `.ex` file before
   making any edits. You need the full picture of what interactive elements
   exist and what classes they already have.
2. **Build an element inventory** — for each file, list every `<a>`, `<button>`,
   `<select>`, `<input>`, `<summary>`, and clickable `<div>`/`<g>`. Note which
   already have transitions, hover states, and focus rings.
3. **Check for modals/dialogs** — search for `phx-remove`, `phx-mounted`,
   `JS.hide`, `JS.show`, `modal`, `dialog` across the scope. If modals exist
   and use `phx-remove`/`phx-mounted`, add smooth open/close transitions
   (fade + scale). If no modals exist in scope, note that explicitly.
4. **Patch element-by-element** — use the `patch` tool with enough surrounding
   context to uniquely identify each element. For class lists that use HEEx
   `[...]` syntax, patch the entire list.
5. **Respect scope exclusions** — the user may say "do NOT touch file X" (e.g.
   files already done in a previous wave). Honor these exclusions strictly.
6. **Verify** with `mix compile --warnings-as-errors`.

### What "already complete" looks like

A nav link that already has transition + hover + active state only needs the
focus-visible ring added:

```heex
<!-- Before: has transition + hover + active, missing focus-visible -->
<a class={[
  "flex items-center gap-2 py-1.5 rounded-lg text-sm transition-colors duration-150",
  @active && "bg-primary/10 text-primary font-medium border-l-2 border-primary",
  !@active && "text-base-content/80 hover:bg-base-200 hover:text-base-content"
]}>

<!-- After: add focus-visible ring -->
<a class={[
  "flex items-center gap-2 py-1.5 rounded-lg text-sm transition-colors duration-150",
  "focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none",
  @active && "bg-primary/10 text-primary font-medium border-l-2 border-primary",
  !@active && "text-base-content/80 hover:bg-base-200 hover:text-base-content"
]}>
```

### Modal/dialog transition pattern

If modals use `phx-remove`/`phx-mounted` with `JS.show`/`JS.hide`, add smooth
transitions by using `JS.transition` with a CSS transition class:

```heex
<div
  id="modal"
  class="modal"
  phx-mounted={show("#modal") |> JS.transition({"transition ease-out duration-200", "opacity-0", "opacity-100"}, to: "#modal")}
  phx-remove={hide("#modal") |> JS.transition({"transition ease-in duration-150", "opacity-100", "opacity-0"}, to: "#modal")}
>
```

If the project doesn't have modals in scope, skip this — don't invent modal
components that don't exist.

### Pitfall: don't add focus-visible to SVG `<g>` elements

SVG `<g>` elements with `phx-click` are interactive but don't naturally receive
keyboard focus. Adding `focus-visible:ring-*` to them does nothing without
`tabindex="0"` and `role="button"`. If the user asks for keyboard nav on SVG
nodes, that's a separate accessibility task — don't half-implement it. For
hover-only feedback on SVG nodes, `transition-transform duration-150` +
`hover:opacity-80` is sufficient.

### Pitfall: subagent audit-only completion (iteration limit)

When a subagent is dispatched to "audit and fix" micro-interactions across
multiple files, it may exhaust its tool-calling iteration limit during the
read phase and return a summary that is a **plan** (tables of needed changes)
rather than a **report** (diffs applied). Detect this by checking `git status`
— if no files were modified, the subagent did the analysis but not the edits.

Recovery: read the subagent's findings, apply the patches yourself, compile,
and commit. This is faster than re-dispatching because the analysis is already
done. To prevent: split large audit tasks into per-file tasks, or instruct
the agent to "patch as you go, don't read everything first."

## App shell / sidebar modernization pattern

When the user asks to "modernize the app shell", "polish the sidebar", or make
the layout look like a "professional personal-management / knowledge app"
(Notion, Linear, Reflect, Capacities vibes), the target is `layouts.ex` —
specifically the `app/1` function component and its sub-components
(`sidebar_nav/1`, `nav_link/1`, `context_selector/1`, `user_footer/1`,
`theme_toggle/1`). This is a distinct class of refactor from dashboard/card
polish: it's the persistent chrome, not page content.

### Layout invariants you MUST preserve

- `flex h-screen` root + `w-64 shrink-0` aside — keep the width, keep `shrink-0`.
- Main wrapper's `overflow-y-auto` — kanban pages and full-viewport boards
  depend on the wrapper scrolling, not the page. Do NOT change to
  `overflow-hidden` or move scroll responsibility.
- `flex-1 ... flex flex-col w-full` on the main wrapper — keeps LiveView
  children filling width and stacking vertically.
- All `attr` declarations, `assign`, form `action={~p"/..."}` / `method=`,
  `onchange="this.form.submit()"`, `phx-click`, `phx-value-*`,
  `data-phx-*` attributes — these are functional contracts, not visual.
  Polish classes only.
- `id="context-selector"` on the `<select>` — `app.js` keyboard shortcut
  (⌘⇧C) focuses it by ID. Renaming breaks the shortcut.
- `<kbd>` with the literal `⌘K` text — `app.js` matches the text to bind
  the command palette opener. Don't translate or change the symbol.
- `live_component` for the command palette, `flash_group` — leave the calls
  and their attr passing alone.

### Visual polish targets (modern PM/knowledge-app aesthetic)

| Area | Pattern |
|---|---|
| **Aside shell** | `bg-base-100` (cleaner than `base-200/50`), `border-r border-base-300/60` (subtler), keep `flex flex-col` |
| **Logo area** | Subtle brand treatment: `hero-cube-transparent` in `text-primary`, `text-lg font-bold tracking-tight`, hover `opacity-80`, `transition-colors duration-150`. Don't over-design — a wordmark + icon is enough. |
| **Search input** | Pill `rounded-lg`, `bg-base-200/50`, `border-base-300/60`, `pl-8 pr-12 py-1.5 text-sm`, icon `absolute left-2.5 top-2.5 size-4 text-base-content/50`, kbd `absolute right-2.5 top-2 text-[10px] font-mono bg-base-300/60 text-base-content/50 rounded-md px-1.5 py-0.5 border border-base-300/60` |
| **Nav items (active)** | `bg-primary/10 text-primary font-medium` + `border-l-2 border-primary` (left accent), `pl-2.5 pr-2` (indent to make room for accent) |
| **Nav items (inactive)** | `text-base-content/80 hover:bg-base-200 hover:text-base-content`, `pl-3 pr-2` (no indent when no accent) |
| **Nav micro-interaction** | `transition-all duration-150 hover:translate-x-0.5` — subtle 2px right-shift on hover. Use `transition-all` (not `transition-colors`) so the transform animates too. |
| **Group labels** | Smaller/subtler: `text-[11px] font-medium uppercase tracking-wider text-base-content/40` (down from `text-xs ... /50`). The `text-[11px]` arbitrary value is the key — `text-xs` is 12px and reads too prominent for a label. |
| **Badges (count pills)** | `ml-auto text-[11px] font-medium px-1.5 py-0.5 rounded-full bg-base-300/70 text-base-content/60` — `rounded-full` (not `rounded-md`) for the pill look, `/70` opacity so it recedes. |
| **Context selector** | Wrap `<select>` in a `relative` div with a `hero-chevron-down` icon `absolute right-2.5 top-1/2 -translate-y-1/2 size-4 text-base-content/50 pointer-events-none`. Select: `appearance-none pr-8 rounded-lg border-base-300/60 bg-base-100`. The chevron makes it read as a modern workspace switcher. |
| **User footer** | Avatar circle: `size-7 rounded-full bg-primary/15 text-primary font-semibold flex items-center justify-center text-sm` showing `String.first(@current_user)`. Username in `text-sm text-base-content/70`. Logout as icon button: `p-1.5 rounded-md hover:bg-base-300 transition-colors duration-150` (NOT `btn btn-ghost btn-xs` — see pitfall). |
| **Theme toggle** | Keep functionality (`phx-click={JS.dispatch("phx:set-theme")}`, `data-phx-theme` values). Only tidy spacing/padding. The sliding-indicator pattern is already good. |
| **Main wrapper polish** | `bg-base-100` on the main `<div>` — gives content area a clean surface. Do NOT add a top header bar inside it; the user explicitly rejected that. |

### The "no chrome added" rule

App-shell modernization is *polish*, not *addition*. Do not introduce a new
top header bar, breadcrumb strip, or command bar inside the main content area
unless the user explicitly asks. The sidebar gets richer; the main area stays
a clean scroll container. Adding chrome breaks full-viewport pages (kanban,
graph, dashboards) that assume the wrapper is a pure scroll surface.

### Sidebar nav active-state contract

The `nav_link/1` component receives `active={@active == item.key}`. The
active styling must use BOTH a soft primary background AND a left accent —
either alone reads weak. The pattern:

```heex
<a class={[
  "flex items-center gap-2 py-1.5 rounded-lg text-sm transition-all duration-150",
  "focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none",
  @active && "bg-primary/10 text-primary font-medium border-l-2 border-primary pl-2.5 pr-2",
  !@active && "text-base-content/80 hover:bg-base-200 hover:text-base-content pl-3 pr-2 hover:translate-x-0.5"
]}>
```

Note the `pl-2.5` (active) vs `pl-3` (inactive) — the 2px difference makes
room for the `border-l-2` so the text doesn't shift when activating. Without
this, toggling active state causes a visible jump.

See `references/app-shell-sidebar-patterns.md` for the full worked example
of a modernized `layouts.ex` (logo, search, nav, context selector, user
footer, theme toggle) with all class lists spelled out.

Álvaro's sidebar group preference: Artifacts and Comparisons belong in the
"Knowledge" group alongside Notes, Concepts, Entities, References, and
Collections — NOT in a separate "Outputs" group. The "Outputs" section was
removed entirely.

## Render-time lookup pattern (when assigns are constrained)

When a task says "keep all handlers/assigns/form logic identical" but a new
display field requires data not in assigns (e.g. a "page count" on a list of
entities that comes from a separate grouped query), you CANNOT add a new assign
in `mount/3`. The pattern: introduce a private helper that issues ONE query per
render, zips the result with the existing list assign, and feeds the pairs
into the `:for` via tuple destructuring.

```elixir
# In the LiveView template:
<.context_card
  :for={{ctx, count} <- contexts_with_counts(@contexts)}
  ctx={ctx}
  page_count={count}
  ...
/>

# Private helper — one grouped query, zipped with the contexts list
defp contexts_with_counts(contexts) do
  counts = Brain.page_counts_by_context()  # returns %{context_id => count}
  Enum.map(contexts, fn ctx ->
    {ctx, Map.get(counts, ctx.id, 0)}
  end)
end
```

Why this is safe:
- The existing `@contexts` assign is unchanged — handlers stay identical.
- ONE grouped query per render (not per item) — scales to N contexts with a
  single DB round-trip.
- The helper is a pure function of the existing assign — no state, no
  LiveView lifecycle coupling.
- Render-time DB calls are normally discouraged, but here it's the only way
  to honor the "assigns identical" constraint while adding a derived display
  field. Acceptable for small lists (a handful of contexts); if the list
  grows large or the query is expensive, push back on the constraint and move
  the lookup into `mount/3` as a proper assign.

### CRITICAL: do NOT call the lookup inside the `:for` directly

The wrong form calls the query function once PER ITEM:

```elixir
# WRONG — N queries for N contexts (N+1 anti-pattern)
<.context_card
  :for={ctx <- @contexts}
  ctx={ctx}
  page_count={page_count_for(ctx)}   # calls Brain.page_counts_by_context/0 per ctx
/>
```

`page_count_for/1` calls `Brain.page_counts_by_context/0` on every invocation.
With N contexts, this issues the same grouped query N times. The query itself
is small, so it won't crash — it'll just silently hammer the DB on every render
and every LiveView diff. Always batch: call the bulk lookup ONCE in a helper
that returns pairs, then destructure `{ctx, count}` in the `:for`.

## Common Pitfalls

- **Unified tab bar:** when a shared `page_detail` has Content+Graph client-side tabs and LiveViews have their own server-side tabs, use `:extra_tabs`/`:extra_content` slots to unify into one bar. See `references/unified-tab-bar-architecture.md`. Tab order: Content → [type-specific] → Related → Graph. Panels must be inside the main content column, not after the sidebar.

- **NEVER retry a tool call that returned 0 results or a "BLOCKED: already
  searched" error.** The single biggest failure mode in this skill class is
  the discovery-phase tool loop: you `search_files` for a class name
  (`btn-primary`, `\.btn\b`, etc.), get 0 matches, and "try again" with the
  same query. The tool emits escalating warnings
  (`idempotent_no_progress_warning`, `repeated_exact_failure_warning`,
  `BLOCKED: You have run this exact search N times in a row`). IGNORE none of
  them — each warning is a hard signal to STOP and change strategy, not to
  retry. If `search_files` returns 0, the class doesn't exist in that scope;
  proceed with the `read_file` of `app.css` you already did. If you need to
  confirm a class exists, read the file once — don't grep it repeatedly.
  This burned an entire session's iteration budget on a single repeated
  search_files call.
- **Do not fabricate AGENTS.md / convention violations to justify changes.**
  If you haven't read AGENTS.md this session, you cannot claim "X violates
  AGENTS.md". daisyUI component classes (`btn`, `btn-ghost`, `btn-xs`,
  `card`, `card-body`, `modal`) MAY be allowed by the project — check before
  asserting they're forbidden. If you want to replace them with plain
  Tailwind utilities for visual reasons, say "for finer hover/spacing
  control" — don't invent a policy violation that doesn't exist.
- **Never use `hover:surface-3`** — custom CSS classes cannot take Tailwind
  variant prefixes. Use `.lift` for hover-elevation or `hover:bg-base-200`
  for hover-color. See the CRITICAL PITFALL section above.
- **Do not nest `.surface-2` inside `.surface-2`** — the inner surface
  becomes invisible (same background as parent). Use `hover:bg-base-200` or
  `rounded-lg` for items inside a surface container.
- **Do not use `@apply` in CSS** — AGENTS.md forbids it. Custom classes must
  be written as plain CSS properties.
- **Always use `<.icon>` component** for icons — never `Heroicons` modules.
- **Keep `mount/3` and `handle_event/3` untouched** when the task is
  visual-only. Only modify `render/1` and internal function components.
  Colocated JS hooks (`<script :type={Phoenix.LiveView.ColocatedHook}>`)
  may be extended for visual feedback, but the `pushEvent` calls and
  `phx-value-*` attributes must remain unchanged.
- **`tabular-nums`** should be on any numeric display (counts, metrics) so
  digits align in columns and don't jitter when values change.
- **daisyUI `/15` opacity** creates a subtle tint — use it for badge
  backgrounds, not for large surface areas where it's too faint.
- **HEEx cannot nest triple-quoted heredocs or multiline sigils in component attrs.** Inside a `~H"""` template, writing `code={"""..."""}` or `code={~S"""..."""}` or `code={~s(...multiline...)}` breaks the tokenizer with `MismatchedDelimiterError` or `SyntaxError` pointing at a line *inside* the string (the parser thinks the inner `"""` closes the template). The compiler error is misleading — it blames the closing delimiter of the outer `~H`. **Fix: move the multiline string to a module attribute** in a plain `.ex` module (e.g. `MyAppWeb.DocsContent` with `@sample """..."""` + a getter function) and reference it with `code={MyAppWeb.DocsContent.sample()}`. Single-line strings and strings without `"""` sequences are fine inline. This bit hard when building `code_block` components for docs pages.
- **Custom `data-*` attributes don't pass through `<.icon>` (CoreComponents.icon/1)** — the compiler warns "undefined attribute" under `--warnings-as-errors`. Wrap the icon in a `<span data-copy-icon>` instead of putting `data-copy-icon` on `<.icon>` itself.
- **String-keyed maps in `:for` comprehensions crash LiveView diffs** with `** (KeyError) key :method not found in %{"method" => ...}` at `Phoenix.LiveView.Diff.process_keyed/5` — only when the diff re-renders (e.g. on tab switch), not on first render, so it slips past `mix compile` and plain `live/2` assertions. If a template reads `item.field` with dot access, the data list must use atom keys: convert `%{"method" => m}` → `%{method: m}`.
- **When migrating kanban/status columns from hardcoded colors**, the
  "neutral" state (backlog, cancelled-if-grey) should use `bg-base-300
  text-base-content/70`, not a semantic color.
- **Cross-file kanban status color consistency trumps semantic-token purity.**
  When a *summary* widget (e.g. a todos-by-status mini-kanban on a dashboard)
  mirrors a *full* board that already uses raw Tailwind palette colors
  (`bg-blue-500/20 text-blue-700` in `todo_live.ex`), the summary MUST mirror
  the board's palette, not impose daisyUI semantic tokens on its own. A user
  glancing from the dashboard summary to the full board should see the same
  blue/amber/purple/green/red mapping — not "info/warning/accent/success/error"
  on one and raw `blue-500`/`amber-500` on the other. The summary's `@kanban_columns`
  attribute should be a copy (or shared import) of the board's, including the
  dark-theme variant: `bg-blue-500/15 text-blue-600 dark:text-blue-400`. The
  `/15` opacity (vs the board's `/20`) reads as a softer tint appropriate for
  the smaller summary badges, but the *hue* must match. This is the one case
  where you deliberately keep hardcoded palette colors rather than migrating
  to `bg-info/15 text-info` — visual consistency across the two surfaces
  outweighs the design-system purity rule. Document the shared-source-of-truth
  in a comment if both attributes exist independently.
- **Long option texts overflow narrow selects (sidebars).** A `w-full select`
  inside a `w-80` attributes sidebar overflows when an option title is long
  ("Escribir libro sobre Segundo Cerebro"). Two-part fix, both in shared
  components so it applies app-wide: (1) add `truncate` to the default select
  class in `CoreComponents.input` (`"w-full select truncate"`) — native
  `<select>` only truncates the CLOSED control; the dropdown still shows full
  text, which is what you want; (2) in the sidebar's meta-fields component,
  use `grid grid-cols-1 gap-4`, NOT `grid-cols-2` — at 320px wide, 2-col
  selects render at ~140px and squash any real content. Verified in browser:
  `truncate` on the select + 1-col grid keeps long titles readable.
- **Flipping a UI default (2D→3D, list→grid, collapsed→expanded) breaks the
  existing test that asserted the old default.** When Álvaro asks to change a
  default view mode, grep the test suite for the old default's hook/marker
  FIRST and rewrite the test to assert the new default + the inverse toggle:
  ```bash
  grep -rn 'GraphPanZoom\|view_mode' test/**/*_test.exs   # before flipping the default
  ```
  The test rewrite should exercise BOTH directions (default renders X → toggle to Y → toggle back to X) so the toggle handler stays covered. Compile-only verification misses this — the test fails at assertion time, not compile time.
- **Moving a feature between tab levels (second-row → first-row) is a slot
  change, not a page rewrite.** If the detail page has a shared first-row tab
  bar (JS-command panels in the shared component) and per-LiveView second-row
  tabs injected via a slot, promote the tab by adding a dedicated slot to the
  shared component + a panel entry — then REMOVE the tab from each LiveView's
  second-row list and REVERT any `active_tab` default that pointed at it (a
  default `active_tab: "graph"` when "graph" no longer exists in the second-row
  list renders a blank panel). Full recipe in `phoenix-liveview-debugging` →
  "Two tab rows on the same detail page".
- **Ecto schema fields are never nil** — writing `item.tags || []` on a
  struct field that the schema defines as `field :tags, {:array, :string},
  default: []` triggers a compiler warning under `--warnings-as-errors`
  ("the right-hand side of || will never be executed"). Use `item.tags`
  directly, or `item.tags != []` for the presence check. This applies to
  any Ecto field with a non-nil default.
- **`patch` tool fails on HEEx string interpolation** — when old_string
  contains HEEx expressions like `{"..." <> variable}`, the patch tool's
  escape-drift detection can reject the match. Use `write_file` to rewrite
  the entire file instead. This is a tool limitation, not a code issue.
- **Strip HTML comments from HEEx** — parallel subagents (or a previous pass)
  may leave `<!-- comment -->` annotations inside HEEx templates. These
  render as real DOM nodes and clutter the output. Remove them; use `<%!-- --%>`
  if a server-side comment is truly needed (it won't render to the client).
- **Verify data availability before adding fields to render** — when a design
  spec asks you to display a field (e.g. "tipo + fecha en .text-caption"),
  trace the data source first: check what the context/brain module actually
  returns in its normalized result map. If the field isn't in the returned
  struct/map and the source file is out of scope (not in the allowed-files
  list), omit it rather than inventing data or modifying unauthorized files.
  Use `search_files` to find the function definition and read its return
  shape before committing to rendering a field.
- **`write_file` does not unescape JSON-style `\"` sequences** — when writing
  Elixir source via `write_file`, pass raw string literals (single `"`), not
  escaped `\"` sequences (which come naturally if you're mentally in JSON
  mode). The tool writes content verbatim, so `def handle_event(\"save_page\"…`
  lands in the file as a literal backslash-quote, which is invalid Elixir and
  fails compilation with a confusing syntax error. The same applies to
  `~s(...)` sigil contents. Always preview a few lines after a large
  `write_file` to confirm quotes are clean before compiling.
- **`patch` against a file modified by a concurrent sibling subagent** — the
  `patch` tool may report `"_warning": "...modified by sibling subagent..."`.
  The patch can still succeed if your `old_string` matches the pre-modification
  content (the fuzzy matcher handles minor drift). After a sibling-warning
  patch, ALWAYS re-read the file with `read_file` to confirm your change landed
  correctly and the sibling's changes weren't clobbered. If the sibling's
  change conflicts with yours, re-read FIRST, then re-patch against the merged
  content. In this skill's domain (HEEx templates + `page_meta.ex`), a
  sibling adding a required `attr` (e.g. `context_id` on `<.meta_fields>`)
  surfaces as a `missing required attribute` compile warning — fix it by
  passing the attr from your caller, not by editing the shared component.
