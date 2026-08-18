# UUID Primary Keys in Ecto/Phoenix

Álvaro wants all tables to use `:binary_id` (UUID) as the primary key, not `:bigserial` integers. This is the standard pattern for Money Bot and future projects.

## Repo config

```elixir
config :core, Core.Repo,
  adapter: Ecto.Adapters.Postgres,
  migration_primary_key: [name: :id, type: :binary_id],
  migration_timestamps: [type: :utc_datetime_usec]
```

This makes `create table(:foo)` generate a UUID `id` column automatically — no need for `primary_key: false` + `add :id, :binary_id, primary_key: true` in every migration.

## Schema pattern

Every schema gets these two module attributes:

```elixir
defmodule Core.Agents.Agent do
  use Ecto.Schema
  import Ecto.Changeset

  @primary_key {:id, :binary_id, autogenerate: true}
  @foreign_key_type :binary_id
  schema "agents" do
    # fields...
    has_many :sessions, Core.Agents.Session
  end
end
```

`@foreign_key_type :binary_id` makes every `belongs_to` use UUID automatically — no need for `type: :binary_id` on each association.

## Migration pattern

With `migration_primary_key: [type: :binary_id]` set in repo config, plain `create table(:foo)` already produces a UUID PK. For explicit control:

```elixir
create table(:agents, primary_key: false) do
  add :id, :binary_id, primary_key: true
  # ...
end
```

Foreign keys must specify `type: :binary_id`:

```elixir
create table(:agent_sessions, primary_key: false) do
  add :id, :binary_id, primary_key: true
  add :agent_id, references(:agents, type: :binary_id, on_delete: :delete_all), null: false
  # ...
end
```

## Critical pitfall: test database schema mismatch

After changing schemas from integer to UUID, `mix test` will fail with:

```
** (DBConnection.EncodeError) Postgrex expected an integer in
-9223372036854775808..9223372036854775807, got <<...binary...>>.
```

This means the **test database** still has the old `bigserial` columns. `mix ecto.reset` only resets the dev database. You must also reset the test database:

```bash
mix ecto.reset              # dev DB
MIX_ENV=test mix ecto.reset # test DB ← THIS IS THE FIX
```

Always reset **both** databases after changing primary key types.

## Converting an existing project to UUID

When converting an existing project from integer IDs to UUID:

1. Add `@primary_key {:id, :binary_id, autogenerate: true}` and `@foreign_key_type :binary_id` to every schema.
2. Edit migrations: `create table(:foo)` → `create table(:foo, primary_key: false)` + `add :id, :binary_id, primary_key: true`.
3. Add `type: :binary_id` to all `references/2` calls in migrations.
4. Remove any explicit `type: :binary_id` from `belongs_to` in schemas — `@foreign_key_type` handles it.
5. `mix ecto.reset` (dev) + `MIX_ENV=test mix ecto.reset` (test).
6. `mix test` to verify.

If the project is in early dev with no production data, editing existing migrations is acceptable. If migrations are already committed and deployed, create a new ALTER migration instead.
