# Ecto/Postgrex SSL vs self-signed Postgres certs in prod

Session-specific detail for the `phoenix-release-deploy` skill (Pitfall J).

## The failure signature

Deploy logs on Coolify (single-container Phoenix release, entrypoint runs
`Release.setup/0` → create DB → migrate → seed):

```
[warning] :ssl_opts is deprecated, pass opts to :ssl instead
[notice] TLS :client: In state :wait_cert_cr at ssl_handshake.erl:2247 generated CLIENT ALERT: Fatal - Bad Certificate
 - :selfsigned_peer
[error] Postgrex.Protocol (#PID<0.163.0> ("db_conn_1")) failed to connect:
  ** (DBConnection.ConnectionError) ssl connect: TLS client: ... generated CLIENT ALERT:
  Fatal - Bad Certificate - selfsigned_peer
[entrypoint] running setup (create DB → migrate → seed admin)...
... (loop repeats) ...
** (RuntimeError) failed to create db for MyApp.Repo: "killed"
    (MyApp 0.1.0) lib/MyApp/release.ex:45: anonymous fn/1 in MyApp.Release.create/0
```

Two things that confuse diagnosis:

1. **The DB already exists.** The error `failed to create db ... "killed"` does NOT mean
   `ecto.create` found a conflict — it means the `storage_up` call was killed mid-flight
   because the TCP/TLS connect itself died. No connection = no way to even check whether
   the DB exists. The entrypoint retries in a loop and dies each time.
2. **It worked before.** The trigger was a "security" commit changing the Repo SSL default
   from `verify_none` (or no ssl opts) to `verify_peer` against
   `:public_key.cacerts_get()`. Any prod DB with a self-signed or private-CA cert
   (Coolify Postgres, AlloyDB, Cloud SQL, plain VPS Postgres with default snakeoil certs)
   breaks at the next deploy.

## The offending config (before)

```elixir
# config/runtime.exs, inside `if config_env() == :prod`
maybe_ssl =
  cond do
    System.get_env("ECTO_SSL") in ~w(false 0) ->
      []

    System.get_env("ECTO_SSL_VERIFY") in ~w(false 0) ->
      [ssl: true, ssl_opts: [verify: :verify_none]]

    true ->
      [ssl: true, ssl_opts: [verify: :verify_peer, cacerts: :public_key.cacerts_get()]]
  end
```

`verify_peer` as the DEFAULT is the bug: it demands the server cert chain up to a CA in
the system bundle. Self-signed certs fail with `bad_certificate - selfsigned_peer`.

## The fix (shipped)

Invert the default: encrypted-but-unverified by default, strict verification opt-in.

```elixir
# SSL on by default (AlloyDB/Cloud SQL require it) WITHOUT certificate
# verification — prod databases use self-signed certs, so verifying against
# the system CA bundle breaks the connection. Set ECTO_SSL=false to disable
# SSL entirely for local dev or non-SSL databases, or ECTO_SSL_VERIFY=true
# to opt back into strict verification against the system CA bundle.
maybe_ssl =
  cond do
    System.get_env("ECTO_SSL") in ~w(false 0) ->
      []

    System.get_env("ECTO_SSL_VERIFY") in ~w(true 1) ->
      [ssl: true, ssl_opts: [verify: :verify_peer, cacerts: :public_key.cacerts_get()]]

    true ->
      [ssl: true, ssl_opts: [verify: :verify_none]]
    end
```

Env-var matrix:

| `ECTO_SSL` | `ECTO_SSL_VERIFY` | Result |
|---|---|---|
| unset | unset | SSL on, `verify_none` (default — works with self-signed) |
| `false`/`0` | — | No SSL (local dev DB) |
| unset | `true`/`1` | SSL on, `verify_peer` + system CA bundle (strict) |

Notes:
- `verify_none` still encrypts the wire. It only skips certificate chain validation.
  For DBs on private networks (VPN, docker network, localhost) this is the pragmatic
  default; strict validation matters when the DB is reachable over the public internet.
- If a CA-signed cert is available later (e.g. RDS CA bundle), better than
  `verify_peer` + system bundle is `cacertfile` pointing at the provider's CA cert
  mounted into the container.
- `:ssl_opts is deprecated, pass opts to :ssl instead` warning comes from newer OTP —
  harmless, Postgrex still honors the options. Not the cause of the failure.

## Mitigation without a code change

If the deployed image hard-codes `verify_peer` but has an env escape hatch
(like `ECTO_SSL_VERIFY=false` above), set it in the PaaS env UI and restart — no
rebuild needed. If there's no escape hatch, only a code change + rebuild fixes it;
no runtime env var can override hard-coded `ssl_opts`.
