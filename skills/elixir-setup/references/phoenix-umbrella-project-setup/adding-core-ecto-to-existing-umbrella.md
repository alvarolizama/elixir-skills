# Adding `:core` Ecto app to an existing umbrella

Session: Money Bot, 2026-06-27.

## Goal

Take an existing Elixir umbrella (already had `mix.exs` with `apps_path: "apps"`,
`.formatter.exs`, `config/config.exs`, no `apps/` yet) and add a new Phoenix Ecto
app called `:core` backed by Homebrew PostgreSQL.

## Commands run

```bash
# Install the Phoenix generator (it was missing initially)
mix archive.install hex phx_new --force

# The generator must run inside apps/, not the umbrella root
mkdir -p apps
cd apps
mix phx.new.ecto core --app core --no-assets --no-html --no-live --no-dashboard --no-mailer

# Back in umbrella root:
mix deps.get
mix compile

# First attempt failed because ecto_repos was missing:
#   warning: could not find Ecto repos in any of the apps: [:core].
# Fixed by adding to config/config.exs:
#   config :core, ecto_repos: [Core.Repo]

# Create databases
mix ecto.create
MIX_ENV=test mix ecto.create

# Validate
mix test
```

## Key error transcripts

### `phx.new.ecto` not found

```
** (Mix) The task "phx.new.ecto" could not be found
```

Fix: `mix archive.install hex phx_new --force`.

### `phx.new.ecto` from umbrella root

```
** (Mix) The ecto task can only be run within an umbrella's apps directory
```

Fix: `mkdir -p apps && cd apps && mix phx.new.ecto ...`

### Missing `ecto_repos`

```
warning: could not find Ecto repos in any of the apps: [:core].

You can avoid this warning by passing the -r flag or by setting the
repositories managed by those applications in your config/config.exs:

    config :core, ecto_repos: [...]
```

Fix: add `config :core, ecto_repos: [Core.Repo]` in `config/config.exs`.

## Final `config/config.exs` shape

```elixir
import Config

config :core, ecto_repos: [Core.Repo]

config :core, Core.Repo,
  adapter: Ecto.Adapters.Postgres,
  migration_primary_key: [name: :id, type: :bigserial],
  migration_timestamps: [type: :utc_datetime_usec]

# App children need these
config :core, Core.PubSub, adapter: Phoenix.PubSub.PG2
config :core, :dns_cluster_query, :ignore

config :logger, :default_formatter,
  format: "$time [$level] $metadata$message\n",
  metadata: [:request_id]

import_config "#{config_env()}.exs"
```

## Postgres user check on macOS/Homebrew

```bash
whoami
# alvaro

psql postgres -c "SELECT usename FROM pg_user;"
# alvaro
# postgres
# brain
```

Use the current macOS user (`alvaro`) with no password for local dev/test;
Homebrew PostgreSQL normally trusts local connections for that user.

## Env-specific database configs

### `config/dev.exs`

```elixir
import Config

config :core, Core.Repo,
  username: System.get_env("DB_USER") || "alvaro",
  password: System.get_env("DB_PASSWORD") || "",
  hostname: System.get_env("DB_HOST") || "localhost",
  database: "money_bot_dev",
  stacktrace: true,
  show_sensitive_data_on_connection_error: true,
  pool_size: 10

config :logger, :default_formatter, format: "[$level] $message\n"
```

### `config/test.exs`

```elixir
import Config

config :core, Core.Repo,
  username: System.get_env("DB_USER") || "alvaro",
  password: System.get_env("DB_PASSWORD") || "",
  hostname: System.get_env("DB_HOST") || "localhost",
  database: "money_bot_test#{System.get_env("MIX_TEST_PARTITION")}",
  pool: Ecto.Adapters.SQL.Sandbox,
  pool_size: System.schedulers_online() * 2

config :logger, level: :warning
```

### `config/runtime.exs`

```elixir
import Config

if config_env() == :prod do
  database_url =
    System.get_env("DATABASE_URL") ||
      raise """
      environment variable DATABASE_URL is missing.
      For example: ecto://USER:PASS@HOST/DATABASE
      """

  maybe_ipv6 = if System.get_env("ECTO_IPV6"), do: [:inet6], else: []

  config :core, Core.Repo,
    url: database_url,
    pool_size: String.to_integer(System.get_env("POOL_SIZE") || "10"),
    socket_options: maybe_ipv6
end
```

## Verification checklist

- [ ] `mix deps.get` completes
- [ ] `mix compile` succeeds with no warnings in `:core` code
- [ ] `mix ecto.create` creates `money_bot_dev`
- [ ] `MIX_ENV=test mix ecto.create` creates `money_bot_test`
- [ ] `mix test` passes
