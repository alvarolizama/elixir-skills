---
name: phoenix-release-deploy
author: Álvaro Lizama
description: Deploy Phoenix (or any Elixir umbrella/app) with `mix release` artifacts to a PaaS like Coolify, Railway, Fly, or Render. Covers `mix phx.gen.release`, git-dep lock outdated in :prod, `mix compile` before `mix deps.get` Dockerfile bug, plain-HTTP deploys over LAN/VPN, Coolify pre-deploy hooks, `npm ci` vs `npm install` node mismatch, `mix release <name>` Unknown release, `validate_compile_env` boot abort, Ecto 3.14 storage_up :already_up, `bin/<app> eval` crash when domain code touches PubSub/TaskSupervisor during partial-boot (including `catch :exit` that `rescue` misses), prod-safe seed separation, search fallback-to-FTS when inference API is unreachable, Docker build OOM during rebar3 dep compilation (ERL_AFLAGS +S fix), PORT vs PHX_PORT vs EXPOSE port confusion, and a parameterised multi-stage Dockerfile + entrypoint template pair.
---

# Phoenix Release Deploy

Use this skill whenever the user is shipping a Phoenix app (or any Elixir OTP app) as a `mix release` to a container-based PaaS — Coolify, Railway, Fly, Render, ECS, k8s, plain Docker. The canonical Phoenix path is `mix phx.gen.release`, and the PaaS invokes the resulting `bin/migrate` / `bin/server` overlays.

## When to load

- User is hitting deploy errors on Coolify / Railway / Fly / Render and shows a build log mentioning `mix compile`, `mix release`, or `lock outdated`.
- User mentions `release`, `bin/migrate`, `ecto.migrate` in a deploy context, or wants to add migrations to deploy.
- User switches between Nixpacks and Railpack and the build still breaks the same way.
- Phoenix 1.7+ app that has no `rel/` directory yet, or has one but no `bin/migrate`.

## Canonical workflow (the right way)

1. Generate release scaffolding once:
   ```bash
   mix phx.gen.release
   ```
   This creates exactly the files you need and nothing more:
   - `lib/<app>/release.ex` — `MyApp.Release.migrate/0`, `rollback/2`, plus `repos/0` and `load_app/0`. Customize only to add `seed/0` or domain-specific commands.
   - `rel/overlays/bin/migrate` — `#!/bin/sh` wrapper that runs `exec ./<app> eval MyApp.Release.migrate`.
   - `rel/overlays/bin/server` — runs `PHX_SERVER=true exec ./<app> start`.
   - `rel/overlays/bin/migrate.bat` and `server.bat` — Windows twins. Do not delete on Unix-only targets; they are harmless and the generator ships them for a reason.

2. Verify the release locally before pushing:
   ```bash
   rm -rf _build/prod
   MIX_ENV=prod mix deps.get --only prod
   MIX_ENV=prod mix release
   ls _build/prod/rel/<app>/bin/   # must show: <app>, <app>.bat, migrate, migrate.bat, server, server.bat
   _build/prod/rel/<app>/bin/<app> eval "IO.puts(:ok)"  # must print :ok (DB will fail on prod config, that's expected)
   ```
   If `bin/migrate` and `bin/server` are missing from the release output, the `rel/overlays/bin/` files were not present at `mix release` time. Re-run `mix phx.gen.release`.

3. Configure the PaaS:
   - **Start command**: `/app/bin/server` (Coolify / generic container).
   - **Pre-deploy command**: `/app/bin/migrate`. This is a one-off: Coolify spins up the new container, runs the command, exits, then swaps traffic. Migrations are applied exactly once per deploy and the running containers stay up. This is safe for N replicas.
   - **First-deploy seed** (optional, when you need initial data): append `&& /app/bin/<app> eval MyApp.Release.seed`.

## Idempotent first-run setup (create DB → migrate → seed in one command)

Some projects need the database itself to be created on the first deploy
(no DBA or Coolify-managed Postgres with no manual psql step). Pattern:
one command that creates the DB if missing, runs migrations, then runs
seeds. Safe to call on every deploy.

Add `setup/0` and `create/0` to `lib/<app>/release.ex`, plus a
`rel/overlays/bin/setup` wrapper that runs it. Then point the PaaS
pre-deploy hook at `/app/bin/setup` instead of `/app/bin/migrate`.

```elixir
# lib/<app>/release.ex — additions
@doc """
Idempotent first-run setup: create DB if missing → migrate → seed.
Safe to invoke on every deploy.
"""
def setup do
  load_app()
  create()
  migrate()
  seed()
  :ok
end

def create do
  load_app()

  for repo <- repos() do
    case ensure_db_created(repo) do
      :ok -> :ok
      {:error, term} -> raise "failed to create db for #{inspect(repo)}: #{inspect(term)}"
    end
  end
end

defp ensure_db_created(repo) do
  case repo.__adapter__.storage_up(repo.config) do
    :ok ->
      IO.puts("[release] created database for #{inspect(repo)}")
      :ok

    {:error, {:already_up, _}} ->
      IO.puts("[release] database already exists for #{inspect(repo)}, skipping create")
      :ok

    {:error, term} ->
      {:error, term}
  end
end
```

```sh
# rel/overlays/bin/setup
#!/bin/sh
set -eu
cd -P -- "$(dirname -- "$0")"
exec ./<app> eval <App>.Release.setup
```

```sh
# rel/overlays/bin/setup.bat  (Windows twin — keep even on Unix-only targets)
@echo off
cd /D "%~dp0"
call <app>.bat eval <App>.Release.setup
```

**Multi-replica caveat:** this is **not** safe to run from N parallel
containers — two replicas racing on `storage_up` will trip
"database already exists" on the loser. For a single Coolify instance
this is fine. If you ever scale to 2+ replicas, switch the pre-deploy
hook back to `/app/bin/migrate` and create the DB exactly once via a
one-off container:

```sh
# One-off (Coolify "execute one-off command" on a stopped container)
/app/bin/<app> eval <App>.Release.create
```

The `priv/repo/seeds.exs` script itself should also be idempotent
(`Repo.get_by/2` then `Repo.insert!` only on `nil`) — `setup/0` runs
seeds on every deploy, so any `insert!` that isn't guarded will
crash with a unique constraint violation on the second run.

**Trade-off vs. `bin/migrate`-only hook:** the idempotent setup removes
the "did I remember to create the DB?" step, at the cost of giving the
release container the privilege to create databases. In a multi-tenant
or shared-DB environment, prefer the `bin/migrate`-only flow and have
DBA tooling create the DB.

## References

- `references/coolify-ssl-domains.md` — SSL-to-Postgres modes (ECTO_SSL/VERIFY),
  force_ssl compile-time vs runtime patterns, ARG vs ENV deploy toggles,
  session salt fail-closed, CHECK_ORIGINS for multi-origin deploys, and the
  Coolify env-var checklist.

## Common pitfalls in the release task code (lib/<app>/release.ex)

The `mix phx.gen.release` template gives you a working `migrate/0` out of
the box. The moment you add a `seed/0` or `setup/0` of your own, you have
to follow the same startup pattern or it will fail at runtime with a
misleading error.

### Pitfall A: `seed/0` calls `MyApp.Repo.get_by/3` without `Ecto.Migrator.with_repo/2`

The shipped `migrate/0` works because `Ecto.Migrator.with_repo/2` starts
the repo ad-hoc and registers it in `Ecto.Repo.Registry` for the duration
of the callback. If you write a `seed/0` that just does
`Code.eval_file("priv/repo/seeds.exs")` (or even just calls
`MyApp.Repo.get_by/3` from Elixir), you get:

