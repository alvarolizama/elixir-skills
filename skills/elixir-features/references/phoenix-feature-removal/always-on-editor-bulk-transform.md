# Always-On Editor — Bulk Transform Across N LiveViews

Recipe for converting a family of similar Phoenix LiveViews from edit/view-toggle
mode to always-on editor in one pass. Extracted from a 10-LiveView refactor
(note, concept, entity, reference, query, todo, comparison, project, goal, plan).

## The transform (per file)

Apply these 8 steps to each LiveView. A Python `execute_code` script can do all
10 files in one shot (see recipe below), but verify each file after — regex
edge cases are real.

1. **Remove Edit/Save/Cancel buttons** from the `<:actions>` slot. Keep the
   Back link and any other nav links (e.g. "View in Kanban"). Three separate
   regexes keyed on `phx-click="toggle_edit"`, `phx-click="save_page"`,
   `phx-click="cancel_edit"` — match the whole `<button ...>...</button>`.

2. **Collapse the `if @editing do ... else ... end`** in `<:tabs>` to just the
   if-branch content (the `<.page_edit_form>`). Two regex shapes:
   - `<%= if @editing do %>A<% else %>B<% end %>` → `A`
   - `<%= if @editing do %>A<% end %>` (no else) → `A`

3. **Remove standalone rendered_body prose div** if the LiveView had one
   inside `<:tabs>` that was only shown when not editing (todo_live case).

4. **`editing: false` → `editing: true`** in `mount` (first occurrence only —
   `replace(..., 1)`).

5. **Remove `toggle_edit`/`cancel_edit` handlers.** Two formats in the wild:
   - Multi-line: `def handle_event("toggle_edit", params, socket), do: PageEdit...`
     followed by `def handle_event("cancel_edit", params, socket), do: PageEdit...`
   - Single-line: `def handle_event("toggle_edit", p, s), do: PageEdit...`
   Keep `save_page`, `validate_page`, `body_change`, `field_change` — the
   autosave form still needs them.

6. **Simplify form creation in `handle_params`.** Replace:
   ```elixir
   editing = Map.get(params, "edit") == "true"
   form = if editing, do: Brain.change_page(page) |> to_form(as: :page), else: nil
   ```
   with:
   ```elixir
   form = Brain.change_page(page) |> to_form(as: :page)
   ```
   Three shapes seen: multi-line `if/else/end`, single-line `if/edit_form`,
   and `edit_form = if editing, do: ..., else: nil` (todo_live).

7. **Rename `params` → `_params`** in `handle_params(%{"slug" => slug} = params, ...)`
   → `= _params`. The `params` var is now unused; `--warnings-as-errors` flags it.

8. **`editing: editing,` → `editing: true,`** and **`form: edit_form,` → `form: form,`**
   in the `assign(socket, ...)` block of `handle_params`.

## Per-file variations (gotchas)

| LiveView | Variation |
|----------|-----------|
| **todo_live** | Local var was `edit_form` not `form`; rename both the var and the assign. Also had a standalone prose div + status buttons that stayed (only the prose div was edit-gated). |
| **goal_live** | `handle_params` had NO `form`/`editing`/`context_id`/`save_status` in its assign block — only in `mount`. Must ADD them: insert `form = Brain.change_page(page) |> to_form(as: :page)` before `rendered_body`, and append `editing: true, form: form, context_id: context.id, save_status: "idle"` to the assign. |
| **project_live** | `handle_params` reads `active_tab = Map.get(socket.assigns, :active_tab, "overview")` to preserve across patches — keep this line; don't let the regex clobber it. |
| **plan_live, project_live** | `handle_params` uses `= params` (not `= _params`) — rename. |

## Dead-code cleanup (after the transform compiles)

Removing the `else` branch (the view-mode dashboard) leaves `defp` helpers
orphaned. `mix compile --warnings-as-errors` catches them as "unused function"
warnings. Delete the dead `defp`s — they were only called from the removed
dashboard HEEx.

Examples from the my_app refactor:

| LiveView | Dead helpers after always-on transform |
|----------|-----------------------------------------|
| **goal_live** | `progress_percent/1`, `format_value/1` (metric panel) |
| **project_live** | `progress_pct/1`, `active_todos/1`, `health_counts/1`, `health_dot_class/1`, `count_plan_status/2`, `health_badge_class/1` (overview dashboard) |
| **plan_live** | `plan_status_class/1` (status badge) |

**Keep** helpers still used by the remaining (non-edit-gated) HEEx: `kanban_status/1`,
`kanban_status_class/1`, `kanban_items/2`, `count_kanban/2`, `kanban_accent_dot/1`,
`health_class/1`, `meta_get/2`, `filter_by_project_slug/3`. Grep each `defp` name
in the file's HEEx before deleting.

## Python regex recipe (execute_code)

