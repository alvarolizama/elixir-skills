# Updating my_app's in-app docs (docs_content.ex)

Use when a task asks to update my_app's in-app documentation to reflect a new
model, feature, or schema change. my_app keeps its doc strings in a **plain
Elixir module** (`lib/dran_web/docs_content.ex`) of module attributes, consumed
by `lib/dran_web/live/docs_live.ex` via public accessor functions. This
separation exists because HEEx `~H"""` templates cannot contain nested
triple-quoted heredocs.

## Architecture

```
docs_content.ex                    docs_live.ex
─────────────────                  ─────────────
@planning_hierarchy_diagram  ──►   DranWeb.DocsContent.planning_hierarchy_diagram()
@agent_connect_example       ──►   DranWeb.DocsContent.agent_connect_example()
@auth_api_curl                ──►   DranWeb.DocsContent.auth_api_curl()
@<new_attr>                   ──►   DranWeb.DocsContent.<new_attr>()
```

- `docs_content.ex` = **static strings only** (module attributes + accessor
  functions). No HEEx, no assigns, no rendering logic.
- `docs_live.ex` = the LiveView that renders those strings inside
  `<.code_block code={...} />` components, plus the narrative prose around
  them.

## When to touch which file

| Change | Touch |
| --- | --- |
| Rewrite a code sample / diagram / ASCII art shown in a `<.code_block>` | `docs_content.ex` only |
| Add a new code sample for a new feature | `docs_content.ex` (add attr + accessor) + `docs_live.ex` (add `<.code_block>` to render it) |
| Change the prose around a code block (narrative, headings, TOC) | `docs_live.ex` only |
| Fix a factual claim about page types, meta fields, statuses | Both — the prose in `docs_live.ex` AND any code sample in `docs_content.ex` |

**Constraint to respect:** if a task says "NO toques código .ex fuera de
docs_content.ex", then you can only edit `docs_content.ex`. In that case you
rewrite the existing module attributes and ADD new ones (with public accessor
functions), but you do NOT wire them into `docs_live.ex` — that's a follow-up
task. The new accessors compile fine even if nothing calls them yet.

## Workflow

1. **Read both files first.** `read_file` on `docs_content.ex` (small, ~50
   lines) and the relevant section of `docs_live.ex` (large, ~1500 lines —
   use `search_files` to find the section by keyword: `planning`, `kanban`,
   `goal`, `todo`, `page-types`).

2. **Identify the module attributes that need rewriting.** As of the v6
   rewrite, `docs_content.ex` has these attributes:
   - `@agent_connect_example` — MCP connection snippet
   - `@auth_api_curl` — REST API auth curl example
   - `@planning_hierarchy_diagram` — ASCII diagram of the planning model
   - `@planning_model_overview` — prose overview of the planning model
   - `@project_page_type` — the `project` page type documentation
   - `@global_kanban_doc` — the `/kanban` global board documentation
   - `@manual_flags_doc` — `progress_manual` / `health_source` flags
   - `@reminder_note_kind_doc` — the `reminder` note kind
   - `@plan_statuses_doc` — corrected plan statuses (no on_hold/completed)
   - `@goal_metrics_doc` — goal metric fields and auto-progress

3. **Rewrite the attribute string(s)** using `write_file` (full file rewrite)
   or `patch` (targeted replacement). Each attribute is a triple-quoted
   heredoc — preserve the closing `"""` alignment.

4. **Add a public accessor function** for every new attribute:
   ```elixir
   def planning_model_overview, do: @planning_model_overview
   ```

5. **Update the `@moduledoc`** if the module's purpose or the model it
   documents has changed. Keep it short — point to the canonical accessor
   functions.

6. **Verify:**
   ```bash
   cd ~/Repos/my_app
   mix compile --warnings-as-errors   # must be clean (0 warnings)
   PORT=4099 mix test                 # must pass (280 tests as of v6)
   ```
   `docs_content.ex` is a plain Elixir module — if it doesn't compile, the
   whole app fails. The most common compile failure is a malformed heredoc
   (unbalanced `"""` or a `"""` not on its own line).

7. **Report** the sections touched, the diff size (`git diff --stat`), and the
   verification output (compile + test results).

## Pitfalls

1. **Touching `docs_live.ex` when told not to.** The task constraint "NO
   toques código .ex fuera de docs_content.ex" is real — `docs_live.ex` may
   be being edited in parallel by another subagent. Only edit
   `docs_content.ex` in that case.

2. **Forgetting the accessor function.** A module attribute without a public
   function is invisible to `docs_live.ex`. Every `@attr` needs a
   `def attr, do: @attr`.

3. **Breaking the heredoc.** Triple-quoted strings in Elixir must close with
   `"""` on its own line (or at end of line). A `"""` mid-line or indented
   wrong causes a compile error. If `mix compile` fails, check heredoc
   closure first.

4. **Documenting stale facts.** Before writing about page types, meta fields,
   or statuses, verify against the actual schema
   (`lib/my_app/brain/page_meta.ex`) and validation attrs
   (`@project_statuses`, `@plan_statuses`, `@note_kinds`, etc.). The
   `references/auditing-this-skill.md` file in the `second-brain` skill has
   the full verification map.

5. **Not running the tests.** `mix compile` alone is not enough —
   `docs_content.ex` is consumed by `docs_live.ex` which has LiveView tests.
   Run `PORT=4099 mix test` (port override avoids conflicts with a dev
   server on 4000).

6. **Leaving old model references.** When rewriting for a new model, grep
   the file for old terminology (e.g. "on_hold", "completed", "precedence",
   "derived from plan") and remove ALL of them — not just the obvious ones.

## Verification commands (copy-paste ready)

```bash
# Compile with warnings as errors (must be clean)
cd ~/Repos/my_app && mix compile --warnings-as-errors

# Full test suite (port 4099 to avoid dev server conflict)
cd ~/Users/alvaro/Repos/my_app && PORT=4099 mix test

# Diff stat for the report
cd ~/Repos/my_app && git diff --stat lib/dran_web/docs_content.ex

# Confirm only docs_content.ex was touched (no other .ex files)
cd ~/Repos/my_app && git status --short
```

## Example: the v6 planning model rewrite (2026-07-19)

Task 4.1 of the v6 plan asked to rewrite `docs_content.ex` to reflect the new
planning model (independent links, project page type, global kanban, derived
health, auto-progress, reminder note kind, corrected plan statuses).

**What was done:**
- Rewrote `@planning_hierarchy_diagram` (was the only planning-related attr;
  now reflects independent links, no precedence, "none" convention, sidebar).
- Added 7 new attributes: `@planning_model_overview`, `@project_page_type`,
  `@global_kanban_doc`, `@manual_flags_doc`, `@reminder_note_kind_doc`,
  `@plan_statuses_doc`, `@goal_metrics_doc`.
- Updated `@moduledoc` to point to the v6 model.
- Did NOT touch `docs_live.ex` (per task constraint) — the new accessors
  compile fine even though nothing renders them yet; wiring them into the
  LiveView is a follow-up task.

**Diff size:** 283 insertions, 12 deletions (295 lines in the diff).

**Verification:** `mix compile --warnings-as-errors` clean; `PORT=4099 mix
test` → 280 passed, 0 failures.

**Corrections applied to old model:**
- Removed precedence `plan > goal > project` and "goal derived from plan".
- Removed plan statuses `on_hold` and `completed` (now `draft|active|done|archived`).
- Removed `/todos` as kanban home (now `/kanban`).
- Removed Project/Goal/Plan as "hierarchical containers" (now knowledge pages).
