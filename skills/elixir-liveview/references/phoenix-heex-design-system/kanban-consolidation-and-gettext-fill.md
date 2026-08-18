# Kanban/list consolidation + gettext-fill recipes

Session-specific detail from the my_app UX simplification waves (jul 2026).
These are reproducible recipes, not one-off narratives.

## 1. Consolidating a duplicated board/list into board + list

When the same entity renders as a kanban board in TWO places (e.g. `/todos`
and `/kanban`), the consolidation pattern that worked:

1. **Canonical board** keeps: drag-drop hook, quick-add inline form, filters.
   Quick-add must respect active filters — when a filter select has exactly
   one real slug selected (not All/None), pre-set that link in the created
   entity's meta (e.g. filter `goal=foo` → `meta["goal_slug"]="foo"`).
2. **List view** becomes rows: title + tags (flex-1), priority badge, due
   date, and per-row quick status-change buttons (one small button per
   kanban column, active state highlighted). Row click navigates to show.
3. **Dead-code sweep after removing the board markup** from the list view —
   grep for ALL of these, they linger: the colocated `<script
   :type={Phoenix.LiveView.ColocatedHook}>` block, `handle_event` clauses for
   drag (`move_todo`, `node_click`, `node_drag`), quick-add assigns
   (`show_form`, `form`, `goal_options`, `priority_options`), helpers only the
   quick-add used (`maybe_put`), and now-unused module attributes (`@priorities`
   — unused attr warns under `--warnings-as-errors`).
4. **PubSub reload handler**: when the index has both an active list AND an
   archived list, the `handle_info({:page_changed, ...})` reload must refresh
   BOTH assigns. Refreshing only the active list leaves archived counts stale
   — a LiveView test caught this (archived a todo externally, archived toggle
   still showed 0).

## 2. Slug de-duplication extraction

Multiple LiveViews had private `unique_slug/2`, `ensure_unique_slug/3`,
`slugify/1` copies. The repo already had `my_app.Slug.generate/3` (title,
context_id, fallback_type). Recipe: delete the private copies, call
`my_app.Slug.generate(title, context.id, "todo")`. Watch for subtle behavior
diffs — the private `slugify` did NOT Unicode-normalize; the shared one does
(NFD + strip non-ASCII). Prefer the shared one (handles Spanish titles).

## 3. Filling empty gettext msgstr in bulk (es-first app)

After a gettext sweep + `mix gettext.extract --merge`:

```bash
# Count remaining untranslated (exclude the header msgid ""):
awk '/^msgid/{id=$0} /^msgstr ""$/{print id}' priv/gettext/es/LC_MESSAGES/default.po | grep -cv '^msgid ""$'
```

126 empties is normal after a big sweep. Delegate the fill to a subagent
with these rules: preserve `%{var}` tokens verbatim, informal-neutral app
voice, don't touch msgids that already have msgstr, don't touch `en/*.po`.

Pitfall that actually happened: a subagent "translated" an existing
Spanish msgid INTO English (`gettext("Más opciones")` → `gettext("More
options")`) — check `git diff` on the source files for msgids being
*changed*, not just wrapped. If the msgid was already Spanish with a
Spanish msgstr, reverting the source is cheaper than reworking the po file.

Another one: a test asserting `html =~ "Más opciones"` failed after the
sweep because the app locale is `es` and the render shows the msgstr —
tests must assert via `Gettext.gettext(DranWeb.Gettext, msgid)` (the
`t(msgid)` helper pattern used in settings_live_test.exs).

## 4. Settings page slimming (thresholds behind "Avanzado")

Pattern: split the form keys into `@brain_keys` (visible: agent_max_pages,
daily_note_enabled) and `@advanced_keys` (semantic thresholds). The form
assigns and save handler use `@brain_keys ++ @advanced_keys`; the render
puts advanced inputs inside a `<details class="group">` with the standard
chevron idiom. Removing dead knobs from the FORM only (agent_max_sources,
research_lang still exist in my_app.Settings for other consumers) — don't
delete the settings keys themselves. Update the settings test to assert
the removed names are GONE (`refute html =~ "agent_max_sources"`) and the
details toggle label is present.

## 5. 3D canvas theme-aware background (Three.js)

Hardcoded `new THREE.Color(0x0f172a)` breaks light mode. Fix in the JS
hook: read the CSS custom property from `:root`, round-trip through a
throwaway DOM element so the browser resolves oklch()/color-mix() to rgb,
feed that to THREE.Color:

```js
readThemeColor(varName, fallback) {
  try {
    const raw = getComputedStyle(document.documentElement).getPropertyValue(varName).trim()
    if (!raw) return fallback
    const probe = document.createElement("div")
    probe.style.color = raw
    probe.style.display = "none"
    document.body.appendChild(probe)
    const resolved = getComputedStyle(probe).color
    document.body.removeChild(probe)
    if (!resolved) return fallback
    return new THREE.Color(resolved)
  } catch { return fallback }
}
// usage: this.scene.background = new THREE.Color(this.readThemeColor("--color-base-300", "#0f172a"))
```

The DOM-probe round-trip is the load-bearing trick — CSS variables in
Tailwind v4 are often oklch() which THREE.Color can't parse directly.
