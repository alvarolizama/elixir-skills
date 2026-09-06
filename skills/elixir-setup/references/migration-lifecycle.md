# Ecto migration indexes: rename, duplicate names, failed-in-prod edits

Patterns for the migration lifecycle — the cases where a single command
silently corrupts schema state or a rename breaks rollback.

## Renaming an index: drop the OLD name explicitly in `up`

**Symptom.** `mix ecto.rollback` after an index rename fails, or the old
index survives alongside the new one.

**Mechanism.** `up` creates the new-named index but the migration did not
remove the old one (relying on a plain rename that `unique_index/2` does not
perform). `down` then drops only the NEW name, leaving the old index behind —
or the renamed `down` drops the new-name index the `up` never created.

**Fix — name every step explicitly in BOTH directions:**

```elixir
def up do
  drop_if_exists unique_index(:api_keys, [:owner_id],
                   name: :api_keys_owner_id_unique_index)
  create unique_index(:api_keys, [:owner_id, :kind],
           name: :api_keys_kind_unique_index)
end

def down do
  drop_if_exists unique_index(:api_keys, [:owner_id, :kind],
                   name: :api_keys_kind_unique_index)
end
```

**Verification.**

```bash
mix ecto.rollback -n 1          # runs the edited `down`
mix ecto.migrate                # runs the edited `up`
psql -d <db> -c "\d <table>" | grep -i unique   # ONLY the correct index exists
```

## Duplicate migration module names

**Symptom.**

```
migrations can't be executed, migration name X is duplicated
```

**Mechanism.** Two migration files (usually from parallel scaffolding)
produce the same module name, or a file's module name does not match its
filename (module must equal the filename minus the timestamp prefix:
`20260629002000_create_widgets.exs` → `CreateWidgets`).

**Fix.** Rename the duplicated module to match its file (or delete the
redundant file). Check ordering by listing files:

```bash
ls apps/<app>/priv/repo/migrations | sort   # verify dependency order
```

## Editing migrations that failed in production

- **Safe to edit in-place**: the migration was NEVER recorded in
  `schema_migrations` (it failed inside its transaction and rolled back).
- **NOT safe**: it succeeded partially (non-transactional DDL, or
  `execute` without a transaction, e.g. Postgres partition operations).
  Inspect the actual DB state with `psql \d` before editing anything —
  never re-run by assumption.

## Recovering deleted or stale build artifacts

The umbrella build tree mirrors `priv` — see `compile-warnings-and-branch-validation.md`
for `_build` hygiene; restorable migrations are tracked in git:

```bash
git checkout -- apps/<app>/priv/repo/migrations/      # restore deleted files
MIX_ENV=test mix ecto.reset                            # reapply clean
```

## Reset recipes

```bash
MIX_ENV=test mix ecto.reset   # drop + create + migrate test DB (also dev with MIX_ENV=dev)
```

Use when: migrations failed mid-flight leaving half-applied state; migration
files were renamed/deleted after already running; you changed an already-executed
migration; `migration name X is duplicated`.

## Verification

```bash
mix ecto.migrate && MIX_ENV=test mix ecto.migrate      # both envs apply clean
psql -d <db> -c "\d <table>" | grep -i unique          # index set as intended
mix ecto.rollback -n 1 && mix ecto.migrate             # rename path both ways
```