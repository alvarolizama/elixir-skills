# Collapsible Sidebar Panels (details/summary pattern)

Álvaro's preference: ALL sidebar panels in the page detail view should be
collapsible `<details>/<summary>` elements, all starting collapsed (no `open`
attribute). This applies to: Metadata, Links (backlinks), Changelog, and
Activity panels.

## The pattern

```heex
<details class="group surface-2 rounded-lg p-4">
  <summary class="flex items-center gap-2 cursor-pointer select-none">
    <.icon
      name="hero-chevron-right"
      class="size-4 shrink-0 text-base-content/40 transition-transform duration-150 group-open:rotate-90"
    />
    <h3 class="text-caption font-semibold text-base-content/60 uppercase tracking-wider">
      {gettext("Metadata")}
    </h3>
  </summary>
  <div class="divide-y divide-base-300/50 mt-2">
    <!-- panel content -->
  </div>
</details>
```

## Key points

- **No `open` attribute** — all panels start collapsed. User explicitly
  asked for this ("colapsar todos").
- `group` class on `<details>` + `group-open:rotate-90` on the chevron icon
  gives the expand/collapse arrow rotation without JS.
- `surface-2 rounded-lg p-4` — same surface styling as non-collapsible
  panels had before, so the visual weight is unchanged.
- When converting a component that HAD internal `<details>` (like the
  backlinks section), flatten the internal details into plain divs with
  headers — nested `<details>` inside `<details>` is confusing UX.
- `summary` needs `cursor-pointer select-none` for the right cursor and
  to prevent text selection on rapid toggling.
- **All panels start collapsed** — no `open` attribute on any `<details>`.
  This includes Metadata, Links, Changelog, and Activity. User explicitly
  asked for this ("dolapsar todos").

## Converting from plain div panels

Before (non-collapsible):

```heex
<div class="surface-2 rounded-lg p-4">
  <h3 class="text-caption font-semibold text-base-content/60 uppercase tracking-wider mb-2">
    {gettext("Changelog")}
  </h3>
  <div class="space-y-1">
    <!-- content -->
  </div>
</div>
```

After (collapsible, collapsed by default):

```heex
<details class="group surface-2 rounded-lg p-4">
  <summary class="flex items-center gap-2 cursor-pointer select-none">
    <.icon
      name="hero-chevron-right"
      class="size-4 shrink-0 text-base-content/40 transition-transform duration-150 group-open:rotate-90"
    />
    <h3 class="text-caption font-semibold text-base-content/60 uppercase tracking-wider">
      {gettext("Changelog")}
    </h3>
  </summary>
  <div class="space-y-1 mt-2">
    <!-- content -->
  </div>
</details>
```

Changes: `<div>` → `<details>`, `<h3>` wrapped in `<summary>` with chevron
icon, `mb-2` on h3 → `mt-2` on the content div (spacing moves from below
the header to above the content).

## Flattening nested details

When a panel already contained its own `<details>` (e.g. backlinks section
had "Linked from" and "Links to" as separate `<details>`), and you're wrapping
the whole thing in an outer `<details>`, flatten the inner ones to plain divs
with `<h3>` headers. Nested `<details>` inside `<details>` is confusing —
clicking the outer summary can collapse inner content unpredictably.

Before (nested details):

```heex
<details class="group surface-2 rounded-lg p-4" open>
  <summary>...</summary>
  <details class="group" open={@inbound_count > 0}>
    <summary>Linked from ({@inbound_count})</summary>
    <!-- inbound links -->
  </details>
  <details :if={@outbound_count > 0} class="group mt-4">
    <summary>Links to ({@outbound_count})</summary>
    <!-- outbound links -->
  </details>
</details>
```

After (flattened):

```heex
<details class="group surface-2 rounded-lg p-4">
  <summary>...</summary>
  <div class="mt-2">
    <h3 class="text-caption font-semibold text-base-content/60 uppercase tracking-wider mb-2">
      {gettext("Linked from")} <span class="ml-1 text-base-content/40">({@inbound_count})</span>
    </h3>
    <div class="space-y-2">
      <!-- inbound links -->
    </div>
  </div>
  <div :if={@outbound_count > 0} class="mt-4">
    <h3 class="text-caption font-semibold text-base-content/60 uppercase tracking-wider mb-2">
      {gettext("Links to")} <span class="ml-1 text-base-content/40">({@outbound_count})</span>
    </h3>
    <div class="space-y-2">
      <!-- outbound links -->
    </div>
  </div>
</details>
```
