---
name: elixir-mix-build
author: Álvaro Lizama
description: Debug and fix Elixir Mix build failures, especially "lock outdated" errors in :prod. Use when mix compile fails on git-based deps, when the lock file and mix.exs don't match in production, when Nixpacks/Railpack/Docker/Coolify build fails at compile, or when pre-deployment verification needs to mirror CI behavior.
---

# Elixir Mix Build

## What this skill covers
Mix build failures that bite you at deploy time — especially the **"lock outdated"** error from git-based deps in `:prod`. Includes pre-deployment verification patterns that mirror what CI, Nixpacks, Docker, and Coolify actually do.

## The "lock outdated" pitfall (git-based deps)

**Symptom.** `MIX_ENV=prod mix compile` (or any build tool that runs it) fails with:

```
Unchecked dependencies for environment prod:
* heroicons (https://github.com/tailwindlabs/heroicons.git - v2.2.0)
  lock outdated: the lock is outdated compared to the options in your mix.exs.
  To fetch locked version run "mix deps.get"
** (Mix) Can't continue due to errors on dependencies
```

**Root cause.** Mix compares the locked **commit SHA** against the options in `mix.exs`, not the tag name. If you pin by `tag:` in `mix.exs` and the lock has a specific commit SHA (from a previous `mix deps.get` when the tag pointed elsewhere, or because tags are mutable), Mix in `:prod` refuses to proceed. `:dev` is permissive and will not catch this — which is why local dev builds pass but the deploy build fails.

**Fix.** Pin by `:ref` with the exact commit SHA from `mix.lock`, then run `mix deps.get` so the lock entries stay aligned.

```elixir
# WRONG — Mix in :prod will reject this when the lock has a different SHA
{:heroicons,
 github: "tailwindlabs/heroicons",
 tag: "v2.2.0",
 sparse: "optimized"}

# RIGHT — pin to the exact commit the lock already has
{:heroicons,
 github: "tailwindlabs/heroicons",
 ref: "0435d4ca364a608cc75e2f8683d374e55abbae26",
 sparse: "optimized"}
```

Commit both `mix.exs` and `mix.lock` together — they must stay in sync.

## Pre-deployment verification

Always mirror the build environment locally before pushing. The deploy tool (Nixpacks, Railpack, Coolify, Docker, CI) will run `mix compile` in `:prod` with `--warnings-as-errors`-style strictness. Reproduce that locally using **the exact same commands the build pack runs**:

```bash
# Nixpacks/Railpack run this sequence in their install + build phases:
MIX_ENV=prod mix deps.get --only prod
MIX_ENV=prod mix compile
```

If you also want warning-as-errors coverage:

```bash
MIX_ENV=prod mix compile --warnings-as-errors
```

If the repo has a `precommit` alias, run it (`mix precommit`). The Phoenix project guideline is to use this before declaring work done — it usually does `compile --warnings-as-errors` + format + test, which catches most prod-only issues. **Note:** `precommit` typically runs in `:test`, not `:prod`, so it catches some issues but not all prod-only lock mismatches. Add an explicit `MIX_ENV=prod mix compile` for the full check.

**Push both files together.** When fixing a `lock outdated` issue, `git add mix.exs mix.lock` and commit in the same commit. The deploy agent reads from the remote branch's `mix.lock`, so a push that only updates `mix.exs` will still fail.

**Why this matters:** Nixpacks and Coolify generate their own Dockerfile. If you only ever run `:dev` locally, you find out about `:prod` lock issues at deploy time. Local `:prod` build is the cheapest way to find them.

## Git-based dep pinning patterns

| Pin style | When to use |
|-----------|-------------|
| `:tag, "v1.2.3"` | Hex packages. For git deps, only if you control the tag and it never moves. **Risky for prod** because tags are mutable. |
| `:ref, "<sha>"` | Git deps when you want a stable, reproducible build. **Prefer this for prod.** |
| `:branch, "main"` | Almost never for prod — branch heads move. |
| `:git, "url", branch: "main"` | Forks or non-public repos. |

For a git dep, `:ref` is the only style that gives deterministic builds. Once you pick a ref and run `mix deps.get`, the lock captures the SHA and future calls will respect it.