```
** (RuntimeError) could not lookup Ecto repo MyApp.Repo because it was not started or it does not exist
    (ecto 3.14.0) lib/ecto/repo/registry.ex:22: Ecto.Repo.Registry.lookup/1
    (<app> 0.1.0) lib/<app>/repo.ex:2: MyApp.Repo.get_by/3
    /app/_build/prod/rel/<app>/lib/<app>-0.1.0/priv/repo/seeds.exs:13: (file)
```

`migrate/0` worked. `seed/0` didn't. The fix is to wrap the seed
callback in the same `Ecto.Migrator.with_repo/2` envelope — do not
assume `Application.ensure_loaded(:MyApp)` is enough (it loads the
module but does not start the supervisor that registers the repo).

```elixir
# CORRECT — seed runs with the repo alive
def seed do
  seeds_file = Application.app_dir(@app, "priv/repo/seeds.exs")
  for repo <- repos() do
    {:ok, _, _} =
      Ecto.Migrator.with_repo(
        repo,
        fn _repo -> Code.eval_file(seeds_file) end,
        timeout: 30_000
      )
  end
end

# WRONG — runs the seeds file outside any repo context
def seed do
  load_app()                              # only loads, does not start
  Code.eval_file("priv/repo/seeds.exs")    # Repo.get_by blows up
end
```

**Rule of thumb:** any function in `lib/<app>/release.ex` that touches
a repo must wrap the work in `Ecto.Migrator.with_repo/2`. `load_app/0`
that only does `Application.ensure_loaded/1` and
`Application.ensure_all_started(:ssl)` is **not** sufficient.

### Pitfall B: `create/0` reads `repo.config` before runtime config has been applied

`Ecto.Adapters.Postgres.storage_up/1` (called by your `create/0`)
resolves the database name and credentials by reading `repo.config`.
That config is set in `config/runtime.exs` under `if config_env() == :prod`,
which only runs as a config provider in a release boot. If you call
`storage_up/1` from a `bin/<app> eval "MyApp.Release.create"` invocation
that has not yet evaluated `runtime.exs`, you'll read a config that
points at a non-existent or default DB.

**Fix:** before reading `repo.config`, force `runtime.exs` evaluation.
The portable way is to touch `Application.get_all_env/1` (which triggers
the config provider):

```elixir
defp load_config do
  Application.ensure_all_started(:ssl)
  Application.ensure_loaded(@app)
  _ = Application.get_all_env(@app)   # forces runtime.exs evaluation
  :ok
end
```

Call `load_config/0` at the top of every public function
(`create/0`, `migrate/0`, `seed/0`, `rollback/2`).

### Pitfall C: `config/runtime.exs` defaults `PHX_HOST` to `"example.com"` and `PHX_SERVER` to unset

Both are silent foot-guns. They come from the `phx.new` template and
make sense in dev, but in prod:

- `PHX_HOST` defaulting to `"example.com"` means every URL the app
  generates (login redirects, signed URLs, Mailer links) silently
  points at `example.com` until you notice. **Fix:** raise at boot
  with a clear message. Never have a hard-coded fallback host in
  `runtime.exs`.
- `PHX_SERVER` not being set means the endpoint starts with
  `server: false` and logs `"Configuration :server was not enabled for
  <App>Web.Endpoint, http/https services won't start"` on every
  container start. This bites you when the PaaS doesn't invoke your
  `bin/server` overlay (e.g. it just calls `bin/<app> start` or the
  start command is a direct `mix phx.server` call). **Fix:** enable
  `server: true` for `:prod` in `runtime.exs` — but keep the
  `PHX_SERVER` gate for other envs. `runtime.exs` runs in EVERY
  environment, so an unconditional `server: true` makes `mix test` boot
  the endpoint and crash with `:eaddrinuse` when a dev server is
  already on the port (verified on MyApp):

```elixir
# runtime.exs — prod always serves; dev/test keep the PHX_SERVER gate
if config_env() == :prod or System.get_env("PHX_SERVER") do
  config :MyApp, MyAppWeb.Endpoint, server: true
end
```

```elixir
# runtime.exs — strict in :prod
host =
  System.get_env("PHX_HOST") ||
    raise """
    environment variable PHX_HOST is missing.
    Set it to the public domain the app is served from.
    """

config :MyApp, MyAppWeb.Endpoint,
  server: true,                          # unconditional
  url: [host: host, port: 443, scheme: "https"],
  http: [ip: {0, 0, 0, 0, 0, 0, 0, 0}]
```

### Pitfall D: Serving over plain HTTP (LAN / VPN / custom port) without TLS

The Phoenix 1.8 default `config/runtime.exs` is hard-coded for HTTPS:

```elixir
if System.get_env("PHX_SERVER") do
  config :MyApp, MyAppWeb.Endpoint, server: true
end
...
config :MyApp, MyAppWeb.Endpoint,
  url: [host: host, port: 443, scheme: "https"]
```

And `config/prod.exs` ships with `force_ssl: [rewrite_on: [:x_forwarded_proto], ...]`.

This breaks three common deploy topologies:

1. **Direct LAN / VPN access** (NetBird, Wireguard, Tailscale, plain `192.168.x.x`) — no TLS terminator in front, just plain HTTP. `force_ssl` will 301 every request to `https://...` and the client hangs.
2. **Custom port over HTTPS** (e.g. `<app>.example.com:8443`) — `url: [host: "<app>.example.com", port: 443]` generates wrong URLs, redirects point at port 443.
3. **PaaS that does not invoke `bin/server`** — e.g. a build pack that runs `bin/<app> start` directly. The `PHX_SERVER` env var is never set, so the endpoint starts with `server: false` and logs the warning below every container boot:

   ```
   [warning] Configuration :server was not enabled for MyAppWeb.Endpoint, http/https services won't start
   [info]    Running MyAppWeb.Endpoint with Bandit ... at :::4000 (http)
   [info]    Access MyAppWeb.Endpoint at https://<host>:4000
   [warning] url: [host: ...] configuration value "host.example:5000" for MyAppWeb.Endpoint is invalid
   [warning] Connection that looks like TLS received on a clear channel
   ```

The last three are dead giveaways that the runtime config is still HTTPS-shaped. The first (`url: ... is invalid`) means the host string has the port glued on (`"local-apps.vpn.cloud:5000"`); Phoenix rejects this and you have to put host and port in separate env vars.

**Fix.** Make `PHX_HOST` / `PHX_SCHEME` / `PHX_PORT` steerable in `runtime.exs` for URL generation — but **keep `force_ssl` in `prod.exs`**. Phoenix marks `:force_ssl` as compile-time (`compile_env` inside the endpoint), so setting it in `runtime.exs` aborts the release boot (verified empirically on MyApp, Phoenix 1.8 / Elixir 1.20):

```
ERROR! the application :MyApp has a different value set for path [:force_ssl] inside key
MyAppWeb.Endpoint during runtime compared to compile time. Since this application environment
entry was marked as compile time, this difference can lead to different behavior than expected:
  * Compile time value was not set
  * Runtime value was set to: [rewrite_on: [:x_forwarded_proto], ...]
Runtime terminating during boot ({<<"aborting boot">>,[{'Elixir.Config.Provider',boot,2,[]}]})
```

The working pattern is: `force_ssl` conditional on a **build-time** env in `prod.exs`, scheme/port/host at runtime:

```elixir
# config/prod.exs — force_ssl stays HERE (compile-time). Toggle with the
# DISABLE_FORCE_SSL=1 BUILD arg for plain-HTTP images; runtime env has no effect.
if System.get_env("DISABLE_FORCE_SSL") != "1" do
  config :MyApp, MyAppWeb.Endpoint,
    force_ssl: [rewrite_on: [:x_forwarded_proto], exclude: [hosts: ["localhost", "127.0.0.1"]]]
end
```

