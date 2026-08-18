# Auth identity → page ownership fields (owner/created_by)

my_app, Aug 2026. How the 3 auth paths resolve to `owner` and `created_by` when
creating pages via MCP, REST API, and web.

## The resolution function

Place in the domain layer (not the web layer) so both MCP and controllers can
call it without a web dependency:

```elixir
# lib/MyApp/auth.ex
def resolve_owner(user) when is_map(user) do
  Map.get(user, :key_name) ||
    case Map.get(user, :email) do
      "api-key:" <> _ = email -> email
      "admin" -> "system"
      email when is_binary(email) -> email
      _ -> "system"
    end
end
def resolve_owner(_), do: "system"

def resolve_created_by(user) when is_map(user) do
  Map.get(user, :key_name) ||
    case Map.get(user, :email) do
      "api-key:" <> _ = email -> email
      "admin" -> "admin"
      email when is_binary(email) -> email
      _ -> "system"
    end
end
def resolve_created_by(_), do: "system"
```

## The 3 auth paths and what identity they carry

| Auth path | Where resolved | Identity | `owner` | `created_by` |
| --- | --- | --- | --- | --- |
| Context API key | `require_api_token` / MCP `authenticate` | `key.name` (the human label set at key creation, e.g. `"chaos-manager"`) | `key.name` | `key.name` (overridable) |
| Per-user token | `Accounts.valid_token?/1` | `%User{}` with `.email` | `user.email` | `user.email` (overridable) |
| Legacy admin | `Auth.api_token()` | `%{email: "admin"}` | `"system"` | `"admin"` |
| Web (session) | `socket.assigns.current_user` | email from login session | `"system"` (always — no API key) | `current_user` (overridable) |

## Don't lose the `key.name` — the original bug

The API key schema (`Accounts.ApiKey`) stores a `name` field (human label set at
creation). But the auth pipeline built a **synthetic user** map that only kept
`email: "api-key:***"` — the `key.name` was loaded from the DB for validation
and then thrown away. Pages created via API key had `owner: "system"` instead
of the key's name.

**Fix:** add `key_name: key.name` to the synthetic user map in both the router's
`require_api_token` plug AND the MCP controller's `authenticate/1`:

```elixir
# router.ex — require_api_token
assign(conn, :user, %{
  is_admin: false,
  email: "api-key:#{key.name}",
  key_name: key.name,   # ← ADD THIS
  contexts: [key.context]
})

# mcp_controller.ex — authenticate
{:ok, %{is_admin: false, email: "api-key:#{key.name}", key_name: key.name, contexts: [key.context]}}
```

## Wiring the 3 creation surfaces

### MCP (`mcp.ex`)

Pass `user` from `process_message` → `execute_tool` → create handlers:

```elixir
# process_message already has user from the controller
result = execute_tool(tool_name, args, user)

# In dran_create_page / dran_create_todo:
owner: Auth.resolve_owner(user),                              # NOT client-settable
created_by: Map.get(args, "created_by", Auth.resolve_created_by(user))  # overridable
```

**Multi-clause default args:** see the `elixir-build-troubleshooting` skill for
the `\\nil` declaration-once pattern — `execute_tool/3` has 18+ clauses and
cannot carry defaults on each.

### REST API (`page_controller.ex`, `todo_controller.ex`)

```elixir
def create(conn, params) do
  user = conn.assigns[:user]
  params =
    params
    |> Map.put_new("owner", MyApp.Auth.resolve_owner(user))
    |> Map.put_new("created_by", MyApp.Auth.resolve_created_by(user))
  # ...
end
```

`Map.put_new/3` respects explicit values from the client — `created_by` is
overridable, `owner` is silently ignored if the client sets it (deliberate:
owner is NOT client-settable). The `Map.put_new` approach means an explicit
`owner` in the JSON body takes effect, but the convention is to NOT pass it.

### Web LiveView (`page_edit.ex`, `page_new_live.ex`)

```elixir
# page_edit.ex — create_page helper
current_user = socket.assigns[:current_user]
page_params =
  page_params
  |> Map.put_new("owner", "system")  # web has no API key — always system
  |> Map.put_new("created_by", if(is_binary(current_user), do: current_user, else: "system"))
```

The web also has `store_file_and_create_page` (upload handler) and
`page_new_live.ex` (new page form) — both need the same wiring. Grep for every
`Brain.create_page` call site in `lib/myapp_web/` to find them all.

### Brain.create_page — the last line of defense

```elixir
# brain.ex — create_page
attrs
|> default_owner_field("owner", "system")        # fills if missing
|> default_owner_field("created_by", "system")    # fills if missing
```

This catches system-internal callers (jobs, curation_agent, graph_rag_agent) that set
their own `owner`/`created_by` explicitly, and falls back to `"system"` for
any path that didn't inject the fields.

## Verification test pattern

```elixir
# Unit tests for the resolver (no DB needed):
test "API key identity -> key.name" do
  user = %{key_name: "chaos-manager", email: "api-key:chaos-manager"}
  assert Auth.resolve_owner(user) == "chaos-manager"
  assert Auth.resolve_created_by(user) == "chaos-manager"
end

test "legacy admin -> system/admin" do
  user = %{email: "admin", is_admin: true}
  assert Auth.resolve_owner(user) == "system"
  assert Auth.resolve_created_by(user) == "admin"
end

# Integration test (needs DataCase + sandbox):
test "MCP create_page with API key assigns key.name as owner" do
  user = %{key_name: "chaos-manager", email: "api-key:...", is_admin: true, contexts: :all}
  # call process_message with tools/call → dran_create_page
  # assert page.owner == "chaos-manager"
  # assert page.created_by == "chaos-manager"
end

test "created_by override is respected, owner is not" do
  # pass created_by: "peer_agent" in args
  # assert page.owner == "peer_agent" (from key_name)
  # assert page.created_by == "peer_agent" (override respected)
end
```

## Updating docs surfaces

When the ownership model changes, update **all 4** surfaces:

1. MCP tool descriptions in `mcp.ex` (`@tools` inputSchema descriptions for
   `owner` and `created_by` in `dran_create_page` and `dran_create_todo`)
2. In-app docs in `docs_live.ex` (the `<:param>` entries shown at `/panel/docs`)
3. `skills/my_app/SKILL.md` — the working rule #6
4. Flow skills (`note-taking-flow`, `research-flow`, `planning-flow`,
   `goal-flow`, `project-flow`) — any code examples showing `owner: "alvaro"`
   should note that `owner` now comes from the API key, not a manual param