# IA / Navigation UX Audit Findings — my_app

Session-specific evidence from a full navigation/IA audit of my_app (2026-07-19). Use as a template for the next IA audit of the same app — the file:line citations will drift as code changes, but the categories of finding (sidebar vs. dashboard drift, kanban duplication, search triplication, missing breadcrumbs/recents, active_nav gaps, orphan routes) recur.

## 1. Sidebar structure vs. usage

### 1.1 Sidebar inventory
`layouts.ex` `sidebar_nav/1` (`layouts.ex:176-365`): 6 groups, 16 items.
- (unnamed top, `:179-219`): Dashboard, Kanban, Projects, Graph, Activity — all with counts.
- Knowledge (`:221-265`): Notes, Concepts, Entities, **Goals**, **Plans**, References — all with counts.
- Outputs (`:268-284`): Artifacts, Comparisons.
- Agents (`:287-301`): Research, Files Ingest — no counts.
- Configs (`:304-320`): Contexts, Settings.
- Docs (`:322-327`): Documentation.

Dashboard `@nav_groups` (`dashboard_live.ex:14-66`) is a **second, parallel** copy with a different grouping: Top / Knowledge / Planning / Outputs. Goals/Plans/Todos live under "Planning" here.

### 1.2 Goals & Plans mis-bucketed (CONFIRMED)
- `layouts.ex:244-257` places Goals/Plans under **Knowledge**.
- `dashboard_live.ex:42-53` correctly groups them under **Planning** with Todos.
- Both GoalLive and PlanLive expose a Todos tab with `/kanban?goal=…` / `?plan=…` links (`goal_live.ex:19-20,226`; `plan_live.ex:15,152`). They are planning entities, not knowledge.
- `@kanban_columns` is duplicated 3× (`dashboard_live.ex:68-76`, `todo_live.ex:21-28`, `kanban_live.ex:11-18`) — same six statuses, confirming one planning workflow.

### 1.3 The "Top" group is a kitchen sink
`layouts.ex:179-219` mixes Dashboard (entry), Kanban (board), Projects (entity), Graph (viz), Activity (log) — no shared concept. Graph/Activity/Search are reachable from the dashboard header (`dashboard_live.ex:101-112`) and are secondary.

### 1.4 Active-nav highlighting is inconsistent
Pages that set `active_nav` (10): activity, settings, smart_collections, search, tags, docs, agents/research, agents/ingest, graph, kanban, contexts.

Pages that do NOT set `active_nav` (≈13): dashboard, notes, concepts, entities, goals, plans, todos, references, projects, artifacts, comparisons, queries, page_new, ingest. The sidebar goes dark on the most-used surfaces.

Dead badge: `counts[:settings]` referenced at `layouts.ex:318` but never populated by `compute_counts/1` (`layouts.ex:141-157`).

### 1.5 Two nav items point nowhere useful
- Sidebar "Files Ingest" → `/agents/ingest` (`layouts.ex:299`) but there is also a separate `/ingest` route (`router.ex:168`) rendering `IngestLive`. Two ingest UIs. `IngestLive` doesn't set `active_nav` (`ingest_live.ex:22`).
- "Documentation" (`layouts.ex:325`) is a single static page over-weighted as a top-level group.

### 1.6 Routes that exist but are unreachable from the sidebar
- `/queries` (`router.ex:119-121`) — fully wired, no sidebar entry, not in dashboard Quick Access.
- `/collections` (`router.ex:164-166`) — sets `active_nav: "collections"` but no sidebar item matches.
- `/ingest` (separate from `/agents/ingest`).
- `/tags/:tag` (`router.ex:161`) — sets `active_nav: "tags"`, no sidebar entry.

## 2. Redundancy

### 2.1 FOUR kanban boards over the same Todo data (HIGH)
- `/todos` → `TodoLive` `:index` renders `id="kanban-board" data-testid="todo-board"` (`todo_live.ex:54-55`), full 6-col drag-drop.
- `/kanban` → `KanbanLive` renders `id="kanban-board"` same 6 cols (`kanban_live.ex:86`) plus project/goal/plan filters (`:46-67`).
- ProjectLive embeds a Kanban tab (`project_live.ex:30 @kanban_columns`, `:332` board) plus "View in Kanban" link (`:62`).
- GoalLive/PlanLive embed Todos tabs that link to `/kanban?goal=…` (`goal_live.ex:226`, `plan_live.ex:152`).

All share the same `@kanban_columns` constant, the same `KanbanDragDrop`/drag-drop JS pattern, the same `kanban_status` meta key. `/todos` is a strict subset of `/kanban`.

### 2.2 Too many "knowledge buckets" — concept overlap
Sidebar Knowledge group has 6 buckets: Notes, Concepts, Entities, Goals, Plans, References (`layouts.ex:221-265`). All are `page_type` strings on the same `Brain.Page` schema (confirmed via `compute_counts/1` reading `stats[:by_type]` at `layouts.ex:142-156`).

