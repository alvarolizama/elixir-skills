# Google OAuth Over VPN (HTTP)

## Problem

Google OAuth **requires HTTPS** for redirect URIs (except `localhost`). When a
Phoenix app is served over plain HTTP on a VPN tunnel (WireGuard, NetBird),
the default `GOOGLE_REDIRECT_URI` derived from `DranWeb.Endpoint.url()` will
be `http://...` — Google rejects it with "redirect_uri_mismatch".

The `PHX_SCHEME=http` env var (used to disable `force_ssl` for VPN) also
changes `Endpoint.url()` to return `http://...`, which breaks OAuth.

## Solution

Set `GOOGLE_REDIRECT_URI` explicitly to the **public HTTPS domain**:

```bash
# Runtime env vars for VPN deployment:
PHX_SCHEME=http                    # Disable HTTPS redirect, use HTTP URLs
GOOGLE_REDIRECT_URI=https://my_app.example.com/auth/google/callback  # HTTPS!
```

This way:
- The app serves over HTTP (VPN, no TLS terminator)
- URL generation uses http:// for internal links
- OAuth redirect goes to the public HTTPS domain (wherever TLS terminates)

## Where This Lives in Code

In `DranWeb.OAuth.Google.redirect_uri/0`:

```elixir
def redirect_uri do
  System.get_env("GOOGLE_REDIRECT_URI") ||
    DranWeb.Endpoint.url() <> "/auth/google/callback"
end
```

The env var override takes priority over the auto-derived URL.

## MyApp Comparison

MyApp does NOT have Google OAuth — it uses session-based auth only
(username/password via env vars). No OAuth redirect_uri issues there.

The `force_ssl` BUILD-time pattern (`DISABLE_FORCE_SSL=1`) is shared between
both projects and is documented in `references/force-ssl-build-time-pattern.md`
under `phoenix-runtime-config-overrides`.

## Key Learning

When deploying a Phoenix app with OAuth over VPN:
1. `DISABLE_FORCE_SSL=1` at build time (prod.exs pattern)
2. `PHX_SCHEME=http` at runtime (URL generation)
3. `GOOGLE_REDIRECT_URI=https://<public-domain>/auth/google/callback` (OAuth)
4. Google Cloud Console must have the HTTPS redirect URI registered

All four are needed. Missing #3 causes the redirect_uri_mismatch error.
