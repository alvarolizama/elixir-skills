# UUID primary keys in Ecto (:binary_id house default)

House rule: all tables use `:binary_id` (UUID) primary keys, never `:bigserial`
integers. This reference is the complete pattern plus the traps that make
UUIDs fail silently.

## Repo config

```elixir
config :core, Core.Repo,
  adapter: Ecto.Adapters.Postgres,
  migration_primary_key: [name: :id, type: :binary_id],
  migration_timestamps: [type: :utc_datetime_usec]
```

With `migration_primary_key` set, plain `create table(:foo)` generates a UUID
`id` automatically — no need for `primary_key: false` + explicit `add :id` in
every migration.

## Schema pattern

Every schema gets these two module attributes:

```elixir
defmodule MyApp.Core.User do
  use Ecto.Schema
  import Ecto.Changeset

  @primary_key {:id, :binary_id, autogenerate: true}
  @foreign_key_type :binary_id

  schema "users" do
    field :email, :string
    has_many :posts, MyApp.Core.Post
  end
end
```

`@foreign_key_type :binary_id` makes every `belongs_to` use UUIDs — do NOT
also declare `type: :binary_id` per association.

### `autogenerate: false` returns nil IDs

**Symptom.** After `Repo.insert` the struct has `id: nil`; tests fail with
`** (Ecto.NoPrimaryKeyValueError) struct is missing primary key value`.

**Mechanism.** `autogenerate: false` tells Ecto to not generate the id AND not
read it back from the DB — even when the migration has
`default: fragment("gen_random_uuid()")`.

**Fix.** `@primary_key {:id, :binary_id, autogenerate: true}`. Ecto omits `id`
from the INSERT (so the DB default kicks in) and reads the generated UUID back.

UUID column default in SQL: use `gen_random_uuid()`, NOT `uuid_generate_v4()`
(the extension is absent on current Postgres).

## Migration pattern

```elixir
# With migration_primary_key set, plain create works:
create table(:users) do
  add :email, :string, null: false
end

# Explicit control:
create table(:posts, primary_key: false) do
  add :id, :binary_id, primary_key: true
  add :user_id, references(:users, type: :binary_id, on_delete: :delete_all), null: false
end
```

## Critical trap: reset BOTH databases after changing key types

**Symptom.** `mix test` fails with:

```
** (DBConnection.EncodeError) Postgrex expected an integer in
-9223372036854775808..9223372036854775807, got <<...>>.
```

**Mechanism.** The test database still has the old `bigserial` columns.
`mix ecto.reset` only resets the dev database.

**Fix.**

```bash
mix ecto.reset              # dev DB
MIX_ENV=test mix ecto.reset # test DB ← THIS IS THE FIX
```

## Converting an existing project to UUID

1. Add `@primary_key {:id, :binary_id, autogenerate: true}` and
   `@foreign_key_type :binary_id` to every schema.
2. Edit migrations: `create table(:foo)` → `create table(:foo, primary_key: false)` +
   `add :id, :binary_id, primary_key: true`.
3. Add `type: :binary_id` to all `references/2` calls.
4. Remove explicit `type: :binary_id` from `belongs_to` — `@foreign_key_type`
   handles it.
5. `mix ecto.reset` (dev) **and** `MIX_ENV=test mix ecto.reset` (test).
6. `mix test`.

Early dev with no production data: editing existing migrations is acceptable.
Once migrations are committed and deployed: NEVER modify them — always create
a new ALTER migration (`mix ecto.gen.migration alter_<table>_<change>`).

## Schema/migration alignment (silent type mismatches)

Ecto does not validate schema-vs-migration at compile time. A schema field
`field :tool_calls, {:array, :map}` over a migration `add :tool_calls, :map`
compiles fine and only the test exercising that path fails. Verify the actual
column type:

```bash
psql -d my_app_dev -tAc "SELECT atttypid::regtype FROM pg_attribute \
  WHERE attrelid = 'my_table'::regclass AND attname = 'my_column'"
# expect: jsonb[]
```

Casting scalar `jsonb` to `jsonb[]` in Postgres needs explicit wrapping — a
bare `ALTER ... TYPE jsonb[]` fails with `cannot cast type jsonb to jsonb[]`:

```sql
UPDATE my_table SET col = jsonb_build_array(col)
WHERE col IS NOT NULL AND NOT jsonb_typeof(col) = 'array';

ALTER TABLE my_table ALTER COLUMN col TYPE jsonb[]
USING CASE WHEN col IS NULL THEN NULL ELSE ARRAY[col]::jsonb[] END;
```

## Field lifecycle: drop cargo-cult fields

Before keeping/removing/renaming a schema field (especially JSONB meta), ask:

1. Does any code READ it? `grep -rn "field_name" lib/` — only schema + forms
   touching it is suspect.
2. Does any query FILTER or ORDER by it?
3. Does any UI display it?
4. Does any lifecycle depend on it (state transitions)?

All "no" → the field is cargo cult. Decision: no production data (or data
regenerable) → clean now: remove validation + form field and run a cleanup
statement. Production data with possible external consumers → keep the column,
stop validating/exposing it, mark deprecated in schema comments.

```bash
psql -d my_app_dev -c "UPDATE items SET meta = meta - 'status' WHERE item_type = 'plan';"
psql -d my_app_dev -c "SELECT count(*) FROM items WHERE item_type = 'plan' AND meta ? 'status';"
# must return 0
```

Related pattern — derived fields with override: when a parent aggregates child
state, compute the derived value automatically, store a source marker
(`health_source: "derived" | "manual"`), recalculate on child updates but
respect manual override, and expose the source selector in the UI.

## Verification

```bash
mix ecto.migrate && MIX_ENV=test mix ecto.migrate   # both schemas current
mix test                                            # sandbox + UUIDs pass
psql -d my_app_dev -tAc "SELECT data_type FROM information_schema.columns \
  WHERE table_name='users' AND column_name='id'"    # → uuid
```
