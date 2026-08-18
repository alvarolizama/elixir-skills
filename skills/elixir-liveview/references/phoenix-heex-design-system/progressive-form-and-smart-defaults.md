# Progressive Disclosure Form + Smart Defaults (my_app page_new_live)

Worked reference for the "Wave 2" page-creation form refactor: removing the
slug field from the UI, collapsing secondary fields behind a `<details>`, and
prefilling meta per page type. The pattern generalizes to any Phoenix
LiveView creation form with a primary/secondary field split.

## Progressive disclosure with `<details>` + hero-chevron

Wrap Summary + `<.meta_fields>` (or any secondary fields) inside a collapsed
`<details>` so the primary fields (Title, Tags, Content) are visible by
default. Use the same hero-chevron idiom as the backlinks section in
`page_components.ex` for visual consistency:

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
    <!-- secondary fields here: summary input, meta_fields component, etc. -->
  </div>
</details>
```

Key conventions:
- **`class="group"` on `<details>`** — enables the `group-open:` variant on
  the chevron so it rotates 90° when the section expands.
- **`hero-chevron-right` + `group-open:rotate-90`** — the standard disclosure
  indicator. `transition-transform duration-150` animates the rotation.
- **Summary text styling** — `text-sm font-semibold text-base-content/60
  uppercase tracking-wider` reads as a section label, not a heading.
- **`ml-6` on the body** — indents the secondary fields to align with the
  chevron, visually grouping them under the disclosure header.
- **No `open` attribute** — the section is collapsed by default. Add `open`
  only if you want it expanded initially (e.g. `open={@show_advanced}`).
- **gettext the summary text** — it's user-visible; "Más opciones" is already
  Spanish in the msgid, so the es translation is identical.

## Smart defaults: prefill meta per type on `:new`

When mounting for `:new`, prefill the `meta` assign with type-specific
defaults so the user doesn't have to pick the common starting state. Pass
the map into `<.meta_fields meta={@meta} context_id={@context_id} />`
instead of `%{}`.

```elixir
# Smart defaults per page type for the :new form.
defp default_meta_for("note") do
  %{"kind" => "thought", "date" => Date.utc_today() |> Date.to_string()}
end

defp default_meta_for("todo") do
  %{"kanban_status" => "backlog", "priority" => "medium"}
end

defp default_meta_for(type) when type in ["project", "plan"] do
  %{"status" => "draft"}
end

defp default_meta_for("goal") do
  %{"health_source" => "derived"}
end

defp default_meta_for(_), do: %{}
```

### Carrying defaults through live validation

On `validate_page`, merge the form-submitted meta on top of the smart
defaults so user edits win:

```elixir
def handle_event("validate_page", %{"page" => page_params}, socket) do
  base_meta = socket.assigns[:meta] || %{}
  meta = Map.merge(base_meta, meta_from_params(page_params))
  # ... build changeset, assign form + body + meta
end

defp meta_from_params(%{"meta" => form_meta}) when is_map(form_meta) do
  form_meta
  |> Enum.reject(fn {_k, v} -> v in ["", nil] end)
  |> Map.new()
end

defp meta_from_params(_), do: %{}
```

The `Enum.reject` for empty/nil values is important — browsers submit empty
select options as `""`, which would overwrite the default if not filtered.

### Operator-precedence pitfall

`socket.assigns[:meta] || %{} |> Map.merge(...)` parses as
`socket.assigns[:meta] || (%{} |> Map.merge(...))` — the `|>` binds tighter
than `||`. Always bind the base to a variable first:

```elixir
# WRONG — operator precedence drops the defaults when @meta is nil
meta = socket.assigns[:meta] || %{} |> Map.merge(meta_from_params(page_params))

# RIGHT — bind base_meta first, then merge
base_meta = socket.assigns[:meta] || %{}
meta = Map.merge(base_meta, meta_from_params(page_params))
```

## Arity-2 with default arg: adding a mode without breaking callers

When a function (e.g. `PageMeta.meta_fields_for/1`) is called by a component
you do NOT own (concurrent agent editing it), add the new parameter with a
default so existing arity-1 calls keep working:

```elixir
# Before: meta_fields_for(type) — one clause per type
def meta_fields_for("note"), do: [...]
def meta_fields_for("goal"), do: [...]

# After: meta_fields_for(type, mode \\ :edit) — arity-2 with default
def meta_fields_for(type, mode \\ :edit)
def meta_fields_for(type, :edit), do: meta_fields_edit(type)
def meta_fields_for("goal", :new) do
  # capture-only fields for goal creation: health, current_value, progress excluded
  [...]
end
def meta_fields_for(type, :new), do: meta_fields_edit(type)

# The old per-type bodies become private meta_fields_edit/1 clauses
defp meta_fields_edit("note"), do: [...]
defp meta_fields_edit("goal"), do: [...]
```

The `:new` filtering activates ONLY once the component gains a `:mode` attr
and forwards it as `meta_fields_for(page_type, mode)`. Until then, the
component's arity-1 call hits the default `:edit` and returns the full list.
This lets you land the backend filtering safely without touching the
component — document this in the function's `@doc`.

## Auto-slug derivation: removing the slug field from the UI

When the slug should be derived from the title (not user-edited), remove the
slug `<.input>` from the form entirely. Brain's `ensure_title_and_slug/1`
derives it via `my_app.Slug.slugify/1` on `create_page`. Keep a `unique_slug`
fallback for collisions but drop the live auto-generation-on-validate logic:

```elixir
# In save_page handler — ensure_slug only runs if no slug was submitted
defp ensure_slug(%{"slug" => slug} = params, _context_id)
     when is_binary(slug) and slug != "",
     do: params

defp ensure_slug(params, context_id) do
  title = Map.get(params, "title", "")
  slug = unique_slug(title, context_id, Map.get(params, "page_type", "page"))
  Map.put(params, "slug", slug)
end
```

`my_app.Slug.slugify/1` normalizes Unicode (NFD), drops combining marks,
lowercases, and hyphenates — so "Mi Nota Nueva" → "mi-nota-nueva". Test the
full derivation path via `Brain.create_page/1` (not just the LiveView) since
that's where `ensure_title_and_slug/1` runs.

## Testing pitfall: `selected=""` attribute order in rendered HEEx

Phoenix's HTML renderer emits boolean attributes as `attr=""` and may order
them differently than you'd write them by hand. A `<.select>` with a
selected option renders as:

```html
<option selected="" value="thought">
```

NOT as `value="thought" selected`. Tests that assert
`~s(value="thought" selected)` will fail. Assert the value and the presence
of `selected=""` separately, or just assert the value appears at all if you
don't need to verify selection:

```elixir
# Robust — doesn't depend on attribute order
assert html =~ ~s(value="thought")
assert html =~ ~s(selected="")

# Also robust — just checking the value is present
assert html =~ ~s(value="draft")
```

## Gettext one-step extract+merge

`mix gettext.extract --merge` runs extraction and merge in a single step,
writing both the `.pot` template and the `.po` locale files. This is faster
than the two-step `mix gettext.extract` + `mix gettext.merge priv/gettext`
when you know you have new strings. Review the output for:
- **New msgids** with empty `msgstr ""` — fill these with translations.
- **Fuzzy entries** (`#, fuzzy`) — gettext guessed a translation from a
  nearby old msgid; review and correct the `msgstr`, then strip `, fuzzy`
  from the `#,` comment line manually (or fix the msgstr and re-run merge).
