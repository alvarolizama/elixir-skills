# LiveView Form and Select Traps

## `<select>` + `phx-change` outside a form = silent failure

A bare `<select phx-change="...">` outside a `<.form>` does **NOT** send the change event to LiveView. The browser fires the DOM event but LiveView's JS bindings don't process it without a form wrapper.

**Wrong (event never reaches the server)**:
```heex
<select phx-change="set-timezone" name="timezone">
  <option value="Etc/UTC">UTC</option>
</select>
```

**Right (event fires correctly)**:
```heex
<.form for={%{}} phx-change="set-timezone">
  <select name="timezone">
    <option value="Etc/UTC">UTC</option>
  </select>
</.form>
```

**Symptoms**: User changes the select, sees no server update, DB value unchanged. The `handle_event` never fires.

**Fix**: Always wrap `<select>` elements that need `phx-change` inside a `<.form>`. The form's `phx-change` attribute carries the event; the select itself does not need `phx-change`.

**Real-world case**: MyApp timezone selector. The `<select id="tz-select" phx-change="set-timezone">` in the sidebar layout was outside any form. Changing the selection appeared to work in the DOM but never persisted. Wrapping it in `<.form for={%{}} phx-change="set-timezone">` made the event fire and the DB update.

## `<select>` + `selected` attribute = unreliable during DOM patches

LiveView does NOT re-render `selected={...}` on `<option>` tags reliably during DOM patches. The `<select>` element keeps its current DOM value. For a timezone/locale selector that must reflect server state:

- Use a `phx-hook` to sync the select value from the server, OR
- Accept that the first render is correct (from DB) and LiveView patches may not update the visual selection — the fix is ensuring the server-side assign chain is correct so refresh shows the right value.

## Event handler must update BOTH assigns when UI reads from nested struct

When the template reads `@current_scope.timezone` (i.e. `current_user.timezone`) but the event handler only updates `socket.assigns[:timezone]`, the UI shows stale data after refresh.

```elixir
# Before — only updates one assign, UI reads from the other
{:ok, _updated_user} ->
  {:halt, Phoenix.Component.assign(socket, :timezone, tz)}

# After — updates both assigns so the layout re-renders with fresh data
{:ok, updated_user} ->
  {:halt,
   socket
   |> Phoenix.Component.assign(:timezone, tz)
   |> Phoenix.Component.assign(:current_user, updated_user)}
```

**Real-world case**: MyApp timezone selector. The handler updated `socket.assigns[:timezone]` but the layout read `@current_scope.timezone`. After the fix, the select reflected the choice immediately and persisted across refresh.

## Debugging checklist

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

5. **Verify the form wrapper** — if the event seems to fire but doesn't, check that `<select>` is actually inside a `<.form>`. The browser console will show the DOM change but no network request to the server.

6. **Rule out stale BEAM code FIRST** — if the UI shows old output after you edited + recompiled (e.g. a tooltip that the new code would render differently), the running dev server may still hold the old module in memory. Probe the live VM with `MIX_ENV=dev mix run -e 'IO.inspect(Keyword.has_key?(MyAppWeb.Layouts.__info__(:functions), :my_new_fn))'`; if `false`, restart the server before any further hypothesis. See `references/stale-beam-code-reload.md`.
