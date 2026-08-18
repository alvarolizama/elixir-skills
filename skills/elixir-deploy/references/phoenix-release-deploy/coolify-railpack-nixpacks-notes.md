# Coolify, Railpack, Nixpacks — notes for Elixir/Phoenix deploys

Empirical notes from a Coolify + Nixpacks + Phoenix 1.8 + Railpack
comparison. Coolify supports three build packs; only Nixpacks is on by
default. Railpack is the newer replacement and shares the Elixir provider
code with Nixpacks.

## Build pack selection in Coolify

In the resource panel:
- **Build Pack** dropdown: `Nixpacks` (default), `Railpack`, `Dockerfile`, `Docker Compose`.
- Switching to Dockerfile makes Coolify ignore Nixpacks/Railpack entirely
  and use the `Dockerfile` in the repo root.
- For Elixir releases, switching to Dockerfile is the most reliable path
  because you control the install + build + start phases and avoid cache
  surprises (see `references/mix-scm-git-lock-status.md`).

## What Nixpacks does for Elixir (default provider)

Install phase:
```sh
MIX_ENV=prod mix local.hex --force
MIX_ENV=prod mix local.rebar --force
MIX_ENV=prod mix deps.get --only prod
```

Build phase:
```sh
mix compile
mix assets.deploy
mix ecto.deploy  # only if the task is defined
```

Start phase: `mix phx.server`.

## What Railpack does for Elixir

Railpack reads the same `mix.exs` detection but uses its own provider
implementation. The default install + build sequence is similar to
Nixpacks. If the same `lock outdated` failure occurs on both, the cause
is your `mix.exs` / `mix.lock` mismatch, not the build pack — fix it at
the source rather than switching build packs.

## Where to put the pre-deploy migration command

In the Coolify resource, **Pre Deployment Command** field (per resource,
not per-environment). Two valid choices, pick by scenario:

**First deploy / no DBA available — use `bin/setup`:**
```sh
/app/bin/setup
```
This runs the idempotent `MyApp.Release.setup/0` which creates the DB
(if missing), runs migrations, and seeds. Safe to leave as the
pre-deploy command on every subsequent deploy too — the create step
short-circuits on `:already_up`, the migrate step is a no-op when the
schema is current, and the seeds step must itself be idempotent
(check-then-insert). Requires the DB user in `DATABASE_URL` to have
`CREATEDB` privilege. Single-instance only.

**Managed DB / multi-replica — use `bin/migrate`:**
```sh
/app/bin/migrate
```
This runs in the **new** container before traffic is switched, exits, and
then Coolify promotes the new container. The old container keeps serving
until the switch. Migrations are applied exactly once per deploy. Safe
for N replicas. Requires the DB to already exist (DBA / Coolify-managed
Postgres / one-off `eval MyApp.Release.create`).

For first-time data load with the `bin/migrate` path, append seed:
```sh
/app/bin/migrate && /app/bin/<app> eval <App>.Release.seed
```

## Env vars: build-time vs runtime

Nixpacks/Railpack auto-promote PaaS env vars to `ARG` and `ENV` in the
generated Dockerfile. This causes two problems:
1. Docker linter warnings (`SecretsUsedInArgOrEnv`) — values end up in
   image layers.
2. Build fails if the env var is required at build time but the value
   changes per environment.

**Fix for sensitive values:** mark them as runtime-only in the PaaS
(env-var scope) so they are not injected at build time. For credential
storage use BWS / Vault / Doppler and load at container start via a
sidecar or init script.

## When to use `phx.gen.release --docker`

If you decide to switch to a custom Dockerfile, `mix phx.gen.release
--docker` generates a multi-stage Dockerfile that's known good for
Phoenix. The generated Dockerfile uses:
- Builder: `hexpm/elixir:1.18.4-erlang-27.3.4.3-debian-trixie-…`
- Runner: `debian:trixie-…-slim`

Important: do not switch to Alpine — DNS resolution in distributed Erlang
breaks on musl libc.

## Common Coolify field names

- **Start Command**: `/app/bin/server` (release) or `mix phx.server` (dev).
- **Pre Deployment Command**: runs in the new container before traffic
  swap. Use for migrations.
- **Post Deployment Command**: runs after the new container is live.
  Use for cache warming, not for migrations.
- **Health Check Path**: `GET /health` if you have one. Without one,
  Coolify uses TCP only.

## When the build keeps failing identically

If you've fixed `mix.exs` + `mix.lock`, the local `mix release` works,
and the PaaS build still fails with the same message:
- The PaaS is using a cached Docker layer from a previous build.
- Switch to Dockerfile build pack and commit a multi-stage Dockerfile
  with explicit `RUN rm -rf _build/prod` and `RUN mix deps.get` in the
  builder stage. This makes caching deterministic.
- Or in the resource settings, find a "Clear cache" / "Rebuild without
  cache" option and use it once to confirm the diagnosis.
