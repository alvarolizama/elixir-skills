# Adding a Phoenix web app to an existing umbrella

Concrete recipe from a session that added an `:admin` app to the `MoneyBot` umbrella, which already had a `:core` Ecto app.

## Goal

Create `apps/admin/` with `mix phx.new.web` so it serves HTML/LiveView but delegates all database work to `Core.Repo`.

## Commands

```bash
cd apps
printf "Y\n" | mix phx.new.web admin --app admin
cd ..
mix deps.get
```

## Required manual fixes

### 1. Depend on `:core`

In `apps/admin/mix.exs`:

```elixir
defp deps do
  [
    {:core, in_umbrella: true},
    {:phoenix, "~> 1.8.8"},
    # ...
  ]
end
```

### 2. Declare no local repo and name the PubSub

In `config/config.exs`:

```elixir
config :admin, ecto_repos: []
config :admin, Admin.PubSub, adapter: Phoenix.PubSub.PG2
```

### 3. Start the PubSub

In `apps/admin/lib/admin/application.ex`:

```elixir
children = [
  Admin.Telemetry,
  {Phoenix.PubSub, name: Admin.PubSub},
  Admin.Endpoint
]
```

### 4. Dev endpoint config

In `config/dev.exs`:

```elixir
config :admin, :dev_routes, true

config :admin, Admin.Endpoint,
  url: [host: nil],
  http: [ip: {0, 0, 0, 0}, port: 3001],
  check_origin: false,
  code_reloader: true,
  debug_errors: true,
  secret_key_base: "...64+ bytes...",
  watchers: [
    esbuild: {Esbuild, :install_and_run, [:admin, ~w(--sourcemap=inline --watch)]},
    tailwind: {Tailwind, :install_and_run, [:admin, ~w(--watch)]}
  ],
  live_reload: [
    patterns: [
      ~r"priv/static/(?!uploads/).*(js|css|png|jpeg|jpg|gif|svg)$",
      ~r"lib/admin/(controllers|live|components)/.*(ex|heex)$"
    ]
  ]
```

### 5. Test endpoint config

In `config/test.exs`:

```elixir
config :admin, Admin.Endpoint,
  url: [host: nil],
  http: [ip: {127, 0, 0, 1}, port: 4002],
  secret_key_base: "...different 64+ bytes...",
  server: false
```

### 6. Tests use `:core`'s sandbox

`apps/admin/test/test_helper.exs`:

```elixir
ExUnit.start()
Ecto.Adapters.SQL.Sandbox.mode(Core.Repo, :manual)
```

`apps/admin/test/support/conn_case.ex`:

```elixir
setup tags do
  Core.DataCase.setup_sandbox(tags)
  {:ok, conn: Phoenix.ConnTest.build_conn()}
end
```

### 7. Remove Swoosh mailbox forward (unless Swoosh is installed)

In `apps/admin/lib/admin/router.ex`:

```elixir
if Application.compile_env(:admin, :dev_routes) do
  import Phoenix.LiveDashboard.Router

  scope "/dev" do
    pipe_through :browser
    live_dashboard "/dashboard", metrics: Admin.Telemetry
  end
end
```

## Verification

```bash
mix compile --warnings-as-errors
mix test
```

## Session-specific notes

- `phx.new.web` overwrote the umbrella root `config/runtime.exs` and `config/prod.exs`; the `:core` database/runtime configuration had to be merged back in.
- `admin` tests failed with `Admin.Repo` undefined until `test_helper.exs` was repointed to `Core.Repo`.
- `Core.DataCase` was invisible to admin until `{:core, in_umbrella: true}` was added to admin deps.
