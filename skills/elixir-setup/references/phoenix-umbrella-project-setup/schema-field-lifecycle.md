# Schema field lifecycle: cargo cult vs real functionality

When designing or evolving Ecto schemas (especially JSONB meta fields), distinguish between fields that have **real consumers** and fields that are **cargo cult** — copied from another pattern without anything reading them.

## Detection checklist

Before deciding to keep, remove, or rename a field, ask:

1. **Does any code READ this field?** `grep -rn "field_name" lib/` — if only the schema definition and forms touch it, it's suspect.
2. **Does any query FILTER or ORDER by it?** If no `where: meta["field"] == ...` exists, it's not powering any feature.
3. **Does any UI DISPLAY it?** If no template renders it, users don't benefit.
4. **Does any lifecycle DEPEND on it?** If nothing transitions state based on this field, it's decorative.

If all answers are "no," the field is cargo cult. Remove it.

## Decision framework

| Situation | Action |
|-----------|--------|
| No production system, local can be reset | **Opción B:** cleanup script immediately. Don't leave "basura histórica" in JSONB. |
| Production data exists, external consumers might read it | **Opción A:** leave field in place, stop validating/exposing it. Mark as deprecated in schema comments. |
| Uncertain | Default to **Opción B** if data can be regenerated; **Opción A** if data is precious. |

Álvaro's preference: **Opción B when possible.** Clean now, don't accumulate inert fields.

## Example: plan status removal

A `plan` page type had `status` (draft/active/on_hold/completed/archived) copied from a pattern. Inspection showed:

- No `plan_live.ex` tab for todos under the plan
- No `sync_planning_relations` consumer of plan status
- No dashboard filter using it
- Plan body was pure markdown prose

**Conclusion:** `status` on plan was cargo cult. Removed validation + form field. Cleanup script:

```bash
psql -d db -c "UPDATE pages SET meta = meta - 'status' WHERE page_type = 'plan';"
```

Verification:

```bash
psql -d db -c "SELECT count(*) FROM pages WHERE page_type = 'plan' AND meta ? 'status';"
# must return 0
```

## Related pattern: derived fields with override

When a parent entity aggregates child state (e.g., project health from goal health):

- Compute derived value automatically (e.g., weighted average with floor for conservatism)
- Store `health_source: "derived" | "manual"` to allow user override
- Recalculate on every child update, but respect manual override
- UI exposes the source selector so user can switch back to derived

This keeps the system self-maintaining while preserving user control.