```elixir
# config/runtime.exs
host =
  System.get_env("PHX_HOST") ||
    raise """
    environment variable PHX_HOST is missing.
    Set it to the bare hostname (no scheme, no port).
    """

scheme = System.get_env("PHX_SCHEME", "https")
url_port = String.to_integer(System.get_env("PHX_PORT", "443"))

# server: true in prod only — unconditionally setting it for ALL envs makes
# `mix test` boot the endpoint and collide with a dev server on the same port.
if config_env() == :prod or System.get_env("PHX_SERVER") do
  config :MyApp, MyAppWeb.Endpoint, server: true
end

config :MyApp, MyAppWeb.Endpoint,
  url: [host: host, port: url_port, scheme: scheme],
  http: [ip: {0, 0, 0, 0, 0, 0, 0, 0}]
```

```dockerfile
# Dockerfile — build-time switch for plain-HTTP images
ARG DISABLE_FORCE_SSL=""
ENV DISABLE_FORCE_SSL=${DISABLE_FORCE_SSL}
```

Then in the PaaS (Coolify / Railpack / Fly / etc.):

- **HTTPS (default)**: just `PHX_HOST`, `PHX_PORT`, `PHX_SCHEME=https`.
- **Plain HTTP (VPN tunnel)**: rebuild with `--build-arg DISABLE_FORCE_SSL=1` **and** set runtime `PHX_SCHEME=http`. Both are needed: the build arg kills the 301-to-https redirect, the runtime var makes generated URLs use http.

**Why the build-arg dance:** it would be nicer to toggle `force_ssl` at runtime with `PHX_SCHEME=http` and skip the rebuild, but `validate_compile_env` makes that impossible — `force_ssl` is baked into the `.app` resource file at `mix release` time. Accept the rebuild; it's the only correct lever.

### Pitfall E: `validate_compile_env` aborts boot when a compile-time env is set at runtime

A release that builds fine can crash at boot with:

```
ERROR! the application :MyApp has a different value set for key :dns_cluster_query during runtime compared to compile time. Since this application environment entry was marked compile time, this difference can lead to different behavior than expected:
  * Compile time value was not set
  * Runtime value was set to: nil
To fix this error, you might:
  * Make the runtime value match the compile time one
  * Recompile your project...
  * Alternatively, you can disable this check. If you are using releases, you can set :validate_compile_env to false...
Runtime terminating during boot ({<<"aborting boot">>,[{'Elixir.Config.Provider',boot,2,[]}]})
```

**Root cause:** `Application.compile_env/3` called in a module attribute (e.g. `@children` in `application.ex`) marks that config key as compile-time. If `config/runtime.exs` then sets the same key at boot (even to `nil` via `System.get_env("VAR")` when the env var is absent), Elixir's `validate_compile_env` check sees a mismatch and aborts boot. The compile-time value was "not set" (the `compile_env` default was used) but the runtime value is `nil` — they differ.

The classic trigger is `DNSCluster` config in `application.ex`:

```elixir
# WRONG — marks :dns_cluster_query as compile-time
@children [
  ...
  {DNSCluster, query: Application.compile_env(:MyApp, :dns_cluster_query, %{}) |> Map.get(:query) || :ignore},
  ...
]

# runtime.exs sets it at boot:
config :MyApp, :dns_cluster_query, System.get_env("DNS_CLUSTER_QUERY")
```

**Fix:** move the children list into the `start/2` callback and use `Application.get_env/2` (runtime read) instead of `Application.compile_env/3`:

```elixir
# CORRECT — runtime read, no compile_env marking
@impl true
def start(_type, _args) do
  children = [
    ...
    {DNSCluster, query: Application.get_env(:MyApp, :dns_cluster_query) || :ignore},
    ...
  ]
  Supervisor.start_link(children, strategy: :one_for_one, name: MyApp.Supervisor)
end
```

**Rule of thumb:** never use `Application.compile_env/3` for a key that `runtime.exs` also sets. `compile_env` is for keys that are truly compile-time only (like `:force_ssl` in `prod.exs`). If the key appears in `runtime.exs`, read it at runtime with `Application.get_env/2` inside `start/2`, not in a module attribute. The `validate_compile_env` check exists to catch this class of bug — disabling it (`validate_compile_env: false`) is a band-aid that hides the real problem.

### Pitfall F: Ecto 3.14 `storage_up` returns `{:error, :already_up}` (atom), not `{:error, {:already_up, _}}` (tuple)

When `MyApp.Release.create/0` (or any `setup/0` that calls `storage_up`) runs against a database that already exists, Ecto 3.14+ returns `{:error, :already_up}` — a bare atom, not the `{:error, {:already_up, _}}` tuple that older Ecto versions returned. If your `ensure_db_created/1` only pattern-matches the tuple form, it falls through to the catch-all `{:error, term}` clause and raises:

```
** (RuntimeError) failed to create db for MyApp.Repo: :already_up
    (MyApp 0.1.0) lib/MyApp/release.ex:48: anonymous fn/1 in MyApp.Release.create/0
```

This happens on **every deploy after the first** — the first deploy creates the DB (`:ok`), the second deploy finds it already up and crashes. The error message is misleading because it says "failed to create" when the DB is actually fine.

**Fix:** match both shapes:

```elixir
defp ensure_db_created(repo) do
  case repo.__adapter__().storage_up(repo.config()) do
    :ok ->
      :ok

    {:error, :already_up} ->              # Ecto 3.14+ (atom)
      :ok

    {:error, {:already_up, _}} ->         # older Ecto (tuple)
      :ok

    {:error, term} ->
      {:error, term}
  end
end
```

**Also fix the deprecation warnings:** Elixir 1.20+ requires parentheses on `repo.__adapter__()` and `repo.config()` — without them you get `using map.field notation (without parentheses) to invoke function ... is deprecated`. These are warnings, not errors, but they clutter the deploy log and `--warnings-as-errors` will fail the build.

### Pitfall G: `Repo.delete_all/1` returns `{count, nil}` — not just the count

When writing release task code or admin functions that delete rows (e.g. a
`reset_context/1` that wipes all pages/relations/versions in a context),
`Repo.delete_all/1` returns a **tuple** `{count, nil}`, not a bare integer.
Storing the tuple directly in a result map and then interpolating it in a
flash message or gettext call crashes:

```elixir
# WRONG — stores {42, nil} in the map, crashes on interpolation
versions_count = from(v in PageVersion, where: ...) |> Repo.delete_all()
%{versions: versions_count, ...}   # versions_count is {42, nil}

# CORRECT — pattern-match to extract the count
{versions_count, _} = from(v in PageVersion, where: ...) |> Repo.delete_all()
%{versions: versions_count, ...}   # versions_count is 42
```

This is easy to miss because `Repo.all/1` returns a list (no tuple), and
`Repo.insert/1` / `Repo.update/1` / `Repo.delete/1` return `{:ok, struct}`
or `{:error, changeset}` — the `{count, nil}` shape is unique to
`delete_all/1` and `update_all/1`. The error only surfaces at runtime when
the result is consumed (e.g. interpolated in a LiveView flash), not at
compile time.

**Rule of thumb:** any time you call `Repo.delete_all/1` or
`Repo.update_all/1` and want the count, pattern-match `{count, _} = ...`
at the call site. Don't store the raw return value.

### Pitfall H: `bin/<app> eval` crashes when domain code touches PubSub or TaskSupervisor

During release tasks (`bin/<app> eval "MyApp.Release.setup"`, `bin/<app> eval "MyApp.Release.seed"`), `Ecto.Migrator.with_repo/2` starts **only the repo** — not the full supervision tree. `Phoenix.PubSub`, `TaskSupervisor`s, `Registry`s, and your app's own `DynamicSupervisor`s are all down. If your `seeds.exs` calls domain functions that broadcast or schedule background work (very common in apps where `create_page/1` also notifies LiveViews and schedules embeddings), the eval crashes:

