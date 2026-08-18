# Tag Input with Colocated Hook (my_app, 2026-07-19)

Reference implementation of a zero-dependency, zero-server-round-trip tag
input for Phoenix LiveView forms. Built for my_app's page create/edit forms.

## Public API

```elixir
attr :id, :string, required: true
attr :name, :string, required: true        # form field name, e.g. "page[tags]"
attr :value, :any, default: nil            # comma-separated string OR list
attr :label, :string, default: nil
attr :placeholder, :string, default: nil   # falls back to gettext("Add tag…")
attr :suggestions, :list, default: []      # existing tags for datalist autocomplete

def tag_input(assigns) do
  assigns =
    assigns
    |> assign_new(:placeholder, fn -> gettext("Add tag…") end)
    |> assign(:tags, normalize_tags(assigns.value))

  ~H"""
  <div phx-hook=".TagInput" id={@id} data-tag-input>
    <label :if={@label} for={"#{@id}-input"} class="label ...">{@label}</label>
    <div class="flex flex-wrap items-center gap-1.5 rounded-lg border ...">
      <span :for={tag <- @tags} data-tag-chip={tag} class="rounded-full bg-primary/10 text-primary text-xs px-2.5 py-1 inline-flex items-center gap-1">
        {tag}
        <button type="button" data-tag-remove={tag} aria-label={gettext("Remove tag %{tag}", tag: tag)}>×</button>
      </span>
      <input id={"#{@id}-input"} type="text" data-tag-field list={"#{@id}-suggestions"}
             placeholder={@placeholder} autocomplete="off" class="flex-1 min-w-24 ..." />
    </div>
    <datalist id={"#{@id}-suggestions"}>
      <option :for={s <- @suggestions} value={s} />
    </datalist>
    <input type="hidden" name={@name} value={Enum.join(@tags, ",")} data-tag-value />
    <script :type={Phoenix.LiveView.ColocatedHook}>
      // see Hook JS below
    </script>
  </div>
  """
end

defp normalize_tags(nil), do: []
defp normalize_tags(v) when is_binary(v), do: v |> String.split(",") |> Enum.map(&String.trim/1) |> Enum.reject(&(&1 == ""))
defp normalize_tags(v) when is_list(v), do: Enum.map(v, &to_string/1)
```

## Hook JS (inside the colocated script)

```js
export default {
  mounted() {
    const field = this.el.querySelector("[data-tag-field]")
    const hidden = this.el.querySelector("[data-tag-value]")

    const tags = () => hidden.value === "" ? [] : hidden.value.split(",")
    const setTags = (list) => {
      hidden.value = list.join(",")
      // rebuild chips row (remove existing chip spans, re-add before field)
      this.el.querySelectorAll("[data-tag-chip]").forEach(c => c.remove())
      list.forEach(t => {
        const chip = document.createElement("span")
        chip.dataset.tagChip = t
        chip.className = "rounded-full bg-primary/10 text-primary text-xs px-2.5 py-1 inline-flex items-center gap-1"
        chip.innerHTML = `${t} <button type="button" data-tag-remove="${t}">×</button>`
        field.before(chip)
      })
    }
    const add = (raw) => {
      const t = raw.trim().replace(/,+$/, "")
      if (t && !tags().includes(t)) setTags([...tags(), t])
      field.value = ""
    }

    field.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(field.value) }
      if (e.key === "Backspace" && field.value === "") {
        const list = tags(); list.pop(); setTags(list)
      }
    })
    this.el.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-tag-remove]")
      if (btn) setTags(tags().filter(t => t !== btn.dataset.tagRemove))
    })
  }
}
```

## Wiring into forms

- **Edit sidebar** (`page_edit_form`): `<.tag_input id="page-edit-tags" name="page[tags]"
  value={@page.tags} tag_suggestions={@tag_suggestions} />`. The page's DB
  `:tags` is `{:array, :string}` — the component's list branch handles it.
- **Create form** (`page_new_live`): same component with
  `value={Phoenix.HTML.Form.input_value(@form, :tags)}` — the param string
  branch handles it.
- **Suggestions**: `Brain.list_tags(context_id)` (distinct non-archived tags
  per context, sorted). Load lazily with a fallback in the shared handler so
  both `toggle_edit` clicks AND direct `?edit=true` entry populate it:
  ```elixir
  defp ensure_tag_suggestions(socket) do
    case socket.assigns[:tag_suggestions] do
      nil -> assign(socket, tag_suggestions: safe_list_tags(context_id(socket)))
      _ -> socket
    end
  end
  ```
- **Server normalization on save**: split → trim → reject empty → join, so the
  stored value is canonical even if the client sent `" a, b ,c "`.

## Test coverage matrix (test/dran_web/components/tag_input_test.exs)

1. Comma-string value renders one chip per tag (`data-tag-chip` attrs).
2. List value renders chips (edit-form path).
3. Hidden input carries canonical `"uno,dos,tres"` (trims + dedups).
4. Empty value → hidden input `value=""`.
5. Datalist renders `<option>` per suggestion.
6. Hook mounts — assert `phx-hook="DranWeb.MarkdownEditorComponents.TagInput"`
   (module-qualified name in component-test context, NOT `".TagInput"`).

## Gotchas hit during the build

- **Hook name in tests**: colocated hooks render module-qualified outside a
  LiveView. First test run failed asserting `".TagInput"`.
- **`Phoenix.HTML.Form.input_value/2`** for the create form's tags field returns
  the raw param string; pass it straight through — the component normalizes.
- **Do NOT add a `phx-change` to the tag field.** All behavior is DOM-only;
  the form's submit reads the hidden input. Adding phx-change would round-trip
  every keystroke and fight the hook's chip re-rendering.
