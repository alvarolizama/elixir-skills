---
name: phoenix-umbrella-project-setup
description: "Scaffold a new Elixir/Phoenix umbrella project for a creator platform with short app names, mise-managed env and secrets, Homebrew PostgreSQL, Tidewave dev plug, Tailwind v4, and a customizable high-conversion landing page."
version: 1.0.0
author: Álvaro Lizama
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [elixir, phoenix, umbrella, setup, scaffolding, creator-platform]
    related_skills: [software-development/plan, elixir-mix-build]
---

# Phoenix Umbrella Project Setup

Use this skill when the user wants to bootstrap a new Elixir umbrella with Phoenix, Ecto/PostgreSQL, multi-domain public sites, an admin panel, and Tidewave for agent-assisted development.

Typical target shape:
- **`apps/core`** — pure logic, Ecto Repo, PubSub, schemas, contexts
- **`apps/sites`** — Phoenix public app, multi-domain, lead capture, landing page
- **`apps/admin`** — Phoenix admin dashboard

## Common triggers

- User says `/plan setup umbrella` for Money Bot or a similar creator-platform project
- User asks to scaffold a new Phoenix umbrella with `:core`, `:sites`, `:admin`
- User asks for "Tidewave setup" on a new umbrella
- User asks for "landing page de alta conversión" + lead capture + thank-you page
- Subagents timed out or left Phoenix endpoint/compile warnings that need manual cleanup

## User preferences to enforce

### 1. Short OTP app names

Use short app names, not prefixed ones:

- `:core`, `:sites`, `:admin`
- Directory must match OTP name exactly for Elixir 1.20+: `apps/core/`, `apps/sites/`, `apps/admin/`

### 2. Runtime and env management with mise

Create `.mise.toml`:

```toml
[tools]
# Pin the exact OTP build; "1.20" may resolve to 1.20.1-otp-29 and break on Erlang 27
elixir = "1.20.1-otp-27"
erlang = "27.0"

[env]
# mise loads .env automatically when entering the directory
_.file = ".env"
```

**Do not** instruct the user to run `source .env`; mise handles it.

After editing `.env`, re-run `mise trust` and `mise exec -- elixir --version` if mise complained about malformed lines.

### 3. PostgreSQL via Homebrew

Assume PostgreSQL is installed with Homebrew. Setup instructions must include:

```bash
brew services info postgresql
brew services start postgresql
```

Default dev credentials in `.env.example`:

```bash
DB_USER=postgres
DB_PASSWORD=
DB_HOST=localhost
DB_NAME=money_bot_dev
```

(Adjust `DB_USER` to the actual macOS user if `postgres` role does not exist.)

### 4. Secret key base generation

For `.env`, generate real secrets:

```bash
cp .env.example .env
mix phx.gen.secret | pbcopy   # SECRET_KEY_BASE_SITES
mix phx.gen.secret | pbcopy   # SECRET_KEY_BASE_ADMIN
```

Then paste into `.env`.

### 5. Production endpoint config

In `config/runtime.exs`, always enable `server: true` for both endpoints:

```elixir
config :sites, SitesWeb.Endpoint,
  server: true,
  url: [host: System.get_env("SITES_HOST"), port: 443, scheme: "https"],
  secret_key_base: System.fetch_env!("SECRET_KEY_BASE_SITES"),
  http: [ip: {0, 0, 0, 0, 0, 0, 0, 0}, port: String.to_integer(System.get_env("SITES_PORT") || "4000")]

config :admin, AdminWeb.Endpoint,
  server: true,
  url: [host: System.get_env("ADMIN_HOST"), port: 443, scheme: "https"],
  secret_key_base: System.fetch_env!("SECRET_KEY_BASE_ADMIN"),
  http: [ip: {0, 0, 0, 0, 0, 0, 0, 0}, port: String.to_integer(System.get_env("ADMIN_PORT") || "4001")]
```

### 6. Tidewave integration

Add to `sites` and `admin` deps:

```elixir
{:tidewave, "~> 0.6", only: :dev}
{:phoenix_live_reload, "~> 1.6", only: :dev}
```

In each endpoint, mount the plug **strictly before** `Plug.Parsers` and **only in dev**. If you put it after `Plug.Parsers`, `Plug.Conn.body_params` is already fetched and Tidewave raises a runtime error.

