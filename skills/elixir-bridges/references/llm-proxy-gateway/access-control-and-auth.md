# Access Control & Authentication

## Per-route access control matrix (updated 2026-07)

| Route | Guard | Admin | Manager | User (no team) |
|-------|-------|-------|---------|-----------------|
| `/dashboard` | `require_authenticated` | ✅ all | ✅ managed teams | ✅ sees zeros + empty states |
| `/dashboard/stats` | `require_authenticated` | ✅ all | ✅ managed teams | ✅ sees zeros |
| `/dashboard/stats/models` | `require_authenticated` | ✅ drill-down | ✅ scoped | ✅ sees zeros |
| `/dashboard/stats/teams` | `require_authenticated` | ✅ drill-down | ✅ scoped | ✅ sees zeros |
| `/dashboard/stats/export` | `:browser_auth` (require_authenticated) | ✅ CSV | ✅ scoped CSV | ✅ empty CSV |
| `/dashboard/teams` | `mount` check `global_role == "admin"` | ✅ CRUD | ❌ redirect | ❌ redirect |
| `/dashboard/teams/:id/members` | `mount` check admin or manager of team | ✅ any team | ✅ own teams | ❌ redirect |
| `/dashboard/keys` | `live_session :admin` (`require_admin`) | ✅ all keys | ❌ redirect | ❌ redirect |
| `/dashboard/models` | `live_session :admin` (`require_admin`) | ✅ CRUD | ❌ redirect | ❌ redirect |
| `/dashboard/users` | `live_session :admin` (`require_admin`) | ✅ CRUD | ❌ redirect | ❌ redirect |
| `/dashboard/providers` | `live_session :admin` (`require_admin`) | ✅ CRUD | ❌ redirect | ❌ redirect |
| `/dashboard/logs` | `require_authenticated` | ✅ all | ✅ scoped | ✅ empty |
| `/auth/google` | `:browser` (public) | ✅ | ✅ | ✅ |
| `/auth/google/callback` | `:browser` (public) | ✅ | ✅ | ✅ |

### What changed (2026-07)

**`/dashboard/models` and `/dashboard/keys` moved to `live_session :admin`.**
Previously these were `require_authenticated` with template-level `is_admin`
gating (read-only for non-admins). The user explicitly requested that
non-admins should not be able to access configuration pages or create API
keys. Both routes now live in `live_session :admin` with `require_admin` —
non-admins are redirected to `/dashboard` before the LiveView mounts.

**`/dashboard/users` added** — admin-only CRUD for user management (create,
edit role, reset password, suspend/activate). Also in `live_session :admin`.

### Sidebar conditional rendering

The sidebar "Configuración" section (Modelos, Proveedores, Usuarios, API Keys)
is now wrapped in `:if={admin?(@current_scope)}` — regular users don't even
see the links. The `admin?/1` private function in `Layouts` checks
`global_role == "admin"`. This is a UX nicety, not a security control — the
router-level `live_session :admin` is the real guard.

### Users without teams (auto-provisioned since 2026-07)

When a user without any memberships logs in, `load_personal_data` in `DashboardLive`
auto-creates a **"General" team**, adds the user as a member (`team_role: "user"`,
`status: "active"`), and generates an API key via `Accounts.replace_api_key/1`.
The token is shown once via the `@new_token` alert. See
`references/new-user-auto-provisioning.md`.

After auto-provisioning, the user sees their General team card with budget bars,
a working API key, and can use the proxy. The sidebar shows only:

- Dashboard ✅
- Estadísticas ✅
- Logs ✅
- Equipos ✅

Everything else (Configuración, Monitoreo) is admin-only and invisible.

### Auth guard patterns (three layers)

1. **Router-level (`live_session`)** — `live_session :admin, on_mount: [{UserAuth, :require_admin}]`. Cleanest. Redirects before the LiveView mounts. Use for admin-only routes (providers, teams, users, models, keys).

2. **Mount-level (`mount` guard)** — `if user.global_role != "admin" do redirect... end`. More flexible (can check team_role, team membership). Use when access depends on data (e.g., manager of THIS specific team).

3. **Template-level (`is_admin` assign)** — buttons/forms gated by `@is_admin`. Weakest — the page loads, data is fetched, but action buttons are hidden. Acceptable for read-only views where seeing the data is fine but editing is not.

### Layering recommendation

- **Admin-only (providers, teams, models, keys, users)** → router-level `live_session :admin`
- **Manager-scoped (team members)** → mount-level guard checking team_role
- **Personal (dashboard, stats, logs)** → `require_authenticated` only (data scoping handles the rest)

