# my_app i18n / Gettext Patterns

Reference for implementing internationalization (i18n) in the my_app Phoenix app
using Gettext. Covers the full workflow: extracting strings, wrapping UI text,
creating translations, and setting the default locale.

## Complete i18n workflow

```bash
# 1. Initial extract — generates priv/gettext/default.pot from existing gettext() calls
mix gettext.extract

# 2. Wrap all user-facing strings in gettext() calls in source files
#    (see "What to wrap" below)

# 3. Re-extract — picks up all newly wrapped strings into the .pot file
mix gettext.extract

# 4. Create the translation .po file for the target locale
#    priv/gettext/<locale>/LC_MESSAGES/default.po

# 5. Merge — syncs .pot → .po files for all locales
mix gettext.merge priv/gettext

# 6. Compile and test
mix compile --warnings-as-errors
PORT=4099 mix test
```

## Setting the default locale

In `lib/dran_web/gettext.ex`, add `default_locale:` to the backend options:

```elixir
defmodule DranWeb.Gettext do
  use Gettext.Backend, otp_app: :my_app, default_locale: "es"
end
```

This makes all `gettext()` calls resolve to Spanish translations by default,
without needing a `SetLocale` plug or per-request locale assignment.

## Components using `use Phoenix.Component` directly need explicit `use Gettext`

**CRITICAL gotcha:** Shared component modules that use `use Phoenix.Component`
directly — not via `use DranWeb, :html` — do NOT inherit the Gettext macros.
The `gettext/1` function will be undefined at compile time.

Affected modules in my_app:
- `lib/dran_web/components/page_components.ex`
- `lib/dran_web/components/page_list_components.ex`

**Fix:** Add `use Gettext, backend: DranWeb.Gettext` alongside `use Phoenix.Component`:

```elixir
defmodule DranWeb.PageComponents do
  use Phoenix.Component
  use Gettext, backend: DranWeb.Gettext   # ← add this
  import Phoenix.HTML, only: [raw: 1]
  import DranWeb.CoreComponents, only: [icon: 1]
  # ...
end
```

LiveView modules (`*_live.ex`) do NOT need this — they get `gettext` via
`use DranWeb, :live_view` → `html_helpers()` → `use Gettext, backend: DranWeb.Gettext`.

## Module attributes can use `gettext()` at compile time

Module attributes like `@nav_groups`, `@kanban_columns`, `@priorities`, and
`@tabs` are evaluated at compile time. Since `use Gettext` is invoked in the
LiveView module body (via the macro chain), `gettext()` calls in module
attributes work correctly:

```elixir
@kanban_columns [
  {"backlog", gettext("Backlog"), "bg-base-300"},
  {"this_week", gettext("This Week"), "bg-blue-500/20 text-blue-700"},
  # ...
]

@priorities [
  {"low", gettext("Low"), "bg-gray-100 text-gray-600"},
  {"medium", gettext("Medium"), "bg-blue-100 text-blue-700"},
  # ...
]
```

The translations are baked into the compiled `.beam` file at compile time,
not resolved at runtime. This means changing the locale at runtime will NOT
update these labels — they're fixed at compile time. For my_app this is fine
because the default locale is set statically.

## Per-type translation lookups — `case` with literal `gettext()` per branch

When you need per-type, per-key, or per-status translations (e.g. empty-state
metadata for 10 page types, status labels, etc.), you CANNOT store untranslated
strings in a module-attribute map and call `gettext()` on them later in the
template or in a lookup function. The `gettext()` macro requires literal
string arguments at compile time so it can extract msgids.

### The error

```elixir
# BAD — module attribute with raw strings
@empty_states %{
  "note" => %{title: "No notes yet", description: "Capture...", cta: "Create Note"},
  # ...
}

defp empty_state(type), do: Map.get(@empty_states, type, @default)

# In the HEEx template:
{gettext(empty_state(@page_type).title)}
# ↑ COMPILE ERROR: Gettext macros expect message keys to expand to strings at compile-time
```

### The fix — `case` with literal `gettext()` calls per branch

