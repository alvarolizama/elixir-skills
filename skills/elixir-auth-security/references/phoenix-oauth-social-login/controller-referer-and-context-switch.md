# Controller Pitfalls: Context Switching and Referer Redirects

Session detail from my_app multi-user auth work (2026-08-02). Two bugs found
in the `SessionController` that handles context switching.

## Bug 1: `redirect(to:)` crashes with the referer header

**Symptom**: `the :to option in redirect expects a path but was "http://localhost:4000/"`

**Root cause**: `get_req_header(conn, "referer")` returns the FULL URL
(`http://localhost:4000/notes`), but `Phoenix.Controller.redirect(to:)`
only accepts local paths (`/notes`). Passing a full URL raises.

**Fix**: parse the referer with `URI.parse` and extract only path + query:

```elixir
defp referer_path(conn) do
  case get_req_header(conn, "referer") |> List.first() do
    nil ->
      ~p"/notes"

    url ->
      case URI.parse(url) do
        %URI{path: path} when is_binary(path) and path != "" ->
          case URI.parse(url).query do
            nil -> path
            query -> path <> "?" <> query
          end

        _ ->
          ~p"/notes"
      end
  end
end
```

**Why this matters**: any controller that redirects back to the referer
(context switching, locale switching, "back" links) hits this. The fix is
always the same — never pass the raw header value to `redirect(to:)`.

## Bug 2: Context switch without access validation

**Symptom**: `switch_context` stored ANY slug in the session without checking
that the context exists or that the user has access. This left the session
pointing at invalid contexts and caused crashes downstream when LiveViews
tried to load pages from a non-existent context.

**Fix**: validate before writing to session:

```elixir
def switch_context(conn, %{"context_slug" => context_slug}) do
  user_email = get_session(conn, "user")
  user = user_email && my_app.Accounts.get_user_by_email(user_email)

  accessible =
    cond do
      is_nil(user) -> :all
      user.is_admin -> :all
      true -> my_app.Accounts.list_user_contexts(user) |> Enum.map(& &1.slug)
    end

  context = my_app.Brain.get_context_by_slug(context_slug)

  cond do
    is_nil(context) ->
      conn
      |> put_flash(:error, "Unknown context")
      |> redirect(to: ~p"/notes")

    accessible != :all and context_slug not in accessible ->
      conn
      |> put_flash(:error, "You don't have access to that context")
      |> redirect(to: ~p"/notes")

    true ->
      conn
      |> SessionAuth.put_context(context_slug)
      |> redirect(to: referer_path(conn))
  end
end
```

**Rule**: any controller action that writes a user-controlled value into the
session (context, locale, theme) must validate it against what the user
actually has access to. Never trust the form value blindly.
