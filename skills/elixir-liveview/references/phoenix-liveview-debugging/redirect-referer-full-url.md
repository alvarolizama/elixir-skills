# `redirect(to:)` crashes on the Referer header — it's a full URL, not a path

From the my_app multi-user auth session: the "switch context" action crashed with

```text
** (ArgumentError) the :to option in redirect expects a path but was "http://localhost:4000/notes"
```

## Cause

The `Referer` request header is always a **full absolute URL** (`http://localhost:4000/notes?context=work`), but `Phoenix.Controller.redirect(to:)` only accepts a **path** (`/notes?context=work`). Passing the raw header straight in crashes.

```elixir
# WRONG — Referer is a full URL, redirect(to:) wants a path
redirect(conn, to: get_req_header(conn, "referer") |> List.first() || ~p"/notes")
```

## Fix — extract path + query with `URI.parse`

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

redirect(conn, to: referer_path(conn))
```

## Security note

This bug usually surfaces in context/switch/redirect-back actions that also need an **access check**. Validate the target resource (the context exists AND the session user is allowed to see it) *before* redirecting, so a crafted Referer + switch can't leave the session pointing at a forbidden or nonexistent context:

```elixir
def switch_context(conn, %{"context_slug" => slug}) do
  user = get_session(conn, "user") |> then(& &1 && my_app.Accounts.get_user_by_email(&1))
  accessible = if user && not user.is_admin, do: my_app.Accounts.list_user_contexts(user) |> Enum.map(& &1.slug), else: :all
  context = my_app.Brain.get_context_by_slug(slug)

  cond do
    is_nil(context) ->
      conn |> put_flash(:error, "Unknown context") |> redirect(to: ~p"/notes")
    accessible != :all and slug not in accessible ->
      conn |> put_flash(:error, "You don't have access to that context") |> redirect(to: ~p"/notes")
    true ->
      conn |> SessionAuth.put_context(slug) |> redirect(to: referer_path(conn))
  end
end
```