Notes/Concepts/Entities share the same `page_detail` component (`page_components.ex:27`) with no per-type form fields — only icon differs. Concepts and Entities are weakly distinguished.

### 2.3 Search box vs command palette (partial duplication)
Three search surfaces:
1. **Sidebar form** (`layouts.ex:82-97`): GET to `/search?q=…`, full-page nav. Has `<kbd>⌘K</kbd>` hint (`:93-95`) implying it opens the palette — it doesn't.
2. **Command palette** (`command_palette.ex:1-285`): `⌘K` overlay, debounced search (`:73`), 8 results (`:261`), 7 static quick actions (`:15-23`). Uses `Brain.search/2` (`:264`).
3. **`/search` page** (`search_live.ex`): strategy selector Auto/FTS/Semantic/Hybrid (`:17-22`), example chips (`:199`).

Sidebar `<kbd>⌘K</kbd>` is misleading — it sits inside the form but opens a separate overlay via a hook.

## 3. Missing navigation affordances

### 3.1 No breadcrumbs
`grep breadcrumb` across `lib/dran_web` → 0 hits. `page_detail` (`page_components.ex:27-100`) shows a metadata bar (type · slug · created · updated) but no path.

### 3.2 Back button is inconsistent and per-page
13 LiveViews reimplement "Back" as a hard-coded link inside `<:actions>`:
- `note_live.ex:34-36` → `~p"/notes"`
- `todo_live.ex:217-218` → `~p"/todos"`
- `reference_live.ex:34`, `concept_live.ex:35`, `entity_live.ex:35`, `artifact_live.ex:35`, `comparison_live.ex:35`, `plan_live.ex:40-42`, `goal_live.ex:47`, `project_live.ex:60`, `query_live.ex:35`, `page_new_live.ex:31`, `smart_collection_live.ex:116`.

This is "Back to list", not true browser-history back. Reaching a note via Graph → "Back" loses graph context.

### 3.3 No "recently viewed pages"
`grep recent_pages|recently_viewed|history` → only `pages_this_week` (a metric). No recents list. Dashboard has "Recently Updated" (`dashboard_live.ex:339-384`) — updated, not viewed. Command palette `@quick_actions` (`command_palette.ex:15-23`) is static, no recents slot.

### 3.4 No "back to list" from many flows
Tag page (`/tags/:tag`) has no back button (`tag_live.ex:55-108`). `/search` results have no back. `/graph/:slug` detail has no breadcrumb back to `/graph`.

### 3.5 No active-state on detail pages
Viewing `/notes/some-slug`, sidebar "Notes" is NOT highlighted (`note_live.ex:14-22` doesn't pass `active_nav`).

## 4. Proposals (effort: S <half day, M 1-2 days, L 3+ days)

| # | Proposal | Effort | Severity | Key file:line |
|---|---|---|---|---|
| P1 | Delete duplicate kanban board (make `/todos` list-only, keep `/kanban` as board) | M | HIGH | `todo_live.ex:21-100`, `kanban_live.ex:11-18`, `project_live.ex:30-413` |
| P2 | Re-group sidebar (Planning bucket, align with dashboard) | S | HIGH | `layouts.ex:179-328` |
| P3 | Unify search (sidebar input + inline results, delete palette or repurpose) | M | MED | `layouts.ex:82-97`, `command_palette.ex:1-285`, `search_live.ex:84-156` |
| P4 | Add breadcrumbs to `page_detail`, replace 13 Back buttons | S | HIGH | `page_components.ex:27`, 13 `*_live.ex` |
| P5 | Fix `active_nav` coverage on 13 LiveViews; delete dead `counts[:settings]` | S | MED | 13 LiveViews; `layouts.ex:318` |
| P6 | Add Recently-viewed surface (dashboard + palette slot) | M | MED | `dashboard_live.ex`, `command_palette.ex:15-23` |
| P7 | Collapse Concept/Entity into Notes (or add distinct fields) | L | LOW | `layouts.ex:230-243`, `page_components.ex` |
| P8 | Resolve `/ingest` vs `/agents/ingest` duplication | S | LOW | `router.ex:156,168`, `ingest_live.ex:22` |
| P9 | Surface or remove orphan routes (`/queries`, `/collections`, `/tags/:tag`, `/ingest`) | S | MED | `router.ex:119,161,164` |

**Top 3 to do first:** P2 (re-group sidebar, ~1h, fixes Goals/Plans misclassification immediately), P5 (active_nav, mechanical), P1 (kill one kanban board — biggest code/UX win).

## Canonical sidebar target (post-fix)

```
Dashboard
Planning
  ├── Kanban       ← global board (todos + filters)
  ├── Projects     ← executive dashboards
  ├── Goals        ← has Todos tab → /kanban?goal=…
  ├── Plans        ← has Todos tab → /kanban?plan=…
  └── Todos        ← list view (NOT a board)
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

Aligns with the dashboard's existing `@nav_groups` (`dashboard_live.ex:14-66`). Extract a shared `DranWeb.NavGroups` module so sidebar and dashboard stop drifting.
