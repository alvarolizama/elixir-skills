# Bulk HEEx Component Extraction (N files → 1 shared component)

When a duplicated inline block (e.g. a `<.form>...</.form>` edit form) is copy-pasted
across many LiveView files with minor per-type variations, extract it into a single
shared function component and replace each occurrence with a call to that component.
This is the N-file cousin of the single-file "Split-renderer component refactor" in
the main SKILL.md.

## When to use

- "Replace the duplicated inline edit form block in N LiveViews with the shared `<.X>` component."
- "Extract the repeated `<.form>` into `<.page_edit_form>` across all page-type LiveViews."
- Any task where one block appears in many `.ex` files and a shared component already
  exists (or is being introduced) to replace it.

## Workflow

### 1. Confirm the scope and locate every occurrence

```bash
# Find every file containing the literal marker (the form id is the stable anchor):
search_files pattern='id="page-edit-form"' target='content' path='lib/dran_web/live'
# or, to list files only:
grep -l 'id="page-edit-form"' lib/dran_web/live/*.ex
```

Record the count — this is the target number of files you must patch. If the task
names 11 files and grep finds 11, you're aligned. If grep finds 12, one extra file
needs the same treatment (ask the user before proceeding to it). If grep finds 10,
one named file may have already been migrated or the marker differs slightly —
re-read that file before assuming it's done.

### 2. Read ALL target files before patching

Batch the `read_file` calls — read every target file in one assistant turn so you
have the full picture of per-file variations. The blocks are "the same" only at a
high level; the details that differ across files are exactly what you must preserve
or intentionally drop:

| Variation you will see | Action |
|---|---|
| `editor_id="<type>-editor"` (note-editor, todo-editor, goal-editor, …) | Preserve — pass as a prop to the shared component |
| Slug input field present in some files, absent in others | Drop (per task: slug is auto-managed now) |
| `gettext("Title")` vs raw `"Title"` labels | Drop — the shared component owns its own labels |
| `meta={@page.meta}` vs `meta={@page.meta || %{}}` | Drop — the shared component owns its own nil-coalescing |
| `phx-blur="field_change"` on slug/summary inputs | Drop with the field |
| Extra buttons inside the form (`suggest_summary`, `suggest_tags`) | Drop — they belonged to the now-removed inline fields |
| `<% else %>` branch with rendered prose/changelog | **KEEP untouched** — only the `<.form>` inside the `if @editing` branch is replaced |
| Wrapper context (status buttons row, `@active_tab == "overview"` div) | **KEEP untouched** — only swap the form |

### 3. Patch each file independently — and in parallel

Each file's `old_string` is unique because the per-file `editor_id` and label text
differ. Issue all `patch` calls in one assistant turn so they run concurrently. The
replacement is a single self-closing component call:

```heex
<.page_edit_form
  form={@form}
  page={@page}
  page_type={@page_type}
  context_id={@context_id}
  save_status={@save_status}
  editor_id="<type>-editor"
/>
```

The `editor_id` MUST be passed as a prop and MUST match the file's existing editor
ID. A shared component cannot hardcode the editor ID — if it did, every page-type
LiveView would render the same DOM id (`note-editor`) and LiveView's diff engine
would conflict when navigating between page types.

### 4. Verify

```bash
# Each file must have exactly 1 occurrence of the new component:
grep -c "page_edit_form" lib/dran_web/live/note_live.ex lib/dran_web/live/todo_live.ex ...

# No file may still contain the literal old form id inside a <.form tag:
grep -l 'id="page-edit-form"' lib/dran_web/live/*.ex   # must return nothing

# Confirm the if/else/end structure around the replacement is intact:
for f in note todo goal plan project concept entity reference artifact comparison query; do
  file="lib/dran_web/live/${f}_live.ex"
  echo "=== $file ==="
  grep -n -E '<\.page_edit_form|editor_id=|@editing do %>|<% else %>|<% end %>|<\.form' "$file"
done

# Compile to catch any attr mismatch:
mix compile --warnings-as-errors
```

Then run the relevant test directory. If tests assert on the old form id
(`#page-edit-form`), update them to assert on the component's rendered output or
on a stable `data-testid`.

## Per-file structural preservation rules

The task brief usually names files with special surrounding structure. Honor these
strictly — the shared component call goes INSIDE the existing wrapper, the wrapper
is not touched:

- **`todo_live.ex`**: the form sits in the content tab AFTER a status-buttons row
  and a `rendered_body` div. Those stay; only the `<.form>` is swapped. todo often
  has NO `<% else %>` branch (the prose always renders, the form is additive).
