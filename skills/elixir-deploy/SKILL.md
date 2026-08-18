---
name: elixir-deploy
description: Ship a Phoenix/Elixir app as a `mix release` to a container-based PaaS — release scaffolding, idempotent first-run, runtime-config pitfalls, and deploy troubleshooting.
version: 1.0.0
author: Álvaro Lizama
---

# Elixir Deploy (Phoenix `mix release` → PaaS)

Use this skill whenever shipping a Phoenix app (or any Elixir OTP app) as a
`mix release` to a container-based PaaS that runs a Docker image and calls a
`bin/*` overlay. Covers the canonical Phoenix path (`mix phx.gen.release`),
idempotent first-run setup, the pitfalls that live in `release.ex` /
`runtime.exs` / `prod.exs`, and the deploy-time 403s and build failures most
often mis-diagnosed as app/auth bugs.

## Decision routing

```mermaid
flowchart TD
    A[Deploying a Phoenix/Elixir app to a PaaS] --> B{Stuck on build?}
    B -- yes --> C[Build-time fixes]
    B -- no --> D{Prepared a release before?}
    C --> C1[lock outdated / mix compile before deps.get]
    C --> C2[Docker build OOM during rebar3 deps]
    C --> C3[Unknown release / missing bin overlays / tag not found]
    D -- no --> E[Canonical mix release workflow]
    D -- yes --> F[Configure PaaS: start + pre-deploy hook]
    E --> F
    F --> G{Need DB created on first run?}
    G -- yes --> H[Idempotent first-run setup hero]
    G -- no --> I[bin/migrate pre-deploy hook]
    H --> J{Deploy fails at boot?}
    I --> J
    J -- runtime.exs / release.ex --> K[release.ex pitfalls + validate_compile_env]
    J -- plain HTTP / LAN / VPN --> L[Plain-HTTP topology]
    J -- 403 on POST / login --> M[CSRF origin + session cookie 403s]
    J -- DB TLS handshake / Ecto repo lookup --> N[Ecto SSL + Ecto.Migrator.with_repo]
    K --> Z[Verify: local release smoke test]
    L --> Z
    M --> Z
    N --> Z
    Z --> END[Ship]
```

## Canonical `mix release` workflow

1. **Generate release scaffolding once.**
   ```bash
   mix phx.gen.release
   ```
   This creates exactly what a container deploy needs and nothing more:
   - `lib/<app>/release.ex` — `MyApp.Release.migrate/0`, `rollback/2`, `repos/0`,
     `load_app/0`. Customize only to add `seed/0`, `create/0`, `setup/0`.
   - `rel/overlays/bin/migrate` — `#!/bin/sh` wrapper running
     `exec ./<app> eval MyApp.Release.migrate`.
   - `rel/overlays/bin/server` — `PHX_SERVER=true exec ./<app> start`.
   - `.bat` twins — keep them even on Unix-only targets; harmless and shipped
     by the generator on purpose.

2. **Verify the release locally before pushing** (both the build and a boot):
   ```bash
   rm -rf _build/prod
   MIX_ENV=prod mix deps.get --only prod
   MIX_ENV=prod mix release
   ls _build/prod/rel/<app>/bin/   # must list: <app>, migrate, server (+ .bat)
   DATABASE_URL=ecto://nope:nope@127.0.0.1:1/nope \
     SECRET_KEY_BASE=some-test-secret \
     _build/prod/rel/<app>/bin/<app> eval "IO.puts(:ok)"   # must print :ok
   ```
   If `bin/migrate` / `bin/server` are missing, the `rel/overlays/bin/` files
   weren't present at `mix release` time — re-run `mix phx.gen.release`. A
   passing `mix precommit` (runs against `:test`) does **not** prove the
   `:prod` boot works — `runtime.exs` runs as a config provider in a release,
   which is a different code path. Re-run this smoke test after any change to
   `runtime.exs`, `release.ex`, or `rel/overlays/bin/`.

