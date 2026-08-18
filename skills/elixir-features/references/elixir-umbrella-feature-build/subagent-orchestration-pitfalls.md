# Subagent Orchestration Pitfalls — Plan Execution

Concrete failure modes observed when executing a multi-task audit plan (24 tasks)
via parallel `delegate_task` batches on a real Phoenix codebase. These are
process pitfalls, not code pitfalls — the code-level patterns live in
`code-audit-patterns.md`.

## 1. Plan Validation Before Execution (highest leverage step)

A plan written in a prior session (or by another agent, or generated from a
code audit) is **stale by default**. Before dispatching a single subagent,
verify every factual claim in the plan against the live codebase:

| Plan claim | Verification | Real finding (my_app audit) |
|---|---|---|
| "3 copies of slugify" | `search_files "defp slugify"` | **7 copies** (4 partial + 3 full) |
| "ts_headline escapes HTML" | Read `brain.ex` fragment options | **False** — no `EscapeAll=true`; XSS fix needs sanitizer, not `raw()` removal |
| "list_pages needs pagination" | Read `brain.ex:85-92` | **Already has** `limit: 50` default |
| "ETS cache fixes re-render" | Check `render_markdown/2` inputs | Cache key misses `inline_links`/`embeds` → **stale HTML bug** |
| "Queue needs Oban persistence" | Read `inference/queue.ex` | Queue is a **permit serializer**, not a job queue — nothing to persist |

**Procedure:**
1. For every "Files: Modify X:NN" line in the plan, `read_file` that range.
2. For every duplication claim, `search_files` the symbol.
3. For every "backend already supports Y" claim, read the function signature.
4. Write a `*-v2.md` plan with a corrections table, dispatch from THAT.

Cost: ~10 tool calls. Savings: 3 of 24 tasks in the my_app audit would have been
executed wrong or were unnecessary.

## 2. Commit Races in Parallel Batches

Leaf subagents share the parent's working tree and git index. When N subagents
each end with `git add <files> && git commit`, they race:

**Observed failure (5 parallel bug-fix subagents):**
- Subagent A (fastest) committed `b372a47` containing **its own change + B's + C's + D's + untracked plan files**.
- Subagent C reported "the fix is committed at `b372a47` but under the wrong message."
- Subagent E reported "nothing to commit — the change was already applied" (because A bundled it).
- History: one commit with 4 tasks instead of four commits with one task each.

**Recovery procedure (safe when commits are unpushed):**
```bash
git log --oneline origin/main..HEAD        # confirm local-only commits
git reset --soft origin/main               # keep all changes, unstage
git reset                                  # unstage everything
# Re-commit per task with correct messages:
git add lib/.../page_detail_component.ex
git commit -m "refactor: remove dead PageDetailComponent module"
git add lib/.../html_sanitizer.ex lib/.../search_live.ex test/.../html_sanitizer_test.exs
git commit -m "fix(security): sanitize search excerpts ..."
# ... repeat per task
git status --short                         # must be empty at the end
```

**Prevention options (pick one):**
1. **Serial dispatch for committing tasks** — parallel only for read-only analysis.
2. **Parent commits, subagents don't** — instruct subagents to leave changes uncommitted; the parent verifies each task's files and commits. Cleanest history, slight parent overhead.
3. **Exact `git add` file lists in the prompt** — reduces cross-contamination but doesn't prevent bundling (A still commits B's staged-but-uncommitted files if they overlap in timing).

## 3. Timeouts Leave Uncommitted Work

A `status=timeout` subagent may have done 90% of the work. Observed: two
subagents (slug extraction, page-types centralization) timed out at 600s with
49-69 API calls — their changes were **in the working tree but never committed**.

**Post-timeout procedure:**
```bash
git status --short          # M/?? entries from the timed-out task
mix compile --warnings-as-errors   # does the tree still work?
# If complete: verify + commit it yourself, don't re-dispatch
# If half-written: finish manually (you have more context than a fresh subagent)
```

Never re-dispatch the same task blind — check the tree first.

## 4. Untracked New Files

Subagents that create new modules often forget `git add` on the new file while
committing modifications to existing ones. Observed: `page_types.ex` created but
left `??` untracked — the next batch's compile failed with "module PageTypes is
not available" because the file was never staged into a commit.

**Rule:** after every batch, `git status --short` and look for `??` entries
that should be tracked. Add them to the matching commit (amend if still HEAD).

## 5. Post-Batch Parent Fix-Up Is Normal

Subagents that remove duplicated code (extract-to-module tasks) reliably leave:

- **Unused imports** in files that called the old functions
  (`import DranWeb.PageComponents, only: [type_path: 1]` after `type_path`
  moved to `PageTypes` → `--warnings-as-errors` fails).