```elixir
  # Tidewave must run before body parsing
  if Mix.env() == :dev do
    plug Tidewave
  end

  plug Plug.Parsers,
    parsers: [:urlencoded, :multipart, :json],
    pass: ["*/*"],
    json_decoder: Phoenix.json_library()
```

If using live reload in dev, include the code-reloading block *after* the static plug and *before* Tidewave:

```elixir
  if code_reloading? do
    socket "/phoenix/live_reload/socket", Phoenix.LiveReloader.Socket
    plug Phoenix.LiveReloader
    plug Phoenix.CodeReloader
    plug Phoenix.Ecto.CheckRepoStatus
  end
```

In modern `phoenix_ecto` versions the migration-status plug is `Phoenix.Ecto.CheckRepoStatus` (not `CheckPendingStatus`). If you get an undefined-module warning and `mix.lock` already shows `phoenix_ecto`, update the name; do not add another dep.

## Landing page requirements

Every public site home must be a high-conversion landing page with these sections (configurable via `site.home_config` with strong defaults):

1. Sticky announcement bar
2. Gradient hero with headline, subheadline
3. Dual CTAs: primary lead-capture form and secondary action
4. Social proof line
5. Stats grid
6. How-it-works steps
7. Trust badges
8. Testimonials with star ratings
9. FAQ accordion
10. Final CTA

After successful lead submission, `push_navigate` to `/thank-you` and show a thank-you page with:
- Celebration headline
- Next steps subtitle
- Primary CTA button
- "Didn't get the email?" fallback

## Subagent execution notes

When the user wants one subagent per task in background, observe these rules:

1. **Sequential dependency:** tasks that create shared infra (`core`, umbrella config) must finish before tasks that depend on them (`sites`, `admin`, schemas, auth).
2. **Parallel batches for disjoint file sets:** `sites` and `admin` apps can run in parallel because they touch different directories, but they both modify `mix.lock`. Run `mix deps.get` yourself after the batch.
3. **Re-read after parallel batches:** concurrent edits to `apps/*/lib/*_web.ex`, `endpoint.ex`, or `config/dev.exs` can silently corrupt files. Always `read_file` and run `mix compile --warnings-as-errors` after a parallel batch returns.
4. **Fix root causes yourself:** when a subagent leaves the umbrella non-compiling, do not re-dispatch the same task. Read the error, patch the file directly, and continue.
5. **Migration ordering:** when multiple subagents create migrations, verify `ls apps/core/priv/repo/migrations | sort` matches dependency order (e.g., `sites` before `members`). Rename files and module names if needed.

See `references/subagent-pitfall-fixes.md` for concrete error patterns and fixes.

## Adding an Ecto-only app to an existing umbrella

Use this when the umbrella root already exists (has `mix.exs` with `apps_path`) and you need to add a new `:core` Ecto app, not build the whole project from scratch.

### 1. Install the Phoenix generator if it is missing

If `mix phx.new.ecto` is not available, install it once per machine:

```bash
mix archive.install hex phx_new --force
```

### 2. Run the generator from inside the umbrella's `apps/` directory

`mix phx.new.ecto` refuses to run from the umbrella root. Create `apps/` and run the generator there:

```bash
mkdir -p apps
cd apps
mix phx.new.ecto core --app core --no-assets --no-html --no-live --no-dashboard --no-mailer
```

This puts the app at `apps/core/` with the correct OTP name, shared `_build`, `deps`, and root `mix.lock`.

### 3. Add umbrella-level Ecto config

Create or edit these files under `config/`:

- `config/config.exs` — import env-specific configs and declare repos:

```elixir
import Config

config :core, ecto_repos: [Core.Repo]

config :core, Core.Repo,
  adapter: Ecto.Adapters.Postgres,
  migration_primary_key: [name: :id, type: :binary_id],
  migration_timestamps: [type: :utc_datetime_usec]

# ... PubSub/DNS/logger configs ...

import_config "#{config_env()}.exs"
```

- `config/dev.exs` — use the local Homebrew PostgreSQL and the current macOS user:

```elixir
config :core, Core.Repo,
  username: System.get_env("DB_USER") || "alvaro",
  password: System.get_env("DB_PASSWORD") || "",
  hostname: System.get_env("DB_HOST") || "localhost",
  database: "money_bot_dev",
  stacktrace: true,
  show_sensitive_data_on_connection_error: true,
  pool_size: 10
```

