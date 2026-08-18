---
name: elixir-umbrella-bootstrap
description: Use when setting up a local Elixir/Phoenix umbrella project.
---

# Elixir Umbrella Local Bootstrap

Get a Phoenix umbrella project running locally on macOS with Homebrew Postgres, mise-managed toolchains, and private Hex dependencies.

## When to use
- "What do I need to run X locally?" / deps / bootstrap / server won't start
- `mix deps.get` fails with `Unknown package <name> in lockfile`
- New machine, fresh clone, or dotfile changes broke the env

## Check the environment first (batch these)
1. `elixir --version`, `erl -eval ...` (OTP version), `node --version`
2. `pg_isready` and `psql -U postgres -c "SELECT 1"` — Homebrew Postgres trusts local user by default; project usually needs a `postgres` superuser (`createuser -s postgres` + `ALTER USER postgres WITH PASSWORD 'postgres';`)
3. `.mise.toml` — pinned tool versions and, crucially, `[env] _.file = ".env"` (see below)
4. `.env` vs `.env.example` — copy example, never invent vars you haven't seen

## mise specifics (the #1 gotcha)
- `.mise.toml` may be untrusted: `mise trust` in the repo root, else every mise command errors
- **`.env` is loaded by mise, NOT by your shell.** Running `mix phx.server` bare won't see `.env` values. Use `mise x -- <cmd>` or `mise run <task>` so env vars apply. Config files read `System.get_env(...)` at compile/runtime.
- `mise ls` shows what's installed vs pinned; `mise x -- mix deps.get` runs with pinned toolchain + env.
- `[tasks.*]` in `.mise.toml` map to `mise run <name>` (bootstrap, dev, test, db_migrate...).

## Private Hex organization deps
- Search `mix.exs` files for `organization: "<org>"` — those packages are NOT on public hex.pm.
- Symptom: `Failed to fetch record for hexpm:<org>/<pkg> from registry (using cache instead)` → `** (Mix) Unknown package <pkg> in lockfile`.
- Fix (usually documented in the repo README, search it first):
  - `mix hex.organization auth <org> --key <READ_ONLY_KEY>` (one time per machine), or
  - buy a hex.pm account, get added to the org, `mix hex.user auth`.
- Check existing auth: `mix hex.organization list`, `~/.hex/hex.config` (contains oauth token if authenticated). If org list is empty, not authed.
- Fix hex auth BEFORE `mix deps.get` — it blocks everything downstream (npm assets, db setup).

## DB with Homebrew Postgres
- Config reads `DATABASE_NAME` / `TEST_DATABASE_NAME` env vars — respect exactly the names the codebase uses (check `config/config.exs` and `config/<env>.exs`).
- In an umbrella, the repo belongs to ONE app (usually `contexts`) — run `mix ecto.create/migrate` from `apps/<owner>` with the umbrella's env loaded (via mise).
- Makefile targets often exist: `make bootstrap` = deps + assets + db setup in one shot.

## Bootstrap sequence (typical)
```bash
mise trust
mise x -- mix deps.get          # needs hex org auth first
mise x -- bash -lc 'cd apps/hub && npm install --prefix assets'
mise x -- bash -lc 'cd apps/contexts && mix ecto.create && mix ecto.migrate'
mise x -- bash -lc 'cd apps/hub && mix phx.server'
```
or `mise run bootstrap` if `.mise.toml` defines it. Verify with `curl http://localhost:<PORT>` and server logs (no "Unknown package", no DB errors).

## Pitfalls
- Bare shell commands silently miss `.env` → weird defaults (wrong DB name, missing tokens). Always `mise x --`.
- `mix hex.organization auth <org> --key <key>` prints NOTHING on success (exit 0). Don't re-run guessing failure — proceed to `mix deps.get`.
- Hermes `read_file` refuses `.env` (secret-bearing). Read/append via terminal (`grep`, `printf >> .env`), and strip `@url:`...`` markdown decoration the user's paste may carry.
- Don't commit `.env`; it's gitignored by convention. Pasting env content into chat may carry markdown decoration (`@url:\`...\``) — strip it before writing the file.
- User may override example DB names ("the db should be called X") — apply their exact names, only update `.env`, leave code config alone.
- Verification runs: for pure config-file changes there's no test suite — the check is `grep`/read-back confirmation, not `mix test`.

## Project-specific references
- `references/hub-umbrella.md` — my_org/hub specifics (org `my_org` deps, env vars, Makefile, ports).