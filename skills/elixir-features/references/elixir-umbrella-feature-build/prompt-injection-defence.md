# Prompt Injection Defence in Elixir Umbrella Projects

Porting Hermes Agent's `tools/threat_patterns.py` scanner to an Elixir umbrella
(e.g. Money Bot's `:harness` app). Use as a recipe when adding a security/safety
scanner to a Phoenix/Elixir project.

## What to port

Hermes organizes threat patterns in three scopes:

- `:all` — classic prompt injection + exfiltration (low false-positive rate)
- `:context` — adds role hijack, promptware/C2, fake updates (good for
  context files, memory, tool results)
- `:strict` — adds persistence, SSH backdoors, hardcoded secrets (use for
  user-mediated writes: agent souls, skills installs, system prompt edits)

Represent each pattern as `{id, regex, scopes}` and filter by scope at scan
time.

## Elixir regex pitfalls

### 1. Curly braces in `~r//` confuse the parser

This line looks fine but fails to compile:

```elixir
~r/(?:api[_-]?key|token|secret|password)\s*[=:]\s*["\'][A-Za-z0-9+/=_-]{20,}/i
# ❌ MismatchedDelimiterError — Elixir sees `{20,}` and thinks the tuple ends
```

Fix: build the regex with `Regex.compile!/2` when you need literal `{n,}`
quantifiers:

```elixir
Regex.compile!(
  "(?:api[_-]?key|token|secret|password)\\s*[=:]\\s*[\"'][A-Za-z0-9+/=_-]{20,}",
  "i"
)
```

### 2. Do NOT use `String.graphemes/1` to filter invisible unicode

Zero-width joiners and non-joiners (U+200C, U+200D) are grouped with the
preceding base character by `String.graphemes/1`:

```elixir
iex> String.graphemes("ab\u200Cc\u200Ddef")
["a", "\u200B", "b\u200C", "c\u200D", "d", "\u2060", "e", "\uFEFF", "f"]
```

Work at the codepoint level instead:

```elixir
@invisible_codepoints MapSet.new([0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, ...])

content
|> String.to_charlist()
|> Enum.reject(&MapSet.member?(@invisible_codepoints, &1))
|> List.to_string()
```

Same for detection:

```elixir
defp invisible_findings(content) do
  content
  |> String.to_charlist()
  |> Enum.uniq()
  |> Enum.filter(&MapSet.member?(@invisible_codepoints, &1))
  |> Enum.map(&"invisible_unicode_U+#{Integer.to_string(&1, 16) |> String.upcase() |> String.pad_leading(4, "0")}")
end
```

## Recommended module split

- `Harness.PromptSecurity` — public API: `scan/2`, `safe?/2`, `sanitize/1`,
  `build_system_prompt/1`.
- `Harness.PromptSecurity.Scanner` — regex patterns, scopes, invisible codepoint
  detection.

## Places to enforce it

1. **Agent soul / system prompt** before persistence.
2. **User messages** before they reach the inference runner.
3. **Tool results / external content** before injecting them back into context.

## Project-specific placement (Money Bot)

In this umbrella, agent/inference-related code belongs to the `:harness` app,
not `:core`. `:core` holds domain schemas and contexts; `:harness` holds the
runner, clients, message builders, and prompt security. When in doubt, put
anything that touches the LLM API or system prompt in `:harness`.

## Verification checklist

```bash
mix test
mix format --check-formatted
mix compile --warnings-as-errors
MIX_ENV=test mix compile --warnings-as-errors
```

## Reference implementation

See Money Bot: `apps/harness/lib/harness/prompt_security/` and
`apps/harness/test/harness/prompt_security/`.
