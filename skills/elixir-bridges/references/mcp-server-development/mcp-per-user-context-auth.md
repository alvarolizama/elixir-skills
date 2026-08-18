# Per-user context auth on MCP Streamable HTTP (worked example)

my_app, Aug 2026. Multi-user context scoping on `POST /api/mcp`. Full working
pattern — adapt the module/alias names to your app.

Domain facts this relies on:
- `my_app.Auth.api_token()` = legacy global admin token from env, and
  `my_app.Auth.default_context_slug()` = app default.
- `my_app.Accounts.valid_token?/1` returns `{:ok, user}` (Ecto `User` with the
  `contexts` `has_many through` association preloaded) or `:error`.
- `my_app.Brain.Context` structs carry `.slug`.

## Controller (`DranWeb.API.MCPController`)

```elixir
def handle_post(conn, _params) do
  with {:ok, user} <- authenticate(conn),
       :ok <- validate_context_access(conn, user) do
    process_mcp_request(conn, user)
  else
    {:error, :unauthorized} ->
      conn |> put_resp_header("www-authenticate", "Bearer")
           |> put_resp_content_type("application/json")
           |> send_resp(401, Jason.encode!(%{errors: %{detail: "invalid token"}})) |> halt()
    {:error, :forbidden} ->
      conn |> put_resp_content_type("application/json")
           |> send_resp(403, Jason.encode!(%{errors: %{detail: "access to context denied"}})) |> halt()
  end
end

defp authenticate(conn) do
  case extract_token(conn) do
    {:ok, token} ->
      # Legacy admin token first (backward compat)
      if token == my_app.Auth.api_token() do
        {:ok, %{is_admin: true, email: "admin", contexts: :all}}
      else
        case my_app.Accounts.valid_token?(token) do
          {:ok, user} -> {:ok, user}
          :error -> {:error, :unauthorized}
        end
      end
    :error -> {:error, :unauthorized}
  end
end

defp validate_context_access(conn, user) do
  requested = conn.params["context"] || get_default_context(user)
  if user.is_admin or user_has_context_access?(user, requested), do: :ok, else: {:error, :forbidden}
end

# Admin map has `:all`; real users have the preloaded assoc list. Match both.
defp get_default_context(%{contexts: :all}), do: my_app.Auth.default_context_slug()
defp get_default_context(%{contexts: []}), do: my_app.Auth.default_context_slug()
defp get_default_context(%{contexts: [first | _]}), do: first.slug

defp user_has_context_access?(%{contexts: :all}, _), do: true
defp user_has_context_access?(%{contexts: ctxs}, slug), do: Enum.any?(ctxs, &(&1.slug == slug))
```

Then thread `user` into every `MCP.process_message(msg, user: user)` call
(notifications and requests alike).

## Processing side (`my_app.MCP`)

Keep `process_message(msg)` callers (tests, internal agents) working by adding
an opts default rather than renaming:

```elixir
def process_message(msg, opts \\ []) do
  user = Keyword.get(opts, :user)
  msg = inject_user_context(msg, user)
  case msg do
    %{"jsonrpc" => "2.0", "method" => "tools/call", "id" => id, "params" => params} ->
      tool_name = params["name"]
      args = params["arguments"] || %{}
      result = execute_tool(tool_name, args)
      %{"jsonrpc" => "2.0", "id" => id,
        "result" => %{"content" => [%{"type" => "text", "text" => result}]}}
    # ... other JSON-RPC method clauses unchanged ...
  end
end

defp inject_user_context(msg, nil), do: msg
defp inject_user_context(%{"jsonrpc" => "2.0", "method" => "tools/call", "params" => p} = msg, user)
     when is_map(p) do
  args = p["arguments"] || %{}
  if Map.has_key?(args, "context") do
    msg
  else
    case get_default_context_for_user(user) do
      nil -> msg
      default -> put_in(msg, ["params", "arguments", "context"], default)
    end
  end
end
defp inject_user_context(msg, _user), do: msg

defp get_default_context_for_user(%{is_admin: true}), do: nil
defp get_default_context_for_user(%{contexts: :all}), do: nil
defp get_default_context_for_user(%{contexts: [first | _]}), do: first.slug
defp get_default_context_for_user(_), do: nil
```

## The bug worth remembering

The first cut (from a spec/LLM) injected at `params["context"]`. It compiles
and runs but does nothing: every `execute_tool` clause pattern-matches
`%{"context" => ctx}` on the tool **arguments**, i.e.
`params["arguments"]["context"]`. So a "default context" that was never really
injected is the classic silent no-op — verify by hitting a tool that requires
`context` and confirming it doesn't error with a missing/failure result.

## Verification notes

- Existing `process_message/1` tests (ExUnit calls `call_tool` with an explicit
  `context` arg) still pass untouched because (a) the default arg keeps arity-1
  working, and (b) injection only kicks in for `tools/call` without a `context`
  in args. Run the MCP test file to confirm backward compat.
- My touched modules compiled with zero warnings under
  `—warnings-as-errors`; pre-existing unrelated compile breakage in another
  file is out of scope — confirm your diff is isolated before blaming your code.
