# 403 Forbidden on POST /login in prod — session cookie + CSRF origin check

Observed on MyApp (Phoenix 1.8, Coolify, dual access: plain HTTP over VPN at `http://local-apps.vpn.cloud:4001` **and** HTTPS via the Coolify proxy at `https://local-apps.vpn.cloud`).

## Symptom

- GET /login renders fine.
- POST /login (correct credentials) returns **403 Forbidden** and the browser lands back on /login.
- No controller log line — the request dies in the `:browser` pipeline before `SessionController.create` runs. That absence is the tell: it's a plug-level rejection (CSRF/session), not auth.

## Root cause 1: `secure: true` session cookie on HTTP

`lib/<app>_web/endpoint.ex`:

```elixir
@session_options [
  store: :cookie,
  secure: true,   # <-- browser drops the cookie on http:// deploys
  ...
]
```

With `secure: true`, the browser never sends `_my_app_key` over plain HTTP. The POST then has no session, so `protect_from_forgery` can't validate the CSRF token → 403. The cookie is already encrypted+signed, so `secure: false` is an acceptable default for HTTP-capable deploys:

```elixir
secure: System.get_env("SESSION_COOKIE_SECURE") in ~w(true 1)  # default false
```

`@session_options` is a module attribute — changing it needs recompile (a release rebuild does this anyway). Note it's ALSO referenced by the `/live` socket `connect_info` — one attribute, both paths.

## Root cause 2: origin mismatch on dual-access

`protect_from_forgery` compares the POST's `Origin` header against the endpoint's `url:` config. Config says `http://host:4001`; the HTTPS browser sends `Origin: https://host` → mismatch → 403. The reverse also fails (config https, VPN browser sends http origin).

Fix in `config/runtime.exs` (prod block):

```elixir
check_origin =
  case System.get_env("CHECK_ORIGINS") do
    nil -> true
    "" -> true
    origins -> String.split(origins, ",", trim: true)
  end

config :MyApp, MyAppWeb.Endpoint,
  url: [host: host, port: url_port, scheme: scheme],
  check_origin: check_origin,
  ...
```

Coolify env for the dual-access case:

```
CHECK_ORIGINS=http://local-apps.vpn.cloud:4001,https://local-apps.vpn.cloud
```

Format: bare `scheme://host:port` per origin, comma-separated, no paths/trailing slashes. Unset = Phoenix default (check against configured `url:`).

## Working prod env for this topology (verified)

```
PORT=4001                 # Bandit listens here
PHX_HOST=local-apps.vpn.cloud
PHX_PORT=4001             # URL-generation port (matches VPN access)
PHX_SCHEME=http           # URLs generated as http (VPN is primary)
ECTO_SSL=false            # DB without TLS
CHECK_ORIGINS=http://local-apps.vpn.cloud:4001,https://local-apps.vpn.cloud
# SESSION_COOKIE_SECURE unset (default false)
```

Trade-off: HTTPS access works for browsing and POSTs (origin allow-listed), but generated absolute URLs (emails, redirects) use the `url:` scheme/host/port — pick the one your users primarily hit.

## Adjacent trap from the same incident

Same deploy also had the Postgres TLS boot loop (`bad_certificate selfsigned_peer` → `Release.create` dies with "killed") — covered in `ecto-ssl-selfsigned.md`. When several "security hardening" commits land together, expect this cluster: DB SSL verify, session cookie secure, origin check. Debug them independently — fixing one does not fix the others.