- **`goal_live.ex` / `project_live.ex`**: the form sits inside
  `<div :if={@active_tab == "overview"}>`. The wrapper and the else branch
  (metrics dashboard / stat cards) stay untouched.
- **Files with an `<% else %>` prose/changelog branch**: keep the else branch
  byte-for-byte. Only the `<.form>...</.form>` inside the `if @editing` branch
  is replaced.

## Intentional field dropping — don't re-add them

When the task says "slug is dropped (auto-managed now)" or "suggest buttons are
dropped", the shared component simply does not render those fields. Do NOT:

- Re-add a slug input "for safety" — it creates a second source of truth for the slug.
- Preserve `phx-blur="field_change"` on fields that no longer exist.
- Keep `suggest_summary` / `suggest_tags` buttons — they referenced fields that
  are now inside the shared component, not the caller. If suggestion is still
  wanted, the shared component must own the buttons; do not leave dangling buttons
  in the caller.

The grep verification confirms the drop: after migration, `grep 'form\[:slug\]'`
on the migrated files should return nothing.

## Concurrent sibling-agent drift

When running alongside parallel subagents (e.g. via `dynamic-workflow`), the
`patch` tool may warn:

```
"_warning": "...modified by sibling subagent '...' at HH:MM:SS — after this agent's last read..."
```

The patch can STILL SUCCEED if your `old_string` matched the pre-modification
content (the fuzzy matcher handles minor drift). After a sibling-warning patch:

1. Re-read the file with `read_file` to confirm your change landed correctly.
2. Confirm the sibling's changes weren't clobbered.
3. If the sibling's change conflicts with yours, re-read FIRST, then re-patch
   against the merged content.

This is the same pitfall documented in the main SKILL.md; the bulk-extraction
context just means you may see it on many files at once.

## Scope-leak detection (the `git diff --stat` audit)

After patching, run `git diff --stat` on the target directory. If a file you did
NOT intend to touch appears in the diff, investigate before reporting completion:

```bash
git diff --stat lib/dran_web/live/
```

Common causes:
- A concurrent sibling subagent modified an adjacent file (e.g. `page_new_live.ex`
  while you were editing the 11 `*_live.ex` files). Confirm by checking the diff
  content — if it uses a different form id (`page-new-form` not `page-edit-form`)
  and you have zero occurrences of your marker in it, you did not touch it.
- Your `patch` `old_string` was too loose and matched a second location. The
  `patch` tool requires uniqueness unless `replace_all=true`, so this is rare —
  but if the file content was identical in two spots, verify with `grep -c`.

Never claim a file you didn't touch as part of your work, and never report a
concurrent agent's modification as your own. State explicitly which files in the
diff are yours and which are a sibling's.

## Worked example: 11 my_app page-type LiveViews → `<.page_edit_form>`

Target files (all in `lib/dran_web/live/`):
`note_live.ex`, `todo_live.ex`, `goal_live.ex`, `plan_live.ex`, `project_live.ex`,
`concept_live.ex`, `entity_live.ex`, `reference_live.ex`, `artifact_live.ex`,
`comparison_live.ex`, `query_live.ex`.

| File | `editor_id` | Notes |
|---|---|---|
| note_live.ex | `note-editor` | had slug field (dropped); had explicit "Content" label span (dropped) |
| todo_live.ex | `todo-editor` | no else branch; status buttons + rendered_body above preserved |
| goal_live.ex | `goal-editor` | raw English labels (not gettext); inside `overview` tab |
| plan_live.ex | `plan-editor` | `meta={@page.meta}` (not coalesced) — dropped, component owns it |
| project_live.ex | `project-editor` | raw English labels; inside `overview` tab |
| concept_live.ex | `concept-editor` | standard pattern |
| entity_live.ex | `entity-editor` | standard pattern |
| reference_live.ex | `reference-editor` | standard pattern |
| artifact_live.ex | `artifact-editor` | had `suggest_summary` + `suggest_tags` buttons (dropped) |
| comparison_live.ex | `comparison-editor` | standard pattern |
| query_live.ex | `query-editor` | used "Question" label instead of "Title" (dropped) |

Result: 11 files patched, each with exactly 1 `<.page_edit_form>` call, zero
residual `id="page-edit-form"` literals. `page_new_live.ex` appeared in
`git diff --stat` but was modified by a concurrent sibling agent and was
correctly NOT touched by this task.
