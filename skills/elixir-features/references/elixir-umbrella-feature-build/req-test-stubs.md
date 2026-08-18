# Stubbing HTTP clients with Req.Test in umbrella apps

## Problem

Business-logic apps use `Req` to call OpenAI-compatible endpoints. Calling real services from tests is slow and flaky. `Req.Test` stubs are the cheapest way to mock these calls, but two things bite umbrella projects:

1. The stub receives a `Plug.Conn` whose `request_path` may or may not include the `base_url` path segment. If `Client.new/2` uses `base_url: "http://localhost:4000/v1"`, a relative `url: "chat/completions"` produces `/v1/chat/completions` at runtime but may produce `/chat/completions` when the test client has no `base_url`.
2. `Req.Test.json(conn, status, body)` does not exist; status is set via `Plug.Conn.put_status/2`.

## Copy-paste stub pattern

```elixir
# test/support/inference_stub.ex or directly in the test setup
Application.put_env(:MyApp, :client_overrides, plug: {Req.Test, :inference_stub})

Req.Test.stub(:inference_stub, fn conn ->
  cond do
    String.ends_with?(conn.request_path, "chat/completions") ->
      Req.Test.json(conn, %{
        "model" => "test-model",
        "choices" => [
          %{"message" => %{"role" => "assistant", "content" => "stubbed"}}
        ],
        "usage" => %{
          "prompt_tokens" => 2,
          "completion_tokens" => 3,
          "total_tokens" => 5
        }
      })

    String.ends_with?(conn.request_path, "models") ->
      Req.Test.json(conn, %{"data" => [%{"id" => "model-a"}, %{"id" => "model-b"}]})

    true ->
      conn
      |> Plug.Conn.put_status(404)
      |> Req.Test.json(%{"error" => "not found"})
  end
end)
```

## Injecting the test client into production code

Give the production client a hook that tests can override without changing call sites:

```elixir
# lib/MyApp/inference/client.ex
def new(agent, opts \\ []) do
  Req.new(
    [
      base_url: agent.api_inference_url,
      headers: [
        {"authorization", "Bearer #{agent.api_inference_token}"},
        {"content-type", "application/json"}
      ]
    ] ++ Application.get_env(:MyApp, :client_overrides, []) ++ opts
  )
end
```

Tests set `Application.put_env(:MyApp, :client_overrides, plug: {Req.Test, :stub})`; production leaves the env empty.

## Verification

```bash
mix test apps/harness
```

If you see `status: 404` from a stub that should match, log `conn.request_path` first. Almost always the path is `"/v1/..."` when the test expected `"..."`.

## Routing stubs: one client, several endpoints AND several chat models

When the code under test triggers MORE than one HTTP call through the same
`Req.Test` stub (e.g. `Brain.create_page` fires `/v1/embeddings` +
`/v1/chat/completions` for the augmenter, while the feature under test fires
its own `/v1/chat/completions` with a different model), a single-purpose stub
breaks: the augmenter's call falls into your feature handler and your asserts
explode (`decoded["model"]` is nil or the wrong value).

Build a **routing stub** that switches on `request_path` AND on the decoded
`"model"` for chat completions:

```elixir
defp routing_stub(extraction_fn) do
  Req.Test.stub(my_app.Inference.Client, fn conn ->
    case conn.request_path do
      "/v1/embeddings" ->
        Req.Test.json(conn, %{
          "object" => "list",
          "data" => [
            %{"object" => "embedding", "index" => 0,
              "embedding" => [0.1 | List.duplicate(0.0, 1023)]}  # never all-zeros, see below
          ]
        })

      "/v1/chat/completions" ->
        {:ok, body, conn} = Plug.Conn.read_body(conn)
        decoded = Jason.decode!(body)

        if decoded["model"] in ["MarkItDown", "Qwen3.6-35B-A3B"] do
          extraction_fn.(conn, decoded)   # your feature assertions live here
        else
          # augmenter/summaries call — answer generically, don't assert
          Req.Test.json(conn, %{
            "choices" => [%{"message" => %{"role" => "assistant", "content" => "{}"}}]
          })
        end

      _ ->
        extraction_fn.(conn, nil)          # e.g. /v1/audio/transcriptions
    end
  end)
end
```

