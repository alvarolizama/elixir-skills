# Release and Deploy — mix release → container PaaS

Symptom: the wave ships code, then the deploy fails — or worse, deploys and
misbehaves only in prod (403 on POST, boot loop, URLs pointing at
`example.com`). Mechanism: prod runs a compiled release with a config
provider; anything that only exists in the `:prod` path breaks at deploy
time, invisible to `mix test` / `mix precommit`.

## Canonical release workflow

```bash
mix phx.gen.release
```

Creates `lib/<app>/release.ex` (`migrate/0`, `rollback/2`, `repos/0`,
`load_app/0`), `rel/overlays/bin/migrate`, `rel/overlays/bin/server`
(`PHX_SERVER=true exec ./<app> start`), plus `.bat` twins (keep them).

Use `mix release` with NO name — `mix release <name>` fails with
`Unknown release` unless a `releases:` block exists in `mix.exs`.

Verify BEFORE pushing — a passing `mix precommit` (runs `:test`) does NOT
prove the `:prod` boot (`runtime.exs` runs as a config provider in a
release — a different code path):

```bash
rm -rf _build/prod && MIX_ENV=prod mix deps.get --only prod && MIX_ENV=prod mix release
ls _build/prod/rel/<app>/bin/                     # must list: <app>, migrate, server
DATABASE_URL=ecto://nope:nope@127.0.0.1:1/nope \
  SECRET_KEY_BASE=test \
  _build/prod/rel/<app>/bin/<app> eval "IO.puts(:ok)"   # must print :ok
```

Missing `bin/migrate`/`bin/server` = overlays absent at release time —
re-run `mix phx.gen.release`. Re-run the smoke after touching `runtime.exs`,
`release.ex`, or `rel/overlays/bin/`.

## PaaS wiring

- Start command: `/app/bin/server`.
- Pre-deploy hook (runs in the NEW container before traffic swaps; safe for
  N replicas): `/app/bin/migrate` when the DB exists (managed Postgres/DBA);
  idempotent `/app/bin/setup` when the first deploy must create the DB
  (single-instance only — racing replicas trip on "already exists").
  First-time data with migrate-only:
  `/app/bin/migrate && /app/bin/<app> eval <App>.Release.seed`.
- Post-deploy: cache warming only, never migrations.
- Build packs (Coolify: Nixpacks default, Railpack newer; only Nixpacks
  detects Elixir by default): install = `mix local.hex --force`,
  `mix local.rebar --force`, `mix deps.get --only prod`; build = `mix
  compile` + `mix assets.deploy` (+ `mix ecto.deploy` if defined); start =
  `mix phx.server`. A Dockerfile build pack ignores the pack entirely —
  most reliable: it controls install + build + start, no cache surprises.
  Never switch the runtime to Alpine — distributed Erlang DNS breaks on
  musl.

## Idempotent first-run setup

```elixir
def setup do
  load_config()
  create()
  migrate()
  seed()        # must itself be idempotent: get_by then insert
  :ok
end

defp ensure_db_created(repo) do
  case repo.__adapter__().storage_up(repo.config()) do
    :ok -> :ok
    {:error, :already_up} -> :ok        # Ecto 3.14+
    {:error, {:already_up, _}} -> :ok   # older Ecto
    {:error, term} -> {:error, term}
  end
end
```

- `storage_up` returns `{:error, :already_up}` (atom, Ecto 3.14+) or a
  tuple on older Ecto — match BOTH, or the second deploy crashes with a
  misleading "failed to create db".
- Parens on `repo.__adapter__()` / `repo.config()`: Elixir 1.20+ deprecates
  the no-paren form — `--warnings-as-errors` fails the build.
- Trade-off: `setup` gives the container CREATEDB privileges; in
  shared/multi-tenant DBs prefer `bin/migrate` + DBA-created DB.
- Gate survival of auto-seeded demo rows behind an env var read at RUNTIME
  in a function body — a module attribute is baked at compile time and the
  guard is unreachable.

## release.ex pitfalls — the startup pattern everyone breaks

RULE: any function in `release.ex` that touches a repo wraps the work in
`Ecto.Migrator.with_repo/2` — it starts the repo ad-hoc and registers it.

- **P1 — seed/setup calling a repo outside `with_repo`:**
  `** (RuntimeError) could not lookup Ecto repo MyApp.Repo because it was not started...`
  `ensure_loaded` + `ensure_all_started(:ssl)` load modules but don't start
  the supervisor that registers the repo.
