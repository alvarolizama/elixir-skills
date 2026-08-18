# Admin-only route protection in Phoenix (without impersonation)

Proven in my_app (2026-08-02): protecting an existing LiveView route (e.g.
`/settings`) so only users with `is_admin: true` can reach it, plus adding
admin CRUD UI to the page.

## Router: `:admin` pipeline + `require_admin` plug

Add a pipeline and a private plug in `lib/<app>_web/router.ex`:

```elixir
pipeline :admin do
  plug :require_admin
end

# The :user session value is the email (my_app stores email, not :user_id).
# Read whichever key your SessionsController/auth writes.
defp require_admin(conn, _opts) do
  user_email = Plug.Conn.get_session(conn, "user")

  if user_email do
    user = MyApp.Accounts.get_user_by_email(user_email)

    if user && user.is_admin do
      conn
    else
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

Then pull the route OUT of the normal `[:browser, :auth]` scope and give it its
own admin scope (keeps the no-op `pipe_through` clean and obviously gated):

```elixir
scope "/", DranWeb do
  pipe_through [:browser, :auth, :admin]
  live "/settings", SettingsLive, :index
end
```

Notes:
- `put_flash` needs `Phoenix.Controller.put_flash/3` here (no LiveView conn helper).
- `.halt()` matters — without it the live route would still mount.
- Actual enforcement is the plug; hiding the sidebar link is cosmetic and lives
  separately in the layout, not the router (see "scope discipline" below).

## Admin CRUD UI in the gated LiveView

- On `mount`, `assign` the users list, ALL contexts (admin sees every context,
  not just `@current_scope`), and an empty `to_form(%{}, as: :user)` for the
  create form. `my_app.Brain.list_contexts/0` returns everything the admin may
  assign — don't scope it to the current user.
- Membership toggles: a checkbox calling `my_app.Accounts.user_in_context?(user, ctx)`
  on render and dispatching a `toggle_context_user` event that add/removes via
  the accounts context. Re-`assign` the users list after the toggle so the
  users table (with per-user context badges) refreshes.
- Create/delete handlers: call the accounts context (`create_user`, `delete_user`),
  then re-`assign` users + a fresh empty form. For `"context_ids"` from
  multi-select checkboxes, `Map.get(params, "context_ids", []) |> List.wrap()`.

## Scope discipline

The user's `ONLY these files` scope for this task did NOT include the layout
(`lib/<app>_web/components/layouts.ex`), where the Settings sidebar link is
rendered unconditionally. The router plug still enforces access (non-admins get
redirected), so the security guarantee holds; the cosmetic "hide the link for
non-admins" item was flagged as a follow-up rather than silently touching the
out-of-scope file. Respect an explicit scope even when a stated requirement
would otherwise need a file outside it — deliver the in-scope guarantee and
surface the gap.

## Elixir/LiveView gotchas that surfaced building this

1. **Module attributes are compile-time and must be defined textually BEFORE the
   function that references them.** Moving `@brain_keys`/`@advanced_keys` below
   a `handle_event` that uses them yields `incompatible types given to ++:
   nil ++ nil` under `--warnings-as-errors`. Keep such attrs at the top of the
   module, right after aliases.
2. **All `handle_event/3` (and any single-name/arity) clauses must be contiguous.**
   Inserting new `handle_event` clauses next to `mount` while the existing ones
   live lower in the file triggers "clauses with the same name and arity should
   be grouped together". Either insert adjacent to the existing cluster, or move
   intervening private `defp`s so no non-`handle_event` def sits between clauses.
   The grouping error is a hard `--warnings-as-errors` failure.
3. **`CoreComponents.button/1` does NOT accept `type`.** Its `attr :rest, :global,
   include: ~w(href navigate patch method download name value disabled)` omits
   `type`, so `<.button type="submit">` fails the component's allowed-attr check
   under warnings-as-errors. Use a native `<button type="submit" class="btn btn-primary ...">`
   for submit buttons inside a form.
