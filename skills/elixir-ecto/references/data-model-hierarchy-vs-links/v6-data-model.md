# my_app v6 Data Model: Hierarchy → Links Migration

## Context

my_app v5 had a rigid hierarchy: `project > goal > plan > todo` with precedence `plan > goal > project`. This caused:

1. **Silent bugs**: A todo with `plan_slug` + `goal_slug` + `project_slug` only materialized `part_of plan`. Dashboards filtering by `project_slug` missed it.
2. **False choices**: A todo belonging to project X, goal Y, and plan Z had to pick one parent.
3. **Complex queries**: `maybe_filter_goal_slug/2` in `brain.ex` did LEFT JOINs to resolve precedence.

## v6 Changes

### 1. Independent Links

```elixir
# Before: sync_planning_relations with cond branches
# After: sync_todo_links with independent sync_one_link per slug

def sync_todo_links(%Page{page_type: "todo"} = page, prior_page) do
  context_id = page.context_id
  
  sync_one_link(page, prior_page, "project_slug", context_id)
  sync_one_link(page, prior_page, "goal_slug", context_id)
  sync_one_link(page, prior_page, "plan_slug", context_id)
  
  :ok
end

defp sync_one_link(page, prior_page, slug_field, context_id) do
  new_slug = meta_string(page.meta, slug_field)
  prior_slug = if prior_page, do: meta_string(prior_page.meta, slug_field), else: nil
  
  maybe_drop_part_of(page.slug, prior_slug, new_slug, context_id)
  ensure_part_of(page.slug, new_slug, context_id)
end
```

### 2. Schema Changes

| Type | v5 | v6 |
|------|----|----|
| **Todo** | kanban_status, priority, due_date, goal_slug, plan_slug | + project_slug |
| **Project** | N/A (new) | status, priority, health, health_source, start_date, target_date, team |
| **Goal** | health, start_date, target_date, team | + metric, target_value, current_value, unit, progress, due_date, project_slug |
| **Plan** | horizon, period, status | + due_date, project_slug, goal_slug (status kept but simplified) |
| **Note** | kind, date, author | + due_date (if kind=reminder) |

### 3. Kanban Global

```elixir
# Route
live "/kanban", KanbanLive, :index

# Filters (combinable)
# ?project=slug&goal=slug&plan=slug&inbox=true

# Query
from p in Page,
  where: p.page_type == "todo" and
         fragment("meta->>'project_slug' = ?", ^project_slug) and
         fragment("meta->>'goal_slug' = ?", ^goal_slug)
```

### 4. Project Dashboard (No Kanban)

```
┌─────────────────────────────────────────┐
│ 🚀 "Lanzar MVP"                         │
│ Status: active │ Health: green │ Q3     │
├─────────────────────────────────────────┤
│ [Overview] [Todos] [Goals] [Plans]     │
│ [Graph] [Related]                       │
├─────────────────────────────────────────┤
│ Todos vinculados:                       │
│ [x] Setup repo  [ ] Deploy staging      │
│ [ ] Write docs                          │
│                                         │
│ "Ver todos en Kanban →"                 │
└─────────────────────────────────────────┘
```

### 5. Goal Page (Progress Tracking)

```
┌─────────────────────────────────────────┐
│ 🎯 "Bajar a 70kg"                       │
│ Health: yellow │ Progress: 60% │ 75→70kg│
├─────────────────────────────────────────┤
│ [Overview] [Todos] [Graph] [Related]   │
├─────────────────────────────────────────┤
│ Todos vinculados:                       │
│ [x] Correr 3x semana  [ ] Dieta         │
│ [x] Gym               [ ] Dormir 8h     │
│                                         │
│ Progress: ████████░░ 60% (12/20 done)   │
└─────────────────────────────────────────┘
```

### 6. Sidebar Reorganization

```
Before:
  Planning
    ├── Goals
    ├── Plans
    └── Todos

After:
  Dashboard
  Kanban          ← NEW
  Projects        ← NEW
  Knowledge
    ├── Notes
    ├── Concepts
    ├── Entities
    ├── Goals     ← MOVED
    ├── Plans     ← MOVED
    └── References
```

## Migration (Opción B — Limpieza Directa)

> **Verified against the actual implementation plan** (`.hermes/plans/2026-07-18_drn-projects-page-type.md` §2.10). The simpler "clear all plan statuses" approach is what shipped — do NOT try to map old values to new ones, just drop the field.

```sql
-- Clear ALL plan statuses (old enum had on_hold/completed which no longer exist).
-- New plans will get a fresh status on next edit. No value-mapping needed
-- because there is no production data to preserve.
UPDATE pages SET meta = meta - 'status'
WHERE page_type = 'plan' AND meta ? 'status';

-- Verify: should return 0
SELECT count(*) FROM pages WHERE page_type = 'plan' AND meta ? 'status';
```

```bash
# Post-cleanup verification
cd ~/Repos/my_app && mix ecto.migrate   # should say "already up"
psql -d dran_dev -c "SELECT count(*) FROM pages WHERE page_type = 'plan' AND meta ? 'status';"
# should return 0
```

**Why clear instead of map:** there is no production data to preserve, and the old `on_hold`/`completed` values have no clean 1:1 mapping to the new `draft|active|done|archived` enum (e.g. was an `on_hold` plan really `active` again, or `archived`?). Clearing forces the user to re-set status on next edit, which is the honest behavior.

## Lessons Learned

1. **Precedence is a smell.** If you need `plan > goal > project`, your model is wrong. Each link should be independent.

2. **Kanban belongs at the top level.** Per-container kanbans duplicate code and fragment attention. One global kanban with filters is simpler and more powerful.

3. **Goals are not containers.** A goal "bajar 5kg" doesn't contain todos — it measures progress. Todos link to it. The goal page shows linked todos and computes progress.

4. **Plans are documents.** A plan "Estrategia Q3" is prose, not a task list. It links to todos for execution tracking, but its primary content is markdown.

5. **Health/progress should be derivable.** Manual health tracking gets stale. Derive from linked items with override option.
