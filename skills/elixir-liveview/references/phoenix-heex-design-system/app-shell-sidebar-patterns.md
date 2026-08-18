# App Shell / Sidebar Modernization Patterns

Worked reference for modernizing `lib/<app>_web/components/layouts.ex` into a
professional personal-management / knowledge-app aesthetic (Notion, Linear,
Reflect, Capacities style). All patterns preserve functional contracts —
`attr` declarations, form actions, `phx-*` handlers, IDs that JS hooks into.

## Layout invariants (DO NOT CHANGE)

```heex
<div class="flex h-screen bg-base-100 text-base-content">
  <aside class="w-64 shrink-0 ... flex flex-col">
    <!-- logo, search, nav, footer -->
  </aside>
  <div class="flex-1 overflow-y-auto flex flex-col w-full">
    {render_slot(@inner_block)}
  </div>
  <.live_component module={...CommandPalette} id="command-palette" ... />
  <.flash_group flash={@flash} />
</div>
```

- `flex h-screen` root — full viewport height.
- `w-64 shrink-0` aside — fixed sidebar width, doesn't shrink.
- `overflow-y-auto` on main wrapper — kanban/graph/dashboard pages depend
  on the wrapper scrolling. Moving this to `overflow-hidden` or per-page
  breaks full-viewport layouts.
- `live_component` + `flash_group` outside `<main>` — they overlay.

## Sidebar polish (function-by-function)

### Logo + brand area

```heex
<div class="px-4 py-3 border-b border-base-300/60">
  <div class="flex items-center gap-2.5">
    <a href={~p"/"} class="flex items-center gap-2 shrink-0 transition-colors duration-150 hover:opacity-80 focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none rounded">
      <.icon name="hero-cube-transparent" class="size-5 text-primary" />
      <span class="text-lg font-bold tracking-tight">my_app</span>
    </a>
    <.context_selector context_slug={@context_slug} contexts={@contexts} page_counts={@page_counts} />
  </div>
</div>
```

- `border-base-300/60` — subtler than full `border-base-300`.
- `px-4 py-3` — slightly tighter than `p-4` for a header feel.
- Logo icon in `text-primary` for brand accent.

### Search input with kbd hint

```heex
<div class="px-3 py-2.5 border-b border-base-300/60">
  <form action={~p"/search"} method="get" class="relative">
    <.icon name="hero-magnifying-glass" class="absolute left-2.5 top-2.5 size-4 text-base-content/50 pointer-events-none" />
    <input
      type="text"
      name="q"
      placeholder={gettext("Search...")}
      class="w-full pl-8 pr-12 py-1.5 text-sm rounded-lg border border-base-300/60 bg-base-200/50 transition-colors duration-150 focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary focus-visible:ring-2 focus-visible:ring-primary"
    />
    <kbd class="absolute right-2.5 top-2 text-[10px] font-mono bg-base-300/60 text-base-content/50 rounded-md px-1.5 py-0.5 border border-base-300/60 pointer-events-none">
      ⌘K
    </kbd>
  </form>
</div>
```

Key points:
- `bg-base-200/50` — subtle tint so input reads as recessed.
- `border-base-300/60` — softer than full border.
- `focus:border-primary` + `focus:ring-1` — border tints primary on focus.
- kbd uses `text-[10px]` (arbitrary value) + `bg-base-300/60` — reads as a
  physical key cap, not a text label.
- `⌘K` literal text — `app.js` matches this to bind the command palette
  opener. DO NOT translate or change the symbol.
- `pointer-events-none` on both icon and kbd — they're decorative; clicks
  pass through to the input.

### Nav items (nav_link/1)

```heex
def nav_link(assigns) do
  ~H"""
  <a
    href={@path}
    class={[
      "flex items-center gap-2 py-1.5 rounded-lg text-sm transition-all duration-150",
      "focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none",
      @active && "bg-primary/10 text-primary font-medium border-l-2 border-primary pl-2.5 pr-2",
      !@active && "text-base-content/80 hover:bg-base-200 hover:text-base-content pl-3 pr-2 hover:translate-x-0.5"
    ]}
  >
    <.icon name={@icon} class="size-4 shrink-0" />
    <span>{@label}</span>
    <span
      :if={@badge && @badge > 0}
      class="ml-auto text-[11px] font-medium px-1.5 py-0.5 rounded-full bg-base-300/70 text-base-content/60"
    >
      {@badge}
    </span>
  </a>
  """
end
```

Key points:
- `transition-all duration-150` (not `transition-colors`) — needed so the
  `hover:translate-x-0.5` transform animates.
