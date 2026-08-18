---
name: elixir-functional-purity-patterns
description: "Pure Elixir modules, ExUnit, reduce/pin/sentinel bug fixes"
version: 0.1.0
author: Álvaro Lizama
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [elixir, exunit, pattern-matching, mix, testing, pure-functions]
    related_skills: [hermes-extools, elixir-build-troubleshooting, test-driven-development, systematic-debugging]
---

# Elixir Functional Purity Patterns

Write pure-function Elixir modules with ExUnit tests that compile warning-free and pass first try. Built from Elixir's three common foot-guns: pin-operator semantics, accumulator-sentinel collisions in `Enum.reduce`, and the `unused def` warning that only surfaces after a refactor.

## When to Use

- Adding a new pure-data module (no side effects, no GenServer, no Repo) under `lib/<app>/...`
- Writing the parallel `test/<app>/.../<thing>_test.exs` for it
- A reduce/cond/case pattern is failing to match and you're not sure why
- An "unused function" warning surfaces on the second compile after a refactor
- You need to dedupe consecutive-but-not-identical elements in a list while preserving order
- Choosing between `Enum.uniq_by`, `Enum.reduce`, and a hand-rolled accumulator

## When NOT to Use

- GenServer / Process / supervision work → use `phoenix-liveview-realtime-ui` or `elixir-dev-bridge`
- Mix build failures (lock mismatch, dep resolution) → use `elixir-build-troubleshooting`
- Credo / Dialyzer / Sobelow sweep → use `hermes-extools` (`elixir_credo`, `elixir_dialyzer`, `elixir_sobelow`)
- LiveView template / form work → use the Phoenix umbrella skills
- Phoenix v1.8 / layouts / `<.input>` conventions → follow the `AGENTS.md` block at project root

## Core Workflow

### 1. Discover the project conventions

Before writing a line:

- `cat AGENTS.md | head -200` for the project's Elixir guideline block (most Phoenix repos have one — MyApp's enforces Spanish test descriptions, `<Layouts.app>` in LiveView, etc.).
- Read 1–2 sibling modules to match style: `read_file` a `lib/<app>/<dir>/<sibling>.ex` and its test.
- For Phoenix: confirm `core_components.ex` exports `.input` / `.icon`, `mix.exs` uses Req (not HTTPoison/Tesla).

### 2. Write the module skeleton — `@moduledoc`, `@spec`, then body

```elixir
defmodule MyApp.Domain.Thing do
  @moduledoc """
  One-paragraph purpose. State any spec-relevant decisions (units, returns).
  """

  @type input :: [map()]
  @type output :: [map()]

  @doc "Short behavior summary."
  @spec transform(input) :: output
  def transform(input) when is_list(input) do
    # ...
  end

  def transform(_), do: []
end
```

Always define the wrong-type clause as `def name(_), do: <sensible default>`. ExUnit's edge-case test for nil/non-list will then pass.

### 3. Write the ExUnit test file in matching style

Match the surrounding repo's test description language (English vs Spanish vs mixed). MyApp uses Spanish test descriptions inside `describe "<func>/N"` blocks. Always `async: true`:

```elixir
defmodule MyApp.Domain.ThingTest do
  use ExUnit.Case, async: true

  alias MyApp.Domain.Thing

  describe "transform/1" do
    test "lista vacía devuelve lista vacía" do
      assert Thing.transform([]) == []
    end

    test "caso normal" do
      assert Thing.transform([...]) == [...]
    end
  end
end
```

### 4. Verify clean compile, then tests, then full suite

Run **in this order**, every time, on a pure module addition:

```bash
mix compile --warnings-as-errors   # catches unused aliases, unused private fns
mix test test/<app>/<dir>/<file>_test.exs --seed 0
mix test                           # full suite — no regressions
```

The order matters. `--warnings-as-errors` is run first because a *new* unused-function warning can be introduced by an edit that removes the only caller of a private helper — and it surfaces on this run, not on the prior compile.

### 5. Ad-hoc behavior probe with `mix run --no-start -e`

To probe a pure module's real runtime behavior outside ExUnit (e.g. a quick
verification script), use `--no-start`:

```bash
mix run --no-start -e '
rate = MyApp.KpiHelpers.cache_hit_rate(40, 160)
unless rate == 20.0, do: System.halt(1)
IO.puts("probe OK")
'
```

Without `--no-start`, `mix run` boots the whole app supervision tree (Repo,
GenServers) — in a bare ad-hoc script with no DB env wired, it crashes on boot
before your code runs. ExUnit doesn't have this problem (`Mix.Task.run("app.start")`
is handled by the test harness). Alternative if you DO need the app running:
`mix run -e` normally, or use `test/` with a real DataCase.

