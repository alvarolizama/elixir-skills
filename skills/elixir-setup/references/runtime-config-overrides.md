# Phoenix 1.8 runtime config: env-var overrides, compile-time keys, `:eaddrinuse`

Runtime crash class: `mix test` or `mix run` fails with `:eaddrinuse` on port
4000, `force_ssl` aborts a release boot, or config values silently don't apply
per environment.

## `runtime.exs` overrides `test.exs` → `:eaddrinuse` on port 4000

**Symptom.**

```
** (Mix) Could not start application app: App.Application.start(:normal, []) returned an error: shutdown: failed to start child: AppWeb.Endpoint
    ** (EXIT) shutdown: failed to start child: {AppWeb.Endpoint, :http}
        ** (EXIT) shutdown: failed to start child: :listener
            ** (EXIT) :eaddrinuse
```

Tell-tale: the blocked port is 4000 (from `runtime.exs`), not 4002 (from
`test.exs`).

**Mechanism.** `config/runtime.exs` runs in ALL environments and AFTER
`config/test.exs`. Unguarded listener config in `runtime.exs` wins:

```elixir
# config/runtime.exs — BAD: lines outside the prod guard
config :app, AppWeb.Endpoint, server: true
config :app, AppWeb.Endpoint, http: [port: String.to_integer(System.get_env("PORT", "4000"))]

if config_env() == :prod do
  # ... rest of prod config (DATABASE_URL, SECRET_KEY_BASE, PHX_HOST ...)
end
```

**Diagnosis.**

```bash
lsof -i:4000                               # dev beam.smp, or empty/TIME_WAIT
grep -n 'server: true\|http: \[port' config/runtime.exs
```

**Workaround (unblock without editing config):** env var wins over the
default.

```bash
PORT=4099 mix test
```

**Proper fix.** Move `server: true` / `http: [port: ...]` inside the prod
guard:

```elixir
if config_env() == :prod do
  config :app, AppWeb.Endpoint, server: true
  config :app, AppWeb.Endpoint, http: [port: String.to_integer(System.get_env("PORT", "4000"))]
end
```

Now `:test` keeps `test.exs`'s `server: false` and no listener starts. The
same `:eaddrinuse` surfaces through a `mix precommit` alias running the full
suite; `PORT=4099` works there too.

## `:eaddrinuse` when `mix run -e` boots the Endpoint

**Symptom.** Ad-hoc script via `mix run -e '...'` dies with `:eaddrinuse` while
the dev server holds the web port.

**Mechanism.** `mix run` boots the full application including the Endpoint.

**Fix 1 — skip the Endpoint with `MIX_ENV=test`** (test config sets
`server: false`):

```bash
MIX_ENV=test mix run -e '
alias MyApp.Repo
# query-level verification against the test DB
IO.puts("PASS: ...")
'
```

**Fix 2 — don't boot the app, start DB dependencies manually:**

```bash
mix run --no-start -e '
  Application.ensure_all_started(:postgrex)
  Application.ensure_all_started(:ecto_sql)
  {:ok, _} = MyApp.Repo.start_link()
  # now run your script
'
```

**Fix 3 — keep the server on another port for tests:**
`PORT=4077 mix test` (runtime.exs reads `System.get_env("PORT")`).

## `force_ssl` is compile-time: the build-time pattern

**Symptom.** Release boot aborts:

```
ERROR! application :my_app has a different value set for path [:force_ssl]
inside key MyAppWeb.Endpoint during runtime compared to compile time
  * Compile time value was not set
  * Runtime value was set to: [rewrite_on: [:x_forwarded_proto], ...]
```

**Mechanism.** `force_ssl` is a COMPILE-TIME setting (Phoenix 1.8+). Setting it
only in `config/runtime.exs` is too late — the endpoint was already compiled
without it.

**Correct pattern — read the env var in `config/prod.exs` at compile time:**

```elixir
# config/prod.exs
if System.get_env("DISABLE_FORCE_SSL") != "1" do
  config :MyApp, MyAppWeb.Endpoint,
    force_ssl: [
      rewrite_on: [:x_forwarded_proto],
      exclude: [hosts: ["localhost", "127.0.0.1"]]
    ]
end
```

In `config/runtime.exs` do NOT set `force_ssl`. Only set `PHX_SCHEME=http`
there (URL generation, not enforcement).

**VPN / plain-HTTP environments** (no TLS at the host level): build with
`DISABLE_FORCE_SSL=1` (compile time) + run with `PHX_SCHEME=http` (runtime):

```dockerfile
ARG DISABLE_FORCE_SSL=0
ENV DISABLE_FORCE_SSL=${DISABLE_FORCE_SSL}
```

```bash
docker build --build-arg DISABLE_FORCE_SSL=1 -t my_app .
PHX_SCHEME=http mix phx.server
```

Key insight: `force_ssl` is the one config value that looks runtime but is
compile-time. You CANNOT toggle it without a rebuild. This is by design —
Phoenix bakes it in to prevent accidental HTTP exposure.

## App-config overrides from env (DB-only, provider-driven)

Pattern for web-configurable feature settings: DB table is the source of
truth; env/app-config is only the fallback (kept so tests can inject via
`Application.put_env`). Getters:

```elixir
def chat_model, do: model_or_setting("chat")
defp model_or_setting(key) do
  case Settings.get("model_#{key}") do
    nil -> get(:"#{key}_model")
    ""  -> get(:"#{key}_model")
    model -> model
  end
rescue
  _ -> get(:"#{key}_model")
end
```

- `Settings.put(key, "")` stores nothing meaningful; normalize `""` → `nil`
  at the edge so `nil` means "fall back to default".
- Never read a secret-bearing env var at compile time via `@attr` — module
  attributes are evaluated when the module is compiled, so a later env change
  silently leaves stale values. Read at runtime, or read in
  `config/runtime.exs` into app env.
- Guard every getter with `rescue` so a missing settings table never crashes
  boot.

## Verification

```bash
grep -n 'server: true\|http: \[port' config/runtime.exs   # all inside :prod guard
PORT=4099 mix test                                         # no :eaddrinuse
grep -n 'force_ssl' config/prod.exs config/runtime.exs     # prod.exs only (compile-time)
MIX_ENV=test mix run -e 'IO.puts(Application.get_env(:app, AppWeb.Endpoint)[:server])'
# → nil or false
```