- Active: `bg-primary/10 text-primary font-medium` (soft tint + primary text)
  + `border-l-2 border-primary` (left accent).
- `pl-2.5` (active) vs `pl-3` (inactive) — the 2px difference makes room
  for the `border-l-2` so text doesn't shift when toggling active.
- `hover:translate-x-0.5` — 2px right-shift on hover. Subtle micro-interaction.
- Badge: `rounded-full` (pill), `text-[11px]`, `bg-base-300/70` (recedes).
  Not `rounded-md` (too boxy for a count pill).

### Group labels (sidebar_nav/1 details summary)

```heex
<summary class="flex items-center gap-1 px-2 pt-2 pb-1 text-[11px] font-medium uppercase tracking-wider text-base-content/40 cursor-pointer select-none transition-colors duration-150 hover:text-base-content/60 focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none rounded">
  <.icon name="hero-chevron-right" class="size-3.5 shrink-0 transition-transform duration-150 group-open:rotate-90" />
  {group.label}
</summary>
```

Key points:
- `text-[11px]` — arbitrary value, down from `text-xs` (12px). Reads as a
  label, not a heading.
- `text-base-content/40` (down from `/50`) — recedes more.
- `hover:text-base-content/60` — subtle lift on hover.

### Context selector (workspace switcher)

```heex
def context_selector(assigns) do
  ~H"""
  <div :if={length(@contexts) > 0} class="flex-1 relative">
    <form action={~p"/context"} method="post">
      <input type="hidden" name="_csrf_token" value={get_csrf_token()} />
      <select
        id="context-selector"
        name="context_slug"
        onchange="this.form.submit()"
        class="w-full appearance-none pl-2.5 pr-8 py-1.5 text-sm rounded-lg border border-base-300/60 bg-base-100 transition-colors duration-150 focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary focus-visible:ring-2 focus-visible:ring-primary cursor-pointer"
      >
        <option :for={ctx <- @contexts} value={ctx.slug} selected={ctx.slug == @context_slug}>
          {ctx.name} ({Map.get(@page_counts, ctx.id, 0)})
        </option>
      </select>
      <.icon
        name="hero-chevron-down"
        class="absolute right-2.5 top-1/2 -translate-y-1/2 size-4 text-base-content/50 pointer-events-none"
      />
    </form>
  </div>
  """
end
```

Key points:
- `appearance-none` — strips native select arrow so we can overlay our own.
- `pr-8` — leaves room for the chevron.
- `hero-chevron-down` icon `absolute right-2.5 top-1/2 -translate-y-1/2`
  — vertically centered chevron, reads as a modern workspace switcher.
- `pointer-events-none` on icon — clicks go to the select.
- `id="context-selector"` — `app.js` ⌘⇧C shortcut focuses by this ID.
  DO NOT rename.
- `onchange="this.form.submit()"` — preserved functional contract.

### User footer (avatar + logout)

```heex
def user_footer(assigns) do
  ~H"""
  <div :if={@current_user} class="flex items-center justify-between gap-2">
    <div class="flex items-center gap-2 min-w-0">
      <span class="size-7 rounded-full bg-primary/15 text-primary font-semibold flex items-center justify-center text-sm shrink-0">
        {String.first(@current_user) |> String.upcase()}
      </span>
      <span class="text-sm text-base-content/70 truncate">
        {@current_user}
      </span>
    </div>
    <form action={~p"/session"} method="post" onsubmit="this.method='delete'; this.submit(); return false;">
      <input type="hidden" name="_csrf_token" value={get_csrf_token()} />
      <button
        type="submit"
        class="p-1.5 rounded-md text-base-content/60 hover:bg-base-300 hover:text-base-content transition-colors duration-150 focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none"
        title={gettext("Logout")}
        aria-label={gettext("Logout")}
      >
        <.icon name="hero-arrow-right-on-rectangle" class="size-4" />
      </button>
    </form>
  </div>
  """
end
```

Key points:
- Avatar: `size-7 rounded-full bg-primary/15 text-primary font-semibold` —
  first letter of username, uppercase. `size-7` (28px) is the sweet spot
  for sidebar footer.
- `String.first(@current_user) |> String.upcase()` — handles nil safely
  because the `:if={@current_user}` guard already prevents render.
- `truncate` on username span — long names don't break layout.
- Logout button: `p-1.5 rounded-md` (NOT `btn btn-ghost btn-xs`) — plain
  Tailwind gives finer control over hover/spacing than daisyUI's btn.
- `aria-label` added alongside `title` for screen reader clarity.
- `onsubmit="this.method='delete'; ..."` — preserved functional contract
  (form POSTs as DELETE for the session destroy route).

