# Attributes Slot Relocation — Form Aside → Sidebar

When the always-on editor refactor leaves the form's attribute panel (Summary,
Tags, MetaFields) as an inline `<aside>` inside `page_edit_form`, relocate it to
the `page_detail` sidebar via a new `<:attributes>` slot. This keeps the editor
column clean (title + editor only) and groups all metadata in one sidebar.

## Changes to page_components.ex

### 1. Add slot declaration

```elixir
slot :attributes, doc: "edit form attributes rendered at the top of the sidebar"
```

### 2. Render the slot in the sidebar

In the sidebar `<aside>`, before the Metadata `<details>`:

```elixir
<aside class="lg:w-72 xl:w-80 shrink-0 space-y-4">
  {render_slot(@attributes)}

  <%!-- Metadata collapsible ── %>
  <details class="group surface-2 rounded-lg p-4">
  ...
```

### 3. Create `page_attributes` component

A collapsible `<details open>` panel matching the sidebar's visual style:

```elixir
attr :form, :any, required: true
attr :page, :map, required: true
attr :page_type, :string, required: true
attr :context_id, :any, required: true
attr :editor_id, :string, required: true
attr :tag_suggestions, :list, default: nil

def page_attributes(assigns) do
  # Lazy fallback for tag suggestions
  suggestions = case assigns.tag_suggestions do
    nil -> case assigns.context_id do
      nil -> []
      id -> my_app.Brain.list_tags(id)
    end
    list -> list
  end
  assigns = assign(assigns, :tag_suggestions, suggestions)

  ~H"""
  <details class="group surface-2 rounded-lg p-4" open>
    <summary class="flex items-center gap-2 cursor-pointer select-none">
      <.icon name="hero-chevron-right" class="size-4 shrink-0 text-base-content/40 transition-transform duration-150 group-open:rotate-90" />
      <h3 class="text-caption font-semibold text-base-content/60 uppercase tracking-wider">
        {gettext("Attributes")}
      </h3>
    </summary>
    <div class="space-y-3 mt-2">
      <.input field={@form[:summary]} type="text" label={gettext("Summary")} ... />
      <.tag_input id={"#{@editor_id}-tags"} name="page[tags]" value={...} label={gettext("Tags")} suggestions={@tag_suggestions} />
      <.meta_fields page_type={@page_type} meta={@page.meta || %{}} context_id={@context_id} />
    </div>
  </details>
  """
end
```

### 4. Simplify `page_edit_form`

Remove the `<aside>` and the flex layout — just title + editor:

```elixir
def page_edit_form(assigns) do
  ~H"""
  <.form for={@form} id="page-edit-form" phx-change="validate_page">
    <div class="flex-1 min-w-0 space-y-5">
      <.input field={@form[:title]} type="text" label={gettext("Title")} ... />
      <div>
        <span class="label mb-1 block text-sm font-medium text-base-content/70">
          {gettext("Content")}
        </span>
        <.markdown_editor id={@editor_id} body={@page.body} context_id={@context_id} save_status={@save_status} />
      </div>
    </div>
  </.form>
  """
end
```

No `phx-submit` — autosave works via `phx-change="validate_page"`.

## Changes to each LiveView

Add the `<:attributes>` slot to every `.page_detail` call:

```elixir
<.page_detail ... editing={@editing}>
  <:actions>...</:actions>

  <:attributes>
    <.page_attributes
      form={@form}
      page={@page}
      page_type={@page_type}
      context_id={@context_id}
      editor_id="note-editor"
    />
  </:attributes>

  <:graph>...</:graph>
  <:tabs>
    <.page_edit_form form={@form} page={@page} ... />
  </:tabs>
</.page_detail>
```

The `editor_id` must match the one used in `<.page_edit_form>` so the tag_input
DOM id stays consistent.

## Bulk application

For 6 simple LiveViews (concept, entity, reference, query, todo, comparison),
a Python script can insert the `<:attributes>` block before `<:graph>` or
`<:tabs>`:

```python
attr_block = '''          <:attributes>
            <.page_attributes
              form={@form}
              page={@page}
              page_type={@page_type}
              context_id={@context_id}
              editor_id="X-editor"
            />
          </:attributes>

'''
content = content.replace('          <:graph>', attr_block + '          <:graph>')
# or if no <:graph>: content.replace('          <:tabs>', attr_block + '          <:tabs>')
```

For project_live, goal_live, plan_live — patch manually (they have `<:extra_tabs>`
and different slot ordering).