- `config/test.exs` — point to the test database + sandbox:

```elixir
config :core, Core.Repo,
  username: System.get_env("DB_USER") || "alvaro",
  password: System.get_env("DB_PASSWORD") || "",
  hostname: System.get_env("DB_HOST") || "localhost",
  database: "money_bot_test#{System.get_env("MIX_TEST_PARTITION")}",
  pool: Ecto.Adapters.SQL.Sandbox,
  pool_size: System.schedulers_online() * 2
```

- `config/runtime.exs` — read `DATABASE_URL` in prod.

### 4. Verify the PostgreSQL user

Homebrew PostgreSQL usually makes the current macOS user a superuser, not `postgres`. Check before choosing credentials:

```bash
whoami
psql postgres -c "SELECT usename FROM pg_user;"
```

Use the current user (e.g. `alvaro`) with an empty password for dev/test.

### 5. Create databases and validate

```bash
mix deps.get
mix compile
mix ecto.create                 # creates money_bot_dev
MIX_ENV=test mix ecto.create    # creates money_bot_test
mix test                        # should pass
```

Common errors and fixes for this flow are captured in `references/adding-core-ecto-to-existing-umbrella.md`.

## Adding a Phoenix web app to an existing umbrella

Use this when the umbrella already has a `:core` Ecto app and you need a new Phoenix web app (e.g. `:admin`) that stores data through `:core`, not through a local repo.

### 1. Run the web generator from inside the umbrella's `apps/` directory

`mix phx.new.web` also refuses to run from the umbrella root.

```bash
cd apps
printf "Y\n" | mix phx.new.web admin --app admin
```

This creates `apps/admin/` with a router, components, endpoint, gettext, assets, and tests. It intentionally has **no Ecto repo**.

### 2. Wire the web app to the `:core` repo

In `apps/admin/mix.exs`:

```elixir
defp deps do
  [
    {:core, in_umbrella: true},
    {:phoenix, "~> 1.8.8"},
    {:phoenix_ecto, "~> 4.5"},
    # ... rest of Phoenix deps
  ]
end
```

**Without this dependency** the web app cannot see `Core.Repo`, `Core.DataCase`, or any `:core` contexts at compile/test time.

In `config/config.exs`:

```elixir
# Admin has no repo of its own
config :admin, ecto_repos: []

# Its PubSub still has to be named
config :admin, Admin.PubSub, adapter: Phoenix.PubSub.PG2
```

### 3. Start Admin.PubSub in the supervision tree

The generator only prints a reminder. Add it yourself in `apps/admin/lib/admin/application.ex`:

```elixir
@impl true
def start(_type, _args) do
  children = [
    Admin.Telemetry,
    {Phoenix.PubSub, name: Admin.PubSub},
    Admin.Endpoint
  ]

  Supervisor.start_link(children, strategy: :one_for_one, name: Admin.Supervisor)
end
```

### 4. Set endpoint dev and test configuration

In `config/dev.exs`:

```elixir
config :admin, :dev_routes, true

config :admin, Admin.Endpoint,
  url: [host: nil],
  http: [ip: {0, 0, 0, 0}, port: 3001],
  check_origin: false,
  code_reloader: true,
  debug_errors: true,
  secret_key_base: "...64+ bytes from mix phx.gen.secret...",
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

In `config/test.exs`:

```elixir
config :admin, Admin.Endpoint,
  url: [host: nil],
  http: [ip: {127, 0, 0, 1}, port: 4002],
  secret_key_base: "...different 64+ bytes...",
  server: false
```

### 5. Re-point tests to `:core`'s database sandbox

The generator assumes the web app has its own `DataCase`. It does not.

In `apps/admin/test/test_helper.exs`:

```elixir
ExUnit.start()
Ecto.Adapters.SQL.Sandbox.mode(Core.Repo, :manual)
```

In `apps/admin/test/support/conn_case.ex`:

```elixir
setup tags do
  Core.DataCase.setup_sandbox(tags)
  {:ok, conn: Phoenix.ConnTest.build_conn()}