```
** (ArgumentError) unknown registry: MyApp.PubSub. Either the registry name is invalid or the registry is not running, possibly because its application isn't started
    (elixir 1.20.2) lib/registry.ex:1280: Registry.meta/2
    (phoenix_pubsub 2.2.0) lib/phoenix/pubsub.ex:232: Phoenix.PubSub.broadcast/4
    (MyApp 0.1.0) lib/MyApp/brain.ex:512: MyApp.Brain.update_page/2
    lib/MyApp-0.1.0/priv/repo/seeds.exs:46: (file)

** (exit) exited in: GenServer.call(MyApp.Embeddings.TaskSupervisor, {:start_task, ...}, :infinity)
    ** (EXIT) no process: the process is not alive or there's no process currently associated with the given name
    (elixir 1.20.2) lib/gen_server.ex:1176: GenServer.call/3
    (MyApp 0.1.0) lib/MyApp/embeddings.ex:84: MyApp.Embeddings.schedule/1
    lib/MyApp-0.1.0/priv/repo/seeds.exs:46: (file)
```

The first error (`unknown registry: MyApp.PubSub`) comes from `Phoenix.PubSub.broadcast/3`. The second (`no process ... TaskSupervisor`) comes from `Task.Supervisor.start_child/3`. Both fire because the domain layer (`Brain.create_page/1`) calls them as side-effects of creating a page, and the seeds script calls `create_page/1`.

**Fix: make the side-effect calls resilient.** These are UI notifications and background enhancements, not data-integrity concerns — safe to skip when the process isn't running. Wrap each in a `rescue` **and, for `Task.Supervisor.start_child/3`, also a `catch :exit`** — see the critical caveat below.

```elixir
# PubSub broadcast — UI notification, skip if PubSub is down
def broadcast_page_change(context_id, action, page) do
  Phoenix.PubSub.broadcast(MyApp.PubSub, "brain:#{context_id}", {:page_changed, action, page})
rescue
  ArgumentError -> :ok   # PubSub not started (release task / eval mode)
end

# TaskSupervisor — background enhancement, skip if supervisor is down
def schedule(%Page{} = page) do
  cond do
    not Inference.enabled?() -> :ignored
    not needs_embedding?(page) -> :ignored
    schedule_async?() ->
      Task.Supervisor.start_child(MyApp.Embeddings.TaskSupervisor, fn -> generate(page) end, restart: :transient)
      :ok
    true -> generate(page); :ok
  end
rescue
  _ -> :ignored   # catches raised exceptions
catch
  :exit, _ -> :ignored   # CRITICAL: catches {:noproc, _} from GenServer.call on dead supervisor
end
```

### ⚠️ Critical: `rescue` does NOT catch `:exit` signals

This is the single most common mistake when hardening domain code for release tasks. `Task.Supervisor.start_child/3` internally does a `GenServer.call/3` on the supervisor name. When that supervisor isn't alive (partial boot via `Ecto.Migrator.with_repo/2`), the call **exits** with `{:noproc, _}` — it does not raise. A bare `rescue _ -> :ignored` will **not** catch it, and the seed/migration script crashes:

```
** (exit) exited in: GenServer.call(MyApp.Embeddings.TaskSupervisor, {:start_task, ...}, :infinity)
    ** (EXIT) no process: the process is not alive or there's no process currently associated with the given name
```

**`rescue` only catches exceptions (from `raise`/`throw`). `catch :exit, _` catches exit signals.** You need **both** clauses when the code might both raise (e.g. `ArgumentError` from PubSub) and exit (e.g. `:noproc` from TaskSupervisor). The `rescue` catches the PubSub case; the `catch :exit, _` catches the TaskSupervisor case. Omitting the `catch` clause is the bug — it will pass your test suite (tests start the full supervision tree) and only fail in prod seeds/release eval.

**Rule of thumb:** any function in your domain layer that calls `Phoenix.PubSub.broadcast`, `Task.Supervisor.start_child`, `Registry.register`, or `DynamicSupervisor.start_child` should be safe to call from a release task. Wrap side-effects in `rescue _ -> :ignored` **plus** `catch :exit, _ -> :ignored` (both clauses — the `:exit` clause is the one most commonly forgotten and the one that bites in prod). Never let a UI notification or background job crash a seed/migration run.

**Why not start the full app during seeds?** You could call `Application.ensure_all_started(:MyApp)` instead of `Ecto.Migrator.with_repo/2`, but that starts the Phoenix endpoint, the scheduler, and every supervisor — which then try to connect to the DB, bind ports, and run cron jobs during a migration. That's worse. The `with_repo/2` pattern is correct; the domain layer just needs to tolerate the partial boot.

### Pattern: separate context seed from demo content (prod-safe seeds)

