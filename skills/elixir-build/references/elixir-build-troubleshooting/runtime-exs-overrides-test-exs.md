# runtime.exs overrides test.exs — `:eaddrinuse` during `mix test`

## Root cause

`config/runtime.exs` is executed for **all** environments, including `:test`, and
it runs **after** `config/test.exs`. Phoenix's generated `runtime.exs` typically
wraps prod-only config (DB url, secret_key_base, PHX_HOST) inside:

```elixir
if config_env() == :prod do
  ...
end
```

But it's common to leave endpoint listener config *outside* that guard so a
release boots without `PHX_SERVER=true`:

```elixir
# config/runtime.exs
config :app, AppWeb.Endpoint, server: true
config :app, AppWeb.Endpoint, http: [port: String.to_integer(System.get_env("PORT", "4000"))]

if config_env() == :prod do
  ...
end
```

In `:test`, those two lines win over `config/test.exs`'s:

```elixir
config :app, AppWeb.Endpoint,
  http: [ip: {127, 0, 0, 1}, port: 4002],
  server: false
```

Result: `mix test` tries to start a real HTTP listener on 4000.

## Symptom

```text
** (Mix) Could not start application app: App.Application.start(:normal, []) returned an error: shutdown: failed to start child: AppWeb.Endpoint
    ** (EXIT) shutdown: failed to start child: {AppWeb.Endpoint, :http}
        ** (EXIT) shutdown: failed to start child: :listener
            ** (EXIT) :eaddrinuse
```

Tell-tale: the blocked port is 4000 (from `runtime.exs`), not 4002 (from
`test.exs`). If `lsof -i:4000` shows another `beam.smp` (your dev server) or
nothing at all (TIME_WAIT), `runtime.exs` is overriding `test.exs`.

## Diagnosis path

1. `mix test` → `:eaddrinuse` on port 4000 (not the 4002 in `test.exs`).
2. `lsof -i:4000` → shows a dev `beam.smp`, or is empty (port stuck in
   TIME_WAIT / the test's own listener raced itself).
3. `grep -n 'server: true\|http: \[port' config/runtime.exs` → hit outside an
   `if config_env() == :prod` block confirms the override.

## Workaround (unblock a run without editing config)

`runtime.exs` reads the port via `System.get_env("PORT", "4000")`, so an env var
overrides the default:

```bash
PORT=4099 mix test
```

`server: true` is harder to override via env without code change; if the endpoint
starting at all is the problem, the config guard fix below is the real fix.

## Proper fix

Move the unconditional `server: true` / `http: [port: ...]` lines inside the
prod guard (or an explicit non-test guard):

```elixir
# config/runtime.exs
if config_env() == :prod do
  config :app, AppWeb.Endpoint, server: true
  config :app, AppWeb.Endpoint, http: [port: String.to_integer(System.get_env("PORT", "4000"))]
  # ... rest of prod config (DATABASE_URL, SECRET_KEY_BASE, PHX_HOST, ...)
end
```

Now `:test` keeps `test.exs`'s `server: false` and no listener starts.

## Note on `mix precommit`

If the project defines a `mix precommit` alias that runs the full test suite,
the same `:eaddrinuse` failure surfaces there. The `PORT=4099` workaround works
for that alias too. Pre-existing test failures from untracked WIP test files
are a separate issue — confirm via `git stash` + re-run before attributing
failures to your change.