- **P2 — create/0 reads repo.config before runtime.exs ran.** `storage_up`
  reads the DB name/credentials set only when the config provider runs at
  release boot. Force evaluation at the top of EVERY public function:
  `defp load_config do Application.ensure_all_started(:ssl); Application.ensure_loaded(@app); _ = Application.get_all_env(@app); :ok end` — the last
  line triggers the config provider.

- **P3 — domain code talking PubSub/TaskSupervisor during partial boot.**
  `with_repo` starts ONLY the repo. `Phoenix.PubSub.broadcast/3` RAISES
  (`ArgumentError`); `Task.Supervisor.start_child/3` EXITS `{:noproc, _}` —
  a bare `rescue` does NOT catch exits. Wrap side-effects in BOTH
  `rescue _ -> :ignored` AND `catch :exit, _ -> :ignored`. Never "fix" via
  `Application.ensure_all_started(:my_app)` — that boots the endpoint, binds
  ports, and runs schedulers during a migration.
- **P4 — `Repo.delete_all/1` returns `{count, nil}`, not a count.**
  Match `{count, _} = Repo.delete_all(query)` before interpolating.

## runtime.exs / prod.exs pitfalls

- **P5 — `PHX_HOST` default `"example.com"`; `PHX_SERVER` unset.** The
  template defaults make generated URLs (login redirects, signed links,
  mailer) point at `example.com`; unset `PHX_SERVER` logs `:server was not
  enabled ... won't start`. Raise at boot when `PHX_HOST` is missing, and
  gate the endpoint: `if config_env() == :prod or System.get_env("PHX_SERVER") do config :my_app, MyAppWeb.Endpoint, server: true end`.
  Unconditional `server: true` makes `mix test` boot the endpoint and die
  `:eaddrinuse` when a dev server holds the port.

- **P6 — `validate_compile_env` aborts boot.** Setting a key at runtime that
  was read via `Application.compile_env/3` in a module attribute
  (e.g. `@children` in `application.ex`) aborts boot:
  `ERROR! ... has a different value set for key :dns_cluster_query during
  runtime compared to compile time...`. Fix: read such keys at runtime in
  `start/2` with `Application.get_env/2`; never `compile_env` a key that
  `runtime.exs` also sets. Disabling the check hides the bug.
- **`force_ssl` is compile-time** (baked into the `.app` at `mix release`):
  runtime setting aborts boot; there is NO runtime lever. Only correct
  toggle is build-time — `config/prod.exs` gated on
  `System.get_env("DISABLE_FORCE_SSL") != "1"`, exposed as a Docker
  `ARG DISABLE_FORCE_SSL`. For apps that flip HTTPS↔plain-HTTP, keep
  `prod.exs` free of `force_ssl` and compute opts in `runtime.exs` from
  `PHX_SCHEME`, applied only when non-empty.

## 403 on POST /login in prod (CSRF + session cookie)

GET renders; POST 403s with NO controller log line (the request dies in the
`:browser` pipeline — that absence is the tell: plug-level, not auth).

1. **Session cookie `secure: true` on HTTP:** browser drops the cookie →
   no session → CSRF can't validate. Default OFF (cookie is encrypted +
   signed):
   `secure: System.get_env("SESSION_COOKIE_SECURE") in ~w(true 1)`.

2. **Origin mismatch on dual access:** `protect_from_forgery` matches the
   POST `Origin` header against the endpoint `url:` config — allow-list
   every real origin at runtime:
   `check_origin: case System.get_env("CHECK_ORIGINS") do nil -> true; "" -> true; s -> String.split(s, ",", trim: true) end`.
   Format: bare `scheme://host:port`, comma-separated, no paths. Several
   "security hardening" commits landing together produce a CLUSTER (DB SSL
   verify + cookie secure + origin check) — debug each independently.

## Ecto/Postgres TLS

`verify_peer` against the system CA bundle breaks self-signed/private-CA
Postgres: `bad_certificate selfsigned_peer` → boot loop; the misleading
`failed to create db for MyApp.Repo: "killed"` actually means the TLS
connect died — the DB may already exist. Default to encrypted-but-unverified,
strict opt-in:

```elixir
maybe_ssl =
  cond do
    System.get_env("ECTO_SSL") in ~w(false 0) -> []
    # ECTO_SSL_VERIFY in ~w(true 1) -> [ssl: true, ssl_opts: [verify: :verify_peer, cacerts: :public_key.cacerts_get()]]
    true -> [ssl: true, ssl_opts: [verify: :verify_none]]
  end
```

