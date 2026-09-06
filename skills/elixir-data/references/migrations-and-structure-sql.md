# Migrations & structure.sql

Everything that bites when renaming/changing columns, constraints, JSONB
defaults, or replacing polymorphic relations with real FKs. All verified.

## `rename/2` does NOT rename columns (Ecto ≥ 3.14)

`rename :old_col, to: :new_col` inside `alter table` raises
`FunctionClauseError` in `Ecto.Migration.rename/2` — the signature changed;
`rename/2` now matches only `%Table{}` and `%Index{}` (renaming tables and
indexes), not atoms for columns.

Fix — raw SQL, reversible inside `change/0`:

```elixir
def change do
  execute(
    "ALTER TABLE providers RENAME COLUMN rerank_dialect TO rerank_format",
    "ALTER TABLE providers RENAME COLUMN rerank_format TO rerank_dialect"
  )
  alter table(:providers) do
    add :embedding_base_url, :string, null: true
  end
end
```

The two-argument `execute(up, down)` keeps `change/0` reversible — no need to
split into `up`/`down`.

## `RENAME CONSTRAINT` uses the NEW name

After `rename table(:old), to: table(:new)`, an `ALTER TABLE ... RENAME CONSTRAINT`
must use the NEW name — using the old one raises `42P01 relation does not exist`.

## One `ALTER` per `RENAME CONSTRAINT`

Postgres does NOT accept multiple `RENAME CONSTRAINT` statements in a single
ALTER (`42601`) — one `execute` per rename.

## `rename table` does NOT rename indexes or constraints

Indexes and constraints keep their OLD names unless explicitly renamed
(`ALTER INDEX ... RENAME`, `RENAME CONSTRAINT`). Verify against the regenerated
`structure.sql` (`mix ecto.dump`) after migrating dev.

## JSONB column defaults

`add :col, :jsonb, default: %{}` in an `alter` is rejected by Ecto. Use:

```elixir
add :col, :jsonb, default: fragment("'{}'::jsonb")
```

## Backfill BEFORE drop (replacing polymorphic relations)

When a new FK (`goal_id`) replaces polymorphic relation rows (`serves`),
backfill the FK column FIRST, then delete the relation rows — never the
reverse:

```sql
-- 1. Backfill the new FK from the polymorphic links
UPDATE pages p
SET goal_id = l.target_id
FROM links l
WHERE l.source_id = p.id AND l.link_type = 'goal';

-- 2. ONLY THEN delete the superseded relation rows
DELETE FROM links WHERE link_type = 'goal';
```

## Dropping constraints safely

- `IF EXISTS` makes re-runs harmless.
- `@disable_ddl_transaction true` + `@disable_migration_lock true` — constraint
  DDL is non-transactional anyway; the flags keep the migration lock sane.
- Parent-level `ALTER TABLE ... DROP CONSTRAINT IF EXISTS ...` propagates to
  all partitions and is an instant metadata op — safe for a production window.
- After the drop, re-run the `information_schema`/`pg_constraint` query and
  assert 0 remaining — on partitioned tables there is one row PER PARTITION;
  the multiplication is the cost you are removing.
- Remove `foreign_key_constraint/3` declarations naming the dropped constraint
  (they would reference something nonexistent).

## Consecutive-migration duplicate indexes

Two migrations an hour apart created the same composite index with different
sort directions — the ASC copy is never used when queries order DESC. Pure
write amplification (B-trees scan backward; keep only the direction queries
use):

```bash
grep -rn 'CREATE INDEX.*<table>' priv/repo/migrations/ | sort
# Any two indexes on the same columns = review for duplication
```

## Legacy columns after feature removal

Columns/FKs often survive in the DB after the Ecto schema stops declaring them
— wasted space per row (16 bytes per uuid, 8-24 per numeric). Detect by
diffing `CREATE TABLE`/`ADD COLUMN` in migrations against the schema's
`field`/`belongs_to` lines. `ALTER TABLE ... DROP COLUMN` on a partitioned
table is metadata-only (Postgres 11+), but the space is not reclaimed until
`VACUUM FULL`/`pg_repack` — schedule that in a maintenance window.

## structure.sql freshness is NOT guaranteed

Some repos regenerate `structure.sql` only on demand. Before trusting it as
schema truth, check whether the recent migrations appear in it. After any
migration: `mix ecto.dump` so `priv/repo/structure.sql` carries the partitions,
indexes, and constraints.

## Verification

- `mix ecto.migrate` succeeds (fresh + rollback-forward round trip
  `mix ecto.rollback --to <previous_ts>` then `mix ecto.migrate`).
- `mix ecto.dump` regenerates; `git diff priv/repo/structure.sql` shows exactly
  the intended DDL changes (renamed constraints/indexes, dropped FKs, defaults).
- Re-run constraint queries: 0 rows.