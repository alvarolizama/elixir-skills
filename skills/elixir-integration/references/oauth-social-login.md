# OAuth & Social Login in Phoenix

Distilled patterns for OAuth 2.0 authorization-code login: helper/controller
split, state round-trip, find-or-create vs find-or-link, multi-user
migration, and VPN/redirect pitfalls. Symptom → mechanism → fix →
verification throughout.

## Helper vs controller split

**Symptom.** OAuth flows are untestable: every unit test needs a fake
`conn` because URL building and session handling live in the same function.

**Mechanism.** Controllers are connectors, not logic. When URL/token logic
references `conn`, tests must fabricate the whole request lifecycle to
exercise a pure URL computation.

**Fix.** Pure helper module with NO `conn` dependency:

```elixir
defmodule MyAppWeb.OAuth.Google do
  def authorize_url(state), do: ...          # pure
  def exchange(code, state), do: ...         # Req call, pure args
  def configured?, do: ...                   # checks env
end
```

Controller keeps session/redirect only. Gate BOTH the controller branch
and the login-button template branch behind `configured?/0` — otherwise
one path (e.g. the button) still renders for unconfigured apps.

**Verification.** Unit tests call `Google.authorize_url/1` with a plain
string; no `conn` anywhere. `configured?/0` false → controller redirects,
template hides button (test both).

## CSRF does not cover the OAuth dance

**Symptom.** A cross-site-request-forgery attack swaps the `state` value and
redirects the user through an attacker-chosen account pre-authentication.

**Mechanism.** The OAuth dance is GET-initiated: the `/session` CSRF token
does NOT protect it. If `state` is a static string or reused, an attacker
can replay or forge the callback.

**Fix.**

```elixir
state = :crypto.strong_rand_bytes(32) |> Base.url_encode64(padding: false)
conn = put_session(conn, :oauth_state, state)
# callback:
Plug.Crypto.secure_compare(conn.session["oauth_state"], params["state"])
```

Compare with `Plug.Crypto.secure_compare/2` — NEVER `!=`. Delete the
stored state on success AND on mismatch (a stale value must not be
reusable).

**Verification.**

```bash
grep -rn "secure_compare" lib/ | grep -ci oauth     # >= 1
grep -rn "put_session(:oauth_state" lib/ | wc -l    # >= 1
```

## Redirect URI consistency

**Symptom.** "redirect_uri_mismatch" from the provider in production, but
working locally.

**Mechanism.** Local dev and production compute the redirect URI
differently, or the flow uses a different URI in `authorize` than in
`exchange`.

**Fix.** One `redirect_uri/0` function derives BOTH the authorize and
exchange URIs. Allow an env override (e.g. `OAUTH_REDIRECT_URI`) for
deployments behind a public HTTPS terminator. When the app serves plain
HTTP (VPN), the override must point at the PUBLIC HTTPS domain — browsers
reject the HTTP callback after the provider redirects to HTTPS.

**Verification.** Test assert `authorize_url(state) == expected` given
fixture env; browser walk-through against the VPN deployment succeeds
end-to-end.

## Find-or-create vs find-or-link

**Symptom.** Single-sign-on opens the app to anyone with a provider
account: a stranger's Google login auto-creates an account with full
sign-up privileges.

**Mechanism.** Find-or-create auto-provisions users. For a user-managed
app (admin adds users), that is exactly backwards.

**Fix.** Find-or-LINK (link to an existing user; `{:error, :unauthorized}`
if none). Find-or-create ONLY for open self-sign-up products. When
hardening an existing app: RENAME the resolver so stale call sites fail to
compile, and replace the "creates a user" test with a rejection test:

```elixir
assert {:error, :unauthorized} = login(...)
assert Repo.aggregate(User, :count, :id) == 0
```

## Multi-user migration

**Symptom.** Replacing Google-only login with a real user model breaks
existing sessions or orphanes data.

**Fix.** Migrate in phases:

1. Add the users table with nullable provider columns; backfill.
2. Land identity as a separate association (`user_id`) before dropping
   provider columns — one migration step per dependency.
3. Run the data migration with a dry-run report (`SELECT` counts) reviewed
   before the `UPDATE`.

**Verification.** Post-migration: every provider login resolves to exactly
one user; dry-run counts match production row counts.

## Session renewal on identity change

**Symptom.** After login, the pre-login session id survives — session
fixation: an attacker who fixes the id before login keeps control after.

**Fix.** Every identity change — login, OAuth callback, impersonation
start/stop — calls `configure_session(conn, renew: true)`.

**Verification.** `grep -rn "configure_session(conn, renew: true)" lib/ | wc -l`
≥ number of identity-change code paths.

## VPN / no-TLS redirect pitfalls

**Symptom.** Login works at home, fails from the office VPN with
"redirect_uri_mismatch" or a mixed-content block.

**Mechanism.** The provider registers an HTTPS callback; the VPN serves
plain HTTP, or the app's `scheme`/`host` at request time reflect the
internal address.

**Fix.**

- Force the public scheme: `Phoenix.Endpoint.url/0` breaks under proxies —
  set `url: [scheme: "https", host: ...]` in the endpoint config for the
  deployment, and use `redirect_uri/0` consistently (see above).
- If `port` is part of the URI, make sure dev and prod agree, or omit it.

**Verification.** From the VPN: browser capture shows a single TLS hop and
the callback matches the provider-registered URI exactly.