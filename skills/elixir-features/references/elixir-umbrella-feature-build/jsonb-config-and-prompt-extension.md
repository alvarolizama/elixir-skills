# JSONB Config Fields & System Prompt Extension Patterns

Patterns for adding per-agent configuration stored as JSONB maps and for
extending a layered system prompt builder to be runtime-aware.

## 1. JSONB Config Map Fields on a Schema

When an entity needs flexible, nested configuration (e.g. `memory_config`,
`brain_config`, `mcp_config`), store each as a `:map` field with a default:

```elixir
schema "agents" do
  field :memory_config, :map,
    default: %{
      "enabled" => false,
      "message_window" => 30,
      "summary_model" => nil
    }

  field :mcp_config, :map, default: %{"servers" => []}
  # ...
end
```

**Key rules:**
- Use string keys in defaults (`"enabled"` not `:enabled`) — PostgreSQL JSONB
  returns string keys, so mixing atom keys creates a mismatch on read-back.
- Cast the field in `changeset/2` alongside other fields.
- Add a `put_default_map/2` helper to fill defaults when the field arrives as
  `nil` or `%{}` (e.g. from a form that didn't include the field):

```elixir
defp put_default_configs(changeset) do
  changeset
  |> put_default_map(:memory_config, %{"enabled" => false, "message_window" => 30})
  |> put_default_map(:mcp_config, %{"servers" => []})
end

defp put_default_map(changeset, field, default) do
  case get_field(changeset, field) do
    nil -> put_change(changeset, field, default)
    val when val == %{} -> put_change(changeset, field, default)
    _ -> changeset
  end
end
```

## 2. LiveView Toggle Handlers for JSONB Config

For JSONB config toggles in a LiveView, use dedicated `phx-click` handlers
instead of form field binding. The handler reads the current config map,
flips a key, and calls `update_agent` with the whole map:

```elixir
def handle_event("toggle_memory_enabled", _params, socket) do
  config = socket.assigns.agent.memory_config || %{}
  new_enabled = !(config["enabled"] == true)
  update_tool_config(socket, :memory_config, Map.put(config, "enabled", new_enabled))
end

defp update_tool_config(socket, field, new_config) do
  case Agents.update_agent(socket.assigns.agent, %{field => new_config}) do
    {:ok, agent} ->
      {:noreply,
       socket
       |> assign(agent: agent, changeset: Agents.change_agent(agent), save_status: :saved)
       |> tap(fn _ -> Process.send_after(self(), :clear_save_status, 2000) end)}

    {:error, changeset} ->
      {:noreply, assign(socket, changeset: changeset, save_status: :error)}
  end
end
```

**Critical:** Use raw HTML `<input type="checkbox" phx-click="...">` instead of
`<.input field={nil}>` for these toggles. `CoreComponents.input/1` requires a
`Phoenix.HTML.FormField` struct and will emit warnings if `field` is `nil`.

### Tool subtab forms

When a subtab needs its own small form (e.g. "Add MCP server") inside a parent
form, create the sub-form's `Phoenix.HTML.FormField` struct and assign it
manually. LiveView's `<.form>` convenience does **not** create `@form` for you:

```elixir
assigns = assign(assigns, :form, to_form(%{}, as: :server))

~H"""
<.form for={@form} phx-submit="add_mcp_server">
  <.input field={@form[:name]} ... />
</.form>
"""
```

Passing `for={%{} |> to_form(as: :server)}` inline does not make `@form`
available, and `<.input field={@form[:name]}>` will raise `KeyError: key :form`.

### Deep-merge for `phx-change` forms with nested JSONB inputs

When a single `<.form phx-change="auto_save">` contains raw HTML inputs for
nested JSONB config fields (e.g. `name="agent[memory_config][message_window]"`),
the browser sends only the fields that have values. Ecto's `cast/3` **replaces**
the entire map, so `enabled`, `summary_model`, and every other key vanish.

**Fix:** Deep-merge the incoming partial map with the existing config in the
`auto_save` handler before passing to `update_agent`:

```elixir
def handle_event("auto_save", %{"agent" => params}, socket) do
  params = merge_tool_configs(socket.assigns.agent, params)
  # ... proceed with Agents.update_agent(socket.assigns.agent, params)
end

defp merge_tool_configs(agent, params) do
  ~w(memory_config brain_config mcp_config)a
  |> Enum.reduce(params, fn field, acc ->
    incoming = Map.get(params, to_string(field))
    case incoming do
      incoming when is_map(incoming) ->
        existing = Map.get(agent, field) || %{}
        Map.put(acc, to_string(field), deep_merge_maps(existing, incoming))
      _ -> acc
    end
  end)
end

defp deep_merge_maps(existing, incoming) when is_map(existing) and is_map(incoming) do
  Map.merge(existing, incoming, fn _k, v1, v2 ->
    if is_map(v1) and is_map(v2), do: deep_merge_maps(v1, v2), else: v2
  end)
end
defp deep_merge_maps(_existing, incoming), do: incoming
```

**Alternative:** Use dedicated `phx-click` handlers for each toggle (as above)
and avoid binding JSONB config fields to `phx-change` forms entirely. The
toggle-handler approach constructs the full map in the handler, bypassing the
partial-map problem.

## 3. Extending a Layered System Prompt Builder

When evolving a static `build/1` to a runtime-aware `build/2` that accepts
optional context (e.g. a session for memory injection):

```elixir
# Before — static, no runtime context
@spec build(Agent.t()) :: {:ok, String.t()} | {:error, String.t()}
def build(%Agent{} = agent) do
  # ...
end

# After — accepts optional session
@spec build(Agent.t(), Session.t() | nil) :: {:ok, String.t()} | {:error, String.t()}
def build(%Agent{} = agent, session \\ nil) do
  # ...
  parts =
    [
      identity,
      memory_section(agent, session),     # new — nil when disabled
      mcp_servers(agent),                  # was mcp_servers/0, now mcp_servers/1
      # ... rest unchanged
    ]
    |> Enum.reject(&is_nil/1)              # new — drop nil sections
    |> Enum.map(&PromptSecurity.sanitize/1)
  # ...
end
```

**Key rules:**
- Add `session \\ nil` as second arg — existing callers with `build(agent)` still work.
- Use `Enum.reject(&is_nil/1)` before `Enum.map` to drop sections that return `nil`.
- For dynamic MCP servers, pattern-match on `mcp_config["servers"]` being non-empty:
  ```elixir
  defp mcp_servers(%Agent{mcp_config: %{"servers" => servers}})
       when is_list(servers) and servers != [] do
    # dynamic text with server names
  end
  defp mcp_servers(_agent), do: "static fallback text"
  ```
- Update `stable_layer/0` to pass a default-struct agent: `mcp_servers(%Agent{})`.
- Existing tests that call `build(agent)` still pass because the session defaults to `nil`.

### Guard clause trap with Access in function heads

You cannot access a JSONB map inside a function-head guard using `config["enabled"]`:

```elixir
# BAD — compile error: cannot invoke remote function Access.get/2 inside a guard
defp memory_section(%{memory_config: config}, _session)
     when is_map(config) and config["enabled"] == true do
  ...
end
```

**Fix:** Match the map in the head, then move the key check into the body:

```elixir
defp memory_section(%{memory_config: config}, %Session{} = session)
     when is_map(config) do
  if config["enabled"] == true do
    ...
  end
end
```

## 4. Wiring Runtime Context Through the Chat Pipeline

When `build_messages` needs session-level context (memory summary), pass the
session struct instead of just `session_id`:

```elixir
# Before
defp build_messages(agent, session_id, user_message) do
  with {:ok, system_prompt} <- SystemPrompt.build(agent) do
    # ...
  end
end

# After — pass session for memory injection + brain retrieval
defp build_messages(agent, session, user_message) do
  with {:ok, system_prompt} <- SystemPrompt.build(agent, session),
       {:ok, brain_context} <- safe_brain_retrieve(agent, query_text) do
    messages = [Message.system(system_prompt) | history] ++ [Message.user(user_text)]
    messages = maybe_prepend_brain(brain_context, messages)
    {:ok, messages}
  end
end

# Optional retrieval failures must not break chat.
defp safe_brain_retrieve(agent, query) do
  try do
    Harness.Agent.Brain.retrieve(agent, query)
  rescue
    _ -> {:ok, nil}
  catch
    _, _ -> {:ok, nil}
  end
end

# Brain context is prepended as a second system message so it stays close to
# the user query while keeping the identity prompt first.
defp maybe_prepend_brain(nil, messages), do: messages
defp maybe_prepend_brain(context, messages), do: [Message.system(context) | messages]
```

**Key ordering rules:**
1. Identity/system prompt first.
2. Brain context (if any) as a second system message.
3. History messages.
4. Final user message.

**Gotcha:** `list_messages_for_session/1` takes `session_id` (a string), not the
session struct. Use `session.id` when calling it, not `session` directly.

## 5. Resilient Optional Side-Effects in Chat

Any optional pipeline step (memory summarization, vectorization, brain retrieval)
must not break the core chat flow (store user message, run inference, store
assistant message). Wrap fire-and-forget steps:

```elixir
if Memory.enabled?(agent) do
  try do
    Memory.summarize_session(session, agent)
  rescue
    _ -> :ok
  end
end
```

## 6. MCP Tool Descriptors for Chat Completions

Enabled MCP tools are formatted as OpenAI-compatible function descriptors:

```elixir
def for_agent(agent_id) do
  agent_id
  |> Agents.list_mcp_tools_for_agent()
  |> Enum.filter(& &1.enabled)
  |> Enum.map(fn t ->
    %{
      type: "function",
      function: %{
        name: "#{t.server_name}__#{t.tool_name}",
        description: t.description || "",
        parameters: t.input_schema || %{}
      }
    }
  end)
end
```

Pass to `Chat.call/4` with `tools:` and `tool_choice:`:

```elixir
tools = Harness.MCP.Tools.for_agent(agent.id)
Chat.call(client, model, messages,
  steps: agent.steps,
  retries: agent.retries,
  tools: tools,
  tool_choice: if(tools == [], do: nil, else: "auto")
)
```

## 7. MCP Tool Toggle in LiveView — Server Name Passing

MCP discovery returns tools with a simple `name` field (e.g. `"search_repos"`),
not a composite `server/tool` key. The server name must be passed separately.

**Pattern:** Use two `phx-value-*` attributes on the checkbox — one for the tool
name, one for the server name:

```elixir
# In the HEEx template:
<input
  type="checkbox"
  phx-click="toggle_mcp_tool"
  phx-value-name={tool.name}
  phx-value-server={@discovering_server || @discovered_tools_server}
/>

# In the handler:
def handle_event("toggle_mcp_tool", params, socket) do
  tool_name = params["name"]
  server_name = params["server"]
  currently_selected = Map.get(socket.assigns.selected_mcp_tools, tool_name, false)
  new_enabled = !currently_selected

  attrs = %{
    "agent_id" => socket.assigns.agent.id,
    "server_name" => server_name,
    "tool_name" => tool_name,
    "enabled" => new_enabled
  }

  # ... upsert and update selected_mcp_tools assign
end
```

**Gotcha:** `@discovering_server` is set to `nil` after discovery completes.
Store the server name in a separate `discovered_tools_server` assign that
persists so toggles after discovery still have the correct server name:

```elixir
# In discover handler — after successful discovery:
assign(socket,
  discovered_tools: tools,
  selected_mcp_tools: selected_map,
  discovering_server: nil,           # loading spinner stops
  discovered_tools_server: name       # server name persists for toggles
)

# In mount — initialize:
assign(socket, discovered_tools_server: nil, ...)
```

**Never** use `String.split(name, "/", parts: 2)` on tool names — they don't
contain `/` and the pattern match will crash with `MatchError`.
