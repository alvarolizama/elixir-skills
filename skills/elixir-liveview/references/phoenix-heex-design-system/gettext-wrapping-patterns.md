# Gettext Wrapping Patterns for Phoenix LiveView HEEx

Consolidated reference for the exact syntax to use when wrapping each type
of hardcoded English string in `gettext()`. These patterns match the
conventions used in `todo_live.ex` (the canonical example in the my_app
codebase).

## Module attributes (compile-time)

Module attributes like `@tabs` are evaluated at compile time, so `gettext()`
works directly — no braces needed:

```elixir
# Before
@tabs [{"content", "Content"}, {"graph", "Graph"}]

# After
@tabs [{"content", gettext("Content")}, {"graph", gettext("Graph")}]
```

## HEEx visible text (between tags)

Wrap in `{gettext("...")}` — the `{}` is required in HEEx to evaluate the
Elixir expression:

```heex
<!-- Before -->
<.icon name="hero-pencil" class="size-4" /> Edit

<!-- After -->
<.icon name="hero-pencil" class="size-4" /> {gettext("Edit")}
```

```heex
<!-- Before -->
<button type="submit" class="btn btn-primary btn-sm">Save</button>

<!-- After -->
<button type="submit" class="btn btn-primary btn-sm">{gettext("Save")}</button>
```

## HEEx attributes (label, placeholder)

Use `attr={gettext("...")}` — the `=` with `{}` evaluates the expression:

```heex
<!-- Before -->
<.input field={@form[:title]} type="text" label="Title" placeholder="Enter a title…" />

<!-- After -->
<.input
  field={@form[:title]}
  type="text"
  label={gettext("Title")}
  placeholder={gettext("Enter a title…")}
/>
```

## Interpolated strings (version history, counts)

Use gettext interpolation with named bindings. This is better than string
concatenation because translators can reorder the placeholders:

```heex
<!-- Before -->
v{version.version} — {format_date(version.inserted_at)} by {version.changed_by || "system"}

<!-- After -->
{gettext("v%{version} — %{date} by %{author}",
  version: version.version,
  date: format_date(version.inserted_at),
  author: version.changed_by || gettext("system")
)}
```

The `"system"` fallback is itself a translatable string — wrap it in
`gettext("system")`.

## Flash messages

Wrap the string argument to `put_flash/3`:

```elixir
# Before
put_flash(socket, :info, "Page enriched with web content.")
put_flash(socket, :error, "Enrichment failed: #{inspect(reason)}")

# After
put_flash(socket, :info, gettext("Page enriched with web content."))
put_flash(socket, :error, gettext("Enrichment failed: %{reason}", reason: inspect(reason)))
```

For interpolated flash messages, use gettext interpolation (`%{reason}`)
rather than Elixir string interpolation (`#{...}`).

## page_title assignments

Wrap the string value in `gettext()`:

```elixir
# Before
{:noreply, assign(socket, pages: pages, page_title: "Notes")}

# After
{:noreply, assign(socket, pages: pages, page_title: gettext("Notes"))}
```

## phx-disable-with

This is user-visible text — wrap it:

```heex
<button type="submit" phx-disable-with={gettext("Creating…")}>
  {gettext("Create")}
</button>
```

## What NOT to wrap

- **CSS class names** — `class="btn btn-primary"` stays as-is
- **Event names** — `phx-click="toggle_edit"` stays as-is
- **HTML IDs** — `id="page-edit-form"` stays as-is
- **Icon names** — `name="hero-pencil"` stays as-is
- **Route paths** — `navigate={~p"/notes"}` stays as-is
- **Field names** — `field={@form[:title]}` stays as-is
- **Type attributes** — `type="text"`, `type="submit"` stay as-is

## Grep verification commands

After wrapping, run these to confirm completeness. Each should return
nothing for a fully-wrapped file:

```bash
# Bare placeholders
grep -n 'placeholder="[^{]' lib/dran_web/live/*.ex

# Bare labels
grep -n 'label="[^{]' lib/dran_web/live/*.ex

# Bare button/visible text
grep -nE '>[A-Z][a-z]+[^<{]*<' lib/dran_web/live/*.ex | grep -v gettext

# Bare flash messages
grep -n 'put_flash.*"' lib/dran_web/live/*.ex | grep -v gettext

# Bare page_title
grep -n 'page_title: "' lib/dran_web/live/*.ex | grep -v gettext
```

## Common strings already in default.po

In a mature codebase, many strings already exist in `default.po` from
prior work (e.g. `todo_live.ex`). When wrapping a new LiveView that shares
the same UI patterns, most strings will already have translations. Only
truly new strings (like "Suggest" in artifact_live.ex) need manual
translation after `mix gettext.merge`.

Always check the merge output — if it says `0 new messages`, all strings
were already translated and no `.po` editing is needed.
