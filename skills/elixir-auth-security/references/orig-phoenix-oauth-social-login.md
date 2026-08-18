---
name: phoenix-oauth-social-login
description: "Add OAuth 2.0 / social login (Google, GitHub) in Phoenix."
version: 1.0.0
author: Álvaro Lizama
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [phoenix, auth, oauth, social-login, session, req]
    related_skills: [phoenix-admin-impersonation, elixir-functional-purity-patterns]
---

# Phoenix OAuth / Social Login

Add OAuth 2.0 social login (proven with Google) to a Phoenix app: a pure
helper module for the HTTP dance, a controller for the request/callback
flow with CSRF-style `state` validation, conditional UI, and find-or-create
user semantics. Verified working in MyApp (2026-08-02, 475 tests green).

## Architecture: split helper vs controller

Keep the HTTP + URL logic in a pure module (e.g. `DranWeb.OAuth.Google`) and
the session/redirect/flash logic in a controller (`DranWeb.OAuthController`).
The helper has no `conn` dependency, so it's unit-testable without a request.

Helper responsibilities:
- `configured?/0` — true only when `client_id` and `client_secret` are set.
  This gates BOTH the controller branch and the login-UI button.
- `authorize_url(state)` / `exchange_code(code)` / `fetch_userinfo(token)`.
- `redirect_uri/0` — default derived from `DranWeb.Endpoint.url()` so local vs
  prod just works; allow an env override (`GOOGLE_REDIRECT_URI`).

Use `Req` for HTTP (matches Phoenix-project conventions; avoid httpoison/tesla).
Form POST to the token endpoint, GET with a `Bearer` header to userinfo, and
always branch on `req.status` (Req decodes JSON into `req.body`):

```elixir
req = Req.post!(@token_url, form: %{...})
case req.status do
  200 -> {:ok, req.body["access_token"]}
  _   -> {:error, :token_exchange_failed}
end
```

## Controller + routes

Two GET actions, routes in the PUBLIC `:browser` scope BEFORE any
auth-required routes (so the pre-login request can reach them):

```elixir
get "/auth/google", OAuthController, :request
get "/auth/google/callback", OAuthController, :callback
```

- `request/2` — if not configured, flash error + redirect `/login`. Else mint
  a random `state`, store it in the session, redirect externally to authorize.
- `callback/2` — two clauses: one matches `%{"code" => code, "state" => state}`
  and verifies against `get_session(:oauth_state)` BEFORE exchanging; a
  catch-all clause redirects `/login` with a flash. Delete the stored state on
  success and on mismatch.

State generation (CSRF protection for OAuth — the OAuth dance is GET-initiated,
so the `/session` CSRF token does NOT cover it):
```elixir
state = :crypto.strong_rand_bytes(32) |> Base.url_encode64(padding: false)
conn = put_session(conn, :oauth_state, state)
```

`with` chain for the exchange: `exchange_code` → `fetch_userinfo` →
`handle_google_user`, with a catch-all `_ ->` redirecting `/login`.

## User resolution: find-or-create (self-service) vs find-or-link (invite-only)

Pick the resolution policy based on whether the app is open-registration or
admin-managed. Both share steps 1–2; they differ at step 3:

1. by `google_id` → return.
2. else by `email` → attach `google_id`/name/avatar to the existing user.
3. else → **self-service**: `create_user(...)`; **invite-only/admin-managed**:
   return `{:error, :unauthorized}` — DO NOT create.

**Security warning:** auto-provisioning on OAuth login (`find_or_create_from_google`)
is a hole in any app where accounts are supposed to be created only by an admin
(Settings UI, first-run `/setup`, allowlist). Anyone with a Google account walks
in and gets a row + a valid `api_token`. MyApp is invite-only: the resolver is
`Accounts.find_or_link_from_google/1`, unknown users get `{:error, :unauthorized}`,
and the controller flashes `"No account found for <email> — ask an admin to
create one"` then redirects to `/login`. Never auto-create unless the product
explicitly offers open sign-up.

Admin promotion is idempotent and re-run on EVERY login (stays in sync with
env config): if the logged-in email matches `DRAN_ADMIN_EMAIL` and the user
isn't already admin, update `is_admin: true`. Never trust the client to self-
admin; gate on the server-side env value.

After resolving the user, log in via your session helper (e.g.
`Plugs.Auth.login(user.email)`), clear `:return_to`, and redirect to it
(default e.g. `~p"/notes"`).

## Login UI button