end
```

### 6. Clean up the generated router

`phx.new.web` adds a Swoosh mailbox-preview forward under the `/dev` scope, but it does **not** add `{:swoosh, ...}` as a dependency, so compilation fails unless you remove or replace it.

In `apps/admin/lib/admin/router.ex`:

```elixir
if Application.compile_env(:admin, :dev_routes) do
  import Phoenix.LiveDashboard.Router

  scope "/dev" do
    pipe_through :browser
    live_dashboard "/dashboard", metrics: Admin.Telemetry
    # Remove this unless you added {:swoosh, ...}:
    # forward "/mailbox", Plug.Swoosh.MailboxPreview
  end
end
```

### 7. Preserve umbrella-level config files

`phx.new.web` writes `config/runtime.exs` and `config/prod.exs` at the umbrella root. If those files already exist for `:core`, the generator will replace their contents. Always `git diff config/` after generating the app and merge/reapply `:core` prod/runtime database settings instead of keeping the generated file verbatim.

### 8. Verify

```bash
mix deps.get
mix compile --warnings-as-errors
mix test
```

Common errors and fixes for this flow are captured in `references/adding-phx-web-app-to-existing-umbrella.md`.

## MIT License on new repos

Every Álvaro repo ships a standard MIT `LICENSE` at the repo root (MyApp, MyApp, etc. all use MIT).

- **Copyright line convention:** `Copyright (c) <current year> Álvaro Lizama` — with the accent. MyApp's `LICENSE` is the reference. Do **not** copy from `git config user.name` (returns `Alvaro Lizama` without the accent).
- **Check before writing:** `search_files` for `LICENSE*` at repo root first — a README/SKILL.md mention of "MIT" does **not** mean the file exists. `node_modules` LICENSE files (e.g. playwright) are third-party noise, not the repo's license.
- **Commit message:** `chore: add MIT license`, then push if asked.
- When verifying whether a sibling repo has a license, check `~/Workspace/Repos/<repo>/LICENSE` (all repos live under `/Users/alvaro/Workspace/Repos/`).

## Suggested task order

1. mise + .mise.toml
2. scaffold `:core` (Repo, DataCase, Application)
3. umbrella config files (dev/test/prod/runtime, .env.example)
4. scaffold `:sites` Phoenix app
5. scaffold `:admin` Phoenix app
6. assets + Tailwind v4 + watchers
7. gettext
8. `Core.Sites` schema + migration
9. `Core.Members` schema + migration with `status` enum
10. `LoadSiteByHost` plug + `HomeLive` landing page (capture leads via `Members.create_lead/1`)
11. `ThankYouLive` + redirect
12. `AdminWeb.DashboardLive`
13. Tidewave verification + README
14. Admin auth (`Core.Users` + protected dashboard)
15. Member auth (`Core.Members.authenticate/3` + protected `/members`)
16. MIT `LICENSE` file at repo root (see "MIT License on new repos")

## Member lifecycle model

**Do NOT create separate `leads` and `members` tables.** Use a single `members` table with status-driven lifecycle:

| status | has password? | can log in? |
|--------|---------------|-------------|
| `lead` | no | no |
| `active` | yes | yes |
| `inactive` | yes | no |
| `banned` | yes | no |

Key functions:

```elixir
# Capture a lead from the landing page (status "lead", no password)
Core.Members.create_lead(%{site_id: site.id, email: "..."})

# Convert a lead to a member (sets password + status "active")
Core.Members.activate_member(lead, %{password: "..."})

