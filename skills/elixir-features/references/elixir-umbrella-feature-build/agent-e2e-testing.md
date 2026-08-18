# E2E testing my_app agent flows with Req.Test stubs

How to test a full agent tool-call sequence (`list_orphans → get_page →
propose_relation → done`) without running the async `Engine.run` loop —
which is hard to test because of sandbox ownership and timing.

This reference covers the pattern used in
`test/my_app/agent/link_gardener_agent_test.exs` (Task 6.3: Link Gardener agent).

## When to use this pattern

- You built a new `my_app.Agent.*` module implementing the
  `my_app.Agent.Engine.Behaviour` and want to verify the full tool-call
  sequence end-to-end.
- You want to stub the LLM (`Inference.chat`) to return scripted tool
  calls, then feed them through the agent's `execute_tool/3` and verify
  DB side-effects.
- Running the real `Engine.run` loop is too fragile (async task, sandbox
  ownership, timing).

## The problem with testing `Engine.run` directly

`Engine.run/4` spawns an async task via `Task.Supervisor.start_child/3`.
That task runs the ReAct loop, calling `Inference.chat` (HTTP) and
`execute_tool/3` (DB). Two issues make it hard to test:

1. **Sandbox ownership:** the async task is a separate process. With
   `async: false` + `shared: true` sandbox, the task CAN access the DB,
   but if the task crashes or the LLM stub returns an unexpected shape,
   the session is marked "failed" and debugging is harder.

2. **Sequential LLM responses:** the engine calls `Inference.chat` once
   per step. Each call must return a different tool call. The stub needs
   a counter that works across processes — the process dictionary does
   NOT work because `Task.Supervisor.async_nolink` spawns a new process.

## The solution: test `execute_tool/3` in sequence with a stubbed LLM

Instead of driving `Engine.run`, call `Inference.chat` (stubbed) to get
the next scripted tool call, then feed it directly to the agent's
`execute_tool/3`. This tests the same code path the engine's
`single_turn/1` takes, without the async/timing complexity.

### Step 1: Create pages BEFORE enabling inference

`Brain.create_page/1` triggers `PageAugmenter.schedule/1`, which checks
`Inference.enabled?()`. If inference is enabled, it spawns an async task
(or runs synchronously) that tries to access the DB. The async task loses
sandbox ownership → `DBConnection.OwnershipError`.

**Fix:** create all test pages with inference DISABLED (the default in
tests — `Application.get_env(:my_app, :inference)` is `nil`). Then enable
inference with the `Req.Test` stub right before the tool-call sequence.

```elixir
test "list_orphans → get_page → propose_relation → done creates a relation" do
  ctx = create_context!()

  # Pages created with inference OFF — PageAugmenter.schedule returns :ignored
  p1 = create_page!(ctx, %{title: "Alpha", slug: "alpha", body: "alpha content"})
  p2 = create_page!(ctx, %{title: "Beta", slug: "beta", body: "beta content"})

  {:ok, _} = Brain.create_relation(%{
    source_id: p1.id, target_id: p2.id, relation_type: "related"
  })

  # NOW enable inference with the stub
  original = Application.get_env(:my_app, :inference)

  Application.put_env(:my_app, :inference,
    base_url: "http://localhost:8000/v1",
    api_key: "test-key",
    chat_model: "Ornith-1.0-9B",
    embedding_model: "Qwen3-Embedding",
    rerank_model: "Qwen3-Reranker",
    markitdown_model: "MarkItDown",
    timeout: 5_000,
    schedule_async: false,          # ← critical
    req_plug: {Req.Test, my_app.Inference.Client}
  )

  on_exit(fn ->
    if is_nil(original),
      do: Application.delete_env(:my_app, :inference),
      else: Application.put_env(:my_app, :inference, original)
  end)
  # ... continue with stub + tool calls
end
```

### Step 2: Stub sequential LLM responses with an Agent counter

The stub must return a different tool call each time it's called. Use an
`Agent.start_link` counter (NOT the process dictionary — the inference
queue runs in the caller process, but it's still cleaner to use an Agent
for shared mutable state across calls):

```elixir
responses = [
  chat_response("call_1", "list_orphans", %{}),
  chat_response("call_2", "get_page", %{"slug" => "alpha"}),
  chat_response("call_3", "propose_relation", %{
    "source_slug" => "beta",
    "target_slug" => "alpha",
    "relation_type" => "supersedes",
    "justification" => "Beta supersedes Alpha per content"
  }),
  chat_response("call_4", "done", %{"summary" => "Proposed 1 relation"})
]

{:ok, counter} = Agent.start_link(fn -> 0 end)

Req.Test.stub(my_app.Inference.Client, fn conn ->
  {:ok, _body, conn} = Plug.Conn.read_body(conn)
  idx = Agent.get_and_update(counter, fn i -> {i, i + 1} end)
  response = chat_completion(Enum.at(responses, idx))
  Req.Test.json(conn, response)
end)
```