**`function_exported?/3` trap in probes**: Elixir loads modules lazily, so in a
`mix run -e` one-liner `function_exported?(MyApp.SomeModule, :fun, 1)` returns
`false` for any module nothing has called yet — even when the function exists
and the app compiled fine. This produces FALSE-NEGATIVE verification output
that looks like your new module is broken. Fix: `Code.ensure_loaded/1` first:

```elixir
{:module, _} = Code.ensure_loaded(MyApp.SomeModule)
function_exported?(MyApp.SomeModule, :fun, 1)  # now true
```

Two more probe traps: (1) `MIX_ENV=test mix run ...` inline may be silently
dropped when the shell session persists env between calls — `export MIX_ENV=test`
in a prior command first. (2) DB probes with `mix run -e` run OUTSIDE a sandbox
transaction — clean up in FK-safe order (relations/children BEFORE parents) or
the cleanup raises a constraint error and leaves rows behind, making the NEXT
run fail on unique constraints. Prefer get-or-create (`Brain.get_x_by_slug(...) || create`)
in probes so reruns are idempotent.

## The Six Foot-Guns (Pitfalls)

### Pitfall 1 — Pin operator on a tuple doesn't compare tuple elements

You intend "skip when the current tool key equals the last one":

```elixir
# WRONG — silently never matches
case key do
  {:tool, ^last_dedup_key} ->     # pattern {:tool, X} with X pinned to last_dedup_key
    {acc, last_dedup_key}         # X must equal the WHOLE last_dedup_key
  ...                             # but key is {:tool, "foo"}, not {:tool, {:tool, "foo"}}
end
```

The pin `^last_dedup_key` binds the *second element* of the tuple to `last_dedup_key`, then implicitly checks `X == last_dedup_key`. But `X` is the string `"foo"`, while `last_dedup_key` is `{:tool, "foo"}`. They never compare equal.

Fix — compare whole tuples:

```elixir
cond do
  match?({:tool, _}, key) and key == last_dedup_key ->
    {acc, last_dedup_key}
  true ->
    {[normalize(msg) | acc], key}
end
```

### Pitfall 2 — `nil` sentinel collides with `{:tag, nil}` payload

You initialize `last_dedup_key` as `nil`, then check `key == last_dedup_key`. Fine — until `key` is `{:tool, nil}` because content is `nil` or missing. The first such message matches the sentinel and gets silently dropped.

Fix — use `:none` (or any atom not used by payload shapes):

```elixir
def reduce_message(msg, {acc, last_dedup_key}) do
  ...
end

Enum.reduce(messages, {[], :none}, &reduce_message/2)
```

When restricting the dedup to *binary* content only (per spec), combine the sentinel fix with a content guard:

```elixir
defp dedup_key(%{"role" => "tool", "content" => content}) when is_binary(content),
  do: {:tool, content}
defp dedup_key(_), do: :keep
```

### Pitfall 3 — `Enum.uniq_by` collapses messages with non-string content

`stable_prefix` style: dedupe system messages. Naïve:

```elixir
# WRONG — two system messages with content=nil both map to nil and the second is dropped
Enum.uniq_by(systems, &get_content/1)
```

If two messages have different non-string content (missing key, explicit nil, list of parts), they should be treated as distinct — not collapsed. Fix: dedupe only against string content, keep non-string messages unconditionally:

```elixir
deduped =
  Enum.reduce(systems, [], fn msg, acc ->
    content = Map.get(msg, "content")
    cond do
      is_binary(content) ->
        normalized = String.trim(content)
        if Enum.any?(acc, fn e ->
             is_binary(Map.get(e, "content")) and
               String.trim(Map.get(e, "content")) == normalized
           end) do
          acc
        else
          [msg | acc]
        end
      true ->
        [msg | acc]
    end
  end)
  |> Enum.reverse()
```

### Pitfall 4 — Reverse-then-rebuild doesn't preserve order if the reducer is wrong

When dedupping "consecutive" elements with a forward-pass reducer, you can be tempted to:

```elixir
messages
|> Enum.reverse()
|> Enum.reduce({[], :none}, &reduce/2)
|> elem(0)
|> Enum.reverse()
```

This is fine **if** the reducer is correct. When a single bug in the reducer drops or duplicates items, the two `Enum.reverse` calls cancel out and you see reversed output. **Trace failures back to the reducer first, not to the reverses** — they didn't break your order, the reducer did. The fix is correct reducer logic, not a third reverse.

### Pitfall 5 — Guard `in` with a variable fails to compile

