# FK on_delete Cost at Scale

Why a parent-row delete times out in production while every other query on the
table is fast — and how to fix it. The canonical case: a partitioned log table
carrying `ON DELETE SET NULL` FKs toward parent tables; deleting one parent row
forced Postgres to visit every referencing log row across every partition.

## Symptom

- Deleting/updating a parent row times out in production (query timeout).
- The admin UI "does nothing" — no flash, no error, the LiveView silently
  restarts.
- A `foreign_key_constraint/3` guard in a context never triggers despite the
  message promising one.

## Mechanism

Every FK `on_delete` action is unbounded write work at parent-delete time:

- `SET NULL` visits and updates EVERY referencing row.
- `:delete_all` deletes them.
- `:nothing` / no FK does nothing.

No index fixes this — an index speeds the lookup, the cost is the per-row
writes. On big (or partitioned) tables the only fix that scales is not having
the action at all.

## Diagnostic

Enumerate FKs and their delete rules. On a partitioned table this returns ONE
ROW PER PARTITION — the multiplication is the cost you are removing:

```sql
SELECT tc.constraint_name, kcu.column_name, rc.delete_rule
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
  ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
JOIN information_schema.referential_constraints rc
  ON rc.constraint_name = tc.constraint_name
WHERE tc.table_name = '<table>' AND tc.constraint_type = 'FOREIGN KEY';
```

## Decision rubric (per column, not per table)

| on_delete | Verdict |
|---|---|
| `SET NULL` on an audit-trail log | **Drop the FK.** Keep the id column as plain historical data — better for auditing than nulling it. Lookup-by-parent was already indexed; the cost is the writes, not the lookup. |
| `CASCADE` | Keep ONLY if the log row is meaningless without the parent. If deleting a parent should keep usage history, this is a bug waiting on row count. |
| No FK (denormalized id) | The intended end state for audit columns: the log row must survive parent deletion. |

A log table can keep a CASCADE FK on columns whose rows are meaningless
without the parent (e.g. the member the row belongs to) and be FK-less on
attribution columns (provider, alias, credential) — end-state policy
decided per column.

## The drop

- Parent-level `ALTER TABLE ... DROP CONSTRAINT IF EXISTS ...` propagates to
  all partitions. Instant metadata op, no row rewrite — safe in a production window.
- Migration module: `@disable_ddl_transaction true` + `@disable_migration_lock
  true`; `IF EXISTS` makes re-runs harmless.
- Flip tests that asserted the old SET NULL behavior to assert id preservation
  — the old assertion passing was the evidence the FK was never protecting anything.
- Simultaneously remove `foreign_key_constraint/3` declarations naming the
  dropped constraint, and audit the ones that remain: a guard naming a
  `SET NULL` FK was already dead code.

## Dead-code guard

A `foreign_key_constraint/3` naming a `SET NULL`/`nilify` FK can never fire —
those FKs cannot raise a violation, so the friendly message is unreachable
(product policy written where it never runs). If the UI must block deletion of
referenced parents, check explicitly first:

```elixir
if Repo.exists?(from p in Provider, where: p.id == ^id) do
  # block with the friendly message
else
  # proceed with the delete
end
```

Keep the context guard only for genuinely restrictive FKs.

## "The front does nothing" — DB timeout arrives as a crash

A DB timeout arrives as a raised `DBConnection.ConnectionError` — an exit, not
an `{:error, changeset}` tuple. A `case`/`with` cannot catch it: the LiveView
dies and restarts with no flash, and the admin never sees an error.

Fix — wrap the context call:

```elixir
try do
  Providers.delete_provider(provider)
rescue
  e in DBConnection.ConnectionError ->
    Logger.warning("delete provider #{provider.id} failed: #{Exception.message(e)}")
    {:noreply, put_flash(socket, :error, "Delete timed out, please retry.")}
end
```

Catch the specific exception; broad `rescue` clauses hide real bugs. Reading
`{:error, _}` coverage as timeout coverage is the classic trap — two different
failure shapes, only one is caught by `case`.

## Consumers audit after FK-less ids

- Renders/preloads over orphaned ids must tolerate a nil association (fall
  back to "—" for a missing parent name).
- Metric groupings by the id keep working; breakdowns by parent NAME naturally
  exclude deleted parents — same output as with SET NULL, no regression.
- Fresh suite: run the full test suite after flipping the assertions.

## Anti-patterns rejected

- **Index on the FK column to "speed the SET NULL"** — helps the lookup, does
  nothing for the per-row writes; on partitioned tables a composite
  `(fk_col, inserted_at)` already serves the lookup.
- **Moving ETS/cache invalidation before the `Repo.transaction`** so routing
  stays coherent "even if the delete times out" — mutates state for a delete
  that may roll back: an atomicity regression for a performance problem.

## Verification

- Re-run the diagnostic query after the migration: 0 rows (per partition).
- Full suite green with the flipped assertions (id preserved instead of nulled).
- `mix ecto.dump` — `structure.sql` must reflect the dropped constraints.