### Theme toggle (spacing tidy only)

Keep the existing sliding-indicator pattern. Only adjust:
- Container padding: `p-0.5` (was `p-2` on buttons — too much).
- Button sizing: keep `w-1/3` but reduce `p-2` → `p-1.5`.
- Icon opacity: `opacity-60` default, `hover:opacity-100` (was `opacity-75`).
- Don't touch `phx-click={JS.dispatch("phx:set-theme")}` or
  `data-phx-theme` values — they're the functional contract.

## The "no chrome added" rule

App-shell modernization is polish, not addition. The user explicitly rejected
adding a top header bar inside the main content area. Reasons:

1. Full-viewport pages (kanban, graph, dashboards) assume the main wrapper
   is a pure scroll container. Adding a header bar above it breaks
   `h-screen` / `h-[calc(100vh-Nrem)]` height math.
2. The sidebar already carries brand + context + search + nav. A duplicate
   header is redundant chrome.
3. Personal-knowledge apps (Reflect, Capacities, Obsidian) keep the main
   area as clean as possible — the sidebar IS the chrome.

If the user later wants breadcrumbs or a page title bar, add it per-page
inside the LiveView, not in `layouts.ex`.

## What to keep identical (functional contracts)

| Element | Contract |
|---|---|
| `attr :flash, :map, required: true` | Type + required flag |
| `attr :current_scope, :map, default: nil` | Name + default |
| `attr :current_user, :string, default: nil` | Name + default |
| `attr :context_slug, :string, default: nil` | Name + default |
| `attr :contexts, :list, default: []` | Name + default |
| `attr :page_counts, :map, default: %{}` | Name + default |
| `attr :active_nav, :string, default: nil` | Name + default |
| `attr :fluid, :boolean, default: false` | Name + default |
| `slot :inner_block, required: true` | Required slot |
| `compute_counts/1` | Private function, untouched |
| `sidebar_nav/1` groups list | Item keys, labels, icons, paths, badge keys |
| `<form action={~p"/search"} method="get">` | Search form GET |
| `<form action={~p"/context"} method="post">` | Context switch POST |
| `<form action={~p"/session"} method="post" onsubmit="...">` | Logout DELETE hack |
| `id="context-selector"` | `app.js` ⌘⇧C focus target |
| `⌘K` kbd text | `app.js` command palette trigger |
| `<.live_component module={DranWeb.CommandPalette} ...>` | Palette mount |
| `<.flash_group flash={@flash} />` | Flash rendering |
| `onchange="this.form.submit()"` | Select auto-submit |
| `phx-click={JS.dispatch("phx:set-theme")}` | Theme toggle dispatch |
| `data-phx-theme="system|light|dark"` | Theme values |

## Verification

```bash
# Compile — catches syntax errors in HEEx class lists, attr mismatches
mix compile --warnings-as-errors

# Run layout-related tests if they exist
mix test test/dran_web/ 2>/dev/null || true

# Manual: start server and check
# - sidebar renders with logo, search, nav groups, footer
# - context selector dropdown opens (⌘⇧C focuses it)
# - ⌘K opens command palette
# - theme toggle switches system/light/dark
# - kanban page still scrolls (overflow-y-auto preserved)
# - active nav item shows primary tint + left accent
# - nav items shift right 2px on hover
```

If the dev server is running (can't restart), `mix compile --warnings-as-errors`
is sufficient — Phoenix's live reload will pick up the HEEx changes without
a server restart.

## Anti-pattern: the tool-loop failure mode

The discovery phase (reading `app.css`, `AGENTS.md`, searching for existing
class patterns) is where this skill class most commonly spirals. The failure
mode:

1. `search_files` for a pattern like `btn-primary|btn-ghost`.
2. Get 0 matches.
3. "Try again" with the same query — still 0.
4. The tool starts emitting warnings: `idempotent_no_progress_warning`,
   `repeated_exact_failure_warning`, `BLOCKED: You have run this exact
   search N times in a row`.
5. Ignore warnings, keep retrying — exhaust iteration budget, never edit
   the file.

Recovery rules:
- **0 matches means the class doesn't exist.** Proceed with what `read_file`
  on `app.css` already told you.
- **"BLOCKED: already searched N times" is a hard stop.** Change query or
  change strategy — never repeat.
- **Discovery is bounded.** Read `app.css` + `AGENTS.md` + the target file
  once each. That's enough. Don't grep for every class you might use —
  you already saw the full CSS file.
- **If unsure whether a class exists, read the file.** `read_file` on
  `app.css` is authoritative. `search_files` is for finding where a known
  pattern is used across many files, not for confirming a single class
  exists in one file you already read.
