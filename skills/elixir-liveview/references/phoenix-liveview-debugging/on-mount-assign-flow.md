# LiveView on_mount Hook Assign Flow Debugging

## The Problem

A value set in an `on_mount` hook (e.g. UserAuth) doesn't persist or reflect in the UI after LiveView events. The assign chain breaks silently when:

1. `on_mount` sets `socket.assigns[:timezone]` from `user.timezone`
2. Event handler updates `socket.assigns[:timezone]` via `assign(:timezone, tz)`
3. BUT the layout/sidebar reads from `@current_scope.timezone` (i.e. `current_user.timezone`)
4. The `<select>` never reflects the change because `current_user` wasn't updated

## The Fix

Event handlers must update BOTH assigns when the UI reads from a nested struct:

```elixir
{:ok, updated_user} = Accounts.update_user_timezone(user, tz)
{:halt,
 socket
 |> Phoenix.Component.assign(:timezone, tz)
 |> Phoenix.Component.assign(:current_user, updated_user)}
```

## Debugging Checklist

1. **Verify DB persistence** — use `mix run -e` to check the value saves and reloads:
   ```elixir
   {:ok, u} = Accounts.update_user_timezone(user, "America/Mexico_City")
   reloaded = Accounts.get_user(u.id)
   # reloaded.timezone should match
   ```

2. **Check which assign the template reads** — search for the assign name in templates vs. event handlers. The layout may read `@current_scope.timezone` while the handler only updates `@timezone`.

3. **Add temporary IO.inspect to the handler** — log the event params, current user state, and update result to see where the chain breaks:
   ```elixir
   IO.inspect({:timezone_event, tz, user && user.timezone}, label: "TZ_EVENT")
   ```

4. **Check user identity** — if multiple users exist in dev DB, verify which one is logged in. The fix may work but the user sees UTC because they're logged in as a different account with default timezone.

## The `<select>` + `selected` Attribute Trap

LiveView does NOT re-render `selected={...}` on `<option>` tags reliably during DOM patches. The `<select>` element keeps its current DOM value. For a timezone/locale selector that must reflect server state:

- **REQUIRED**: Wrap in a `<.form>` with `phx-change` on the form element (NOT on the select itself). A bare `<select phx-change="...">` outside a form does NOT send the event to LiveView.
- Use a `phx-hook` to sync the select value from the server, OR
- Accept that the first render is correct (from DB) and LiveView patches may not update the visual selection — the fix is ensuring the server-side assign chain is correct so refresh shows the right value.

**Wrong (event never fires)**:
```heex
<select phx-change="set-timezone" name="timezone">
  <option value="Etc/UTC" selected={...}>UTC</option>
</select>
```

**Right (event fires correctly)**:
```heex
<.form for={%{}} phx-change="set-timezone">
  <select name="timezone">
    <option value="Etc/UTC" selected={...}>UTC</option>
  </select>
</.form>
```

## Session Example: MyApp Timezone Selector

**Symptom**: User changes timezone in sidebar select, sees times update, but on refresh the select resets to UTC.

**Root cause**: `handle_timezone_event` updated `socket.assigns[:timezone]` but not `socket.assigns[:current_user]`. The layout's `<.timezone_selector current_scope={@current_scope}>` reads `current_scope.timezone`, so the select always rendered the stale value.

**Fix applied** (`user_auth.ex`):

```elixir
# Before
{:ok, _updated_user} ->
  {:halt, Phoenix.Component.assign(socket, :timezone, tz)}

# After
{:ok, updated_user} ->
  {:halt,
   socket
   |> Phoenix.Component.assign(:timezone, tz)
   |> Phoenix.Component.assign(:current_user, updated_user)}
```

**Verification**: `mix run -e` confirmed DB persistence worked. The bug was purely in the LiveView assign chain.
