# structure.sql Drift — stale dumps and pg_dump noise

Symptom: the adversarial reviewer blocks a migration wave because
`priv/repo/structure.sql` does not match the migrations. Mechanism: the dump
is a snapshot taken at one moment; migrations applied after the dump (or a
dump taken mid-wave) leave it stale, and the mismatch only surfaces as a
blocked commit — or worse, as a fresh clone with the wrong schema.

Territory: how to AUTHOR migrations (renames, `RENAME CONSTRAINT`,
backfill-before-drop, duplicate indexes) is the elixir-data skill's
reference (`skills/elixir-data/references/migrations-and-structure-sql.md`);
this file is the ship-time drift check only.

## The signature of a stale dump

- The `schema_migrations` INSERT block lists FEWER versions than there are
  `priv/repo/migrations/*.exs` files (dump taken after only the first
  migration of the wave).
- Dropped columns still declared in table DDL (e.g. a column the wave's
  migration dropped still appears in `CREATE TABLE`).
- Widened types missing (`character varying(255)` where the wave made it
  `text`).
- New tables absent.

## The check

```bash
ls priv/repo/migrations/*.exs | wc -l
grep -c 'INSERT INTO public.schema_migrations' priv/repo/structure.sql
# count the version rows inside that block, not just the block's presence

mix ecto.migrations          # must show ALL migrations "up" on dev
```

The dump reads the dev database — migrations must be applied there first,
otherwise `mix ecto.dump` snapshots a half-migrated schema.

## The fix

```bash
mix ecto.dump
```

Then re-grep, point by point:

```bash
grep '<new_version_number>' priv/repo/structure.sql        # new version row present
grep 'CREATE TABLE public.<new_table>' priv/repo/structure.sql
grep '<dropped_column>' priv/repo/structure.sql            # expect NO match
grep '<widened column>' priv/repo/structure.sql            # expect new type
```

## What is NOT drift

- **pg_dump `\restrict` / `\unrestrict` meta-commands.** pg_dump 18.3+ emits
  them on every regeneration; full-file diffs show them as churn. Version
  noise — ignore.
- **Indexes over JSONB accessors.** An index like
  `pages_meta_kanban_status_idx` on `meta->>'kanban_status'` survives the
  drop of the column it served; its presence after a column drop is not
  drift.

Compare table DDL, indexes, and `schema_migrations` rows — never raw diff
size.

## Moduledoc claims vs the final schema

When a wave is split across several migrations, migration moduledocs lie
easily: one declares "second step of X" but has the EARLIER timestamp, and
another says "Y is not renamed here" while the earlier one renames it.
Timestamp order is the only execution order. Verify every moduledoc claim
against the final structure.sql before committing the wave.

## Verification

- Version-row count in `schema_migrations` == number of migration files.
- New table DDL / type changes present; dropped columns absent.
- Diff against the previous dump contains only expected schema changes plus
  known version noise.
- Fresh-clone sanity: `mix ecto.create && mix ecto.load && mix test` on a
  scratch DB boots from the shipped dump alone.
