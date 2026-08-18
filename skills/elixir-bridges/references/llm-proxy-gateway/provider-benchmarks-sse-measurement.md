# Provider Benchmarks — SSE Streaming Measurement with Finch

How to measure TTFT, TPS, latency, and token count for LLM providers using
`Finch.stream_while/5` to consume SSE streams from OpenAI-compatible
`/chat/completions` endpoints.

## Architecture

A benchmarks runner sends the same prompt to multiple providers in parallel
via `Task.async_stream/3`, each making a streaming chat completion request.
Measurements are taken with `System.monotonic_time(:millisecond)`.

```
┌─ Task.async_stream ──────────────────────────────────────┐
│                                                          │
│  Target A ──POST /chat/completions (stream=true)──→ Finch │
│             ↓ SSE chunks                                 │
│             measure: TTFT, tokens, total time, TPS        │
│                                                          │
│  Target B ──POST /chat/completions (stream=true)──→ Finch │
│             ↓ SSE chunks                                 │
│             measure: TTFT, tokens, total time, TPS        │
│                                                          │
└──────────────────────────────────────────────────────────┘
        │
        ▼
  Enum.zip(results, targets)  ← single-element 2-tuples!
  Enum.map(fn {{:ok, result}, target} -> ... end)
```

## Measurements

| Metric | How |
|--------|-----|
| **TTFT** (time to first token) | `monotonic_time` at request start → `monotonic_time` when first SSE data chunk with content arrives |
| **Total time** | `monotonic_time` at request start → stream end (`[DONE]` or connection close) |
| **Tokens** | `usage.completion_tokens` from final SSE chunk (with `stream_options: {include_usage: true}`); fallback: count delta chunks |
| **TPS** (tokens/sec) | `tokens / ((total_ms - ttft_ms) / 1000)` — generation throughput excluding initial latency |
| **Latency** | Total end-to-end time |

## Runner pattern

```elixir
def run(targets, prompt, opts \\ []) do
  targets
  |> Task.async_stream(
    fn target -> measure_target(target, prompt, max_tokens, receive_timeout, runs) end,
    timeout: receive_timeout + 10_000,
    on_timeout: :kill_task
  )
  |> Enum.zip(targets)
  |> Enum.map(fn {{:ok, result}, _target} -> result
    {{:exit, :timeout}, target} -> Target.error(target, "Timeout")
    {{:exit, reason}, target} -> Target.error(target, "Crashed: #{inspect(reason)}")
  end)
end
```

## SSE parsing with Finch.stream_while

```elixir
acc = %{
  start_ms: System.monotonic_time(:millisecond),
  ttft_ms: nil,
  first_chunk_at: nil,
  token_count: 0,
  chunk_count: 0,
  usage_tokens: nil,
  done: false,
  buffer: "",
  error: nil
}

Finch.stream_while(request, my_app_gateway.Finch, acc, fn entry, acc ->
  case entry do
    {:status, status} ->
      if status in 200..299, do: {:cont, acc}, else: {:halt, %{acc | error: "HTTP #{status}"}}
    {:headers, _} -> {:cont, acc}
    {:data, data} -> process_sse_data(data, acc)
    {:trailers, _} -> {:cont, acc}
  end
end, receive_timeout: receive_timeout)
```

## Key pitfalls

### 1. `Enum.zip` produces single-element 2-tuples

`Task.async_stream` yields `{:ok, result} | {:exit, reason}`. Zipping with
targets produces `[{{:ok, result}, target}, ...]` — each element is ONE
2-tuple. An `Enum.map` with a 2-arity fn raises `BadArityError`.

```elixir
# BROKEN
|> Enum.map(fn {:ok, r}, target -> r; {:exit, _}, target -> :err end)
# FIXED
|> Enum.map(fn {{:ok, r}, target} -> r; {{:exit, _}, target} -> :err end)
```

### 2. Return type consistency in chained helpers

When chaining `acc = f(acc, chunk); acc = g(acc, chunk)`, ALL clauses of
both `f` and `g` must return the same type. Mixing `{:cont, acc}` in one
clause of `f` with plain `acc` in another causes `BadMapError` when `g`
receives the tuple. The `{:cont, acc}` / `{:halt, acc}` shape is ONLY for
the `Finch.stream_while` reducer fn — not for helper functions called
inside it.

### 3. `stream_options: {include_usage: true}` is required

Without this, the provider's SSE stream won't include a final chunk with
the `usage` object, and token counts fall back to counting delta chunks
(less accurate). Add it to the payload:

```elixir
payload = %{
  "model" => target.model,
  "messages" => [%{"role" => "user", "content" => prompt}],
  "stream" => true,
  "stream_options" => %{"include_usage" => true},
  "max_tokens" => max_tokens
}
```

### 4. Some providers don't support `stream_options`

Providers that don't support `stream_options` will either ignore it or
return an error. The runner should fall back to counting delta chunks
with content when `usage_tokens` is nil.

### 5. TTFT measurement needs the first content chunk

Not all SSE chunks carry content (some are role-only deltas). Measure
TTFT only when a chunk with actual `delta.content` (or
`delta.reasoning_content`) arrives, not on the first SSE event.

```elixir
defp count_delta_tokens(acc, %{"choices" => choices}) when is_list(choices) do
  deltas = Enum.count(choices, fn
    %{"delta" => %{"content" => c}} when is_binary(c) and byte_size(c) > 0 -> true
    %{"delta" => %{"reasoning_content" => r}} when is_binary(r) and byte_size(r) > 0 -> true
    _ -> false
  end)
  %{acc | chunk_count: acc.chunk_count + deltas}  # plain map, NOT {:cont, ...}
end
```