## When `mix deps.get` itself fails

Different failure mode: the lock has a SHA that no longer exists in the remote (force-push, deleted branch, etc.). The fix is:

```bash
mix deps.unlock --all
mix deps.get
```

Then commit the new `mix.lock`. Use this sparingly — it drops reproducibility for that dep.

## Pitfalls

- **Fixing the lock without fixing `mix.exs`.** Running `mix deps.get` after a tag change in `mix.exs` updates the lock, but if the lock already has a different SHA pinned, you need to update `mix.exs` to match. The order is: update `mix.exs` first, then `deps.get` to align the lock.
- **`mix.exs` requirement behind the lock.** If the lock resolves a newer version than your requirement advertises (e.g. `mix.exs` says `~> 0.5` but `mix.lock` has `0.6.1`), builds still run but the manifest lies about intent. Align `mix.exs` to the resolved version — `~> 0.6.1` when you want to pin the patch, or `~> 0.6` if you intentionally accept the newer minor. Re-run `mix deps.get`, verify the lock, and commit both files together. See `references/manifest-lock-alignment.md`.
- **Trusting `:dev` builds.** `:dev` is permissive and will happily run with mismatched locks. Always verify in `:prod` before deploy.
- **Skipping local prod verification.** Nixpacks/Coolify generate their own Dockerfile and run `mix compile` in `:prod`. If you don't run `:prod` locally, you only find lock issues at deploy time — and the deploy log is harder to debug than your terminal.
- **The `precommit` alias is not a full substitute.** It runs `compile --warnings-as-errors` (usually in `:test`, not `:prod`), so it catches some issues but not all prod-only lock mismatches. Add an explicit `MIX_ENV=prod mix compile` for the full check.
- **Sparse checkouts.** If a git dep uses `sparse:`, the lock entry will include the sparse option. Changing it requires a `mix deps.get` to update the lock.
- **Multi-app umbrellas.** If the dep is in a sub-app's `mix.exs`, the lock lives in the umbrella root. Verify in the umbrella root: `MIX_ENV=prod mix deps.get` from the root, not the sub-app.

## Umbrella-specific gotchas

See `references/umbrella-gotchas.md` for full details on each.

- **Elixir 1.20+ requires directory names to match OTP app names.** `apps/core/` fails — must be `apps/my_app_core/`. This is a hard requirement in Elixir 1.20+. Plan directory names accordingly from the start.
- **Phoenix.PubSub in a non-Phoenix app.** If your core app (no Phoenix dep) starts `{Phoenix.PubSub, name: MyApp.PubSub}`, add `{:phoenix_pubsub, "~> 2.1"}` to its deps. Without it, the app crashes on start with `Phoenix.PubSub.PG2` errors.
- **Ecto UUID autogeneration.** `@primary_key {:id, :binary_id, autogenerate: false}` does NOT pick up the DB's `default: gen_random_uuid()`. IDs come back as `nil` after insert, causing `NoPrimaryKeyValueError` in tests. Use `@primary_key {:id, :binary_id, autogenerate: true}` — Ecto will skip sending the id in INSERT, let the DB default kick in, and read it back.
- **Ecto Sandbox pool not applied.** When `Application.start/2` starts the Repo, it uses the pool from `config/config.exs` (usually `DBConnection.ConnectionPool`). `config/test.exs` sets `pool: Ecto.Adapters.SQL.Sandbox` but the Repo is already running with the wrong pool. Fix: conditionally set the pool in `Application.start/2` based on `Mix.env()`, or don't start the Repo in the Application for test and let the DataCase manage it.
- **Missing `errors_on/1` in DataCase.** Tests that call `errors_on(changeset)` need this helper defined in the DataCase module — it's not included by default.

## Running `mix run` scripts while the dev server is up

**Symptom.** `mix run -e '...'` fails with `(EXIT) shutdown: failed to start child: {App.Endpoint, :http}` / `eaddrinuse` when `mix phx.server` is already listening on the same port.

**Root cause.** `mix run` boots the entire application including the HTTP endpoint, so it collides with the running server.

**Fix.** Use `--no-start` and manually start only the DB dependencies:

```bash
mix run --no-start -e '
  Application.ensure_all_started(:postgrex)
  Application.ensure_all_started(:ecto_sql)
  {:ok, _} = MyApp.Repo.start_link()
  # now run your script (seeds, one-off data fixes, etc.)
  MyApp.Accounts.create_user(%{email: "...", password: "..."})
'
```

Without the two `ensure_all_started` calls, `Repo.start_link()` crashes with `no process: the process is not alive ... because its application isn't started` — the DBConnection tree must come up first.

This runs in a **separate OS process** from the dev server (no BEAM name conflicts), using the same `dev` database. Useful for one-off user creation, data cleanup, or seed verification without restarting the server.

## Tailwind v4 asset setup (CSS not loading)

When CSS doesn't load in a Phoenix app, the usual culprit is a Tailwind v3→v4 migration gap. The `tailwind` hex package ≥0.3 ships Tailwind CLI v4, which has a fundamentally different config model — no `tailwind.config.js`, config lives in CSS via `@theme {}`. Key steps: migrate config to `@theme` in `app.css`, add tailwind profiles to `config/config.exs`, add watchers to `config/dev.exs`, compile initial CSS with `mix tailwind <profile>`, and use `type="module"` in layouts for ESM JS imports. For dev without npm/esbuild, copy `phoenix.mjs` and `phoenix_live_view.esm.js` from deps to `priv/static/assets/` and use absolute path imports. See [references/phoenix-tailwind-v4-assets.md](references/phoenix-tailwind-v4-assets.md) for the full setup recipe.

## Ecto changeset & Decimal test assertion gotchas

- **`==` on Decimal structs compares representation, not value.** `Decimal.round(x, 6)` yields `0.012500` (coef 12500, exp -6), and `Decimal.new("0.012500") != Decimal.new("0.0125")` under `==`. In test assertions over money/cost values always use `Decimal.equal?(actual, expected)` (or `Decimal.compare/2`), never raw `==`.
- **Composite `unique_constraint` reports the error on the FIRST field given.** `unique_constraint([:organization_id, :name], name: :idx)` puts `"has already been taken"` on `:organization_id`, so `errors_on(changeset).name` is nil. To land the error on the field the user sees, pass that field first: `unique_constraint(:name, name: :model_aliases_organization_id_name_index)` — the DB index stays composite, only the error placement changes.
- **A `default:` on a schema field silently defeats `validate_required`.** `field :billing_type, :string, default: "pay_per_token"` + `validate_required([:billing_type])` never fails when attrs omit the field — the default fills it before validation. Decide consciously: truly required (remove the default) or optional-with-default (drop the required test). This matters extra when downstream logic (cost calculation) branches on the value being explicit.

## Ecto/Postgres schema, migration & test gotchas

- **UUID defaults: use `gen_random_uuid()`, NOT `uuid_generate_v4()`.** `fragment("uuid_generate_v4()")` in a migration fails at migrate time with `ERROR 42883 (undefined_function) function uuid_generate_v4() does not exist` on current Postgres. `gen_random_uuid()` is the function that exists (pgcrypto provides it, and it's the repo's convention — see `003_create_relations.exs`). In the Ecto **schema** set `autogenerate: true` (see Ecto UUID bullet above); in the **migration** use `default: fragment("gen_random_uuid()")`. Rule of thumb: whenever you reach for `uuid_generate_v4`, use `gen_random_uuid()`. Verify with `mix ecto.migrate` since compile won't catch it.
- **jsonb `:map` / `{:array, :map}` fields round-trip with STRING keys.** A `top_pages` column of jsonb array-of-maps stored with atom keys (`%{slug: ..., title: ...}`) comes back from Postgres as `%{"slug" => ..., "title" => ...}`. Never assert with `.slug` dot-access after a DB round-trip — use `&1["slug"]`. (Common trigger: `** (KeyError) key :slug not found in: %{...}` in tests.) This mirrors how `Page.meta` is already all string-keyed.
- **For a jsonb column default in a migration, use `default: fragment("'[]'::jsonb")`, not `default: "[]"`.** The latter is quoted as a Postgres string literal and errors; the fragment casts to jsonb.
- **Descending ranges in Elixir warn.** `Enum.map(15..6, &.../1)` compiles but warns `"15..6 has a default step of -1, please write 15..6//-1"`. Use `15..6//-1`. Since `mix compile --warnings-as-errors` and `mix precommit` turn warnings into failures, write the explicit step up front.
- **`Task.async_stream` DB work in tests needs the sandbox in shared mode.** Use `use MyApp.DataCase, async: false` — this runs `Sandbox.start_owner!` with `shared: true`, so the concurrent worker processes `Task.async_stream` spawns can check out the Repo connection. `async: true` (exclusive sandbox) would let only the owner use the connection and break `generate_all/1`-style concurrent writes. Keep each test on its own isolated context so concurrent workers don't collide.