```elixir
defp empty_state(page_type) do
  {title, description, cta} =
    case page_type do
      "note" ->
        {gettext("No notes yet"),
         gettext("Capture your first thought, idea or journal entry."),
         gettext("Create Note")}

      "concept" ->
        {gettext("No concepts yet"),
         gettext("Define the ideas and techniques you keep coming back to."),
         gettext("Create Concept")}

      # ... one clause per type ...

      _ ->
        {gettext("No pages yet"),
         gettext("Your second brain is empty. Capture your first page."),
         gettext("Create Page")}
    end

  %{title: title, description: description, cta: cta}
end
```

Then in the template, use the pre-translated values directly (no `gettext()` wrapper):

```heex
<h3>{empty_state(@page_type).title}</h3>
<p>{empty_state(@page_type).description}</p>
```

**Key points:**
- Every `gettext("...")` call must have a literal string argument — the compiler
  and `mix gettext.extract` need to see the msgid at compile time.
- The `_` catch-all clause handles `nil` (All Pages) and any unknown type.
- The function returns translated strings, so the template does NOT wrap the
  result in `gettext()` again.
- This pattern works for any per-key lookup: page types, status labels, priority
  labels, etc. — anywhere you'd want a map but need i18n.

## What to wrap in `gettext()`

Wrap ALL user-facing strings visible in rendered HTML or flash messages:

| Category | Examples | Where |
|----------|----------|-------|
| Button labels | "Delete", "Edit", "Save", "Cancel", "Create", "Back" | `page_components.ex`, `todo_live.ex` |
| Section headers | "Metadata", "Relations", "Versions", "Activity", "Changelog" | `page_components.ex` |
| Sidebar nav labels | "Dashboard", "Notes", "Concepts", "Settings" | `layouts.ex` |
| Form labels & placeholders | "Title", "Priority", "What needs to be done?" | `todo_live.ex` |
| Flash messages | "Todo created.", "Title is required.", "Could not update todo." | `*_live.ex` handlers |
| Empty states | "No pages yet", "No version history yet." | `page_components.ex`, `page_list_components.ex` |
| Tooltips / titles | "Logout", "Save as smart collection" | `layouts.ex`, `page_list_components.ex` |
| Page titles | `page_title: gettext("Dashboard")` | `*_live.ex` mount/handle_params |
| `data-confirm` attributes | `data-confirm={gettext("Are you sure? This cannot be undone.")}` | `page_components.ex` |
| Kanban column labels | "Backlog", "Today", "In Progress", "Done" | `dashboard_live.ex`, `todo_live.ex` |
| Priority labels | "Low", "Medium", "High", "Urgent" | `todo_live.ex` |
| Select dropdown options | `{"No goal", ""}` → `{gettext("No goal"), ""}` | `todo_live.ex` |

## What NOT to wrap

- CSS class names, icon names, HTML attribute values (except `title` and `data-confirm`)
- Route paths (`~p"/todos"`)
- Database field values (`@page.title`, `@page.owner`)
- Log messages
- `phx-click` / `phx-value-*` event names and values

## Interpolated strings

Use gettext bindings for dynamic values. Don't use `String.replace` hacks:

```elixir
# BAD — String.replace hack (was in search_live.ex)
gettext("No results found for \"%{query}\".") |> then(&String.replace(&1, "%{query}", @query))

# GOOD — proper gettext interpolation
gettext("No results found for \"%{query}\".", query: @query)
```

For version history lines with multiple interpolations:

```elixir
gettext("v%{version} — %{date} by %{author}",
  version: version.version,
  date: format_date(version.inserted_at),
  author: version.changed_by || gettext("system")
)
```

## .po file structure

The `default.po` file for a locale lives at
`priv/gettext/<locale>/LC_MESSAGES/default.po`. Structure:

