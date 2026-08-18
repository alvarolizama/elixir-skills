# User onboarding patterns for LLM proxy/gateway

## Auto-provision team + API key on first login

When a new user without any team memberships visits the dashboard, auto-create a default "General" team with membership and API key:

```elixir
# In the LiveView's load_personal_data/2:
memberships = Accounts.list_team_members_for_user(user.id)

{memberships, socket} =
  if memberships == [] do
    {:ok, team} = Accounts.create_team(%{name: "General"})
    {:ok, member} = Accounts.create_team_member(%{
      user_id: user.id, team_id: team.id,
      team_role: "user", status: "active"
    })
    {:ok, _api_key, new_token} = Accounts.replace_api_key(member)

    {Accounts.list_team_members_for_user(user.id),
     socket |> assign(:new_token, new_token) |> assign(:new_token_team, "General")}
  else
    {memberships, socket}
  end
```

### Why

- Every user needs at least one team + API key to use the proxy
- Without this, a new user sees "No perteneces a ningún equipo todavía" with no way to generate a key
- Admin impersonation then works because the user already has a functional setup

### Important: socket propagation

The `socket = assign(socket, ...)` inside the `if` block creates a LOCAL binding that is lost when the `if` returns only the memberships. Return `{memberships, socket}` as a tuple from both branches instead.

### Role-based sidebar visibility

Links to admin-only pages (`live_session :admin`) must be hidden behind `if admin?(@current_scope)` in the sidebar template. Users without admin role who click the link would get redirected at the router level — it's better to not show the link at all.

```heex
<div :if={admin?(@current_scope)} class="space-y-1">
  <p class="px-3 text-xs font-semibold uppercase tracking-wide text-base-content/40">
    Monitoreo
  </p>
  <.sidebar_link href={~p"/dashboard/alerts"} label="Alertas" icon="hero-bell-alert" />
  <.sidebar_link href={~p"/dashboard/credits"} label="Créditos" icon="hero-banknotes" />
</div>
```
