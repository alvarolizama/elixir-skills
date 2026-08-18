# PGVector setup in an Ecto umbrella app

## Context

When a migration uses `add :embedding, :vector, size: N`, Postgrex's default types module cannot decode the `vector` OID. You must register `pgvector` extensions with a custom `PostgrexTypes` module and point the repo at it.

## Steps

1. Install the PostgreSQL extension. On macOS with Homebrew:

```bash
brew install pgvector
```

2. Add dependency to the repo app:

```elixir
# apps/core/mix.exs
defp deps do
  [
    {:ecto_sql, "~> 3.13"},
    {:postgrex, ">= 0.0.0"},
    {:pgvector, "~> 0.4"},
    {:jason, "~> 1.2"}
  ]
end
```

3. Define the types module:

```elixir
# apps/core/lib/core/postgrex_types.ex
Postgrex.Types.define(Core.PostgrexTypes,
  Pgvector.extensions() ++ Ecto.Adapters.Postgres.extensions(),
  []
)
```

4. Configure the repo to use it:

```elixir
# config/config.exs
config :core, Core.Repo,
  adapter: Ecto.Adapters.Postgres,
  types: Core.PostgrexTypes,
  migration_primary_key: [name: :id, type: :bigserial],
  migration_timestamps: [type: :utc_datetime_usec]
```

5. Enable the extension in a migration:

```elixir
# apps/core/priv/repo/migrations/20260101000000_enable_pgvector.exs
defmodule Core.Repo.Migrations.EnablePgvector do
  use Ecto.Migration

  def up do
    execute "CREATE EXTENSION IF NOT EXISTS vector"
  end

  def down do
    execute "DROP EXTENSION IF EXISTS vector"
  end
end
```

6. Use the vector type in later migrations:

```elixir
add :embedding, :vector, size: 1536
```

7. Use it in the schema:

```elixir
field :embedding, Pgvector.Ecto.Vector
```

## Verification

```bash
MIX_ENV=dev mix ecto.migrate
MIX_ENV=test mix ecto.migrate
mix test
```

Errors like `type vector can not be handled by the types module Postgrex.DefaultTypes` mean step 3 or 4 is missing.