```po
## "msgid"s here are often extracted from source code.
## Add new messages manually only if they're dynamic
## messages that can't be statically extracted.
##
## Run "mix gettext.extract" to bring this file up to
## date. Leave "msgstr"s empty as changing them here has no
## effect: edit them in PO (.po) files instead.
##
msgid ""
msgstr ""
"Language: es\n"
"Plural-Forms: nplurals=2; plural=(n != 1);\n"

#: lib/dran_web/live/dashboard_live.ex:63
#, elixir-autogen, elixir-format
msgid "Dashboard"
msgstr "Panel"

#: lib/dran_web/live/search_live.ex:156
#, elixir-autogen, elixir-format
msgid "No results found for \"%{query}\"."
msgstr "No se encontraron resultados para \"%{query}\"."
```

- The `#, elixir-autogen, elixir-format` lines are managed by `mix gettext.extract`
  and `mix gettext.merge` — don't edit them manually.
- The `msgid` must match the exact string passed to `gettext()` in source.
- Interpolation placeholders like `%{query}` are preserved verbatim in `msgstr`.

## merge output interpretation

`mix gettext.merge priv/gettext` reports per-locale stats:

```
Wrote priv/gettext/es/LC_MESSAGES/default.po (0 new, 0 removed, 123 unchanged, 0 fuzzy, 0 obsolete)
Wrote priv/gettext/en/LC_MESSAGES/default.po (123 new, 0 removed, 0 unchanged, 0 fuzzy, 0 obsolete)
```

- `0 new` for `es` means all msgids already had translations (good).
- `123 new` for `en` means the English default.po was just created from the .pot
  template with empty msgstrs — expected on first merge for a locale.

### `gettext.merge` silently drops new strings when compile fails elsewhere

`mix gettext.extract` compiles the project to find `gettext()` calls. If
there's a **compile error in any other file** (e.g. another agent's
in-progress work in `settings_live.ex`), the extractor may still write the
`.pot` file with the new msgids, but `mix gettext.merge` will NOT pick them
up into the `.po` files — it reports `0 new` even though the `.pot` clearly
contains the new entries.

**Symptom:** `grep "Linked from" priv/gettext/default.pot` finds the entry,
but `grep "Linked from" priv/gettext/es/LC_MESSAGES/default.po` returns
nothing. `mix gettext.merge` exits 0 with no output.

**Fix:** manually add the new entries to the `.po` files. Append to the end
of `priv/gettext/es/LC_MESSAGES/default.po` and
`priv/gettext/en/LC_MESSAGES/default.po`:

```po
#: lib/dran_web/components/page_components.ex:305
#, elixir-autogen, elixir-format
msgid "Linked from"
msgstr "Enlazado desde"
```

For the `en` locale, leave `msgstr ""` (English is the source language).
For `es`, provide the translation. The `#, elixir-autogen, elixir-format`
comment lines and `#:` source references are managed by the tooling —
copy the format from existing entries.

**Prevention:** always ensure `mix compile` is clean (no errors in ANY file)
before running `mix gettext.extract` + `mix gettext.merge`. If another agent
or concurrent process has broken the build, fix or stash that first.

## Strings that appear in multiple files

A single msgid can be extracted from multiple source locations. The .pot/.po
file lists all locations under one entry:

```po
#: lib/dran_web/components/layouts.ex:127
#: lib/dran_web/live/dashboard_live.ex:28
#: lib/dran_web/live/dashboard_live.ex:129
#: lib/dran_web/live/todo_live.ex:52
#, elixir-autogen, elixir-format
msgid "Todos"
msgstr "Tareas"
```

One translation covers all occurrences. This is normal for shared labels like
"Todos", "Graph", "Search", "Dashboard" that appear in both the sidebar and
page headers.

## my_app-specific translation choices (es)

| English | Spanish | Notes |
|---------|--------|-------|
| Dashboard | Panel | Not "Tablero" (that's for Kanban board) |
| Todos | Tareas | Not "Quehaceres" |
| Backlog | Pendientes | |
| Orphans | Huérfanas | Refers to pages with no relations |
| Broken Links | Enlaces rotos | |
| Artifact | Artefacto | |
| References | Referencias | |
| Concept | Concepto | |
| Entity | Entidad | |
| Changelog | Historial de cambios | |
| Files Ingest | Importar archivos | Action-oriented translation |
| Smart Collection | Colección inteligente | |
| View board | Ver tablero | Kanban board |
| Drop here | Soltar aquí | Drag-and-drop target |
