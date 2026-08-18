---
name: data-model-hierarchy-vs-links
description: "Design data models for knowledge work: when to use rigid hierarchies vs independent links, kanban placement, and sidebar organization for GTD-style task management."
version: 1.0.0
author: Álvaro Lizama
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [data-modeling, hierarchy, links, kanban, gtd, knowledge-management]
    related_skills: [plan, elixir-umbrella-feature-build]
---

# Data Model: Hierarchy vs. Links

Use this skill when designing data models for knowledge work, task management, or any system where items can belong to multiple containers.

## The Hierarchy Trap

Rigid hierarchies (`project > goal > plan > todo`) with precedence rules (`plan > goal > project`) create three concrete problems:

1. **Precedence is opaque.** A record with multiple parent slugs set only materializes one relationship; the others become inert metadata. Users believe the record is linked to all three; the database says otherwise. This causes silent bugs in dashboards and filters.

2. **Multiple parents are impossible.** A todo that belongs to a project AND a goal AND a plan must choose one. The model forces a false choice.

3. **Queries get complex.** Resolving precedence requires JOINs or nested conditionals in application code. Extending to new parent types requires rewriting the resolution logic.

## Prefer Independent Links

```
TODO (huérfano o con vínculos opcionales)
  ├── meta.project_slug  →  part_of project  (si seteado)
  ├── meta.goal_slug     →  part_of goal     (si seteado)
  └── meta.plan_slug     →  part_of plan     (si seteado)

Sin precedencia. Los tres son independientes. Un todo puede tener 0, 1, 2 o 3 vínculos.
```

**Benefits:**
- Each slug materializes its own `part_of` relation in the graph
- Sync logic is simple: for each slug, if changed, drop old relation and create new one
- Queries filter by `meta->>'field' = ?` directly on JSONB — no JOINs needed
- New link types are trivial to add (just add a new slug field)

## When to Use Hierarchy

Only when the domain truly requires single-parent trees:
- File systems
- Org charts
- Biological taxonomies

For knowledge work and GTD-style task management, independent links are more expressive and simpler.

## Kanban Placement

**Prefer a single global kanban** over per-container kanbans:

| Anti-pattern | Better |
|-------------|--------|
| Kanban inside GoalLive | Global `/kanban` with filters |
| Kanban inside ProjectLive | Project page shows list + link to filtered kanban |
| 3 LiveViews with ~600 lines each | 1 KanbanLive with filter dropdowns |

**Card design:**
- Badges show at most 2 linked containers, tooltip for the rest
- Color-code by type: blue=project, green=goal, purple=plan
- Click badge to filter kanban by that link

**Filters should be combinable:**
- `project:X AND goal:Y`
- `project:X AND no-goal`
- `inbox` (no links)

## Sidebar Organization for GTD

The canonical grouping — verified against the actual MyApp codebase (`dashboard_live.ex` `@nav_groups`):

```
Dashboard
Planning
  ├── Kanban       ← global board view (todos with filters)
  ├── Projects     ← executive dashboards
  ├── Goals        ← measurable, health, progress; has Todos tab → /kanban?goal=…
  ├── Plans        ← documents, horizon, status; has Todos tab → /kanban?plan=…
  └── Todos        ← list view (NOT a board — see pitfall below)
Knowledge
  ├── Notes
  ├── Concepts
  ├── Entities
  └── References
Outputs
  ├── Artifacts
  └── Comparisons
Agents           (Research, Ingest)
System           (Contexts, Settings, Docs)
```

**Key decisions (corrected):**
- Kanban is top-level under Planning (most used view)
- Projects is top-level under Planning (executive dashboard)
- **Goals and Plans live under Planning, NOT Knowledge.** They have Todos tabs, link to `/kanban?goal=…`/`?plan=…`, and drive execution. Calling them "concepts" contradicts their own behavior. (Earlier version of this skill placed them under Knowledge — that was wrong and caused a regression in the actual sidebar — see `references/ia-audit-findings.md` §1.2.)
- Todos appear in the sidebar under Planning as the LIST view; Kanban is the BOARD view. Do not put two board UIs in the sidebar (see pitfall).
- Activity, Graph, Search are secondary views — reachable from the dashboard header or command palette, not necessarily in the sidebar.

### Pitfall: sidebar groups drifting from dashboard groups

If the dashboard `@nav_groups` and the sidebar `sidebar_nav/1` groups disagree, the IA is incoherent — users learn one grouping on the dashboard and a different one in the nav. **Keep them as a single source of truth.** In MyApp, `dashboard_live.ex:14-66` and `layouts.ex:179-328` duplicate the grouping by hand and have drifted: the dashboard correctly groups Goals/Plans/Todos under "Planning", while the sidebar (`layouts.ex:244-257`) buries Goals/Plans under "Knowledge". When you change one, change both — or extract a shared `DranWeb.NavGroups` module.

### Pitfall: `active_nav` coverage gaps

