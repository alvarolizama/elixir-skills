# HEEx Pitfalls — Render-time Crashes

Common HEEx template errors that crash LiveView at render time (500 response)
or on first event handler dispatch.

## 1. `not nil` in disabled attrs → ArgumentError (500 in ~14ms)

`Kernel.not/1` requires a strict boolean. `not nil` raises
`ArgumentError: argument error` at render time.

```heex
<!-- BROKEN: not nil → ArgumentError -->
<select disabled={not @selected_provider_id}>

<!-- FIXED: is_nil/1 -->
<select disabled={is_nil(@selected_provider_id)}>
```

**When it hits:** `mount/3` initializes assigns to `nil`. The first render
(before any event handler fires) evaluates `not nil` → crash. The stack trace
points to an anonymous fn in `render/1` inside the `.html.heex` file.

**Fix:** search ALL templates for `not @` and replace with `is_nil(@...)`:

```
search_files(pattern="not @", path="lib/.../live", target="content")
```

**Real-world case:** my_app_gateway BenchmarksLive — three `<select disabled={not @...}>`
attrs all crashed on mount. Fixed in commit 7b8fb2e.

## 2. `phx-value-*` button sends flat params; form submit sends nested

A `<button phx-click="add" phx-value-foo="1" phx-value-bar="2">` sends:

```elixir
%{"foo" => "1", "bar" => "2", "value" => "add"}
```

— flat. A `<.form phx-submit="add">` with `name="target[foo]"` sends:

```elixir
%{"target" => %{"foo" => "1"}}
```

— nested. If the same `handle_event` must handle both, normalize:

```elixir
def handle_event("add_target", params, socket) do
  target = Map.get(params, "target", params)
  provider_id = target["provider_id"] || ""
  ...
end
```

Pattern-matching `%{"target" => params}` in the head crashes with
`BadArityError` when the button fires (flat params don't match the
`%{"target" => _}` shape).

**Real-world case:** my_app_gateway BenchmarksLive — add button used `phx-value-*`
but handler pattern-matched `%{"target" => params}`. Fixed in commit 64e44e2.

## 3. `Enum.zip` produces single-element 2-tuples

`Enum.zip([{:ok, 1}], [:a])` yields `[{{:ok, 1}, :a}]` — a list of
2-tuples. An `Enum.map` with a 2-arity fn raises `BadArityError` because
each element is ONE tuple (one argument), not two.

```elixir
# BROKEN: 2-arity fn → BadArityError
|> Enum.map(fn {:ok, r}, target -> r; {:exit, _}, target -> :err end)

# FIXED: 1-arity fn with nested pattern match
|> Enum.map(fn {{:ok, r}, target} -> r
  {{:exit, :timeout}, target} -> {:err, target}
  {{:exit, reason}, target} -> {:err, target, reason}
end)
```

**Real-world case:** my_app_gateway Benchmarks.Runner — `Task.async_stream` results
zipped with targets. The `Enum.map` had 2-arity fn heads. Fixed in commit f98a47c.

## 4. Return type consistency when chaining private helpers

When two private functions update the same accumulator in sequence
(`acc = f(acc, chunk); acc = g(acc, chunk)`), ALL clauses of both functions
must return the same type (plain map). Mixing `{:cont, acc}` in one clause
of `f` with plain `acc` in another causes `BadMapError` when `g` receives
the tuple.

```elixir
# BROKEN: count_delta_tokens/2 has two clauses with different return types
defp count_delta_tokens(acc, %{"choices" => choices}) do
  {:cont, %{acc | chunk_count: acc.chunk_count + deltas}}  # ← tuple
end
defp count_delta_tokens(acc, _chunk), do: acc              # ← plain map

# The caller chains: acc = count_delta_tokens(acc, chunk)
#                   acc = extract_usage(acc, chunk)         # ← BadMapError here
#                   {:cont, acc}

# FIXED: both clauses return plain maps
defp count_delta_tokens(acc, %{"choices" => choices}) do
  %{acc | chunk_count: acc.chunk_count + deltas}            # ← plain map
end
defp count_delta_tokens(acc, _chunk), do: acc              # ← plain map
```

The `{:cont, acc}` / `{:halt, acc}` shape is for `Finch.stream_while` reducers
— not for helper functions called *inside* the reducer body.

**Real-world case:** my_app_gateway Benchmarks.Runner — `count_delta_tokens/2`
returned `{:cont, %{...}}` in the choices clause but plain `acc` in the
fallback. `extract_usage/2` then received the tuple and crashed with
`BadMapError`. Fixed in commit 9d8408a.