# Authenticate only active members
Core.Members.authenticate(site.id, email, password)
```

Benifits: single unique constraint on `site_id + email`, no email duplication, lead-to-member conversion is an update.

## Testing a Phoenix umbrella

When running `mix test` in a Phoenix umbrella, several config details bite before any test starts:

1. **`elixirc_paths(:test)` must include `"test"`** in every Phoenix app `mix.exs`, or ExUnit finds no test modules.
   ```elixir
   defp elixirc_paths(:test), do: ["lib", "test/support", "test"]
   ```

2. **Error views must be configured per endpoint.** Phoenix 1.8 endpoints no longer implicitly define an `ErrorView`. Add to `config/config.exs` or per-env config:
   ```elixir
   config :sites, SitesWeb.Endpoint,
     render_errors: [view: SitesWeb.ErrorHTML, accepts: ~w(html json), layout: false]
   ```
   Then create `SitesWeb.ErrorHTML`/`ErrorJSON` and template files under `lib/sites_web/controllers/errors/` (e.g., `404.html.heex`, `500.html.heex`).

3. **`secret_key_base` and `live_view` signing salt must be long enough.** The cookie store requires **at least 64 bytes**; LiveView expects its signing salt to be present and reasonably long. Use `mix phx.gen.secret` for both in dev/test:
   ```elixir
   config :sites, SitesWeb.Endpoint,
     secret_key_base: "...",      # 64+ bytes
     live_view: [signing_salt: "..."]  # generated with mix phx.gen.secret
   ```

4. **Sessions are read-only in LiveView; controller login writes session.** Build member/admin login flows as controller actions that `put_session/3` and redirect; then protect LiveViews with `on_mount` hooks checking the same session key.

## Member auth route pattern

Use a plug for controller routes and `live_session` + `on_mount` for LiveViews:

```elixir
# router.ex
scope "/", SitesWeb do
  pipe_through :browser

  get "/login", MemberSessionController, :new
  post "/login", MemberSessionController, :create
end

scope "/", SitesWeb do
  pipe_through [:browser, SitesWeb.RequireMember]

  live_session :members,
    on_mount: [SitesWeb.LiveMemberAuth] do
    live "/members", MemberAreaLive, :index
  end