3. **Release task name.** Use `mix release` with **no** name. `mix release <name>`
   fails with `Unknown release` unless a `releases:` block exists in `mix.exs`
   (overlay files alone don't configure the release name). The unnamed call
   defaults to the `app:` atom, which is exactly what Phoenix expects.

## Configure the PaaS

- **Start command:** `/app/bin/server`.
- **Pre-deploy hook** (runs in the *new* container, then traffic swaps; safe
  for N replicas):
  - DB already exists (managed Postgres / DBA): `/app/bin/migrate`.
  - Need DB created on first run + initial data:
    `/app/bin/setup` (idempotent; see next section).
- **Post-deploy:** use for cache warming, never for migrations.

### Build-time vs runtime env vars

Secrets go in **runtime `ENV`** only (set via the PaaS env-var UI), never in
`ARG` — Docker's `SecretsUsedInArgOrEnv` linter flags them and the values bake
into image layers. Mark sensitive vars as runtime-scoped so the build pack
doesn't promote them to `ARG`/`ENV` at build time. Prefer loading credentials
from a vault/secret manager at container start when available.

## Idempotent first-run setup (create DB → migrate → seed)

For first deploys with no DBA and no manual DB-creation step, make one
**idempotent** command safe to run on every deploy. Point the pre-deploy hook
at `/app/bin/setup` instead of `/app/bin/migrate`.

```elixir
# lib/<app>/release.ex
def setup do
  load_config()
  create()
  migrate()
  seed()        # must itself be idempotent (get_by then insert)
  :ok
end

def create do
  load_config()
  for repo <- repos() do
    case ensure_db_created(repo) do
      :ok -> :ok
      {:error, term} -> raise "failed to create db for #{inspect(repo)}: #{inspect(term)}"
    end
  end
end

defp ensure_db_created(repo) do
  case repo.__adapter__().storage_up(repo.config()) do
    :ok -> :ok
    {:error, :already_up} -> :ok        # Ecto 3.14+ returns a bare atom
    {:error, {:already_up, _}} -> :ok   # older Ecto returns a tuple
    {:error, term} -> {:error, term}
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
(plus a `setup.bat` Windows twin).

Pitfalls to get right:
- **`storage_up` return shape:** Ecto 3.14+ returns `{:error, :already_up}`
  (atom); older Ecto returns `{:error, {:already_up, _}}` (tuple). Match **both**.
  If you only match the tuple, the second deploy finds the DB already up and
  crashes with a misleading "failed to create db" — the first deploy created it.
- **Parentheses on `repo.__adapter__()` / `repo.config()`:** Elixir 1.20+
  deprecates the no-paren map/field notation; without them `--warnings-as-errors`
  fails the build.
- **`seeds.exs` must be idempotent** (`Repo.get_by/2` then insert only on
  `nil`) because `setup/0` runs it on every deploy.
- **Multi-replica caveat:** two replicas racing on `storage_up` will trip
  "database already exists" on the loser. `bin/setup` is single-instance only.
  Beyond one replica, use `/app/bin/migrate` and create the DB once via a
  one-off `bin/<app> eval <App>.Release.create`.
- **Trade-off:** the idempotent setup gives the release container
  `CREATEDB`-level privilege; in shared/multi-tenant DBs prefer the
  `bin/migrate`-only flow and let DBA tooling create the DB.
- **Separate prod-safe seeds from demo content.** Running the full
  `priv/repo/seeds.exs` on a fresh prod deploy can pollute the DB with demo
  rows. Split `seed/0` (full demo, dev/test) from a prod-safe `seed_context/0`
  and point `setup/0` at the latter. If an auto-seeded row should survive
  deletion, gate its creation behind an env var read **at runtime in a function
  body** (a module attribute is baked at compile time and `--warnings-as-errors`
  flags it as an unreachable clause).

## `release.ex` pitfalls — the startup pattern everyone breaks

The shipped `migrate/0` works because `Ecto.Migrator.with_repo/2` starts the
repo ad-hoc and registers it. Anything you add that touches a repo must follow
the same envelope, or it fails only in a release/prod context with a misleading
error.

### P1 — `seed`/`setup` calling a repo outside `Ecto.Migrator.with_repo/2`
`Application.ensure_loaded/1` + `ensure_all_started(:ssl)` loads modules but
does **not** start the supervisor that registers the repo. Result:
```
** (RuntimeError) could not lookup Ecto repo MyApp.Repo because it was not started...
```
Wrap the callback in the same envelope:
```elixir
def seed do
  load_config()
  seeds_file = Application.app_dir(@app, "priv/repo/seeds.exs")
  for repo <- repos() do
    {:ok, _, _} = Ecto.Migrator.with_repo(repo, fn _repo -> Code.eval_file(seeds_file) end, timeout: 30_000)
  end
end
```
**Rule:** any function in `release.ex` that touches a repo wraps the work in
`Ecto.Migrator.with_repo/2`.

### P2 — `create/0` reads `repo.config` before `runtime.exs` has run
`storage_up/1` reads the DB name/credentials from `repo.config`, which is set
by `config/runtime.exs` — only evaluated as a config provider in a release
boot. `bin/<app> eval "MyApp.Release.create"` reads a default config if
`runtime.exs` hasn't run. Force evaluation at the top of every public function:
```elixir
defp load_config do
  Application.ensure_all_started(:ssl)
  Application.ensure_loaded(@app)
  _ = Application.get_all_env(@app)   # triggers the config provider
  :ok
end
```

### P3 — domain code touching PubSub / TaskSupervisor during partial boot
`Ecto.Migrator.with_repo/2` starts **only the repo**, not the supervision
tree. If a seed calls domain functions that broadcast or schedule background
work, the eval crashes:
```
** (ArgumentError) unknown registry: MyApp.PubSub. ...
** (exit) exited in: GenServer.call(MyApp.TaskSupervisor, ...) :: no process
```
`Phoenix.PubSub.broadcast/3` raises (`ArgumentError`); `Task.Supervisor.start_child/3`
does a `GenServer.call` that **exits** with `{:noproc, _}` when the supervisor is
dead — a bare `rescue` does **not** catch exit signals. Make UI notifications /
background jobs skip gracefully:
```elixir
def schedule(page) do
  Task.Supervisor.start_child(MyApp.TaskSupervisor, fn -> work(page) end, restart: :transient)
rescue
  _ -> :ignored
catch
  :exit, _ -> :ignored   # CRITICAL: catches {:noproc, _} — rescue misses this
end
```
**Rule:** any domain function calling `Phoenix.PubSub.broadcast`,
`Task.Supervisor.start_child`, `Registry.register`, or
`DynamicSupervisor.start_child` must be release-task-safe — wrap side-effects
in **both** `rescue _ -> :ignored` **and** `catch :exit, _ -> :ignored`. Don't
"fix" this by `Application.ensure_all_started(:my_app)` — that boots the
endpoint, binds ports, and runs schedulers during a migration.

### P4 — `Repo.delete_all/1` returns `{count, nil}`, not a bare count
Interpolating the raw return in a flash/message stores `{42, nil}` and crashes
at runtime. Pattern-match to extract: `{count, _} = Repo.delete_all(query)`.
Same for `update_all/1`.

## `runtime.exs` / `prod.exs` config pitfalls

### P5 — `PHX_HOST` defaulting to `"example.com"` and `PHX_SERVER` unset
Both come from the `phx.new` template. The host default makes generated URLs
(login redirects, signed links, mailer URLs) silently point at `example.com`.
`PHX_SERVER` unset means the endpoint starts with `server: false` and logs
`:server was not enabled ... http/https services won't start`.
Fix: **raise** at boot when `PHX_HOST` is missing (never a hard-coded fallback
host), and make prod always serve:
```elixir
if config_env() == :prod or System.get_env("PHX_SERVER") do
  config :my_app, MyAppWeb.Endpoint, server: true
end
```
Keep the `PHX_SERVER` gate for non-prod — an unconditional `server: true`
makes `mix test` boot the endpoint and collide with a dev server on the port.

### P6 — `validate_compile_env` aborts boot when a compile-time env is set at runtime
A release that builds fine can crash at boot:
```
ERROR! the application :my_app has a different value set for key :dns_cluster_query
during runtime compared to compile time...
Runtime terminating during boot ({...Config.Provider...})
```
Cause: `Application.compile_env/3` in a module attribute (e.g. `@children` in
`application.ex`) marks a key compile-time; `runtime.exs` then sets the same key
(possibly to `nil`) at boot. Fix: read such keys at runtime in the `start/2`
callback with `Application.get_env/2`, not in a module attribute. Rule: never
`compile_env` a key that `runtime.exs` also sets. `compile_env` is only for
truly compile-time keys like `:force_ssl`. Disabling the check
(`validate_compile_env: false`) hides the real bug.

## Plain-HTTP / LAN / VPN topologies (no TLS in front)

The Phoenix templates are hard-coded for HTTPS, which breaks three common
topologies: direct LAN/VPN access (NetBird, Wireguard, Tailscale), a custom
port over TLS, and PaaS builds that don't invoke `bin/server`. Dead giveaways
in the log:
```
[warning] Configuration :server was not enabled for MyAppWeb.Endpoint...
[warning] url: [host: ...] configuration value "host.example:5000" ... is invalid
[warning] Connection that looks like TLS received on a clear channel
```
The `url: ... is invalid` warning means the host string has the port glued on
(`"local-apps.vpn.cloud:5000"`) — Phoenix rejects that; keep host and port in
separate env vars.

**Key constraint:** `force_ssl` is **compile-time** in Phoenix (its value is
baked into the `.app` resource at `mix release`). Setting it at runtime aborts
the boot with a `validate_compile_env` error — it **cannot** be toggled at
runtime regardless of `PHX_SCHEME`. The only correct lever is a **build-time**
toggle:
```elixir
# config/prod.exs — force_ssl stays HERE (compile-time). Runtime env has no effect.
if System.get_env("DISABLE_FORCE_SSL") != "1" do
  config :my_app, MyAppWeb.Endpoint,
    force_ssl: [rewrite_on: [:x_forwarded_proto], exclude: [hosts: ["localhost", "127.0.0.1"]]]
end
```
```dockerfile
# Dockerfile — build-time switch for plain-HTTP images
ARG DISABLE_FORCE_SSL=""
ENV DISABLE_FORCE_SSL=${DISABLE_FORCE_SSL}
```
And make scheme/port/host runtime-steerable:
```elixir
scheme   = System.get_env("PHX_SCHEME", "https")
url_port = String.to_integer(System.get_env("PHX_PORT", "443"))

config :my_app, MyAppWeb.Endpoint,
  url: [host: host, port: url_port, scheme: scheme],
  http: [ip: {0, 0, 0, 0, 0, 0, 0, 0}]
```
Deploy:
- **HTTPS (default):** `PHX_HOST`, `PHX_PORT`, `PHX_SCHEME=https`.
- **Plain HTTP (VPN tunnel):** rebuild with `--build-arg DISABLE_FORCE_SSL=1`
  **and** set runtime `PHX_SCHEME=http`. **Both** are needed — the build arg
  kills the 301-to-https redirect; the runtime var makes generated URLs use http.

If toggling HTTPS↔plain-HTTP without a rebuild matters, the alternative is the
runtime pattern: keep `prod.exs` free of `force_ssl`, compute the opts in
`runtime.exs` from `PHX_SCHEME`, and apply via `if opts != [], do: config(...)`.

### `PORT` vs `PHX_PORT` vs `EXPOSE`
Three different layers that look the same:
| Var | What it does | Where |
|-----|--------------|-------|
| `PORT` | Real listen port — the server binds here inside the container | `runtime.exs` `http: [port: ...]` |
| `PHX_PORT` | Generated-URL port — appears in redirects, emails, links | `runtime.exs` `url: [port: ...]` |
| `EXPOSE` | Docker metadata only — does **not** set the listen port; static | `Dockerfile` |
If the container listens on 4001 but `EXPOSE 4000`, external traffic maps to
4000 where nothing listens → `ERR_CONNECTION_RESET`. When in doubt, set all
three to the same value.

## 403 Forbidden on POST /login in prod (CSRF + session cookie)

Symptom: GET /login renders; POST dies with 403 and bounces back to /login,
with **no controller log line** — the request never reaches the action. Two
independent root causes, both plug-level:

1. **Session cookie `secure: true` on HTTP deploy.** The browser refuses to
   send the cookie over plain HTTP → no session → CSRF token can't be
   validated. Make it an env flag, default **off** (the cookie is
   encrypted/signed anyway):
   ```elixir
   # lib/<app>_web/endpoint.ex — module attribute (recompiles on release)
   @session_options [store: :cookie, secure: System.get_env("SESSION_COOKIE_SECURE") in ~w(true 1), ...]
   ```
2. **Origin mismatch on dual-access.** `protect_from_forgery` rejects POSTs
   whose `Origin` header doesn't match the endpoint `url:` config. If the app
   is reachable as both `http://host.vpn:4001` and `https://host.example`
   (proxy terminates TLS), the `url:` config matches only one — POSTs from the
   other origin 403. Allow-list every real origin at runtime:
   ```elixir
   check_origin =
     case System.get_env("CHECK_ORIGINS") do
       nil -> true
       "" -> true
       origins -> String.split(origins, ",", trim: true)
     end
   config :my_app, MyAppWeb.Endpoint, url: [...], check_origin: check_origin
   ```
   PaaS env: `CHECK_ORIGINS=http://host.vpn:4001,https://host.example`
   (bare `scheme://host:port`, comma-separated, no paths/slashes).

Diagnosis: a 403 on POST that never touches the controller is a CSRF/origin
layer check, not an auth bug. Check #1 first on a plain-HTTP-only deploy;
check #2 when the same app is served from 2+ scheme/host/port combos. If
several "security hardening" commits landed together, expect a cluster (DB SSL
verify + session cookie secure + origin check) — debug each independently.

## Ecto / Postgres TLS

Self-signed or private-CA Postgres (managed providers) against the default
`verify: :verify_peer` + system CA bundle causes a fatal TLS handshake and a
boot loop (`bad_certificate selfsigned_peer`) — the DB may already exist; the
entrypoint can't even connect to check. Default to **`verify: :verify_none`**
(traffic still encrypted, cert not validated) with env opt-outs both ways:
```elixir
maybe_ssl =
  cond do
    System.get_env("ECTO_SSL") in ~w(false 0) -> []                       # no SSL
    System.get_env("ECTO_SSL_VERIFY") in ~w(true 1) -> [ssl: true, ssl_opts: [verify: :verify_peer, cacerts: :public_key.cacerts_get()]]
    true -> [ssl: true, ssl_opts: [verify: :verify_none]]                  # self-signed OK
  end
config :my_app, MyApp.Repo, [url: database_url] ++ maybe_ssl
```
Do NOT ship `verify_peer` as the default for existing prod with self-signed
certs — it deploys as a "security improvement" and takes the app down. Don't
leave `# ssl: true` commented out either — that silently disables SSL in prod.

## Build-time fixes (Dockerfile / build pack)

- **`mix compile` before `mix deps.get`.** A Dockerfile that copies the app
  then `RUN mix compile` without fetching deps first fails with `lock outdated`
  even when `mix.exs` and `mix.lock` agree (dev tolerates this; prod is strict).
  Split layers and fetch first:
  ```dockerfile
  COPY mix.exs mix.lock ./
  COPY config config
  RUN mix deps.get --only prod
  RUN mix deps.compile
  COPY lib priv assets rel ./
  RUN cd assets && npm install
  RUN mix compile
  RUN mix assets.deploy
  RUN mix release
  ```
  `mix deps.get` is the load-bearing step — the error is about the lock not
  being fetched, not compiled.
- **`lock outdated` on a git-pinned dep.** The commit SHA can match perfectly
  while Mix still reports `:outdated` — the mismatch is in the dep *options*
  keyword list (`ref`/`branch`/`tag` — pick exactly one — plus `sparse`,
  `subdir`, `depth`, which Mix compares in order). If local `mix release`
  works but the PaaS fails, it's reusing a cached `mix.lock` layer: commit the
  lock, rebuild without cache, or use a custom Dockerfile with explicit
  `rm -rf _build/prod` + `mix deps.get`.
- **Docker build OOM during `mix deps.compile`.** rebar3/Erlang deps compile in
  parallel across schedulers and can exhaust tight memory (512 MB–1 GB),
  producing a bare `exit code 255` mid-`===> Compiling idna ...`. Compile them
  with a single scheduler: `RUN ERL_AFLAGS="+S 1:1" mix deps.compile idna telemetry telemetry_poller`
  then `RUN mix deps.compile`. Use inline `ERL_AFLAGS` on that line only (not
  `ENV`), and never `+MBas busy_wait` (invalid: `bad "MBa" value`).
- **`npm ci` vs node/npm mismatch.** `npm ci` is strict — a
  `package-lock.json` generated on node 22/npm 10 fails inside a node
  20/npm 9 container with an unhelpful usage dump. In a Dockerfile you control,
  prefer `npm install` (still respects the lock), or match the node major used
  locally (node 22 LTS is a safe default).
- **Pin a real `hexpm/elixir` image tag.** The tag format looks uniform but
  only a subset exists on Docker Hub. A plausible-but-unpublished tag fails at
  the `FROM` line. Query the registry API and filter, then match the runtime
  `debian:*-slim` date slug to the builder's to avoid glibc drift.
- **`.dockerignore` excludes a later `COPY` source.** A repo-root
  `.dockerignore` applies to every `COPY` in every stage. Before ignoring a
  path, grep the Dockerfile for every `COPY` (all stages). `_build`, `deps`,
  `assets/node_modules`, `.env`, `.git` are safe; `docker/`, `rel/`,
  `config/`, `priv/` are frequently COPY'd and must not be ignored.
- **Do not switch to Alpine** for the runtime — DNS resolution in distributed
  Erlang breaks on musl libc. Use a `debian:*` runner.
- **Custom Dockerfile vs build pack.** A repo-root multi-stage Dockerfile
  (parameterised: `hexpm/elixir` builder → `debian:*-slim` runner) is the most
  reliable path when a build pack keeps tripping on cache staleness or locking
  — you control install + build + start and there's no hidden layer cache.

## Session-salt hardening

Never ship hard-coded fallback salts:
```elixir
# BAD
signing_salt: System.get_env("SESSION_SIGNING_SALT", "TwS/TtVu")
# GOOD — fail closed, like SECRET_KEY_BASE
signing_salt: System.get_env("SESSION_SIGNING_SALT") || raise("SESSION_SIGNING_SALT is missing")
```
Applies to `SESSION_ENCRYPTION_SALT` too. Hardened set: signing + encryption
salt, `same_site: "Lax"`, `http_only: true`, `max_age` (~8h), and `secure`
behind the `SESSION_COOKIE_SECURE` env toggle.

## Typical env-var checklist (document in the app README)

`DATABASE_URL`, `PHX_HOST`, `PHX_SCHEME` (https / http for VPN),
`SECRET_KEY_BASE`, `SESSION_SIGNING_SALT`, `SESSION_ENCRYPTION_SALT`,
`SESSION_COOKIE_SECURE`, `ECTO_SSL` (+ `ECTO_SSL_VERIFY` for CA-valid certs),
`CHECK_ORIGINS`, `POOL_SIZE`. Build arg: `DISABLE_FORCE_SSL` only when the
build-time force_ssl pattern is in use.

## Quick verification recipe

```bash
# 1. release builds and ships the overlay scripts
rm -rf _build/prod
MIX_ENV=prod mix deps.get --only prod
MIX_ENV=prod mix release
test -x _build/prod/rel/<app>/bin/migrate && echo "migrate OK"
test -x _build/prod/rel/<app>/bin/server   && echo "server OK"

# 2. prod boot path is sound (validates runtime.exs providers + compile_env)
DATABASE_URL=ecto://nope:nope@127.0.0.1:1/nope SECRET_KEY_BASE=test \
  _build/prod/rel/<app>/bin/<app> eval "IO.puts(:ok)"   # -> :ok

# 3. migrations run against a real DB
DATABASE_URL=ecto://u:p@host/db /app/bin/migrate
```
If `eval "IO.puts(:ok)"` fails, the release is broken regardless of what
`mix precommit` says — fix the runtime config first, then re-run.