```python
import re

base = '/Users/alvaro/Repos/my_app/lib/dran_web/live'
files = ['note_live.ex', 'concept_live.ex', 'entity_live.ex', 'reference_live.ex',
         'query_live.ex', 'todo_live.ex', 'comparison_live.ex', 'project_live.ex',
         'goal_live.ex', 'plan_live.ex']

for fname in files:
    path = f'{base}/{fname}'
    with open(path) as f:
        content = f.read()

    # 1. Remove Edit/Save/Cancel buttons (3 regexes, DOTALL)
    content = re.sub(r'\n\s*<button\s*:if=\{not @editing\}[^>]*phx-click="toggle_edit"[^>]*>.*?</button>', '', content, flags=re.DOTALL)
    content = re.sub(r'\n\s*<button\s*:if=\{@editing\}[^>]*phx-click="save_page"[^>]*>.*?</button>', '', content, flags=re.DOTALL)
    content = re.sub(r'\n\s*<button\s*:if=\{@editing\}[^>]*phx-click="cancel_edit"[^>]*>.*?</button>', '', content, flags=re.DOTALL)

    # 2. Collapse if/else and if-only
    content = re.sub(r'<%= if @editing do %>(.*?)<% else %>(.*?)<% end %>',
                     lambda m: m.group(1).strip(), content, flags=re.DOTALL)
    content = re.sub(r'<%= if @editing do %>(.*?)<% end %>',
                     lambda m: m.group(1).strip(), content, flags=re.DOTALL)

    # 3. Remove standalone prose div (todo_live)
    content = re.sub(r'\s*<div class="prose prose-base dark:prose-invert max-w-none">\s*\{@rendered_body\}\s*</div>', '', content)

    # 4. mount: editing: false -> editing: true (first occurrence)
    content = content.replace('editing: false,', 'editing: true,', 1)

    # 5. Remove toggle_edit/cancel_edit handlers (2 formats)
    content = re.sub(r'\n\s*def handle_event\("toggle_edit", params, socket\),\n\s*do: PageEdit\.handle_event\("toggle_edit", params, socket\)\n\s*\n\s*def handle_event\("cancel_edit", params, socket\),\n\s*do: PageEdit\.handle_event\("cancel_edit", params, socket\)\n', '\n', content)
    content = re.sub(r'\n\s*def handle_event\("toggle_edit", p, s\), do: PageEdit\.handle_event\("toggle_edit", p, s\)\n\s*def handle_event\("cancel_edit", p, s\), do: PageEdit\.handle_event\("cancel_edit", p, s\)\n', '\n', content)

    # 6. Simplify form creation (3 shapes)
    content = re.sub(r'\s*editing = Map\.get\(params, "edit"\) == "true"\n\s*\n\s*form =\n\s*if editing do\n\s*Brain\.change_page\(page\) \|> to_form\(as: :page\)\n\s*else\n\s*nil\n\s*end\n',
                     '\n          form = Brain.change_page(page) |> to_form(as: :page)\n', content)
    content = re.sub(r'\s*editing = Map\.get\(params, "edit"\) == "true"\n\s*form = if editing, do: Brain\.change_page\(page\) \|> to_form\(as: :page\), else: nil\n',
                     '\n          form = Brain.change_page(page) |> to_form(as: :page)\n', content)
    content = re.sub(r'\s*editing = Map\.get\(params, "edit"\) == "true"\n\s*edit_form = if editing, do: Brain\.change_page\(page\) \|> to_form\(as: :page\), else: nil\n',
                     '\n          form = Brain.change_page(page) |> to_form(as: :page)\n', content)

    # 7. Rename params -> _params in handle_params head
    content = content.replace('def handle_params(%{"slug" => slug} = params, _url, socket)',
                              'def handle_params(%{"slug" => slug} = _params, _url, socket)')

    # 8. assign block: editing: editing, -> editing: true, ; form: edit_form, -> form: form,
    content = content.replace('editing: editing,', 'editing: true,')
    content = content.replace('form: edit_form,', 'form: form,')

    with open(path, 'w') as f:
        f.write(content)
```

After running: `mix compile --warnings-as-errors`, delete the dead `defp`s
it reports, re-compile, then `grep -rn "toggle_edit\|cancel_edit\|editing: false"
lib/dran_web/live/` → expect 0 hits.

## goal_live.ex special case (manual patch after the script)

goal_live's `handle_params` assign block had no `editing`/`form`/`context_id`/
`save_status` keys. The Python script can't infer where to add them, so patch
manually:

1. Insert `form = Brain.change_page(page) |> to_form(as: :page)` before the
   `rendered_body =` line.
2. Append to the `assign(socket, ...)` block (before the closing `)}`):
   ```elixir
   editing: true,
   form: form,
   context_id: context.id,
   save_status: "idle"
   ```