The default `setup/0` → `seed/0` → `Code.eval_file("priv/repo/seeds.exs")` path runs **the entire seeds file** on every fresh prod deploy. If your `seeds.exs` creates demo content (sample goals, todos, notes, relations — the kind of thing useful in dev/test but not in a real user's brain), that content pollutes the prod database on first boot. Idempotency (`Repo.get_by` then insert) prevents duplicates on subsequent deploys, but the **first** deploy still creates 20 demo pages.

**Fix: split `seed/0` (full demo, dev/test) from `seed_context/0` (context only, prod-safe), and point `setup/0` at the prod-safe one.**

```elixir
# lib/<app>/release.ex

@doc """
Idempotent first-run setup: create DB → migrate → seed default context.
Safe for prod: does not create demo pages/todos/relations.
"""
def setup do
  load_config()
  create()
  migrate()
  seed_context()
  :ok
end

@doc """
Create only the default context if it doesn't exist.
Used by setup/0 so prod gets a working context without demo content.
"""
def seed_context do
  load_config()

  for repo <- repos() do
    {:ok, _, _} =
      Ecto.Migrator.with_repo(
        repo,
        fn _repo ->
          alias MyApp.Repo
          alias MyApp.Brain
          alias MyApp.Brain.Context

          slug = MyApp.Auth.default_context_slug()
          name = MyApp.Auth.default_context_name()

          case Repo.get_by(Context, slug: slug) do
            nil ->
              {:ok, ctx} = Brain.create_context(%{name: name, slug: slug})
              Logger.info("[release] created context: #{ctx.name} (#{ctx.slug})")

            existing ->
              Logger.info("[release] context already exists: #{existing.name} (#{existing.slug})")
          end
        end,
        timeout: @start_timeout
      )
    end
  end
end

@doc """
Run priv/repo/seeds.exs (full demo content). Dev/test only.
For prod, use seed_context/0 instead.
"""
def seed do
  load_config()
  seeds_file = Application.app_dir(@app, "priv/repo/seeds.exs")

  for repo <- repos() do
    {:ok, _, _} =
      Ecto.Migrator.with_repo(
        repo,
        fn _repo -> Code.eval_file(seeds_file) end,
        timeout: @start_timeout
      )
    end
  end
end
```

Then update `docker/entrypoint.sh` (or `templates/entrypoint.sh`) to reflect that `setup` no longer seeds demo content:

```sh
# Runs MyApp.Release.setup/0 (create DB if missing → migrate → seed default
# context) before starting the Phoenix release. Demo content (goals, todos,
# notes) is NOT seeded in prod — run `bin/<app> eval MyApp.Release.seed`
# manually if you need it.
```

**Dev/test still uses the full seeds:** `mix seed` alias (`run priv/repo/seeds.exs`) is unchanged — it evaluates the file directly without going through `Release`. Only the release entrypoint path is affected.

**Optional hardening: gate the auto-created seed row behind an env var (2026-08-06).** The `seed_context/0` pattern above resurrects its row on EVERY deploy — if the user deletes the default context (or tenant/org) in the UI, the next deploy recreates it ("zombie context"). If deletion should stick, only auto-create when the env vars are explicitly set:

```elixir
# lib/<app>/auth.ex (or wherever the defaults live)
@doc "True when the default context was explicitly configured via env."
def default_context_configured? do
  System.get_env("DRAN_CONTEXT_SLUG") != nil or System.get_env("DRAN_CONTEXT_NAME") != nil
end
```

```elixir
# lib/<app>/release.ex
def seed_context do
  if MyApp.Auth.default_context_configured?() do
    do_seed_context()   # the original with_repo body, extracted to a defp
  else
    Logger.info("[release] DRAN_CONTEXT_SLUG/NAME not set, skipping default context seed")
    :ok
  end
end
```

And the same guard at the top of `priv/repo/seeds.exs`:

```elixir
unless MyApp.Auth.default_context_configured?() do
  IO.puts("DRAN_CONTEXT_SLUG/DRAN_CONTEXT_NAME not set — skipping seeds.")
  exit(:normal)   # NOT Kernel.exit(0) — that aborts mix setup/ecto.reset aliases
end
```

Three gotchas: (1) read the env at RUNTIME in a function body — a module attribute (`@configured System.get_env(...)`) is baked at compile time and `--warnings-as-errors` will flag the constant `if` as an unreachable-clause warning (dev compiles with the var unset); (2) use `exit(:normal)`, not `Kernel.exit(0)` — a non-zero/abnormal exit inside `mix setup` / `mix ecto.reset` fails the whole alias chain; (3) remember to actually REMOVE the env var from the PaaS (Coolify) — if `DRAN_CONTEXT_SLUG=personal` is still set in the container env, the context revives on next deploy regardless of this gate.

**If you ever need demo content in prod** (e.g. a fresh staging deploy), run it manually:
```bash
bin/<app> eval "MyApp.Release.seed"
```

**Verification:** after implementing the split, verify both paths — `seed_context/0` should create zero pages (only the context), `seed/0` should create the full demo set. With a running server, use `psql` or the MCP `dran_get_stats` tool to count pages after each path.

### Pitfall I: Search hard-fails when the inference API host is unreachable

When an OpenAI-compatible inference API is **configured** (URL + API key present,
so `Config.enabled?()` returns `true`) but temporarily unreachable — host down,
VPN disconnected, DNS not resolving — `semantic_search/1` and `hybrid_search/1`
call `Inference.embed/1` → `Client.embeddings/2` → `Req.request/1`, which returns
`{:error, %Req.TransportError{reason: :econnrefused}}`.

The fallback in `Brain.search/2` only caught `{:error, :not_configured}` — the
`TransportError` bubbled up to the user as `Error: %Req.TransportError{...}`.
This is easy to miss because short queries (≤2 words, ≤25 chars) use FTS/fuzzy
and never touch the inference API, so search appears to work until someone types
a longer query.

**Fix.** Guard the `requested_strategy == :auto` case to fall back to FTS on
**any** error — not just `:not_configured`:

```elixir
def search(query_string, opts \\ []) do
  requested_strategy = Keyword.get(opts, :strategy, :auto)
  strategy = resolve_strategy(requested_strategy, query_string)

  case do_search(query_string, opts, strategy) do
    {:error, :not_configured} when requested_strategy != :auto ->
      {:error, :not_configured}

    # Auto strategy should never hard-fail — not_configured, host down,
    # timeout, etc. all fall back to fts so search always works.
    {:error, _reason} when requested_strategy == :auto ->
      do_search(query_string, opts, :fts) |> normalize_results(:fts)

    result ->
      normalize_results(result, strategy)
  end
end
```

Note: `resolve_strategy/2` always converts `:auto` to a concrete strategy
(`:fts`, `:hybrid`, etc.), so you must capture the **requested** strategy before
resolving it — comparing `strategy == :auto` after `resolve_strategy/2` triggers
a compiler warning ("comparison between distinct types") and is always false.

**Diagnostics.** Add a `Client.ping/0` health-check (`GET /models`) with a
"Probar conexión" button in the Settings UI so the user can see whether the
inference server is reachable (latency + model count on success, specific error
on failure) without guessing from search errors.

### Pitfall G: A "passing" precommit doesn't prove the release works

`mix precommit` runs against `:test` (or `:dev` for the compile step).
The `:prod` boot path is a different code path: `runtime.exs` is
evaluated as a config provider, `rel/overlays/bin/*` is what
`bin/<app>` invokes, and the Ecto adapter pool is sized differently.
**Always re-run the local release smoke test** after touching
`config/runtime.exs`, `lib/<app>/release.ex`, or `rel/overlays/bin/`:

```bash
rm -rf _build/prod
MIX_ENV=prod mix release
DATABASE_URL=ecto://nope:nope@127.0.0.1:1/nope \
  SECRET_KEY_BASE=some-test-secret \
  _build/prod/rel/<app>/bin/<app> eval "IO.puts(:ok)"
# must print :ok. If you get "DATABASE_URL is missing" or any
# Application.load error, the runtime config is broken.
```

If `eval "IO.puts(:ok)"` fails, your release is broken regardless of
what `mix precommit` says. Fix the runtime config first, then rerun
the release.

## The two common mistakes and how to spot them

### Mistake 1: Adding `commands:` under `releases:` in `mix.exs` to register `migrate`

```elixir
# WRONG — does nothing useful, the commands never appear in `bin/<app>`
def project do
  [..., releases: [
    MyApp: [
      commands: [
        migrate: ["ecto.migrate"],          # even more wrong: no `mix` inside a release
        seed: ["run priv/repo/seeds.exs"]  # same problem
      ]
    ]
  ]]
end
```

Two stacked errors here:
- Inside a release there is no `mix` binary. `mix ecto.migrate` and `run priv/repo/seeds.exs` cannot resolve. You must use `eval "MyApp.Release.migrate"` or call `Ecto.Migrator` directly from your own module.
- Even with `eval "..."`, the `commands:` key under `releases:` does not register user-facing bin commands. The `bin/<app>` script's hard-coded command list is `start, start_iex, daemon, daemon_iex, install, eval, rpc, remote, restart, stop, pid, version` — that's it. Custom bin commands come from `rel/overlays/bin/*` scripts that wrap `eval`, not from the `releases:` config.

**Symptom in deploy log:** "release generated, `bin/migrate` still missing" or "`migrate` command not found". **Fix:** delete the `commands:` block, ensure `rel/overlays/bin/migrate` exists, regenerate the release.

### Mistake 2: `lock outdated` on a git-pinned dep in `:prod`

```
Unchecked dependencies for environment prod:
* heroicons (https://github.com/tailwindlabs/heroicons.git - <full sha>)
  lock outdated: the lock is outdated compared to the options in your mix.exs.
** (Mix) Can't continue due to errors on dependencies
```

**Root cause** (from `lib/mix/scm/git.ex` in Elixir ~1.15–1.20): `lock_status/1` returns `:outdated` when `get_lock_rev/2` returns `nil`, which happens when `lock_opts == get_lock_opts(opts)` is `false`. `get_lock_opts/1` only retains `:branch | :ref | :tag | :sparse | :subdir | :depth` from the dep options. So `:app`, `:compile`, `:runtime`, etc. are filtered out and don't cause this — but `:ref` vs `:tag` (and the order of those four keys) absolutely does, because Mix compares the keyword list literally.

**Diagnosis flow:**
1. Confirm `:prod` is the failing env. In `:dev` Mix tolerates the same lock mismatch; `:prod` is strict. So `mix compile` locally can pass while CI/prod build fails.
2. Compare the four lock-bearing keys in `mix.exs` and `mix.lock`:
   - URL (`github:` vs `git:` — they expand to the same URL, that's fine)
   - `ref:` / `branch:` / `tag:` — pick exactly one
   - `sparse:`, `subdir:`, `depth:` — order matters because Mix compares the keyword list literally
3. If they match exactly and it still fails, Nixpacks/Railpack is reusing a cached layer with an older `mix.lock`. Either:
   - commit the lock and force a no-cache rebuild in the PaaS, or
   - provide a custom Dockerfile (multi-stage, secrets only in runtime) and switch the build pack to Dockerfile, or
   - add an `nixpacks.toml` with explicit `[phases.install]` `cmds = ["mix deps.get"]` to force re-resolution.

**Symptom in deploy log:** `lock outdated` and the commit SHA shown is the same SHA you have in your lock + mix.exs. The mismatch is in the **options keyword list**, not the commit.

## Custom Dockerfile (multi-stage) — when to use it, and the entrypoint-migrator pattern

Switching Coolify from the Nixpacks/Railpack build pack to a repo-root `Dockerfile` is the most reliable path when the build pack keeps tripping on cache staleness or the `lock outdated` mismatch (see Mistake 2 above). You control the install + build + start phases, the image is reproducible, and there is no hidden layer cache.

**Use the templates, don't hand-roll:** `templates/Dockerfile.multistage` and `templates/entrypoint.sh` in this skill are known-good starting points. Copy them into the repo, replace the placeholders (`APP_NAME` in the Dockerfile, `BIN_NAME` + `APP_MODULE` in the entrypoint, and the `ELIXIR_IMAGE` / `DEBIAN_RUNTIME` tags), and commit. The `mix phx.gen.release --docker` generator produces a similar Dockerfile but writes concrete values that are harder to re-use across projects; the templates here are parameterised on purpose.

### Pitfall: `mix compile` before `mix deps.get` in the Dockerfile

The build failure that most often pushes people to a custom Dockerfile is:

```
#15 0.560 Unchecked dependencies for environment prod:
#15 0.560 * heroicons (https://github.com/tailwindlabs/heroicons.git - <sha>)
#15 0.560   lock outdated: the lock is outdated compared to the options in your mix.exs.
#15 0.562 ** (Mix) Can't continue due to errors on dependencies
#15 ERROR: process "/bin/bash -ol pipefail -c mix compile" did not complete successfully: exit code: 1
```

The Dockerfile did `COPY . /app/.` then `RUN mix compile` **without a `mix deps.get` step first**. Inside the image, the deps were never fetched, so Mix can't verify the lock and bails with `lock outdated` — even when `mix.exs` and `mix.lock` agree perfectly. In `:dev` Mix tolerates the same mismatch locally, so this only surfaces in the `:prod` container build.

**Fix (already in the template):** split the dep layer from the app layer and run `mix deps.get --only prod` before `mix compile`:

```dockerfile
# deps layer (cached until mix.exs/mix.lock change)
COPY mix.exs mix.lock ./
COPY config config
RUN mix deps.get --only prod
RUN mix deps.compile

# app layer
COPY lib lib
COPY priv priv
COPY assets assets
COPY rel rel
RUN cd assets && npm install
RUN mix compile
RUN mix assets.deploy
RUN mix release
```

The `mix deps.get` step is the load-bearing one. `mix deps.compile` is good practice but not what fixes the error — the error is about the lock not being fetched, not about it not being compiled.

### Where migrations run: entrypoint vs pre-deploy hook

Two valid patterns, pick by topology:

**Entrypoint migrator (single-instance default):** the container's `ENTRYPOINT` runs `bin/<app> eval MyApp.Release.migrate` then `exec bin/<app> start` on every boot. No PaaS pre-deploy command needed. A failed migration aborts boot and the PaaS rolls back. Use `templates/entrypoint.sh`. Trade-off: with N replicas all N run the migration on deploy — only safe with idempotent migrations (which they should be anyway, since Ecto tracks `schema_migrations`).

**Pre-deploy hook (multi-replica / managed DB):** configure the PaaS Pre Deployment Command to `/app/bin/migrate`. Coolify spins up the new container, runs the command, exits, then swaps traffic. Migrations apply exactly once per deploy. The running containers stay up. See `references/coolify-railpack-nixpacks-notes.md` for the field name.

The entrypoint pattern is the lower-friction default for a single-instance Coolify deploy: no PaaS config to remember, migrations can't be forgotten, and a broken migration fails loud at boot. Switch to the pre-deploy hook only when you scale past one replica or the DB user lacks migration privileges on the running container.

### Pitfall: inventing an `hexpm/elixir` image tag that doesn't exist

The `ELIXIR_IMAGE` `ARG` in the Dockerfile must point at a tag that is **actually published** on Docker Hub. The tag format is `<elixir>-erlang-<otp>-debian-<distro>-<yyyymmdd>-slim`, but hexpm only publishes a subset of version combinations — guessing a tag (e.g. `1.18.3-erlang-27.2-debian-bookworm-20250203-slim`) that *looks* right but was never built fails the build immediately at the `FROM` line:

```
#5 [internal] load metadata for docker.io/hexpm/elixir:1.18.3-erlang-27.2-debian-bookworm-20250203-slim
#5 ERROR: ...: not found
ERROR: failed to build: failed to solve: docker.io/hexpm/elixir:1.18.3-...-slim: not found
```

**Always verify the tag before committing.** Query the Docker Hub API and filter to your Elixir + OTP + distro + slim:

```bash
curl -s "https://hub.docker.com/v2/repositories/hexpm/elixir/tags?page_size=100&name=1.20" \
  | python3 -c "import json,sys; [print(t['name']) for t in json.load(sys.stdin)['results']
                if 'erlang-29' in t['name'] and 'bookworm' in t['name'] and 'slim' in t['name']]"
```

Pick the closest published tag to what the dev toolchain actually runs (check `mise current` / `elixir --version` locally — matching the container to local avoids skew bugs). Patch-level differences are fine (local 1.20.1 + container 1.20.2 is compatible). Keep the runtime `debian:bookworm-<yyyymmdd>-slim` tag's date **identical** to the build image's date slug to avoid glibc drift between stages.

**This is the single most common Dockerfile authoring mistake for Elixir releases** — the tag format looks uniform, so a plausible-but-unpublished tag slips through and only fails at deploy time on the PaaS.

### Pitfall: `.dockerignore` excluding files the Dockerfile `COPY`s in a later stage

A `.dockerignore` at the repo root applies to **every** `COPY` in **every** stage of a multi-stage build, including the runtime stage. Excluding a directory that the Dockerfile later `COPY`s produces a cryptic error at the runtime stage:

```
#28 [app 7/8] COPY --chown=app:app docker/entrypoint.sh /app/entrypoint.sh
#28 ERROR: failed to calculate checksum of ref ...: "/docker/entrypoint.sh": not found
ERROR: failed to build: failed to solve: failed to compute cache key: failed to calculate checksum of ref ...: "/docker/entrypoint.sh": not found
```

The build stage succeeded (it never referenced `docker/`), so this looks like the file is missing from the repo — but `git status` shows it's committed. The real cause is a `.dockerignore` line like `/docker` or `/docker/**` that excludes the directory the runtime stage needs.

**Rule:** before adding a path to `.dockerignore`, grep the Dockerfile for every `COPY` (across all stages) and confirm none of them source from that path. Common safe-to-ignore paths (`_build`, `deps`, `assets/node_modules`, `.env`, `.git`) never appear in a `COPY` line. Paths like `docker/`, `rel/`, `config/`, `priv/` are frequently `COPY`d and must **not** be ignored.

### Build-time vs runtime env vars in the Dockerfile

All secrets go in runtime `ENV` (set via the PaaS env-var UI), never in `ARG`. Docker's `SecretsUsedInArgOrEnv` linter flags any `ARG`/`ENV` that looks like a secret, and the value lands in image layers / build metadata.

`DISABLE_FORCE_SSL` is always a **build arg** — `force_ssl` is compile-time in Phoenix, so a runtime env var can never disable it (see Pitfall D for the boot abort this avoids). Build plain-HTTP images with `--build-arg DISABLE_FORCE_SSL=1` and pair it with runtime `PHX_SCHEME=http`.

### Pitfall: `npm ci` fails on node/npm version mismatch

When the Dockerfile installs a different node major than the dev who generated `package-lock.json` used locally, `npm ci` aborts immediately:

```
#25 0.642 npm error
#25 0.642 npm error Clean install a project
#25 0.642 npm error
#25 0.642 npm error Usage:
#25 0.642 npm error npm ci
...
#25 0.643 npm error A complete log of this run can be found in: /root/.npm/_logs/...
#25 ERROR: process "/bin/sh -c cd assets && npm ci" did not complete successfully: exit code: 1
```

**Root cause:** `npm ci` is strict — it requires the lock file to have been generated with a compatible npm version. A `package-lock.json` with `lockfileVersion: 3` generated by node 22 / npm 10+ will fail `npm ci` inside a container running node 20 / npm 9. The error message is unhelpful — it just prints `npm ci` usage as if you'd typo'd the command.

**Fix (two options, pick one):**

1. **Switch to `npm install`** — more tolerant of lock version differences, still respects the lock file. The only downside is it may update `package-lock.json` if deps have drifted, but in a Docker build that's ephemeral and harmless.
2. **Match the node version** — bump the Dockerfile's node setup to the same major the dev team uses locally (check with `node --version` / `mise current`). Node 22 LTS (`setup_22.x`) is a safe default for 2025–2026 projects.

```dockerfile
# Fix: use npm install + node 22
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
  && apt-get install -y nodejs
...
RUN cd assets && npm install    # NOT npm ci
```

**Rule of thumb:** in a Dockerfile you control, `npm install` is the safer default than `npm ci` unless you have a specific reason to enforce lock fidelity (CI reproducibility, supply-chain audits). The tailwind/esbuild hex wrappers don't care — they fetch their own binaries independently of `node_modules`.

### Pitfall: Docker build OOM during `mix deps.compile` (Erlang/rebar3 deps)

In resource-constrained build environments (Coolify with 512 MB–1 GB RAM, small VPS), `mix deps.compile` can silently die during compilation of Erlang/rebar3-based hex packages (`idna`, `telemetry`, `telemetry_poller`). The build log shows the last line as `===> Compiling idna` (or similar rebar3 output) followed by a generic `exit code 255` / `exit code 1` with no Elixir stack trace. The Erlang VM spawns one scheduler per CPU core by default; when running inside a Docker container with tight memory limits, parallel compilation exhausts RAM and the OOM killer terminates the build process.

**Symptom:** Docker build fails at `RUN mix deps.compile` after compiling 10–12 packages. Only rebar3-based deps (identified by `[:rebar3]` in `mix.lock`) trigger this — Elixir deps compile fine. The log cuts off mid-compilation with no error message.

**Fix:** compile the rebar3 deps first with a single Erlang scheduler:

```dockerfile
# Compile Erlang/rebar3 deps first with a memory-constrained Erlang VM.
# +S 1:1 limits to 1 scheduler, dramatically reducing RAM usage.
RUN ERL_AFLAGS="+S 1:1" mix deps.compile idna telemetry telemetry_poller
RUN mix deps.compile
```

**Wrong flags to avoid:**
- `+MBas busy_wait` — `+MBas` is for memory allocator strategies (e.g. `aoff`, `bf`, `gf`), not busy waiting. Using it causes `bad "MBa" value: busy_wait` and the build fails immediately.
- `+S 1` (without `:1`) — valid but less explicit. `+S 1:1` sets both total and online schedulers to 1.

**Scope the flag:** use inline `ERL_AFLAGS="+S 1:1"` on the specific `RUN` line rather than `ENV ERL_AFLAGS=...` — the latter persists across all subsequent layers and slows down `mix compile` and `mix release` (which also run on the Erlang VM but don't need the memory constraint).

**Verification:** after the fix, the Docker build should complete `mix deps.compile` and proceed to `mix compile` / `mix assets.deploy` / `mix release`. If the same step still fails, the build container genuinely doesn't have enough RAM even for single-scheduler Erlang — increase the build container's memory limit in the PaaS or add swap to the host.

### Pitfall: `PORT` vs `PHX_PORT` vs `EXPOSE` confusion

Three different things that look the same but control different layers:

| Variable | What it does | Where |
|----------|-------------|-------|
| `PORT` | **Real listen port** — Bandit binds here inside the container | `runtime.exs`: `http: [port: String.to_integer(System.get_env("PORT", "4000"))]` |
| `PHX_PORT` | **Generated URL port** — the port that appears in redirects, emails, links | `runtime.exs`: `url: [port: String.to_integer(System.get_env("PHX_PORT", "443"))]` |
| `EXPOSE` | **Docker metadata** — purely documentary, does NOT set the actual listen port. Static, cannot read env vars | `Dockerfile`: `EXPOSE 4000` |

**Common deploy topology:** host exposes port 4001, container listens on 4000, PaaS maps host:4001 → container:4000:

```
PORT=4000           # Bandit listens here INSIDE the container
PHX_PORT=4001       # Public URLs use this port
EXPOSE 4000         # Matches PORT (Dockerfile static)
```

If `PORT=4001` but `EXPOSE 4000`, the container is listening on 4001 but the PaaS maps external traffic to 4000 → `ERR_CONNECTION_RESET` (nothing listening on 4000).

Simplest fix: pick one port and use it everywhere — set `PORT`, `PHX_PORT`, and `EXPOSE` to the same value. Only split them when you have a specific port-remapping topology (e.g. multiple services behind a single reverse proxy).

### Pitfall: `mix release <name>` fails with "Unknown release" when releases aren't configured

If the project never ran `mix phx.gen.release` (or the `releases:` block in `mix.exs` and `config/releases.exs` were removed), the release is not named-configured. Calling `mix release <name>` then fails:

```
#28 0.652 ** (Mix) Unknown release :MyApp. The available releases are: []
#28 ERROR: process "/bin/sh -c mix release MyApp" did not complete successfully: exit code: 1
```

**Root cause:** `mix release <name>` looks for a release configured under the `releases:` key in `mix.exs` or in `config/releases.exs`. When neither exists, Mix has no named release to build and bails. This is easy to miss because `rel/overlays/bin/{migrate,server,setup}` may still exist on disk (from a previous `phx.gen.release` run that was later partially reverted) — but overlays alone don't configure the release name.

**Fix:** use `mix release` **without** a name. It defaults to the `app:` atom from `mix.exs` (e.g. `:MyApp`), which is exactly what Phoenix expects. The output goes to `_build/prod/rel/<app>/` with `bin/<app>`, `bin/migrate`, `bin/server` all intact.

```dockerfile
# Fix: omit the release name
RUN mix release
```

**Verify locally before pushing:**

```bash
MIX_ENV=prod mix release
# Release created at _build/prod/rel/MyApp
ls _build/prod/rel/MyApp/bin/   # MyApp, migrate, server, ...
```

If you later want named releases (e.g. for multi-environment release configs), run `mix phx.gen.release` to generate the full scaffolding — but for a single-app deploy, the unnamed `mix release` is sufficient and avoids this failure mode entirely.

## Security pitfall in auto-generated Dockerfiles

Nixpacks auto-injects secrets the user passes as `ARG` or `ENV` at build time. Docker's `SecretsUsedInArgOrEnv` linter will warn (and some registries / scanners will fail) because those values end up baked into image layers.

**Fix:** pass secrets as runtime `ENV` only (via the PaaS env-var UI, not build args), and never include them in `ARG`. Better: read from BWS / Vault / Doppler at container start and write to a tmpfs.

## Quick verification recipe (run before declaring done)

```bash
# 1. lock and mix.exs agree
diff <(grep -A1 "heroicons\|\".*ref:" mix.lock) <(grep -B0 -A6 "ref:" mix.exs)
# (visually compare the four keys: ref/branch/tag + sparse + subdir + depth)

# 2. release builds and ships the overlay scripts
rm -rf _build/prod
MIX_ENV=prod mix deps.get --only prod
MIX_ENV=prod mix release
test -x _build/prod/rel/<app>/bin/migrate && echo "migrate OK"
test -x _build/prod/rel/<app>/bin/server   && echo "server OK"

# 3. precommit stays green
mix precommit

# 4. migrations run with a real DB
DATABASE_URL=ecto://u:p@host/db /app/bin/migrate
```

## Linked references

- `references/mix-scm-git-lock-status.md` — exact source code excerpts of `Mix.SCM.Git.lock_status/1`, `get_lock_rev/2`, `get_lock_opts/1` in Elixir 1.20.1, with the line that causes `:outdated` annotated.
- `references/coolify-railpack-nixpacks-notes.md` — empirical notes on how Railpack differs from Nixpacks (default Elixir version pinning, cache invalidation, pre-deploy hook field name).
- `references/plain-http-deploy-errors.md` — exact log transcripts of the 5 most common plain-HTTP / LAN / VPN / custom-port deploy errors (`:server was not enabled`, `url: ... is invalid`, `Plug.SSL redirecting`, redirect to `example.com`, `could not lookup Ecto repo`) plus the working `runtime.exs` + `prod.exs` + env-var configuration for serving Phoenix over plain HTTP.
- `references/ecto-ssl-selfsigned.md` — Postgres TLS `verify_peer` vs self-signed certs in prod: the `bad_certificate selfsigned_peer` boot-loop signature, why `ecto.create` dies with `"killed"`, and the `ECTO_SSL` / `ECTO_SSL_VERIFY` env-var pattern for runtime.exs.
- `references/csrf-origin-session-cookie-403.md` — 403 Forbidden on POST /login in prod: `secure: true` session cookie dropped on HTTP deploys + `protect_from_forgery` origin mismatch on dual-access (HTTP VPN + HTTPS proxy) topologies, with the `SESSION_COOKIE_SECURE` / `CHECK_ORIGINS` env-var fixes and a verified prod env for the dual-access case.

## Ecto Repo SSL against self-signed Postgres (Pitfall J)

Symptom in prod deploy logs: `Postgrex.Protocol failed to connect: ** (DBConnection.ConnectionError) ssl connect: TLS client: ... generated CLIENT ALERT: Fatal - Bad Certificate - selfsigned_peer`, repeated in a loop, ending with `** (RuntimeError) failed to create db for MyApp.Repo: "killed"` from `Release.create/0`. The DB may already exist — the entrypoint isn't recreating it; it **can't even connect** to check.

Cause: `runtime.exs` defaults Repo SSL to `verify: :verify_peer` against `:public_key.cacerts_get()` (system CA bundle). Private-network / managed Postgres (Coolify Postgres, AlloyDB, Cloud SQL) commonly presents a self-signed or private-CA cert → TLS handshake is fatal → `storage_up` gets killed mid-connect.

Pattern that survives prod: **default to `verify: :verify_none`** (traffic still encrypted, cert just not validated), with env opt-outs in both directions:

```elixir
# config/runtime.exs (inside `if config_env() == :prod`)
maybe_ssl =
  cond do
    System.get_env("ECTO_SSL") in ~w(false 0) ->         # no SSL at all (local dev DB)
      []
    System.get_env("ECTO_SSL_VERIFY") in ~w(true 1) ->   # strict: real CA-signed certs
      [ssl: true, ssl_opts: [verify: :verify_peer, cacerts: :public_key.cacerts_get()]]
    true ->                                              # default: encrypted, self-signed OK
      [ssl: true, ssl_opts: [verify: :verify_none]]
  end

config :MyApp, MyApp.Repo, [url: database_url] ++ maybe_ssl
```

Two rules of thumb:
- Making `verify_peer` the default is a breaking change for any existing prod with self-signed certs — it ships as a "security improvement" and takes the whole app down at next deploy. Default to `verify_none`; let users opt INTO strictness.
- Quick mitigation without redeploying: set the env var in the PaaS UI (`ECTO_SSL=false` or whatever disables verification) and restart — but if the code hard-codes `verify_peer` with no env escape hatch, only a code change + rebuild fixes it.

Full detail and log transcripts: `references/ecto-ssl-selfsigned.md`.

## Session cookie + CSRF origin check 403s on login (Pitfall K)

Symptom: user submits POST /login in prod and Phoenix answers **403 Forbidden**, redirecting back to /login. Happens after a "security hardening" commit or on dual-access topologies (plain HTTP over VPN **and** HTTPS via a TLS-terminating proxy). Two independent root causes, both in the same class — the browser request carries session/CSRF state the server rejects:

1. **Session cookie `secure: true` on an HTTP deploy.** If `@session_options` in `endpoint.ex` hard-codes `secure: true`, the browser refuses to send the session cookie over plain HTTP → the POST arrives with no session → the CSRF token can't be validated → 403. Fix: make it an env flag, default OFF (cookie works on both HTTP and HTTPS, since the cookie is encrypted anyway):

   ```elixir
   # lib/<app>_web/endpoint.ex
   @session_options [
     store: :cookie,
     secure: System.get_env("SESSION_COOKIE_SECURE") in ~w(true 1),  # default false
     # ...
   ]
   ```

2. **CSRF origin check on dual-access.** `protect_from_forgery` rejects POSTs whose `Origin` header doesn't match the endpoint `url:` config. If the app is reachable as both `http://host.vpn:4001` (VPN, no TLS) and `https://host.example` (proxy terminates TLS, forwards HTTP), the `url:` config can only match ONE of them — POSTs from the other origin 403. Fix: `check_origin` as a comma-separated env list covering every real origin:

   ```elixir
   # config/runtime.exs (prod block)
   check_origin =
     case System.get_env("CHECK_ORIGINS") do
       nil -> true
       "" -> true
       origins -> String.split(origins, ",", trim: true)
     end

   config :MyApp, MyAppWeb.Endpoint,
     url: [host: host, port: url_port, scheme: scheme],
     check_origin: check_origin,
     # ...
   ```

   PaaS env: `CHECK_ORIGINS=http://host.vpn:4001,https://host.example` (bare scheme://host:port per origin, no paths).

Diagnosis shortcuts: 403 on POST (form or LiveView) that never reaches the controller = CSRF/origin layer, not auth. GET /login renders fine; only the POST dies. Check (1) first if the deploy is plain-HTTP only; check (2) when the same app is served from 2+ scheme/host/port combos. Note these are compile-sensitive in different ways: `@session_options` is a module attribute (recompile required, which a release does anyway), `check_origin` is runtime config.

Full detail: `references/csrf-origin-session-cookie-403.md`.

## Linked templates

- `templates/Dockerfile.multistage` — parameterised multi-stage Dockerfile (hexpm/elixir builder → debian:slim runner) with the deps layer split that fixes `lock outdated`. Copy to repo root, replace `APP_NAME` + image tags, commit.
- `templates/entrypoint.sh` — container entrypoint that runs `MyApp.Release.setup/0` (create DB → migrate → seed) or `MyApp.Release.migrate/0` (migrations only), controlled by the `SETUP_MODE` env var (default `setup`). Then `exec bin/<app> start`. Set `SKIP_MIGRATIONS=1` to bypass. Alternative to the PaaS pre-deploy hook for single-instance deploys.