## Google OAuth (IMPLEMENTED 2026-07)

### Goal

Users who exist in the DB and are active can log in with password OR Google.
New users can auto-register via Google if their email domain is in an
allowlist.

### Schema changes (applied)

```
users table:
  + status, :string, default: "active", null: false   # active | suspended
  + google_id, :string, nullable: true                 # sub claim from Google
  + avatar_url, :string, nullable: true                # Google profile picture

  unique_index(:users, [:google_id])                  # only for users with google_id
```

### User schema changesets

The `User` module gained 4 new changesets:

- `admin_create_changeset/2` — admin creates user: email + name + password + global_role. Validates password complexity (min 12, letter+digit). Hashes password.
- `admin_update_changeset/2` — admin edits: name, global_role, status. Does NOT touch password.
- `reset_password_changeset/2` — admin resets password: validates + hashes new password.
- `google_oauth_changeset/2` — sets google_id, avatar_url, name, email. Does NOT touch password_hash (existing users keep their password).

### OAuth flow (no external libs — uses Req)

```
1. GET /auth/google
   → generate CSRF state, store in session
   → redirect to https://accounts.google.com/o/oauth2/v2/auth?
     client_id=...&redirect_uri=...&response_type=code&
     scope=openid+email+profile&state=<csrf>&prompt=select_account

2. Google redirects to GET /auth/google/callback?code=...&state=...
   → validate state matches session (anti-CSRF)
   → Req.post!(token_url, form: %{code, client_id, client_secret, redirect_uri, grant_type})
   → extract access_token from response
   → Req.get!(userinfo_url, auth: "Bearer #{access_token}")
   → obtain {id (sub), email, name, picture}
   → Accounts.find_or_create_from_google(%{google_id: id, email, name, avatar_url: picture})
   → put_session(:user_id, user.id)
   → redirect /dashboard
```

### `find_or_create_from_google/1` logic (implemented)

```
1. Look up by google_id:
   - Found + active → {:ok, user}
   - Found + suspended → {:error, :suspended}

2. If not found by google_id, look up by email:
   - Found + active → link google_id → {:ok, user}
   - Found + suspended → {:error, :suspended}

3. If not found by either:
   → {:error, :not_found}
   → caller (OAuthController) checks domain allowlist:
     - Domain allowed → Accounts.create_from_google/1 (auto-register, global_role: "user", status: "active", no password_hash)
     - Domain not allowed → redirect to /login with "dominio no autorizado"
```

### `authenticate_user/2` modification (implemented)

Now checks `status == "active"` before password verification:

```elixir
def authenticate_user(email, password) do
  case Repo.get_by(User, email: String.downcase(email)) do
    %User{status: "suspended"} -> {:error, :suspended}
    %User{password_hash: hash} = user when is_binary(hash) ->
      if Bcrypt.verify_pass(password, hash), do: {:ok, user}, else: {:error, :unauthorized}
    _ ->
      Bcrypt.no_user_verify()
      {:error, :unauthorized}
  end
end
```

The `SessionController.create/2` handles three outcomes:
- `{:ok, user}` → session + redirect /dashboard
- `{:error, :suspended}` → flash "Tu cuenta está suspendida. Contacta al administrador." + re-render form
- `{:error, :unauthorized}` → flash "Credenciales inválidas." + re-render form

### Config

```elixir
# config/dev.exs
config :MyApp, :google_oauth,
  client_id: System.get_env("GOOGLE_OAUTH_CLIENT_ID"),
  client_secret: System.get_env("GOOGLE_OAUTH_CLIENT_SECRET"),
  redirect_uri: System.get_env("GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:4000/auth/google/callback"),
  allowed_domains: ["MyApp.local"]

# config/runtime.exs (prod)
config :MyApp, :google_oauth,
  client_id: System.get_env("GOOGLE_OAUTH_CLIENT_ID"),
  client_secret: System.get_env("GOOGLE_OAUTH_CLIENT_SECRET"),
  redirect_uri: System.get_env("GOOGLE_OAUTH_REDIRECT_URI") || "https://#{host}/auth/google/callback",
  allowed_domains: (System.get_env("GOOGLE_OAUTH_ALLOWED_DOMAINS") || "")
    |> String.split(",", trim: true) |> Enum.map(&String.trim/1)
```

When `client_id` / `client_secret` / `redirect_uri` are nil (env vars not
set), `Google.configured?/0` returns false. The OAuth controller redirects
to `/login` with "Inicio de sesión con Google no está configurado." The
button still renders on the login page but does nothing useful.

