# my_org/hub umbrella — local setup specifics

Private git repo: `~/Workspace/Repos/my_org/hub` (branch main, umbrella Phoenix).

## Toolchain (`.mise.toml`)
- elixir `1.19.5-otp-28` + erlang `28.1` + node `20.0.0` (mise-pinned).
- Machine was running Elixir 1.20.1/OTP 29 via a different shim; mise pins the project versions — trust and always `mise x --` / `mise run`.
- `.mise.toml` has `[env] _.file = ".env"` → **mise loads `.env`; plain shell does NOT**.
- `[tasks.bootstrap] = "make bootstrap"`, `[tasks.dev] = "make server"`, `[tasks.db_setup]`, `[tasks.test]`, `[tasks.db_reset]`.

## Private Hex org
- Org **`my_org`** hosts `hub_reporter` (~> 0.3.0) and `hub_novelties` (~> 0.1.x), required in `apps/hub/mix.exs` and `apps/tracker/mix.exs`.
- First-time auth (README §2.1): `mix hex.organization auth my_org --key <READ_ONLY_KEY>`. Key shared via password manager; alternatively a hex.pm account added to the org (`mix hex.user auth`).
- Machine state: `~/.hex/hex.config` contained an oauth token but `mix hex.organization list` returned empty → **not authenticated to my_org**; user must supply the key/account.
- lockfile pins: `hub_novelties 0.1.2` (repo `hexpm:my_org`), `hub_reporter 0.3.1`.

## Env / DB names
- `.env` (user-provided secrets live here; gitignored):
  - `DATABASE_NAME=bravo_hub`, `TEST_DATABASE_NAME=bravo_hub_test` ← user's explicit override; default in code is `bravo_hub_dev` / `bravo_hub_test`.
  - `GOOGLE_CLIENT_ID/SECRET`, `GOOGLE_AI_API_KEY`, `SECRET_KEY_BASE`, `PHOENIX_HOST=bravobook-pro.vpn.cloud`, `BIND_IP=0.0.0.0`, `PORT=4000`, R2 creds for Cloudflare R2 storage.
- `config/config.exs` + `config/dev.exs` read `DATABASE_NAME` (fallback `bravo_hub_dev`), username `postgres`/password `postgres` on `localhost:5432`, db `contexts_dev` in old DATABASE_URL form (superseded — DATABASE_NAME is canonical).
- Repo owner app for ecto: `apps/contexts` (Contexts.Repo).
- Makefile: `make setup` (brew+mise+postgres), `make bootstrap` (deps+assets+db), `make db.setup/create/drop/reset/migrate`, `db.psql` connects to `contexts_dev` (stale name — may need updating).

## Server
- `cd apps/hub && mix phx.server` (or `mise run dev`), port 4000 (PORT env override).
- Watchers: esbuild + tailwind run in dev; `npm install --prefix assets` needed first.
- External services optional in dev: Google OAuth (login), R2 (image upload), GitHub App (repos), Coolify (deploy webhooks). Without tokens the app still boots; only the wired features 401/fail.

## Verification state (this machine — bootstrap COMPLETE)
- Postgres running (pg_isready OK, `psql -U postgres` works — local trust for user `postgres`).
- Hex org auth DONE via key from user (`HEX_KEY` appended to `.env`, `mix hex.organization auth my_org --key <key>` silent success).
- `mix deps.get` OK (public + `hub_reporter` 0.3.1 + `hub_novelties` 0.1.2 from hexpm:my_org); `npm install --prefix assets` OK (audit warnings only).
- DB `bravo_hub` created + migrated (last migration drops miniapps tables); `mix ecto.create/migrate` from `apps/contexts`.
- `mix compile` OK. Preexisting warnings (do NOT treat as regressions): unused aliases `Repo`/`WorkItem` in `apps/contexts/lib/contexts/permissions.ex`; deprecated `Contexts.Permissions.is_root?/1` used in `work_items_constraints.ex`. `mix compile --warnings-as-errors` therefore FAILS on this repo.
- Server verified: `mix phx.server` (background), Bandit at `0.0.0.0:4000`; `curl /` → 200, `curl /api/v1/health` → 200. Env `PHOENIX_HOST=bravobook-pro.vpn.cloud` + `BIND_IP=0.0.0.0` makes it reachable via VPN.