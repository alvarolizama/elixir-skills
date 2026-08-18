# MCP to OpenAI Agent Bridge

> Converting MCP tool schemas to OpenAI function-calling format for internal agents.

## The Pattern

When an internal Elixir agent (using `Agent.Engine` or similar ReAct loop) needs to call the same tools exposed via MCP, convert the MCP schemas to OpenAI `tool_calls` format instead of maintaining a separate tool list.

## Implementation

### 1. Expose tool_schemas/0 in the MCP module

```elixir
# lib/my_app/mcp.ex
@tools [
  %{"name" => "dran_search", "description" => "...", "inputSchema" => %{...}},
  # ... 17 more tools
]

@doc "Returns the MCP tool schemas list (for conversion to OpenAI format)."
def tool_schemas, do: @tools
```

### 2. Convert in the agent module

```elixir
# lib/my_app/agent/copilot.ex
@impl true
def tools do
  mcp_tools =
    my_app.MCP.tool_schemas()
    |> Enum.map(fn schema ->
      %{
        "type" => "function",
        "function" => %{
          "name" => schema["name"],
          "description" => schema["description"],
          "parameters" => schema["inputSchema"]
        }
      }
    end)

  # Append the engine-required `done` tool
  mcp_tools ++ [done_tool()]
end

defp done_tool do
  %{
    "type" => "function",
    "function" => %{
      "name" => "done",
      "description" => "Finish the session with a summary answer to the user.",
      "parameters" => %{
        "type" => "object",
        "properties" => %{
          "summary" => %{"type" => "string", "description" => "The final answer"}
        },
        "required" => ["summary"]
      }
    }
  }
end
```

### 3. Dispatch via process_message for consistency

```elixir
@impl true
def execute_tool(tool, args, state) do
  # Inject context defaults the MCP expects
  args = inject_context(args, state)

  msg = %{
    "jsonrpc" => "2.0",
    "method" => "tools/call",
    "id" => 1,
    "params" => %{"name" => tool, "arguments" => args}
  }

  case my_app.MCP.process_message(msg) do
    %{"result" => %{"content" => [%{"text" => text} | _]}} ->
      if String.starts_with?(text, "Error:") do
        {{:error, text}, state}
      else
        {{:ok, text}, state}
      end

    %{"error" => %{"message" => reason}} ->
      {{:error, reason}, state}
  end
end
```

## Why This Works

- **Single source of truth**: Add a tool to `@tools` once — both the MCP server and all internal agents get it automatically.
- **Same validation**: `process_message` runs the same arg validation, error formatting, and telemetry as external MCP clients.
- **Context injection**: Internal agents often have implicit context (e.g. the current user's context slug) that external clients pass explicitly. Inject it in the agent's `execute_tool`, keeping the MCP handler pure.
- **The `done` tool is NOT an MCP tool** — it's the agent's control signal to finish the ReAct loop. Append it after conversion.

## Pitfall: execute_tool vs process_message

Calling `MCP.execute_tool/2` directly skips the JSON-RPC envelope validation and error wrapping. Always use `process_message/1` with a proper `tools/call` envelope — it returns the same shape external clients get, including error strings prefixed with `"Error:"`.

## Example: my_app Copilot

The my_app Copilot agent exposes all 18 MCP tools to the LLM via this pattern. The user asks a question in the chat widget → `Chat.Server` starts a `Copilot` agent session → the agent calls `dran_search`, `dran_get_page`, etc. via `process_message` → the `done` tool returns the final answer → the chat widget displays it with source citations.