Feature tests then receive `(conn, decoded)` with the body already read:

```elixir
routing_stub(fn conn, decoded ->
  assert decoded["model"] == "MarkItDown"
  Req.Test.json(conn, %{"choices" => [%{"message" => %{"content" => "# Report"}}]})
end)
```

Rules:
- **Read the body ONCE in the router** and pass `decoded` down — a handler
  that calls `Plug.Conn.read_body/1` again gets an empty binary.
- **Answer the augmenter generically** (any model you don't care about) —
  otherwise `Summaries.augment_page` calls poison your feature asserts.
- **`Req.Test.reset/1` does not exist (req 0.6.x)** — do not call it in
  `on_exit`; stubs are process-owned and die with the test process.

## Stubbed LLM turn sequences: `Process.get` counters reset across Tasks (CRITICAL)

When a test scripts a multi-turn LLM conversation by counting calls inside
the Req.Test stub with the process dictionary:

```elixir
# WRONG — breaks when the system under test runs each turn in a Task
count = Process.get(:qa_chat_count, 0)
Process.put(:qa_chat_count, count + 1)
{tool, args} = Enum.at(@chat_sequence, count, List.last(@chat_sequence))
```

…the counter resets to 0 on EVERY LLM turn if the code under test spawns
each turn in a separate process (e.g. an agent engine that runs
`Task.Supervisor.async_nolink` per turn, or a GenServer that delegates the
HTTP call to a Task). The process dictionary is per-process; each Task gets a
fresh one. Symptom: the agent repeats step 1 of the scripted sequence forever,
hits its consecutive-error cap, and the test fails with a session summary like
"stopped after 5 consecutive tool errors and 2 recovery attempts" instead of
`done`.

Fix: hold the counter in cross-process storage.

**Option A — `:counters` (single test module, no named process):**

```elixir
defp chat_counter do
  case :persistent_term.get({__MODULE__, :chat_seq}, nil) do
    nil ->
      ref = :counters.new(1, [])
      :persistent_term.put({__MODULE__, :chat_seq}, ref)
      ref
    ref ->
      ref
  end
end

defp chat_counter_tick do
  ref = chat_counter()
  :counters.add(ref, 1, 1)
  :counters.get(ref, 1) - 1
end

# in setup, reset for test isolation:
setup do
  case :persistent_term.get({__MODULE__, :chat_seq}, nil) do
    nil -> :ok
    ref -> :counters.put(ref, 1, 0)
  end
  :ok
end

# in the stub:
count = chat_counter_tick()
```

**Option B — `Agent` (clearer ownership, multiple related tests):**

```elixir
setup_all do
  {:ok, _pid} = Agent.start_link(fn -> 0 end, name: __MODULE__.ChatSeq)
  :ok
end

# in the stub:
count = Agent.get_and_update(__MODULE__.ChatSeq, fn n -> {n, n + 1} end)
```

Reset the Agent in `setup` (`Agent.update(pid, fn _ -> 0 end)`) so tests
don't leak counts into each other.

**Rule:** any stub state that must survive across LLM turns in an OTP
process tree must NOT live in the process dictionary. This is the stub-side
mirror of the "don't use `Process.get` for cross-turn agent state" rule on
the production side.

## Never stub embeddings with an all-zero vector

`List.duplicate(0.0, 1024)` is a ZERO vector. pgvector's cosine distance
(`<=>`) divides by the vector norm — norm 0 ⇒ `NaN`, and Postgres raises
`division by zero` or returns NaN distances that break `ORDER BY` /
threshold filters in the code under test (it surfaced as agents looping on
mysterious `{:error, ...}` search results). Always stub with a non-zero
vector, e.g. `[0.1 | List.duplicate(0.0, 1023)]`.
