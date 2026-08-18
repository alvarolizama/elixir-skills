# The `active_nav` Sweep — Worked Recipe

Full trace of a sweep that fixed sidebar highlighting across 14 LiveViews in
the my_app Phoenix app. The sidebar (`layouts.ex` → `sidebar_nav/1`) defines a
fixed set of nav keys (`panel/dashboard`, `kanban`, `projects`, `graph`,
`activity`, `notes`, `concepts`, `entities`, `goals`, `plans`, `references`,
`artifacts`, `comparisons`, `research`, `ingest`, `contexts`, `settings`,
`docs`, `collections`, `todos`). Each LiveView must set `active_nav` to the
matching key AND forward it via `<Layouts.app active_nav={@active_nav}>` for
the highlight to fire.

## The three bug classes found in one sweep

1. **Missing assign + missing forwarding** (12 LiveViews): `note_live`,
   `concept_live`, `entity_live`, `goal_live`, `plan_live`, `reference_live`,
   `project_live`, `artifact_live`, `comparison_live`, `ingest_live`,
   `page_new_live`, `todo_live`. All compiled and rendered fine — the
   `default: nil` on the attr masked the missing wiring.

2. **Mismatched key** (2 LiveViews):
   - `tag_live.ex` set `active_nav: "tags"` — no sidebar entry exists for
     tags. Fix: remove the assign AND the render forwarding (the attr defaults
     to nil, which is correct for a page that shouldn't highlight any nav).
   - `agent_live.ex:421` set `active_nav: "agents"` in `mount` — no sidebar
     entry for agents. A per-type override in `agent_type_label/1` later set
     it to `"research"` or `"ingest"` (which exist), so the mount value was
     dead. Fix: remove the dead assign from mount; the per-type override
     stays.

3. **Skipped (no sidebar entry)**: `query_live.ex` — queries have no sidebar
   nav item, so no `active_nav` should be set. Explicitly out of scope.

## Diagnosis — the three-way grep

```bash
# 1. What keys does the sidebar know? (the valid value set)
search_files 'key: "' path=lib/dran_web/components/layouts.ex

# 2. Which LiveViews set the assign?
search_files 'active_nav:' path=lib/dran_web/live

# 3. Which LiveViews forward the attr in render?
search_files 'active_nav=' path=lib/dran_web/live
```

- Files in (2) but not (3) → missing forwarding (bug class 1).
- Files in (3) but not (2) → dangling forwarding (hits `default: nil`).
- Values in (2) not present in (1)'s key set → mismatch (bug class 2).

## The patch pattern (for each missing-assign LiveView)

Two edits per file, both required:

### Edit 1 — add the assign in `mount/3`

```elixir
# before
{:ok,
 assign(socket,
   context: context,
   page_type: @page_type,
   tabs: @tabs,
   active_tab: "content",
   editing: false,
   save_status: "idle"
 )}

# after
{:ok,
 assign(socket,
   context: context,
   page_type: @page_type,
   tabs: @tabs,
   active_tab: "content",
   editing: false,
   save_status: "idle",
   active_nav: "notes"      # <- the sidebar key for this page type
 )}
```

The key is the **plural sidebar key** (`"notes"`, `"concepts"`, `"entities"`,
`"goals"`, `"plans"`, `"references"`, `"projects"`, `"artifacts"`,
`"comparisons"`, `"ingest"`, `"todos"`), NOT the page_type string
(`"note"`, `"concept"`, ...). The sidebar uses plural keys; `page_type` is
singular.

### Edit 2 — forward the attr in `render/1`

```heex
# before
<Layouts.app
  flash={@flash}
  current_scope={@current_scope}
  current_user={@current_user}
  context_slug={@context_slug}
  contexts={@contexts}
>

# after
<Layouts.app
  flash={@flash}
  current_scope={@current_scope}
  current_user={@current_user}
  context_slug={@context_slug}
  contexts={@contexts}
  active_nav={@active_nav}
>
```

## The `PageNewLive` variant (type-derived key)

`PageNewLive` is a generic LiveView that handles `/notes/new`,
`/concepts/new`, `/plans/new`, etc. The `active_nav` must match the page type
being created, which is derived from the URL in `handle_params`. Use
`PageTypes.path/1` which returns the plural key:

```elixir
# mount — default before handle_params runs
{:ok,
 assign(socket,
   ...,
   active_nav: "notes"   # default; handle_params overrides per-type
 )}

# handle_params — derive from the resolved page_type
{:noreply,
 assign(socket,
   page_type: page_type,
   back_path: back_path,
   ...,
   active_nav: PageTypes.path(page_type)   # "notes" | "concepts" | "plans" | ...
 )}
```

This is the one case where the assign belongs in `handle_params`, not `mount`
— the value depends on the URL, which isn't known until `handle_params`.

## The concurrent-edit constraint

If a sibling subagent or parent process owns one of the files in the sweep
(e.g. the parent is adding the `todos` sidebar key to `todo_live.ex`
concurrently), add ONLY the `active_nav` assign to that file — nothing else.
The parent's edit will add the render forwarding. Document this in the report:

```
- todo_live.ex — active_nav: "todos" in mount only (render not touched;
  parent owns this file concurrently and will add the forwarding)
```

The patch tool will warn ("modified by sibling subagent") if the file changed
between your read and your write — re-read and re-apply if so.

## The mismatch-removal pattern

For a LiveView that sets `active_nav` to a non-existent sidebar key:

1. Remove the assign from `mount` (or wherever it's set).
2. Remove `active_nav={@active_nav}` from the `<Layouts.app>` render call —
   otherwise the render references an undefined assign and crashes at
   runtime (HEEx raises on `@undefined_assign` unless the attr has a
   default, which `active_nav` does — `default: nil`. So it won't crash, but
   leaving the forwarding dangling is misleading and should be cleaned up.)

Exception: if another code path (e.g. a per-type override in
`handle_params`) sets the assign later, keep the render forwarding and remove
only the dead mount assign. This is the `agent_live.ex` case — the mount
sets `"agents"` (dead), but `handle_params` → `agent_type_label/1` sets
`"research"` or `"ingest"` (live). Remove the mount value; keep the render
forwarding and the per-type override.

## Verification

```bash
# 1. Compile — must pass with no NEW warnings
eval "$(mise env)" && mix compile

# 2. Re-run the three-way grep to confirm coverage
search_files 'active_nav' path=lib/dran_web/live   # every LV should now have
                                                   # both the assign and the forwarding

# 3. Spot-check the sidebar key set matches the assigned values
search_files 'key: "' path=lib/dran_web/components/layouts.ex
```

Pre-existing warnings in files you're forbidden to touch (e.g.
`kanban_live.ex` has unused module attributes) are not your concern — don't
fix them, don't report them as failures.

## Report format

The user wants a per-file list, not a narrative. Use this shape:

```
**Adds (assign + render forwarding):**
- note_live.ex — active_nav: "notes" in mount + active_nav={@active_nav} in render
- concept_live.ex — ...
(list every file that got both edits)

**Removes (mismatches):**
- tag_live.ex — removed active_nav: "tags" assign + render forwarding (no sidebar key)
- agent_live.ex — removed dead active_nav: "agents" from mount (per-type override stays)

**Untouched (as instructed):** layouts.ex, dashboard_live.ex, kanban_live.ex.
query_live.ex skipped (no sidebar entry for queries).

**Verification:** mix compile passes (exit 0); only pre-existing kanban_live.ex
warnings remain.
```

The "Untouched" line is load-bearing — it lets the user cross-check against
their constraint list and confirms you respected the file-level exclusions.