end
```

The controller calls `Core.Members.authenticate(site.id, email, password)` and puts `:member_id` in the session. The LiveViews read `session["member_id"]` in their `on_mount` hook.

## Common pitfalls

- **`mix phx.new.web` overwrites umbrella root config。** The generator writes its own `config/runtime.exs` and `config/prod.exs` at the umbrella root. If `:core` config already lived there, regenerate or merge — do not commit the generated versions blindly; they will drop `:core`'s database/runtime settings.
- **Web apps in the umbrella must declare `{:core, in_umbrella: true}` in their deps。** Without it, `Core.Repo`, `Core.DataCase`, and any generated context are not on the code path when the web app compiles or tests run. The symptom is an `UndefinedFunctionError` for `Core.Repo.get_dynamic_repo/0` or `Core.DataCase`.
- **Web apps don't have their own `DataCase`.** If `test_helper.exs` points to `Admin.Repo` and `conn_case.exs` calls `Admin.DataCase.setup_sandbox/1`, tests crash because those modules don't exist. Repoint both to `Core.Repo` and `Core.DataCase.setup_sandbox/1`.
- **Generated `/dev/mailbox` forward references `Plug.Swoosh.MailboxPreview`.** `phx.new.web` includes `forward "/mailbox", Plug.Swoosh.MailboxPreview` in the `/dev` scope, but does **not** add `{:swoosh, ...}` as a dependency. Either add Swoosh or remove the forward; otherwise compilation fails.
- **Elixir 1.20 directory naming:** the directory must match the OTP app name. `apps/core/` is correct for `:core`; `apps/money_bot_core/` is required only if the OTP app is `:money_bot_core`.
- **Mix lock concurrency:** multiple parallel subagents editing `mix.exs` files can corrupt `mix.lock`. Run `mix deps.get` yourself after a parallel batch that adds/changes deps before compiling.
- **Phoenix 1.8 `web.ex` macros:**
  - `PhoenixHTMLHelpers.Form/Link/Tag` are **functions**, not `__using__` modules. Import them, do not `use` them.
  - `Phoenix.Component` already provides `embed_templates/1`; do not also `import Phoenix.Template, only: [embed_templates: 1]` or you get a conflict.
  - `verified_routes()` should be unquoted inside `:router`, `:controller`, `:live`, `:component`, and `:html` macros so `~p` works everywhere.
- **Endpoint live-reloader plugs:** generated endpoints often reference `Phoenix.LiveReloader` and `Phoenix.Ecto.CheckRepoStatus`. If `phoenix_live_reload` is not added as a dev dep, add `{:phoenix_live_reload, "~> 1.6", only: :dev}` to `mix.exs`, run `mix deps.get`, and recompile; otherwise remove the entire `if code_reloading? do ... end` block from the endpoint to keep `mix compile --warnings-as-errors` clean. In `phoenix_ecto` 4.7+ the migration-status plug is `Phoenix.Ecto.CheckRepoStatus` (older docs/templates use `CheckPendingStatus`).
- **Tidewave plug position:** `plug Tidewave` must be placed before `Plug.Parsers` in the endpoint. If it runs after the body is parsed, Tidewave raises because it cannot intercept the request.
- **`server: true` in prod:** both `:sites` and `:admin` endpoints must set `server: true` in `config/runtime.exs` or they won't start in production/Release.
- **`import_config "#{config_env()}.exs"`** must be at the end of `config/config.exs` or test env loads dev DB.
- **HTTP adapter must be configured or `mix phx.server` crashes with `Plug.Cowboy is not available`.** Phoenix 1.8 does not bundle an HTTP server by default. Either add `{:bandit, "~> 1.0"}` to every Phoenix app and set `adapter: Bandit.PhoenixAdapter` in endpoint config, or add `{:plug_cowboy, "~> 2.0"}` and leave the default Cowboy adapter. Verify before declaring the project working:
  ```elixir
  # config/dev.exs and config/test.exs
  config :sites, SitesWeb.Endpoint,
    adapter: Bandit.PhoenixAdapter,
    ...
  ```
- **`secret_key_base`** must exist in dev/test endpoint config or LiveView tests fail.
- **`timeout` does not exist on macOS.** To smoke-test `mix phx.server` for a few seconds, use the Hermes background process (`terminal(background: true)`) or `gtimeout` from coreutils, not GNU `timeout`. Poll the endpoints with `curl` until the server responds; then kill the process.
- **Subagent races:** two subagents creating the same app component (e.g., `AdminWeb` macro or `layouts.ex`) in parallel will produce subtle corruption. Re-read affected files after parallel batches and reconcile manually with `write_file` if needed.
- **Plug assigns do not transfer to LiveView sockets.** Use `put_session(:site_id, site.id)` in the plug and reload from session in `mount/3`.
- **LiveView sessions are read-only.** Do not call `put_session/3` inside LiveView; use controllers for writes.
- **`render_slot(@inner_block)`** is the correct API for slots in Phoenix 1.8.
- **JSONB array columns** in Ecto need `{:array, :map}` in the schema AND `{:array, :map}` in the migration (which creates `jsonb[]`). Using `:map` in the migration creates plain `jsonb` (single object), causing `{"is invalid", [type: {:array, :map}, validation: :cast]}` errors at runtime when saving lists. Verify with `psql -tAc "SELECT atttypid::regtype FROM pg_attribute WHERE attrelid = 'table'::regclass AND attname = 'col'"`.
- **NEVER modify a committed migration — always create a new ALTER migration.** If a migration has already been committed (even in an unpushed commit), editing it breaks any database that already ran it. The user catches this immediately. Always run `mix ecto.gen.migration alter_<table>_<change>` and write the ALTER there. This is a hard rule — the user will say "falta una no?" or "no agregaste la migración".
- **UUID primary keys are the default.** Álvaro wants all tables to use `:binary_id` (UUID) as the primary key, not `:bigserial` integers. Set `migration_primary_key: [name: :id, type: :binary_id]` in repo config. Every schema gets `@primary_key {:id, :binary_id, autogenerate: true}` and `@foreign_key_type :binary_id`. See `references/uuid-primary-keys.md` for the full pattern.
- **Casting `jsonb` to `jsonb[]` in Postgres requires a USING clause with ARRAY[].** `ALTER TABLE ... ALTER COLUMN col TYPE jsonb[]` fails with `cannot cast type jsonb to jsonb[]`. The correct syntax is: `ALTER TABLE ... ALTER COLUMN col TYPE jsonb[] USING CASE WHEN col IS NULL THEN NULL ELSE ARRAY[col]::jsonb[] END`. For data migration, first wrap non-array values: `UPDATE ... SET col = jsonb_build_array(col) WHERE col IS NOT NULL AND NOT jsonb_typeof(col) = 'array'`.
- **`runtime.exs` config leaking to all environments:** any `config :app, Endpoint, http: [...]` placed outside the `if config_env() == :prod do` block overrides dev/test endpoint config (IP binding, port). Always put endpoint `http:` config inside the `:prod` block; dev/test have their own endpoint config in `dev.exs`/`test.exs`.
- **Inline `<script>` in HEEx templates:** Phoenix 1.8 + AGENTS.md forbids inline `<script>` tags in templates. The scaffold ships a theme-toggle `<script>` in `root.html.heex` — move it to `app.js` as an IIFE that runs before first render (avoids FOUC). The only `<script>` tag allowed in templates is the one loading `app.js` via `phx-track-static`.
- **Blocking `handle_info` in LiveView:** never do synchronous HTTP/API calls in `handle_info/2` — it freezes the LiveView for the entire request duration. Use `Task.Supervisor.async_nolink/2` to run the call, then handle the result in a `handle_info({ref, result}, socket)` clause (demonitor with `Process.demonitor(ref, [:flush])`) plus a `handle_info({:DOWN, _ref, :process, _pid, _reason}, socket)` fallback for crash recovery.
- **Pattern-match crashes in LiveView helpers:** `{:ok, result} = Some.create(...)` in a `handle_params` or private function crashes the LiveView process if the DB call fails. Use `case` with an explicit `raise` or error path instead.
- **Empty system message sent to API:** if an agent's system prompt (`soul`) can be empty `""`, don't prepend `%{role: "system", content: ""}` to the API messages — some providers reject it. Conditionally prepend only when non-empty.
- **API key in edit forms:** a `type="password"` input pre-filled with the current `api_key` sends the secret to the client. Use a placeholder like "Leave unchanged" and have `update_agent/2` skip the field when it arrives as an empty string (`Map.delete(attrs, "api_key")`).
- **Silent error swallowing in background tasks:** `{:error, _reason} -> :ok` in `Task.Supervisor.start_child` workers makes failures invisible. Always `Logger.warning` with the reason and context.
- **Layout `max-w-2xl` constraining all pages:** the default Phoenix scaffold wraps `<main>` content in `<div class="mx-auto max-w-2xl">`. This is too narrow for chat interfaces, dashboards, and grid layouts. Remove the wrapper from `layouts.ex` and add per-page containers (`max-w-6xl` for index, `max-w-4xl` for detail, `max-w-3xl` for forms).
- **Scaffold cruft in navbar and home page:** Phoenix-generated `layouts.ex` has links to phoenixframework.org, GitHub, and "Get Started" that are irrelevant to the actual product. Clean the navbar to only app-specific links + theme toggle, and replace the scaffold home page with a real landing page. The scaffold branding spans **four files**, not just the navbar — see `references/phoenix-scaffold-rebranding.md` for the complete checklist: (1) `priv/static/images/logo.svg` (Phoenix bird → custom logo), (2) `home.html.heex` (Phoenix demo page → product landing), (3) `root.html.heex` (`<.live_title>` suffix `· Phoenix Framework` → product tagline, also fix casing), (4) `layouts.ex` `app/1` navbar (Phoenix links → app CTAs). Also create a real `README.md` — the scaffold only ships a placeholder.
- **Stale test assertions after rebranding.** When you replace the Phoenix scaffold home page (`home.html.heex`) with a custom landing page, the generated `PageControllerTest` still asserts the old Phoenix default text (e.g. `"Peace of mind from prototype to production"`). The test passes before the rebrand and fails after — update the assertion to match the new page content (e.g. `"Tu gateway autohospedado para modelos de lenguaje."`). This is easy to miss because the test file is not in the rebranding checklist.
- **Sidebar menu grouping by setup workflow.** Álvaro wants dashboard sidebar links grouped by **setup order**, not alphabetically or randomly. Each group has a uppercase section header (`text-xs font-semibold uppercase tracking-wide text-base-content/40`) followed by its links. The grouping reflects the conceptual dependency chain: you must configure X before Y. Example from MyApp: `Configuración` (Aliases → Proveedores → Suscripciones → Pricing → Reglas de routing) → `Acceso` (Equipos → API Keys) → `Monitoreo` (Logs). When Álvaro says "agrupa los menús en orden de setup", group links with `<div class="space-y-1">` sections inside the `<nav>`, each starting with a `<p>` header. Also: when a user asks "where do I do X?" and it's not in the menu, add the missing link — the sidebar should surface every route the user needs, not hide them.

See `references/phoenix-code-review-checklist.md` for a comprehensive bug-hunting checklist distilled from a full-codebase review.

See `references/schema-field-lifecycle.md` for how to decide when a schema field is cargo cult vs real functionality, and when to run cleanup scripts (Opción B) vs leave fields inert (Opción A).

## Customizing daisyUI themes & adding a CSS design system

When the user wants to restyle the daisyUI color palette (e.g. Linear/Notion
aesthetic with oklch teal + cool gray), add typography/elevation/skeleton
utilities, or change border radii — all within `assets/css/app.css` only —
see `references/daisyui-theme-customization.md` for the complete pattern:
oklch color values for both dark/light themes, plain-CSS utility classes
(no `@apply`), elevation with per-theme shadow variables, skeleton shimmer
with reduced-motion, and what NOT to break (TipTap styles, `@custom-variant`,
`@plugin` blocks).

## Extending `<.input>` with help text (`:hint` attr)

The generated `core_components.ex` `<.input>` component has no built-in help
text. When building forms with non-obvious fields (API keys, rate limits,
billing types), add a `:hint` attr so each field can show a one-line
explanation below the input.

### 1. Add the attr

```elixir
attr :hint, :string, default: nil, doc: "help text shown below the input"
```

### 2. Render in every input variant

Add this line **after** `<.error>` and **before** `</div>` in each clause
(checkbox, select, textarea, and the default text/url/number catch-all):

```heex
<p :if={@hint} class="text-xs text-base-content/50 mt-1">{@hint}</p>
```

### 3. Use in templates

```heex
<.input
  field={@form[:api_key_encrypted]}
  type="text"
  label="API key"
  placeholder="sk-..."
  hint="El token que entrega el proveedor (sk-...)."
