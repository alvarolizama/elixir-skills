# Elixir functional purity patterns — the seven foot-guns

Symptom: pure-function Elixir modules whose reduce/cond/case logic silently
matches nothing, dedupes the wrong elements, or crashes on edge inputs — plus
ExUnit tests that pass "without crashing" while returning the wrong shape.
These patterns apply when writing a new pure module (no side effects, no
GenServer, no Repo) and its ExUnit test.

## Module skeleton

Always define the wrong-type clause so edge inputs return a sensible default
instead of crashing:

```elixir
defmodule MyApp.Domain.Thing do
  @moduledoc "One-paragraph purpose. State spec-relevant decisions (units, returns)."

  @type input :: [map()]
  @type output :: [map()]

  @doc "Short behavior summary."
  @spec transform(input) :: output
  def transform(input) when is_list(input), do: # ...

  def transform(_), do: []   # required wrong-type clause
end
```

## The seven foot-guns

### 1. Pin on a tuple doesn't compare tuple elements

`case key do {:tool, ^last_dedup_key} -> ...` binds the SECOND element of the
pattern to `last_dedup_key` and compares it against the whole `{:tool, "foo"}`
— never equal to the string `"foo"`. Compare whole tuples:

```elixir
cond do
  match?({:tool, _}, key) and key == last_dedup_key -> {acc, last_dedup_key}
  true -> {[msg | acc], key}
end
```

### 2. `nil` sentinel collides with a `{:tag, nil}` payload

Initializing an accumulator sentinel as `nil`, then `key == last`, silently
drops the first `{:tool, nil}` message. Use an atom that payload shapes can't
produce:

```elixir
Enum.reduce(messages, {[], :none}, &reduce_message/2)
```

If only BINARY content should dedupe, add a content guard:

```elixir
defp dedup_key(%{"content" => c}) when is_binary(c), do: {:tool, c}
defp dedup_key(_), do: :keep
```

### 3. `Enum.uniq_by` collapses non-string content

Two messages with missing/nil/list `content` all map to the same key and one
gets dropped. Dedupe only against string content; keep non-string messages
unconditionally (hand-rolled `Enum.reduce` matching on `is_binary(content)`).

### 4. Reverse-then-rebuild order bugs blame the wrong thing

`Enum.reverse |> reduce |> elem(0) |> Enum.reverse` is fine IF the reducer is
correct. When output is reversed or duplicated, the bug is in the reducer, not
the reverses. Trace the reducer first; never add a third reverse.

### 5. Guard `in` with a variable won't compile

`defp f(..., disabled) when type in disabled` → compile error: a guard `in`
needs a compile-time list/range. Move membership to the body with `if`. Keep
literal guards (`nil`, `""`) — those are fine.

### 6. `Map.get(map, key, default)` returns `nil` when the key EXISTS with a nil value

The default only fires on ABSENT keys — a response like
`%{"content" => nil, "model" => "..."}` returns `nil`, then `String.trim(nil)`
crashes. For "nil-or-empty → use default," pattern match with a guard:

```elixir
case MyApp.Inference.chat(payload) do
  {:ok, %{"content" => c}} when is_binary(c) and c != "" -> String.trim(c)
  _ -> fallback_value()
end
```

or `content = message["content"] || ""` (`||` also catches `false` — only use
for non-boolean fields).

### 7. Helper returns `{:cont, acc}` but the chain expects a plain `acc`

The `{:cont, acc}`/`{:halt, acc}` protocol belongs ONLY at the
`stream_while` callback boundary. Helpers called INSIDE the callback must
return plain values — if any clause wraps in a tuple, the next chain step gets
a non-map (`BadMapError`). Audit every `defp` called from a stream callback.

## Standard dedup-with-state pattern

Keep the first of N consecutive identical elements, preserve order:

```elixir
def dedup_consecutive(messages, key_fn) do
  {reversed, _} =
    Enum.reduce(messages, {[], :none}, fn msg, {acc, last} ->
      key = key_fn.(msg)
      cond do
        match?({:tool, _}, key) and key == last -> {acc, last}
        true -> {[msg | acc], key}
      end
    end)

  Enum.reverse(reversed)
end
```

## Edge-case test matrix

Every pure-function module with list-in/list-out wants these, in order:

| # | Test | Why |
|---|------|-----|
| 1 | empty list → empty list | guards the `when is_list` clause |
| 2 | all non-matching → identity | proves the no-op baseline |
| 3 | mixed input with the transform target in the middle | proves order preservation |
| 4 | two consecutive duplicate targets → one survives | proves the dedup core |
| 5 | two NON-consecutive identical targets → both survive | proves "consecutive" semantics |
| 6 | boundary case (exactly N chars, exactly N+1) | proves the threshold is inclusive |
| 7 | nil content / missing key → no crash | guards `Map.get` access |
| 8 | non-string content (list of parts) → untouched | guards the `is_binary` branch |

## Symptom table

| Symptom | Likely pitfall | Fix |
|---------|----------------|-----|
| Dedup silently drops first element | #2 nil sentinel | `:none` sentinel + content guard |
| Dedup never matches any pair | #1 pin on tuple 2nd elem | match whole tuple `key == last` |
| Non-string content collapsed | #3 `Enum.uniq_by` over nil | dedup against string content only |
| Output reversed | #4 buggy reducer | trace reducer, not reverses |
| `unused def` on 2nd compile | leftover private helper | delete helper, recompile |
| Compile error guard `in` variable | #5 | move check to `if` in body |
| `String.trim(nil)` / wrong default | #6 `Map.get` nil-value | pattern match with `is_binary` guard |
| `BadMapError` in stream callback | #7 helper wraps tuple | helpers return plain `acc` |

## Verification

```bash
mix compile --warnings-as-errors   # exit 0, zero output — catches unused helpers
mix test test/<path>/<file>_test.exs --seed 0
mix test                            # full suite — no regressions
```

Anti-patterns: assert the output value for nil/missing cases (often the input
unchanged), not just "no crash"; don't add `@spec` and forget the wrong-type
clause; don't skip `mix compile --warnings-as-errors` between edits — the
unused-fn warning only appears on the second compile; don't `String.length/1`
strings that may exceed tens of thousands of chars — use `byte_size/1`; don't
log inside a pure function — split pure transform + thin impure wrapper.