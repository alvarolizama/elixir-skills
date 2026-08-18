# New-User Auto-Provisioning (Onboarding)

Applies when a user without any team memberships logs into the dashboard for the first time. The gateway should bootstrap them with a personal team + API key rather than showing an empty/inaccessible state.

## The problem

A freshly registered user (Google OAuth or admin-created) has no teams, no memberships, and no API key. Visiting `/dashboard` showed "No perteneces a ningún equipo todavía" and the user had no way to generate a token — the "Generar clave" button only appears inside a team card, and there were no teams.

## The fix — auto-create in `load_personal_data`

```elixir
# in dashboard_live.ex
defp load_personal_data(socket, user) do
  memberships = Accounts.list_team_members_for_user(user.id)

  # If the user has no teams, auto-create "General" team + API key
  {memberships, socket} =
    if memberships == [] do
      {:ok, team} = Accounts.create_team(%{name: "General"})
      {:ok, member} =
        Accounts.create_team_member(%{
          user_id: user.id,
          team_id: team.id,
          team_role: "user",
          status: "active"
        })
      {:ok, _api_key, new_token} = Accounts.replace_api_key(member)

      {Accounts.list_team_members_for_user(user.id),
       socket |> assign(:new_token, new_token) |> assign(:new_token_team, "General")}
    else
      {memberships, socket}
    end

  # ...rest of load_personal_data builds teams list as usual
end
```

### Key mechanics

- **`socket` must be returned from BOTH branches** of the `if` — the pattern `{memberships, socket} = if ...` requires the else branch to return `{memberships, socket}` (the original socket, unmodified).
- **Re-query via `Accounts.list_team_members_for_user/1`** instead of preloading manually — the function already does `preload [:team, :api_key]`.
- **`replace_api_key/1`** handles both create and replace — it generates the token, hashes it, and either creates a new `ApiKey` record or updates an existing one. Returns `{:ok, api_key, new_token}` where `new_token` is the raw token shown once.
- **The `new_token` assign** triggers the "Nueva clave generada" alert in the template — the user sees the key exactly once.

### Why not in the registration flow

Putting this in `load_personal_data` (called on every `mount`) is intentionally lazy — it only fires when the user actually visits `/dashboard`. This avoids:
- Creating orphan teams for users who never log in
- Coupling the onboarding logic into the OAuth/registration code paths
- Needing a migration to bootstrap existing users

The operation is idempotent: once the user has memberships, the `if memberships == []` branch is never entered again.

### Team name "General"

Hardcoded. Could be parameterized in config if needed, but the single-user personal team name doesn't need localization or customization in practice.

## Test pattern

```elixir
test "user without teams auto-gets General team and API key", %{conn: conn} do
  %{user: user, password: password} = register("user")
  conn = login(conn, user, password)
  {:ok, view, _html} = live(conn, ~p"/dashboard")
  html = render(view)                           # use render(), not live()'s returned html

  assert html =~ "General", "should show General team name"
  assert html =~ "Tus equipos", "should show teams section"
  assert html =~ "Reemplazar", "should show replace key button (auto-created)"
end
```

Critical: `live()` returns the **disconnected render** (static HTML). The auto-created token alert and team card only appear after the connected mount. Use `render(view)` to get the connected render for assertions.

## Sidebar visibility for non-admin users

Once the user has a team and API key, the sidebar must only show sections they can actually access. Admin-only routes in `live_session :admin` must NOT show in the sidebar for regular users, even though the router-level guard already redirects them. Mapping:

| Section | Admin | Regular user |
|---------|-------|-------------|
| Dashboard | ✅ | ✅ |
| Estadísticas | ✅ | ✅ |
| Configuración (Modelos, Proveedores, Usuarios, API Keys) | ✅ | ❌ |
| Acceso (Equipos, Logs) | ✅ | ✅ |
| Monitoreo (Alertas, Créditos) | ✅ | ❌ |

In `layouts.ex`:
```elixir
defp admin?(%{global_role: "admin"}), do: true
defp admin?(_), do: false
```

Wrap Admin-only sections with `:if={admin?(@current_scope)}`. Keep `require_authenticated` sections (Logs, Equipos) unconditionally visible.
