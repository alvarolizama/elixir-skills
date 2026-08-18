# Plain-HTTP / LAN / VPN deploy error transcripts

Reference log snippets from a real Phoenix 1.8 deploy over NetBird VPN at
`local-apps.vpn.cloud:5000` (plain HTTP, no TLS, custom port). Use these
to grep against new deploy logs and instantly identify which pitfall
you are hitting.

## Symptom 1: `Configuration :server was not enabled`

```
[info] Configuration :server was not enabled for MyAppWeb.Endpoint, http/https services won't start
```

Cause: `PHX_SERVER` env var not set, or `bin/server` overlay not invoked.
The default `config/runtime.exs` gates `server: true` behind
`if System.get_env("PHX_SERVER") do`. **Fix:** enable `server: true` for
`:prod` in `runtime.exs`, keeping the `PHX_SERVER` gate for other envs —
an unconditional `server: true` runs in EVERY env (runtime.exs is
evaluated for dev and test too) and makes `mix test` boot the endpoint,
crashing with `:eaddrinuse` when a dev server already holds the port
(verified on MyApp):

```elixir
if config_env() == :prod or System.get_env("PHX_SERVER") do
  config :MyApp, MyAppWeb.Endpoint, server: true
end
```

## Symptom 2: `url: [host: ...] configuration value "host:port" is invalid`

```
[warning] url: [host: ...] configuration value "local-apps.vpn.cloud:5000" for MyAppWeb.Endpoint is invalid
```

Cause: someone set `PHX_HOST=local-apps.vpn.cloud:5000` (host with port
glued on). Phoenix rejects this — `url: [host: ...]` expects a bare
hostname. **Fix:** split into `PHX_HOST=local-apps.vpn.cloud` and
`PHX_PORT=5000`.

## Symptom 3: redirect to `https://` over plain HTTP

```
[info] Plug.SSL is redirecting GET / to https://local-apps.vpn.cloud:5000 with status 301
[warning] Connection that looks like TLS received on a clear channel
```

Cause: `force_ssl: [rewrite_on: [:x_forwarded_proto], ...]` is enabled in
`config/prod.exs`, so Plug.SSL 301s every plain-HTTP request to HTTPS.
The "TLS on clear channel" warnings are the client retrying with TLS
after the redirect and failing. **Fix:** compile-time opt-out via
`DISABLE_FORCE_SSL=1` in the build env (NOT runtime — `force_ssl` is
embedded in the release `.app` file at `mix release` time).

## Symptom 4: redirect to `example.com` (or some unrelated default)

```
[info] Access MyAppWeb.Endpoint at https://example.com
```

Cause: `PHX_HOST` env var not set, `runtime.exs` defaulted to
`"example.com"`. Every URL the app generates (login redirects, signed
URLs) points at that domain. **Fix:** remove the fallback and raise at
boot with a clear message.

## Symptom 5: `could not lookup Ecto repo ... because it was not started`

```
** (RuntimeError) could not lookup Ecto repo MyApp.Repo because it was not started or it does not exist
    (ecto 3.14.0) lib/ecto/repo/registry.ex:22: Ecto.Repo.Registry.lookup/1
    (ecto 3.14.0) lib/ecto/repo/supervisor.ex:182: Ecto.Repo.Supervisor.tuplet/2
    (<app> 0.1.0) lib/<app>/repo.ex:2: MyApp.Repo.get_by/3
    /app/_build/prod/rel/<app>/lib/<app>-0.1.0/priv/repo/seeds.exs:13: (file)
```

Cause: a `seed/0` (or `setup/0` -> `seed/0`) function called
`Code.eval_file(seeds.exs)` outside an `Ecto.Migrator.with_repo/2`
callback. `migrate/0` worked because `with_repo` registers the repo
in the Ecto registry for the duration of the callback. **Fix:** wrap
the seed work in the same envelope.

## Symptom 6: `validate_compile_env` boot abort when `force_ssl` is set in runtime.exs

```
ERROR! the application :MyApp has a different value set for path [:force_ssl] inside key
MyAppWeb.Endpoint during runtime compared to compile time. Since this application environment
entry was marked as compile time, this difference can lead to different behavior than expected:
  * Compile time value was not set
  * Runtime value was set to: [rewrite_on: [:x_forwarded_proto], exclude: [hosts: ["localhost", "127.0.0.1"]]]
Runtime terminating during boot ({<<"aborting boot">>,[{'Elixir.Config.Provider',boot,2,[]}]})
```

Cause: someone moved `force_ssl` from `prod.exs` to `runtime.exs` hoping to
toggle it at runtime with `PHX_SCHEME=http`. Phoenix marks `:force_ssl` as
compile-time (`compile_env` inside the endpoint), so any runtime value that
differs from the compile-time one aborts the boot. **Fix:** `force_ssl` MUST
stay in `prod.exs`; disabling it requires a rebuild with
`DISABLE_FORCE_SSL=1` as a BUILD arg (see Symptom 3 and the working setup
below). There is no runtime lever.

## Working setup for plain-HTTP / NetBird / LAN deploy

`config/runtime.exs`:
```elixir
host =
  System.get_env("PHX_HOST") ||
    raise """
    environment variable PHX_HOST is missing.
    Set it to the bare hostname (no scheme, no port).
    """

scheme = System.get_env("PHX_SCHEME", "https")
url_port = String.to_integer(System.get_env("PHX_PORT", "443"))

# prod always serves; dev/test keep the PHX_SERVER gate so `mix test`
# doesn't boot the endpoint (see Symptom 1)
if config_env() == :prod or System.get_env("PHX_SERVER") do
  config :MyApp, MyAppWeb.Endpoint, server: true
end

config :MyApp, MyAppWeb.Endpoint,
  url: [host: host, port: url_port, scheme: scheme],
  http: [ip: {0, 0, 0, 0, 0, 0, 0, 0}]
```

`config/prod.exs`:
```elixir
endpoint_config =
  if System.get_env("DISABLE_FORCE_SSL") == "1" do
    []
  else
    [force_ssl: [rewrite_on: [:x_forwarded_proto], exclude: [hosts: ["localhost", "127.0.0.1"]]]]
  end

config :MyApp, MyAppWeb.Endpoint, endpoint_config
```

PaaS env vars (Coolify / Railpack / Fly / Render):
- **Build env:** `DISABLE_FORCE_SSL=1` (rebuild required for it to take effect)
- **Runtime env:**
  ```
  PHX_HOST=local-apps.vpn.cloud
  PHX_PORT=5000
  PHX_SCHEME=http
  PORT=5000
  ```

## Verifying the release is healthy

After rebuilding, smoke test locally before pushing:

```bash
rm -rf _build/prod
MIX_ENV=prod mix release
DATABASE_URL=ecto://nope:nope@127.0.0.1:1/nope \
  SECRET_KEY_BASE=*** \
  _build/prod/rel/<app>/bin/<app> eval "IO.puts(:ok)"
```

If you get `DATABASE_URL is missing`, the runtime config is broken before
the DB ever comes into play. If you get
`could not lookup Ecto repo`, see Symptom 5. If you get
`Connection that looks like TLS received on a clear channel`, see
Symptom 3.