You want to skip adding a badge when its type is disabled:

```elixir
# WRONG — ArgumentError at compile time
# "invalid right argument for operator \"in\", it expects a compile-time
#  proper list or compile-time range on the right side when used in guard
#  expressions, got: disabled"
defp maybe_add_badge(list, type, _slug, disabled) when type in disabled, do: list
```

`in` in a **guard** requires the right side to be a literal list or range at compile time. A variable like `disabled` (a runtime list) is not allowed.

Fix — move the check into the function body with `if`:

```elixir
defp maybe_add_badge(list, _type, nil, _disabled), do: list
defp maybe_add_badge(list, _type, "", _disabled), do: list

defp maybe_add_badge(list, type, slug, disabled) do
  if type in disabled do
    list
  else
    [%{type: type, slug: slug, label: String.slice(slug, 0, 12)} | list]
  end
end
```

Keep the guard clauses for `nil` and `""` — those are fine because they don't use `in`. Only the variable-membership check needs the `if`.

### Pitfall 6 — `Map.get(map, key, default)` returns nil when key EXISTS with nil value

Distinct from Pitfall 2 (nil sentinel in accumulators). The trap: you pass a default to `Map.get/3` expecting it to cover both absent keys and nil values, but it **only fires when the key is absent**.

```elixir
# Server response: %{"content" => nil, "model" => "qwen3"}

# WRONG — returns nil, NOT ""
Map.get(message, "content", "")     # key exists → nil returned, default ignored

# WRONG — then crashes
String.trim(Map.get(message, "content", ""))
# String.trim(nil) → ** (FunctionClauseError)
```

**Why it happens in practice:** LLM inference clients map the OpenAI response with `Map.get("message", %{"content" => nil})` — the key is always present, sometimes with nil (empty choices, reasoning-only responses from Qwen3 models). The default never fires.

**Fix — pattern match with guard (preferred):**

```elixir
case Inference.chat(payload) do
  {:ok, %{"content" => content}} when is_binary(content) and content != "" ->
    String.trim(content)

  {:ok, _} ->
    fallback_value()

  {:error, _reason} ->
    fallback_value()
end
```

The `when is_binary(content) and content != ""` guard catches both nil and empty-string content, routing both to the fallback. No `Map.get` needed at all.

**Alternative — `||` after access:**

```elixir
content = message["content"] || ""
```

Note: `||` also catches `false`, so only use when the value is never boolean. Pattern matching with `is_binary` is safer for string-or-nil fields.

**Generalized rule:** when you need "nil-or-empty → use default" semantics, do NOT rely on `Map.get/3`. Either pattern-match with a guard or use `||` after access.

**Seen in:** `MyApp.Graph.CommunitySummaries.summarize_with_llm/1` (crashed prod), `MyApp.Summaries.summarize_page/1` (same latent risk), `MyApp.Agent.Engine.process_message/3` (same latent risk).

### Pitfall 7 — Helper returns `{:cont, acc}` but caller expects plain `acc`

When writing `Finch.stream_while/5` callbacks, the callback must return `{:cont, acc}` or `{:halt, acc}`. But private helpers called *inside* the callback should return plain `acc` maps — not wrapped tuples.

```elixir
# WRONG — one clause wraps, the other doesn't
defp count_delta_tokens(acc, %{"choices" => choices}) do
  {:cont, %{acc | chunk_count: acc.chunk_count + deltas}}  # ← tuple!
end
defp count_delta_tokens(acc, _chunk), do: acc              # ← plain map

# Caller chains both, expecting plain maps:
acc = count_delta_tokens(acc, chunk)  # gets {:cont, %{...}}
acc = extract_usage(acc, chunk)       # BadMapError: expected a map, got {:cont, ...}
```

**Fix — all clauses of a helper that feeds into a chain must return the same shape:**

```elixir
defp count_delta_tokens(acc, %{"choices" => choices}) do
  %{acc | chunk_count: acc.chunk_count + deltas}  # plain map
end
defp count_delta_tokens(acc, _chunk), do: acc     # plain map
```

**Rule:** the `{:cont, acc}` / `{:halt, acc}` protocol belongs to the `stream_while` callback boundary ONLY. Helpers called inside the callback body return plain values. Audit every `defp` called from a stream callback: if any clause wraps in `{:cont, ...}` or `{:halt, ...}`, it will break the chain.

**Seen in:** `my_app_gateway.Benchmarks.Runner.count_delta_tokens/2` — crashed at runtime when processing SSE chunks.

## Dedup With State — The Standard Pattern

For "keep the first of N consecutive identical messages, preserve order":