/>
```

The hint renders as small muted text below the input, above nothing else.
It degrades gracefully — omit `hint=` and the input looks identical to before.

### When to use

- Fields with non-obvious semantics (nil = unlimited, 0 = disabled, etc.)
- Fields where the user asked "what does this do?"
- Security-sensitive fields (API keys, tokens) where placement matters
- Any form where the user picked an element and asked for an explanation
- **Per-entity vs per-member limits:** when a form has budget/concurrency/RPM fields on a `Team` schema, clarify in the hint whether the value applies per-team or per-member. Example MyApp: `default_daily_budget_usd` is a per-member default (each member gets this amount, plus their individual `extra_daily_budget_usd`), not a team-wide pool. If unclear, check the `effective_limits/1` function — the calculation (add vs share) reveals the semantics. Write the hint to match: "Presupuesto diario por miembro. Cada miembro puede tener un extra que se suma a este valor."

## Verification commands

```bash
# After every batch of tasks:
mix compile --warnings-as-errors
mix test

# Dev servers:
mix phx.server

# PostgreSQL:
brew services info postgresql
```

- **Static assets and node_modules must be gitignored.** Add to `.gitignore`:
  ```
  /apps/sites/assets/node_modules/
  /apps/admin/assets/node_modules/
  /apps/sites/priv/static/assets/
  /apps/admin/priv/static/assets/
  ```
  Run the initial Tailwind/esbuild build once before committing, then stage only source files (`css/app.css`, `js/app.js`, `package.json`) and ignore generated assets.

## Favicon setup

After scaffolding, add a favicon. See `references/favicon-generation.md` for the macOS-native recipe using `sips` + Python to build a multi-resolution `.ico` from the project's SVG logo, no ImageMagick needed.

## References

- `references/session-money-bot-2026-06-22.md` — concrete fixes for subagent-left Phoenix compilation errors, render_errors, LiveView signing salts, and member auth
- `references/brew-postgres-env.md` — Homebrew PostgreSQL, mise .env, and secret generation cheat sheet
- `references/phoenix-code-review-checklist.md` — comprehensive bug-hunting checklist for Phoenix codebase reviews: type mismatches, runtime.exs leaks, blocking handle_info, pattern-match crashes, API key exposure, silent error swallowing, inline scripts, layout constraints
- `references/phoenix-scaffold-rebranding.md` — complete 4-file checklist for stripping Phoenix Framework branding from a generated project: logo.svg, home.html.heex, root.html.heex title suffix, layouts.ex navbar. Includes README creation and visual verification steps.
- `templates/endpoint.ex` — known-good Phoenix 1.8 endpoint template with correct `Tidewave`, `Phoenix.LiveReloader`, and `Phoenix.Ecto.CheckRepoStatus` ordering