`verify_none` still encrypts the wire. Prefer `cacertfile` over the system
bundle when the provider's CA is available. Never leave `# ssl: true`
commented out — silent no-SSL in prod.

## Plain-HTTP / LAN / VPN topologies

Dead giveaways: `Configuration :server was not enabled`;
`url: [host: ...] configuration value "host.example:5000" is invalid`
(host string with port glued — keep `PHX_HOST` and `PHX_PORT` separate);
`Plug.SSL is redirecting ... 301` + `Connection that looks like TLS
received on a clear channel` (force_ssl enabled — needs the build-time
flag).

`PORT` (real listen) vs `PHX_PORT` (generated-URL port) vs `EXPOSE`
(Docker metadata only, does NOT set the listen port — `EXPOSE 4000` while
listening on 4001 = `ERR_CONNECTION_RESET`; set all three to the same
value).

## Build-time fixes (Dockerfile / build pack)

- **`mix compile` before `mix deps.get`** → `lock outdated` even when
  `mix.exs` and `mix.lock` agree (prod is strict; dev tolerates it). Fetch
  deps first (`RUN mix deps.get --only prod` then compile).
- **Git-pinned dep "outdated"** — `Mix.SCM.Git.lock_status/1` compares the
  URL AND a keyword list taken from `[:branch, :ref, :tag, :sparse,
  :subdir, :depth]` (in that source order!): `ref` vs `tag` vs `branch`
  must pick EXACTLY ONE and the options' ORDER must match the lock entry;
  `:app`, `:compile`, `:runtime` are NOT compared. The SHA in the error is
  from `mix.exs`, not the lock. Fix at the source: align options, `mix
  deps.get`, commit `mix.lock`. Local-passes-PaaS-fails = cached lock layer
  or stale Docker cache — clean rebuild or custom Dockerfile with
  `rm -rf _build/prod`.
- **OOM during `mix deps.compile`** (rebar3 deps, tight memory, bare
  `exit code 255`): `RUN ERL_AFLAGS="+S 1:1" mix deps.compile <deps...>`
  then `mix deps.compile`. Never `+MBas busy_wait` (invalid).
- **`npm ci` strictness:** lock generated on node 22/npm 10 fails inside
  node 20/npm 9 with a usage dump. Use `npm install` or match the node
  major.
- **Pin real `hexpm/elixir` tags** (only a subset exists; an unpublished-tag
  `FROM` fails) and match the runtime `debian:*-slim` slug to the builder's
  (glibc drift).
- **`.dockerignore` blocks later COPYs** — grep the Dockerfile for every
  `COPY` before ignoring a path; `rel/`, `config/`, `priv/` are often
  COPY'd.
- **Secrets:** never in `ARG` — `SecretsUsedInArgOrEnv` flags them and
  values bake into image layers. Runtime ENV only, or a secret manager
  loaded at container start.
- **Session salts fail closed:** `signing_salt:
  System.get_env("SESSION_SIGNING_SALT") || raise("... is missing")` —
  never a hard-coded fallback. Same for `SESSION_ENCRYPTION_SALT`. Hardened
  set: signing + encryption salt, `same_site: "Lax"`, `http_only: true`,
  `max_age` (~8h), `secure` behind the env toggle.

## Env-var checklist (document in the app README)

`DATABASE_URL`, `PHX_HOST`, `PHX_SCHEME` (https / http for VPN),
`SECRET_KEY_BASE`, `SESSION_SIGNING_SALT`, `SESSION_ENCRYPTION_SALT`,
`SESSION_COOKIE_SECURE`, `ECTO_SSL` (+ `ECTO_SSL_VERIFY` for CA-valid
certs), `CHECK_ORIGINS`, `POOL_SIZE`; build arg `DISABLE_FORCE_SSL` only
with the build-time force_ssl pattern.

## Verification

```bash
rm -rf _build/prod && MIX_ENV=prod mix release
test -x _build/prod/rel/<app>/bin/migrate && test -x _build/prod/rel/<app>/bin/server && echo "bins OK"
DATABASE_URL=ecto://nope:nope@127.0.0.1:1/nope SECRET_KEY_BASE=test \
  _build/prod/rel/<app>/bin/<app> eval "IO.puts(:ok)"    # -> :ok
```

If the eval fails, the release is broken regardless of `mix precommit` —
fix runtime config first. `DATABASE_URL is missing` = runtime config broken
before the DB is ever consulted.