`allowed_domains: []` or `nil` means ALL domains are allowed (auto-registration
for any Google email). Set a non-empty list to restrict to specific domains.

### Files created/modified

| File | Action |
|------|--------|
| `lib/MyApp/accounts/user.ex` | +status, +google_id, +avatar_url fields, +4 changesets (admin_create, admin_update, reset_password, google_oauth) |
| `lib/MyApp/accounts.ex` | +admin_create_user/1, +admin_update_user/1, +reset_user_password/2, +get_user_by_google_id/1, +find_or_create_from_google/1, +create_from_google/1. Modified authenticate_user/2 (status check) |
| `lib/my_app_web/oauth/google.ex` | NEW: authorize_url/1, exchange_code/1, fetch_userinfo/1, domain_allowed?/1, configured?/0 |
| `lib/my_app_web/controllers/oauth_controller.ex` | NEW: request/2 (redirect to Google), callback/2 (process callback, create session) |
| `lib/my_app_web/controllers/session_controller.ex` | +handle {:error, :suspended} in create/2 |
| `lib/my_app_web/controllers/session_html/new.html.heex` | +botón "Entrar con Google" with divider |
| `lib/my_app_web/router.ex` | +/auth/google, +/auth/google/callback (public), +/dashboard/users (admin) |
| `lib/my_app_web/live/users_live.ex` | NEW: admin CRUD — list, create, edit role, reset password, suspend/activate |
| `lib/my_app_web/components/layouts.ex` | +admin?/1 helper, sidebar "Configuración" section gated by :if={admin?(@current_scope)} |
| `priv/repo/migrations/*_add_user_status_and_google_oauth_fields.exs` | +status, +google_id, +avatar_url, +unique_index |
| `config/dev.exs`, `config/test.exs`, `config/runtime.exs` | +:google_oauth config |

## User management (admin CRUD — IMPLEMENTED 2026-07)

Admin page at `/dashboard/users` (admin-only via `live_session :admin`):

- **List all users** — email, name, role badge, status badge, Google-linked badge, creation date. Uses `stream/3` with `phx-update="stream"` on `<tbody>`.
- **Create user** — form with email, name, password, global_role (user/admin). Validates password complexity (min 12 chars, letter+digit). Uses `admin_create_changeset`.
- **Edit user** — form with name, global_role, status (active/suspended). Uses `admin_update_changeset`. Does NOT touch password.
- **Reset password** — separate form with just password field. Uses `reset_password_changeset`.
- **Suspend/activate** — toggle button. Suspended users cannot login (password or Google). Root admin (env-configured) cannot be suspended — `root_admin?/1` checks against `MY_APP_ADMIN_EMAIL`.

### Root admin protection

The admin user created via seeds (env var `MY_APP_ADMIN_EMAIL`) cannot:
- Be suspended (`toggle_status` handler checks `root_admin?/1`)
- Have its role downgraded (`protect_root_user/2` forces `global_role: "admin"`)

### Stream table gotcha

`<tbody id="users" phx-update="stream">` requires each child `<tr>` to have
an `id` matching the stream entry's ID. Do NOT wrap the table in a
`<div id="users" phx-update="stream">` — the direct children of a
`phx-update="stream"` container must be the stream items themselves. If you
wrap in a div, the `<thead>`, `<table>`, etc. become direct children and
lack IDs, causing an `ArgumentError` at runtime. Put `phx-update="stream"`
on the `<tbody>` directly.

### Form mode pattern

UsersLive uses a single `@form` assign that serves 3 modes (`:create`,
`:edit`, `:reset_password`), tracked by `@form_mode`. The template
conditionally renders the appropriate form card. A `cancel_form` event
clears both assigns. This avoids needing 3 separate form assigns — but
means `handle_event("save_user")` must dispatch on `@form_mode` to call
the right save function.

### Test patterns

- `assert_patch(view)` returns a **string** (the patched path), NOT `{:ok, path}`. The path is URL-encoded: `assert URI.decode(path) =~ "period=30d"`.
- `Phoenix.Flash.get(conn.assigns.flash, :key)` replaces deprecated `get_flash/2`.
- For scoped data tests, assert on a specific element's rendered HTML (`view |> element("#kpi-cost-real") |> render()`) rather than full page HTML — full page HTML may contain session tokens or IDs that match refuted strings.
- Forms with `phx-change` need an `id` attribute — Phoenix LiveView warns about missing form recovery without it.