## Phoenix LiveView testing gotchas

Testing LiveViews in umbrella apps has several non-obvious failure modes:
- `live_isolated` does NOT support `assign:` option — pass data via `session:` instead
- `live_isolated` passes `:not_mounted_at_router` (atom) as first arg to `mount/3` — add a dedicated clause
- ConnCase needs `Sandbox.mode({:shared, self()})` for LiveView processes to see test data
- Tests with `async: true` need unique slugs (`System.unique_integer`) to avoid constraint violations
- **If unique slugs aren't enough, set `async: false`** on test modules using LiveView with shared sandbox — the nuclear option that eliminates all parallel-interference issues
- HEEx `@variable` looks up assigns, not module attributes — copy module attrs to assigns before `~H`
- `put_session` in a plug crashes test conns — use `assign/2` instead
- `Repo.get_by` with nil argument raises — add guard clauses
- Ecto queries with `where: field == ^nil` also raise — same guard clause pattern needed for any function that receives a potentially-nil user_id
- Function components that iterate over list attrs must guard against nil — `attr :badges, :list, default: []` does NOT default when nil is explicitly passed from a template

See [references/phoenix-liveview-testing.md](references/phoenix-liveview-testing.md) for full details and code examples.

## Phoenix 1.8 runtime gotchas

- **`Phoenix.CodeReloader` listener warning.** Phoenix 1.8 requires `listeners: [Phoenix.CodeReloader]` in the umbrella root `mix.exs` `project/0`. Without it, code reload in dev works but logs a warning on every reload. Add it to the root `mix.exs`, not the sub-app.
- **Admin app auth in dev.** If the admin app has a `RequireAdmin` plug that redirects to `/login` but no `/login` route exists, the admin is completely inaccessible in dev (302 → NoRouteError). Fix: make `RequireAdmin` auto-assign a dev admin user when `Mix.env() == :dev` and no session exists.
- **LiveView `PubSub.subscribe` with nil site.** If a LiveView calls `Phoenix.PubSub.subscribe(pubsub, "site:#{site.id}:topic")` and `site` is nil (no site configured for localhost in dev), it crashes with `BadMapError`. Always guard: `if site, do: Phoenix.PubSub.subscribe(...)`.
- **Function components with nil list attrs.** When a template passes `badges={@home_config["trust_badges"]}` and the key doesn't exist, `nil` is passed. The `attr :badges, :list, default: []` default does NOT apply because nil was explicitly passed. Fix: `badges = assigns[:badges] || []` at the top of the function component.

## Reference

- [references/lock-outdated-pitfall.md](references/lock-outdated-pitfall.md) — full error transcript and reproduction recipe from a Coolify/Nixpacks deploy of a Phoenix 1.8 app (June 2026).
- [references/phoenix-tailwind-v4-assets.md](references/phoenix-tailwind-v4-assets.md) — Tailwind v4 asset pipeline setup for Phoenix apps (config migration, watchers, no-npm JS imports, verification checklist).
- [references/phoenix-liveview-testing.md](references/phoenix-liveview-testing.md) — LiveView testing gotchas in umbrella apps: `live_isolated` quirks, sandbox shared mode, async test slug conflicts, HEEx assigns vs module attrs, plug session issues, Ecto nil query guards.
- [references/phoenix-1.8-runtime-gotchas.md](references/phoenix-1.8-runtime-gotchas.md) — Runtime crashes in dev: CodeReloader listener warning, admin auth bypass, PubSub nil site, function component nil list attrs, map-not-list fallback bugs.
