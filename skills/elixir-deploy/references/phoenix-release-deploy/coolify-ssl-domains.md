# Coolify SSL/Domains Config Patterns for Phoenix

Verified against MyApp + my_app (Aug 2026). How to wire SSL to Postgres and
domain/TLS handling for Coolify-deployed Phoenix releases.

## DB SSL (Ecto Repo) — runtime.exs pattern

Support three modes via env vars, default matching the target managed PG:

```elixir
maybe_ssl =
  cond do
    System.get_env("ECTO_SSL") in ~w(false 0) ->
      []                                        # local dev / non-SSL PG
    System.get_env("ECTO_SSL_VERIFY") in ~w(true 1) ->
      [ssl: true, ssl_opts: [verify: :verify_peer,
                             cacerts: :public_key.cacerts_get()]]
    true ->
      [ssl: true, ssl_opts: [verify: :verify_none]]  # AlloyDB/Cloud SQL self-signed
  end

config :MyApp, MyApp.Repo, [url: database_url, ...] ++ maybe_ssl
```

- `verify: :verify_none` default is CORRECT for AlloyDB/Cloud SQL (self-signed
  certs not in system CA bundle). For RDS/Supabase with CA-valid certs, the
  operator opts into `ECTO_SSL_VERIFY=true`.
- `ssl: true` also works via the `DATABASE_URL` query param (`?ssl=true`) but
  explicit opts give control over verification.
- Do NOT leave `# ssl: true` commented out in runtime.exs (my_app had this) —
  that means no SSL in prod silently.

## Domain / force_ssl — the compile-time trap

`force_ssl` is `compile_env` in Phoenix: it CANNOT be changed at runtime.
Two workable patterns:

1. **Build ARG (MyApp)** — `ARG DISABLE_FORCE_SSL="1"` in the Dockerfile,
   `if System.get_env("DISABLE_FORCE_SSL") != "1"` guard in prod.exs.
   Changing it requires a rebuild. Coolify exposes build args in its UI.
2. **Runtime conditional (my_app)** — compute `force_ssl_opts` in runtime.exs
   from `PHX_SCHEME` + `DISABLE_FORCE_SSL`, apply via
   `if opts != [], do: config(:MyApp, MyappWeb.Endpoint, opts)`. Keep
   prod.exs free of force_ssl. Test that the endpoint picks it up.

Recommendation: prefer pattern 2 for apps that flip between HTTPS-public and
plain-HTTP-behind-VPN (NetBird/Wireguard) — no rebuild to switch.

## Dockerfile ARG vs ENV for deploy toggles

If a toggle should be changeable from the Coolify UI WITHOUT rebuild, it must
be `ENV`, not `ARG`:

```dockerfile
# ARG  = build-time only, frozen into the image
# ENV  = runtime, overridable in Coolify env settings
ENV DISABLE_FORCE_SSL="1"
```

Caveat: `ENV` only helps if the config reading it is runtime (pattern 2
above). If prod.exs reads it at compile time, `ENV` in the runtime stage is
invisible to the already-compiled config — pair them correctly.

## Session cookie salts — fail closed in prod

Never ship hardcoded fallback salts in endpoint.ex:

```elixir
# BAD — every deploy that forgets the env var shares the repo's public salts
signing_salt: System.get_env("SESSION_SIGNING_SALT", "TwS/TtVu")

# GOOD — same fail-closed pattern as SECRET_KEY_BASE
signing_salt: System.get_env("SESSION_SIGNING_SALT") ||
  raise("SESSION_SIGNING_SALT is missing")
```

Applies to `SESSION_ENCRYPTION_SALT` too. Full hardened set: signing_salt +
encryption_salt (encrypted, not just signed) + `same_site: "Lax"` +
`http_only: true` + `max_age` (8h typical) + `secure` flag behind a
`SESSION_COOKIE_SECURE` env toggle (unset = secure only on HTTPS requests, so
plain-HTTP VPN deploys keep working).

## check_origin for multi-origin deploys

When the app is served from more than one scheme/host (HTTPS public + plain
HTTP over VPN), Phoenix's CSRF origin check 403s logins. Wire a
comma-separated `CHECK_ORIGINS` env var in runtime.exs:

```elixir
check_origin_config =
  case System.get_env("CHECK_ORIGINS") do
    nil -> []
    "" -> []
    origins -> [check_origin: String.split(origins, ",", trim: true)]
  end
config :MyApp, MyappWeb.Endpoint, [...] ++ check_origin_config
```

Unset = Phoenix default (check against configured url). Document it: the
symptom is "403 on POST /login only on the secondary origin".

## Coolify env-var checklist (put in the app README)

DATABASE_URL, PHX_HOST, PHX_SCHEME (https default / http for VPN),
SECRET_KEY_BASE, SESSION_SIGNING_SALT, SESSION_ENCRYPTION_SALT,
SESSION_COOKIE_SECURE=true, ECTO_SSL (+ ECTO_SSL_VERIFY when CA-valid cert),
CHECK_ORIGINS, POOL_SIZE. Build args: DISABLE_FORCE_SSL only when using
pattern 1.