Render Google only when configured, as an `<a href={~p"/auth/google"}>` (GET
= no CSRF worry) after a divider. Use the project's `<.icon>` component with a
`hero-*` name (MyApp's CoreComponents maps `hero-*` to a Heroicons span):

```heex
<%= if DranWeb.OAuth.Google.configured?() do %>
  <div class="divider my-4">OR</div>
  <a href={~p"/auth/google"} class="btn btn-outline w-full gap-2">
    <.icon name="hero-globe-alt" class="size-5" />
    Sign in with Google
  </a>
<% end %>
```

## Multi-user migration (adding OAuth to an existing single-user app)

When adding Google OAuth to an app that already has single-user env-var auth
(e.g. `DRAN_USERNAME`/`DRAN_PASSWORD`/`DRAN_API_TOKEN`), the migration path
is additive, not destructive:

1. **Keep the old `Auth` module working** — rename its `@moduledoc` to
   "Deprecated legacy…" but keep every function operational. Existing
   deployments must not break.
2. **New `Accounts` context** — full user CRUD, a Google user resolver
   (`find_or_create_from_google/1` for open registration, or
   `find_or_link_from_google/1` when accounts are admin-created only — see the
   User resolution section above), `valid_token?/1` (returns `{:ok, user}` or
   `:error`), and context-membership functions (`user_in_context?/2`,
   `add_user_to_context/2`).
3. **Admin via env var** — `DRAN_ADMIN_EMAIL` auto-promotes on EVERY login
   (idempotent). Never trust the client; gate on the server-side env value.
4. **One `api_token` per user** — auto-generated on `create_user`, unique
   in DB, grants access to ALL their assigned contexts (not per-context).
   Legacy env `DRAN_API_TOKEN` still works as admin for backward compat.
5. **Auth-gated routes** — `/settings` moves behind a `:admin` pipeline.
   Existing LiveView tests for that route will fail with
   `{:error, {:redirect, %{flash: %{"error" => "Admin access required"}}}}`
   because the test session has no DB user. Fix the SETUP: insert a real
   user whose email matches the session value, with `is_admin: true` for
   admin-gated routes. Use idempotent create-or-fetch to avoid
   `unique_constraint` violations on re-runs.

```elixir
# In test setup for admin-gated routes
case Accounts.get_user_by_email("test_user") do
  nil -> {:ok, _} = Accounts.create_user(%{email: "test_user", is_admin: true})
  _ -> :ok
end
```

6. **Sidebar admin link** — thread `is_admin` through layouts to the sidebar
   component and conditionally render `/settings`. Non-admin users get 403
   on `/settings` and don't see the link.

7. **Legacy admin fallback in auth plugs** — when the app keeps the old
   single-user env-var login (`DRAN_USERNAME`/`DRAN_PASSWORD`) alongside the
   new OAuth, the session user (`"admin"`) has no row in the `users` table.
   A naive `require_admin` plug doing `get_user_by_email("admin")` gets `nil`
   and halts with "Admin access required". Fix: treat a missing DB user as
   full admin (legacy session), matching the layout's behavior:

   ```elixir
   defp require_admin(conn, _opts) do
     user_email = Plug.Conn.get_session(conn, "user")

     if user_email do
       user = MyApp.Accounts.get_user_by_email(user_email)

       cond do
         is_nil(user) -> conn        # legacy session = admin
         user.is_admin -> conn        # DB user admin
         true ->
           conn
           |> Phoenix.Controller.put_flash(:error, "Admin access required")
           |> Phoenix.Controller.redirect(to: ~p"/")
           |> Plug.Conn.halt()
       end
     else
       conn
       |> Phoenix.Controller.redirect(to: ~p"/login")
       |> Plug.Conn.halt()
     end
   end
   ```

   The layout already resolves `is_admin` the same way (nil → true); the
   router plug must match or the sidebar shows Settings but the route 403s.

## Verification

```bash
mix compile --warnings-as-errors && mix test
```

Then run the project's `mix precommit` alias if one exists (usually
`compile --warnings-as-errors` + `deps.unlock --unused` + `format` + `test`),
and `mix format --check-formatted`. If the flow is genuinely OAuth-configured,
smoke-test the real redirect locally.

## Pitfalls

- **`@deprecated` module attribute breaks `mix compile --warnings-as-errors`**
  when the deprecated function has many call sites. Each caller emits a
  deprecation warning, and with dozens of callers you get dozens of warnings
  that fail the build. `@compile {:nowarn_deprecated}` was removed in Elixir
  1.20 (silently ignored), so there is no clean suppression. When migrating a
  legacy auth module (step 1 of the multi-user migration), DON'T use
  `@deprecated` annotations on the old functions — instead rename the
  `@moduledoc` to "Deprecated legacy…" and add `# @deprecated Use MyApp.Accounts…`
  as plain `@doc` comments. The code keeps working with zero warnings and
  future readers still see the deprecation notice.
- OAuth state is NOT covered by the standard `/session` CSRF token — the
  request GET is issued before any login. Always implement the `:oauth_state`
  session round-trip, never trust the callback `state` alone.
- No `is_`-prefixed predicate names: use `configured?/0` per Elixir style.
- Store the exact `redirect_uri` used for authorize at exchange time — Google
  rejects a mismatch; deriving both from the same `redirect_uri/0` avoids the
  classic "redirect_uri mismatch" foot-gun.
- Don't put the OAuth `callback` behind an auth required-plug (chicken-and-
  egg: the user is not logged in yet). Public scope only.
- If `mix precommit` also runs `format`, write well-formatted code so it's a
  no-op — a dirty tree after a clean commit attempt indicates the format step
  rewrote your files.
- **Harden-then-test order**: when flipping an OAuth flow from find-or-create
  to find-or-link, the EXISTING test suite may assert the vulnerable behavior
  (e.g. a test named "creates a new user when neither google_id nor email
  exists"). Replace it with a rejection test that asserts `{:error, :unauthorized}`
  AND `Repo.aggregate(User, :count, :id) == 0` — otherwise CI stays green while
  the hole is open. Rename the function too (not just the logic) so no stale
  call sites compile against the old auto-provisioning name.

## Controller pitfalls (context switching / referer redirects)

Two bugs that show up when building the session/context-switch controller
that pairs with multi-user auth. See `references/controller-referer-and-context-switch.md`:

1. **`redirect(to:)` crashes with the referer header** — `get_req_header(conn, "referer")`
   returns the full URL (`http://localhost:4000/notes`); `redirect(to:)` only
   accepts local paths. Parse with `URI.parse` and extract path+query.
2. **Context switch without access validation** — never write a user-supplied
   slug to the session without checking the context exists AND the user has
   access. Validate before `put_session`.