Sidebar highlighting only works if every LiveView sets `active_nav` in `mount`/`handle_params` and the value matches a `key` in `sidebar_nav`. Common regression: 13 of ~23 MyApp LiveViews don't set it, so the sidebar goes dark on the most-used pages (notes, concepts, entities, goals, plans, todos, projects, references, artifacts, comparisons, queries, page_new, ingest). When you add a sidebar item, audit every LiveView that should highlight it — grep for `active_nav:` and cross-check.

## Metadata Patterns

| Type | Own fields | Optional links |
|------|-----------|----------------|
| **Todo** | kanban_status, priority, due_date | project_slug, goal_slug, plan_slug |
| **Project** | status, priority, health, health_source, dates | — |
| **Goal** | health, metric, target_value, current_value, unit, progress, due_date | project_slug |
| **Plan** | horizon, period, status, due_date | project_slug, goal_slug |
| **Note** | kind, date, author | due_date (if kind=reminder) |

**Derived fields:**
- Project health = average of linked goals' health (floor, conservative)
- Goal progress = % of linked todos completed
- Plan auto-suggests done when all linked todos are done

## Auditing Navigation & IA

When asked to audit navigation / information architecture for UX friction in a Phoenix + LiveView second-brain app like MyApp, the workflow that produced a high-quality report:

1. **Read the four canonical surfaces end-to-end first:** the layout module (sidebar + command palette mount), the router (all routes), the dashboard LiveView (its `@nav_groups` is a second copy of the sidebar IA), and the command palette component. Don't skim — the contradictions live in details.
2. **Cross-check sidebar grouping vs. dashboard grouping.** They are usually hand-duplicated and drift. The dashboard often models the *correct* IA; the sidebar is the regression. Cite both `dashboard_live.ex` and `layouts.ex` line numbers side by side.
3. **Grep for `active_nav:` across all LiveViews** and cross-check against `sidebar_nav` keys. Any LiveView that doesn't set it is a broken highlight. Also grep `counts[:<key>]` in the layout vs. what `compute_counts/1` actually populates — dead badges hide here.
4. **For each nav item, verify the route exists in the router AND that the sidebar is the only way to reach it.** Orphan routes (fully wired LiveViews with no sidebar entry) are a common finding — `grep` `live "` in `router.ex` and diff against `path:` entries in `sidebar_nav`.
5. **Count kanban-board implementations.** Search for `id="kanban-board"` and `@kanban_columns` across the codebase. If >1, you have duplicated board UIs over the same data model — flag for consolidation.
6. **Count search surfaces.** Sidebar form + command palette + `/search` page is the typical triplication. Check whether the `⌘K` hint in the sidebar actually opens the palette or just submits the form — misleading kbd labels are a real finding.
7. **Grep for breadcrumbs and recents.** `breadcrumb|recent_pages|recently_viewed|history` returning 0 hits is the finding. Count how many LiveViews reimplement "Back" buttons by hand (`hero-arrow-left` + `gettext("Back")`) — that number is the duplication pain.
8. **Report format that lands well:** numbered sections (1) sidebar vs. usage, (2) redundancy, (3) missing affordances, (4) concrete proposals with effort S/M/L. Cite `file:line` for every claim. End with a summary table: `# | proposal | effort | severity | file:line`.

Full session-specific evidence (file:line citations, the 9 proposals P1–P9, the active-nav coverage table) is in `references/ia-audit-findings.md`.

### Pitfall: multiple search surfaces with a misleading ⌘K hint

A sidebar search form that displays a `<kbd>⌘K</kbd>` badge but actually submits a GET to `/search` (not opening the command palette) is a usability trap — users press ⌘K expecting the input to focus, and a separate overlay opens instead. Either wire ⌘K to focus the sidebar input (and show inline results), or remove the kbd badge. Don't ship both a sidebar form and a command palette that duplicate `Brain.search/2` calls without a clear division of labor (palette = fast overlay, 8 results; `/search` page = full strategy selector).

### Pitfall: too many "knowledge buckets" with no distinct fields

If Notes, Concepts, Entities, References all map to `page_type` strings on the same schema and the shared `page_detail` component renders them identically (no per-type form fields — no entity "organization" field, no concept "definition" field), the user pays N sidebar slots for what is functionally 1-2 page types. Either add genuine distinguishing fields per type, or collapse weak types into Notes with a `page_type` filter chip on the index page.

## References

- `references/MyApp-v6-data-model.md` — Complete case study of migrating from hierarchy to links in MyApp (schema diff, sync_todo_links implementation, migration SQL verified against the actual plan)
- `references/kanban-ui-patterns.md` — Badge design, filter UX, drag-drop implementation
- `references/updating-MyApp-docs-content.md` — Workflow for updating MyApp's in-app docs (`docs_content.ex` module of static string attributes) when the data model changes, including the "don't touch docs_live.ex" constraint pattern
- `references/ia-audit-findings.md` — Concrete findings from a full navigation/IA UX audit of MyApp (file:line evidence, 9 proposals P1–P9, active-nav coverage table, orphan-route list). Use as a template for the next IA audit of the same app.