- **Straggler call sites** in files the subagent wasn't told about
  (`page_list_components.ex` used `type_plural/1` and `type_path/1` but wasn't
  in the original task's file list).

**Between batches, always:**
```bash
mix compile --warnings-as-errors   # catch unused imports + missing refs
PORT=<free_port> mix test          # catch behavior breakage
```

Fix these yourself — they're 2-minute fixes, and a fresh subagent has less
context than you.

## 6. `mix precommit` / dev-server Port Collisions in Parallel Runs

`config/runtime.exs` binding a fixed port (4000) makes `mix precommit` fail for
every subagent after the first when run concurrently (endpoint tries to boot).
Mitigation used in the my_app audit: `PORT=4099 mix test` / `PORT=4099 mix precommit`.
When writing subagent prompts for Phoenix projects, always include the `PORT=`
prefix in the verification commands, or fix `runtime.exs` to not force
`server: true` outside prod.

## 7. When You Are the Subagent (phase-execution discipline)

The sections above are written for the **parent** orchestrating subagents. This section is for when you **are** the subagent dispatched to execute one phase of a plan with file-scoped constraints (e.g. "implement tasks 2.1-2.5 ONLY in `lib/my_app/brain.ex`").

The plan's code is idealized — it may not match the codebase's actual API surface. This is the most common source of silent breakage in phase-by-phase execution.

Discipline that prevents it:

1. **Read the cited plan sections first.** If the task says "implement §3.2 and §9.6", read those sections before writing anything. The task summary drops nuances the full section carries (e.g. the SQL-vs-in-memory variant choice in §9.6 was only visible by reading the section).
2. **Verify every function the plan's code calls actually exists** with `search_files` before using it. Plans frequently reference helpers by names that are *close but wrong*:
   - Plan said `fetch_page_by_slug/2` → actual function was `get_page_by_slug/2` (same module, different name).
   - Plan said `PageMeta.meta_get/2` → function didn't exist anywhere in the codebase.
   Adapt to the real name instead of creating a duplicate — duplicates silently shadow the intended function or fail with "redefining module" warnings.
3. **If the plan references a helper that doesn't exist anywhere**, create a minimal local fallback and report it in your summary. Example: a `meta_get/2` that does `Map.get(meta, key)` with atom→string fallback. The parent can promote it to the right module later.
4. **Respect the file boundary strictly.** If the task says "ONLY `lib/foo/bar.ex`", do not touch other files even if you can see they reference functions you just removed. Note the breakage in your summary and let the parent coordinate — another subagent may own that file in parallel. Example observed: a `describe "sync_planning_relations ..."` block in `test/my_app/planning_hierarchy_test.exs` referenced the removed function — flagged in summary, not touched.
5. **Run the verification gate yourself and paste the real output.** For Elixir that's `mix compile --warnings-as-errors` (no `--force`). If it fails with "redefining module" warnings, report it and let the parent decide whether to run `--force` — don't paper over it.
6. **Report three things at the end:** (a) functions added/removed, (b) any helper you had to create or adapt with the reason, (c) the actual compile/test output. The parent needs all three to reconcile parallel work.

The recurring failure mode: a subagent blindly copies the plan's code, creates a `fetch_page_by_slug` that shadows nothing (or conflicts with a later phase), and the build breaks in a way the parent has to debug. Five seconds of `search_files` before writing prevents it.

## 8. Iteration-limit exhaustion: audit done, big file never written

A `status=completed` subagent can still have produced **nothing** if it burned its
whole tool-call budget (~100 calls) on the *read/verify* phase and hit the limit
before writing. Observed (my_app 2026-07-19, plan Phase 3): a subagent told to
"create `project_live.ex` (~500 lines, 6 tabs) + 3 routes + a patch, but first
verify every module the plan references" returned "**NOT completed — blocked
before file creation**" after 100 calls. Its summary was a perfect, verified
analysis (real module names, the right `meta_get` pattern, the DB filter to use,
plus a genuine blocker it found) — but zero lines written.

Unlike the small-patches case (§5), the remaining work was a **large new file** —
too big for the parent to hand-patch without blowing its own context window.

### Recovery: re-dispatch with pre-digested analysis

1. **Paste the prior subagent's verified findings into the new prompt's context** —
   the module table, the exact pattern to copy, the blocker it found. Say
   explicitly: "ANÁLISIS PREVIO YA HECHO — confía en esto, no re-verifiques."
2. **Shrink the scope to a write-only checklist** — "create file X with these 6
   sections, add these 3 route lines, add this 1 clause." No open-ended "verify
   the plan's assumptions."
3. **Name what NOT to touch** — every file already completed in the wave.

Result: the fresh agent wrote the 507-line file + routes + patch in 14 API calls
/ 117s, compile clean, because it spent zero budget re-doing the analysis.

### Which recovery for which stall

| Situation | Recovery |
|-----------|----------|
| Audited, edits are a handful of small patches | Apply them yourself (§5) |
| Audited, deliverable is a big new file / many files | **Re-dispatch with pre-digested analysis** |
| `status=timeout`, files already on disk | Verify + commit (§3) |

### Prevention

The trigger is an over-broad prompt: "create X, **but first** verify every
assumption." For write-heavy tasks, do the verification **on the parent** (or
reuse the prior wave's verified findings) and hand the subagent a write-only
checklist. Every call spent re-verifying is one it can't spend writing.

## Quick Checklist for Plan Execution Batches

- [ ] Plan validated against live code; v2 written with corrections
- [ ] Batch grouped by disjoint files AND by who commits (serial commits)
- [ ] Each subagent prompt: exact file list to `git add`, `PORT=` prefix on mix commands
- [ ] After batch: `git status --short` (untracked?), `git log --stat` (bundled?), `mix compile --warnings-as-errors`, `mix test`
- [ ] Timeouts: check tree before re-dispatching
- [ ] Final: verify history is one-commit-per-task before pushing
