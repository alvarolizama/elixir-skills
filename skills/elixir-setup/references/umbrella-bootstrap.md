# Umbrella local bootstrap (mise + Homebrew PostgreSQL + private Hex)

**Symptom.** Fresh clone of an Elixir/Phoenix umbrella: `mix deps.get` fails
with `Unknown package <pkg> in lockfile` or `Failed to fetch record for
hexpm:<org>/<pkg>`, the server boots with wrong defaults (wrong DB name,
missing tokens), or `mix` resolves a different Elixir/OTP than the repo pins.

**Mechanism.** Three independent environment layers must all be correct before
any `mix` command: (1) the toolchain pin, (2) the env vars, (3) Hex
organization auth. mise owns layers 1–2 and loads `.env` **only for commands
run through it** — bare shell commands silently miss every `.env` value, which
produces "weird defaults" failures that look like code bugs.

## Check the environment first (batch these)

```bash
elixir --version
erl -eval "erlang:display(erlang:system_info(otp_release)), halt()." -noshell
node --version
pg_isready
psql postgres -c "SELECT 1"
cat .mise.toml
ls .env.example .env 2>/dev/null
```

Copy `.env.example` to `.env`; never invent vars you have not seen in the
example or the repo config files. Respect exactly the env var names the
codebase reads (`config/config.exs`, `config/<env>.exs`).

## mise: the #1 gotcha

```toml
# .mise.toml
[tools]
# Pin the exact OTP build; "1.20" may resolve to 1.20.1-otp-29 and break on Erlang 27
elixir = "1.20.1-otp-27"
erlang = "27.0"

[env]
# mise loads .env automatically when entering the directory
_.file = ".env"
```

- Run `mise trust` in the repo root first — untrusted config makes every mise
  command error.
- **Never `source .env`.** mise loads it; plain shell does not. Always run
  `mise x -- <cmd>` or `mise run <task>` so env vars apply.
- `[tasks.*]` in `.mise.toml` map to `mise run <name>` (bootstrap, dev, test,
  db_reset...).
- After editing `.env`: re-run `mise trust` and `mise exec -- elixir --version`
  if mise complained about malformed lines.
- Paste secrets as **single-line strings**. Line continuations (`\`) in `.env`
  make mise fail with `malformed value in .env`. Strip any markdown
  decoration (`@url:` fences) from pasted content.

## Private Hex organization auth

Search all `mix.exs` files for `organization: "<org>"` — those packages are
NOT on public hex.pm.

- Symptom: `Failed to fetch record for hexpm:<org>/<pkg> from registry (using
  cache instead)` → `** (Mix) Unknown package <pkg> in lockfile`.
- Fix (usually documented in the repo README — search it first):
  `mix hex.organization auth <org> --key <READ_ONLY_KEY>` (one time per
  machine), or get a hex.pm account added to the org and run
  `mix hex.user auth`.
- Check auth state: `mix hex.organization list` (empty = not authed) and
  `~/.hex/hex.config`.
- `mix hex.organization auth <org> --key <key>` prints NOTHING on success
  (exit 0). Do not re-run it guessing at failure — proceed to `mix deps.get`.
- Fix Hex auth **before** `mix deps.get` — it blocks everything downstream
  (assets, DB setup).

## Homebrew PostgreSQL

```bash
brew services info postgresql    # or postgresql@17
brew services start postgresql
psql postgres -c "SELECT usename FROM pg_user;"   # find your local role
```

Homebrew creates a superuser matching the macOS username, not `postgres`.
Use that role with an empty password for dev/test, or create the `postgres`
role the repo expects: `createuser -s postgres`. If the project uses a
Makefile, `make setup` usually covers brew + mise + postgres and
`make bootstrap` = deps + assets + DB in one shot.

## Secrets

```bash
cp .env.example .env
mix phx.gen.secret | pbcopy   # SECRET_KEY_BASE_<APP1>
mix phx.gen.secret | pbcopy   # SECRET_KEY_BASE_<APP2>
```

Paste each into `.env`. `.env` is gitignored by convention — never commit it.

## Bootstrap sequence (typical)

```bash
mise trust
mise x -- mix deps.get                      # needs hex org auth first
mise x -- bash -lc 'cd apps/<web> && npm install --prefix assets'
mise x -- bash -lc 'cd apps/<repo-owner> && mix ecto.create && mix ecto.migrate'
mise x -- bash -lc 'cd apps/<web> && mix phx.server'
```

Or `mise run bootstrap` if `.mise.toml` defines it. In an umbrella the Repo
belongs to ONE app (the repo owner) — run `mix ecto.create/migrate` from that
app's directory with the umbrella env loaded via mise.

## Verification

```bash
curl -sf http://localhost:<PORT>                       # home page 200
curl -sf http://localhost:<PORT>/api/v1/health         # health endpoint 200
MIX_ENV=test mix run -e 'IO.puts(Application.get_env(:<core>, <Core>.Repo)[:database])'
# → my_app_test  (proves MIX_ENV=test loads test config, not dev config)
```

External services (OAuth providers, object storage, deploy webhooks) are
optional in dev: without tokens the app still boots, only the wired features
fail with 401.

## Pitfalls

- Bare shell commands silently miss `.env` → wrong DB names, missing tokens.
  Always `mise x --`.
- For pure config-file changes there is no test suite — the check is a
  read-back (`grep`/cat), not `mix test`.
- A user may override the example DB names ("the DB should be called X"):
  apply their exact names in `.env` only; leave code config defaults alone.
- A `.mise.toml` with an untrusted-config error is easy to misread as a
  broken toolchain — `mise trust` first.