```elixir
def dedup_consecutive(messages, key_fn) do
  {reversed, _} =
    Enum.reduce(messages, {[], :none}, fn msg, {acc, last} ->
      key = key_fn.(msg)
      cond do
        match?({:tool, _}, key) and key == last ->
          {acc, last}
        true ->
          {[msg | acc], key}
      end
    end)

  Enum.reverse(reversed)
end
```

The accumulator holds `{acc, last_key}`. `Enum.reverse` once at the end restores original order. See Pitfalls 1, 2, and 4 for the bugs that turn this pattern wrong.

## Edge-Case Test Matrix

Every pure-function module with list-in/list-out needs these tests, in this order:

| # | Test | Why |
|---|------|-----|
| 1 | empty list → empty list | guards the `when is_list` clause |
| 2 | all non-matching role → identity | proves the no-op baseline |
| 3 | mixed roles with the transform target in the middle | proves order preservation |
| 4 | two consecutive duplicate targets → one survives | proves the dedup core |
| 5 | two NON-consecutive identical targets → both survive | proves "consecutive" semantics |
| 6 | boundary case (exactly N chars, exactly N+1) | proves the threshold is inclusive |
| 7 | nil content / missing key → no crash | guards `Map.get` access |
| 8 | non-string content (list of parts) → untouched | guards the `is_binary` branch |
| 9 | combined: transform → transform → identity to spec | integration |

## Verification Checklist

Before declaring done:

- [ ] `mix compile --warnings-as-errors` passes with zero output
- [ ] `mix test test/<path>/<file>_test.exs` passes the new test file in isolation
- [ ] `mix test` (full suite) shows no new regressions — diff the count against pre-edit
- [ ] No `defp` helper left behind after a refactor (leftover dead code → unused-fn warning)
- [ ] Every described behavior has at least one passing test
- [ ] Non-string content (list of parts, nil, missing key) is asserted as untouched, not just "doesn't crash"

## Anti-Patterns

- **Don't** write a test that *only* asserts "doesn't crash" for nil/missing-key cases — assert the *output* matches the expectation, even if it's the input unchanged.
- **Don't** add `@spec` documentation and forget the wrong-type clause (e.g. only `when is_list`, no fallback). ExUnit will fail this test because the call from a non-list context crashes.
- **Don't** skip `mix compile --warnings-as-errors` between edits — the unused-function warning only surfaces on the second compile after a refactor changes who calls the helper, and the test run alone won't catch it.
- **Don't** use `String.length/1` to size a string you may have over 40_000 chars — use `byte_size/1` (fast, codepoint-safe for the truncation goal).
- **Don't** log inside a pure function. If a transformation needs a Logger, split it: pure transform + thin impure wrapper.

## Hermes Agent Integration

For running tests, prefer the `terminal` tool with the patterns above. The `hermes-extools` plugin's `elixir_compile(strict: true)` and `elixir_test(path: "test/...exs")` tools give the same outputs with structured parses — use them when you want diff-able warning lists or single-line test results.

For TDD discipline at a deeper level, use the `test-driven-development` skill (red → green → refactor with watched failures). This skill assumes you've already committed to writing the test alongside the impl, and focuses on the Elixir-specific pitfalls that the general TDD skill doesn't cover.

For systematic root-cause work when a single test fails mysteriously, combine with `systematic-debugging` — write the failing test, bisect the module into a minimal repro, then apply the matching pitfall.

## Quick Reference

| Symptom | Likely pitfall | Fix |
|---------|----------------|-----|
| Dedup silently drops first element | Pitfall 2 (nil sentinel) | use `:none` sentinel + content guard |
| Dedup doesn't match any consecutive pair | Pitfall 1 (pin on tuple second elem) | match whole tuple with `key == last` |
| Non-string-content messages get collapsed | Pitfall 3 (`Enum.uniq_by` over nil) | dedup against string content only |
| Output is reversed | Pitfall 4 (buggy reducer, blamed on reverses) | trace reducer, not reverses |
| `unused def` warning on second compile | leftover private helper | delete the helper, recompile |
| Test "doesn't crash" passes but func actually returns wrong shape | Anti-pattern 1 | assert exact output equality |
| Compile error "invalid right argument for operator in" | Pitfall 5 (guard `in` with variable) | move check to `if` in body |
| `String.trim(nil)` / nil-default returns wrong value | Pitfall 6 (`Map.get` nil-value trap) | pattern match with `is_binary` guard |
| `BadMapError` in `stream_while` callback | Pitfall 7 (helper returns `{:cont, acc}`) | helpers return plain `acc`, only the callback wraps |
