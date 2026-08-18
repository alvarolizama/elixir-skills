# force_ssl Build-Time Pattern (Phoenix 1.8+)

## The Problem

`force_ssl` is marked **compile-time** by Phoenix's Endpoint module. Setting it
only in `config/runtime.exs` causes a boot-time abort in releases:

```
ERROR! application :my_app has a different value set for path [:force_ssl]
inside key DranWeb.Endpoint during runtime compared to compile time
  * Compile time value was not set
  * Runtime value was set to: [rewrite_on: [:x_forwarded_proto], ...]
```

## The Correct Pattern (MyApp/my_app)

Read the env var in `config/prod.exs` at COMPILE TIME:

```elixir
# config/prod.exs
if System.get_env("DISABLE_FORCE_SSL") != "1" do
  config :MyApp, MyAppWeb.Endpoint,
    force_ssl: [
      rewrite_on: [:x_forwarded_proto],
      exclude: [hosts: ["localhost", "127.0.0.1"]]
    ]
end
```

In `config/runtime.exs`, **DO NOT set force_ssl** — it's compile-time. Only set
`PHX_SCHEME=http` there (for URL generation, not for force_ssl).

## VPN Without HTTPS

Set `DISABLE_FORCE_SSL=1` at BUILD time + `PHX_SCHEME=http` at runtime:

```dockerfile
# Dockerfile
ARG DISABLE_FORCE_SSL=0
ENV DISABLE_FORCE_SSL=${DISABLE_FORCE_SSL}
```

```bash
# Build for VPN:
docker build --build-arg DISABLE_FORCE_SSL=1 -t MyApp .

# Runtime:
PHX_SCHEME=http mix phx.server
```

Or in Coolify: set `DISABLE_FORCE_SSL=1` as a build arg + `PHX_SCHEME=http`
as a runtime env var.

## Key Insight

force_ssl is the ONE config value that is compile-time but looks like it
should be runtime. You CANNOT toggle it without a rebuild. The
`DISABLE_FORCE_SSL` env var is read at compile time by `prod.exs`, so changing
it requires `mix compile` (or a Docker rebuild). This is by design — Phoenix
wants force_ssl baked in at compile time to prevent accidental HTTP exposure.

## Sessions

- my_app: 2026-08-02 — discovered the mismatch when deploying to AlloyDB/GCP.
  Initially fixed with a hardcode (always set), then corrected to match the
  MyApp pattern (conditional on DISABLE_FORCE_SSL).