### Step 3: Drive the tool-call sequence

Call `Inference.chat` (stubbed) to get the next tool call, extract it,
and feed it to `LinkGardenerAgent.execute_tool/3`:

```elixir
state = LinkGardenerAgent.init_state(session, LinkGardenerAgent, [])

# Step 1: list_orphans
{:ok, msg1} = my_app.Inference.chat(%{"model" => "Ornith-1.0-9B", "messages" => []})
{tool1, args1} = extract_tool_from_message(msg1)
{result1, state} = LinkGardenerAgent.execute_tool(tool1, args1, state)

# Step 2: get_page
{:ok, msg2} = my_app.Inference.chat(%{"model" => "Ornith-1.0-9B", "messages" => []})
{tool2, args2} = extract_tool_from_message(msg2)
{result2, state} = LinkGardenerAgent.execute_tool(tool2, args2, state)

# Step 3: propose_relation
{:ok, msg3} = my_app.Inference.chat(%{"model" => "Ornith-1.0-9B", "messages" => []})
{tool3, args3} = extract_tool_from_message(msg3)
{result3, state} = LinkGardenerAgent.execute_tool(tool3, args3, state)

# Step 4: done
{{:ok, :done}, _state} = LinkGardenerAgent.execute_tool("done", %{}, state)
```

### Step 4: Verify DB side-effects

```elixir
rel = Repo.get_by(Relation,
  source_id: p2.id, target_id: p1.id, relation_type: "supersedes")

assert rel != nil
assert rel.meta["justification"] == "Beta supersedes Alpha per content"
assert rel.meta["proposed_by"] == "link-gardener"
```

## Helper: building a chat completion response with a tool call

The engine's `extract_tool_call/1` expects `message["tool_calls"]` with
`function.name` (string) and `function.arguments` (JSON string). Build
the response accordingly:

```elixir
defp chat_completion(%{"tool_call_id" => id, "tool_name" => name, "args" => args}) do
  %{
    "id" => "chatcmpl-#{id}",
    "object" => "chat.completion",
    "model" => "Ornith-1.0-9B",
    "choices" => [
      %{
        "index" => 0,
        "message" => %{
          "role" => "assistant",
          "content" => "Calling #{name}",
          "tool_calls" => [
            %{
              "id" => id,
              "type" => "function",
              "function" => %{
                "name" => name,
                "arguments" => Jason.encode!(args)
              }
            }
          ]
        },
        "finish_reason" => "tool_calls"
      }
    ],
    "usage" => %{"prompt_tokens" => 10, "completion_tokens" => 10, "total_tokens" => 20}
  }
end

defp extract_tool_from_message(message) do
  [%{"function" => %{"name" => name, "arguments" => args_str}} | _] =
    Map.get(message, "tool_calls", [])
  {:ok, args} = Jason.decode(args_str)
  {name, args}
end
```

## Attaching `meta` to relations created by slug lookup

`Brain.create_relation_by_slugs/4` resolves slugs and creates a
relation, but it does NOT accept a `meta` map. When you need to attach
metadata (e.g. `justification`, `proposed_by`), do the slug lookups
yourself and call `Brain.create_relation/1` with `meta` included:

```elixir
source = Brain.get_page_by_slug(source_slug, context_id)
target = Brain.get_page_by_slug(target_slug, context_id)

meta = %{"justification" => justification, "proposed_by" => "link-gardener"}

Brain.create_relation(%{
  source_id: source.id,
  target_id: target.id,
  relation_type: relation_type,
  meta: meta
})
```

`Brain.create_relation/1` uses `on_conflict: :nothing`, so duplicate
`(source, target, type)` tuples are silently ignored at the SQL level.

## Key differences from the guard unit-testing pattern

| Aspect | Guard unit test (no DB) | E2E flow test (with DB) |
|--------|------------------------|------------------------|
| Test case | `use ExUnit.Case, async: true` | `use my_app.DataCase, async: false` |
| DB sandbox | Not needed | Shared sandbox (`async: false`) |
| Inference | Not configured (disabled) | Enabled with `Req.Test` stub |
| What's tested | Limit/validation guards only | Full tool-call sequence + DB side-effects |
| State | In-memory `%State{}` + `%Session{}` | `init_state/3` + real DB pages |

See `references/my_app-agent-guard-unit-testing.md` for the guard-only pattern.

## Verification gate

```bash
mix test test/my_app/agent/link_gardener_agent_test.exs
```

Must be 14 passed, 0 failed. The E2E test runs in ~20ms because it
never spawns an async task — all tool execution is synchronous in the
test process.
