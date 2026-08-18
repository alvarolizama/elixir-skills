# Removing a feature-tab from a LiveView: shared-assign & orphaned-helper pitfalls

my_app case: removing the "Kanban" tab (board UI + drag-drop JS + status helpers +
`move_todo` event) from `project_live.ex`, `goal_live.ex`, `plan_live.ex`. The
surviving "Todos" / "Tareas" tabs stayed. The removal SPEC was 5 mechanical
steps (drop tab entry, drop board HEEx block, drop `kanban_columns` assign,
drop todo-loading code, drop helper functions). Working mechanically it revealed
several judgment calls the spec did not anticipate.

## 1. Shared assign between the removed tab AND a surviving tab (do NOT delete)

The spec said "remove the todo loading code / `project_todos` assign." But
`@project_todos` / `@goal_todos` / `@plan_todos` were used by BOTH the kanban
board tab AND the surviving "Todos" list tab in the same `:extra_content`.
Blindly following the spec (removing the `Brain.list_pages(...)` block + the
`X_todos: X_todos` assign) would break compilation of the surviving Todos tab
(missing assign) and delete live functionality.

Rule: **before removing a variable-assignment block, grep the whole `render`
template for `@<var>`.** If another surviving branch (`<div :if={@active_tab ==
"todos"}>`) still references it, KEEP the load + assign and only remove the
kanban-specific renders. Judgement trumps a mechanical checklist.

## 2. Orphaned helpers fail `--warnings-as-errors` (sweep them too)

After the consuming templates are removed, the now-unused private helpers
become dead code and `mix compile --warnings-as-errors` FAILS (Elixir warns on
unused private functions/clauses). Sweep ALL of:
- `kanban_status/1`, `kanban_status_class/1`, `kanban_accent_dot/1`,
  `kanban_items/2`, `count_kanban/2`
- the `handle_event("move_todo", ...)` clause
- any helper that was ONLY called by the removed helpers — e.g. `meta_get/2`
  in `plan_live.ex` was the sole accessor used by `kanban_status`; once those
  went, `meta_get/2` had zero callers and had to be deleted too.

Also fix the `{String.capitalize(kanban_status(todo))}` badge spans in the
surviving Todos list — they call the deleted helpers, so replace them (drop the
badge, keep a plain link row).

## 3. Cross-file component rename breaks a reverted LiveView (align to current API)

Concurrent work had renamed the graph component `page_graph` → `graph_3d` in
`lib/<app>_web/components/page_components.ex`, and `graph_3d/1` requires `:class`
and `:style` assigns. When the LiveViews were reverted to an older commit that
still rendered `<.page_graph ...>`, the whole project failed to compile with
`undefined function page_graph/1`. Fix: update the reverted LiveViews to the
current component:

```heex
<.graph_3d id="plan-page-graph" nodes={@graph_nodes} edges={@graph_edges}
  class="w-full" style="height: calc(100vh - 200px);" />
```

Rule: when a revert re-introduces references to a function the current codebase
no longer exports, do NOT re-add the old component — align the reverted file to
the current component API (check `search_files "def <name>|<newname>"
components/` to find the replacement).

## 4. Sibling subagent reverted the shared files mid-task (recover, don't panic)

A parallel subagent (`sa-0-62f4e530`) edited the SAME LiveViews and at one point
ran `git checkout`, reverting all three target files to HEAD — wiping the first
pass entirely. Detection: after an edit, `patch` started reporting
`file modified by sibling subagent`; `git status --short` no longer listed the
three files (they matched HEAD again); `git diff HEAD -- <file>` was empty.

Recovery:
1. Confirm revert: `git diff HEAD --stat -- <files>` empty + file line counts
   back to their ORIGINAL sizes.
2. Re-apply your removal from the clean baseline, one file at a time.
3. Compile after each file (`mix compile --warnings-as-errors`) — if the compile
   surfaces errors that are NOT kanban-related (e.g. `page_graph/1 undefined`,
   `health_class/1 unused` from the sibling's half-finished edits), fix them to
   get a green tree, but keep your own scope (kanban) clean.
4. The sibling's unrelated changes (community-summary insights, `graph_3d`) are
   NOT yours to remove — only touch what your task owns, plus what's needed to
   compile.

Verification end-state (this session): `grep -n "kanban\|move_todo\|count_kanban"`
on each touched file → goal_live: 0 refs, plan_live: 0 refs, project_live: only
the intentional `~p"/kanban?project=..."` link to the standalone global kanban
page (kept — it's a link to a live route, not internal board code). `mix compile
--warnings-as-errors` exits 0.
