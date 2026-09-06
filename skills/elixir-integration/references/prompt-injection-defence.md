# Prompt Injection Defence in Elixir

Porting a threat-pattern scanner and enforcing prompt-injection hygiene in
LLM features: scope discipline, Elixir regex pitfalls, codepoint filtering,
and enforcement points. Symptom → mechanism → fix → verification.

## Scope: scanner vs enforcement

**Symptom.** The scanner never fires, or fires on legit content; the
enforcement layer blocks everything.

**Mechanism.** Scanning and enforcement have different costs and different
false-positive budgets. A scanner over-includes (it can afford to
re-read); enforcement must be surgical or it breaks the product.

**Fix.** Define scope explicitly:

- **Scanner**: read-only audit tool; scans user content for
  injection patterns; reports findings with file/line/severity. High
  recall is fine.
- **Enforcement**: applies to a NARROW, enumerated set of surfaces (e.g.
  user-supplied system-prompt fragments, tool arguments that become
  instructions). High precision only — blocking false positives is a
  product bug.

Ship them as separate modules with separate tests; never let the scanner
silently feed the enforcer.

## Elixir regex pitfalls

**Symptom.** A pattern that works in Python/JS (PCRE-style) is silently
wrong in Elixir: no match, partial match, or a hang.

**Mechanism.** `Regex` is RE2-flavored: **no backreferences, no lookahead/
lookbehind, no atomic groups**. Pattern sources from other languages fail
or compile into different semantics. Also: Elixir regexes operate on
codepoints, not bytes — an app assumed bytes and the pattern missed
multi-byte content or split a UTF-8 char.

**Fix.**

1. Rewrite any lookaround into plain alternation + capture, or use
   `:unicode` compile options deliberately.
2. Match codepoints: explicitly compile with `~r//u` and unittest the
   multi-byte cases (emoji, accented chars, CJK) — a "strip the prompt"
   regex that slices a codepoint produces replacement chars.
3. Test every pattern with `Regex.run/3` on fixtures: match, no-match,
   and near-match inputs.

## Codepoint filtering

**Symptom.** `String.replace(payload, ~r/[<>{}\[\]\\]/u, "")` mangles
legitimate UI text or leaves dangling markers.

**Mechanism.** Filtering by raw codepoints removes valid syntax from
user content (a user posting code snippets loses brackets) and can break
HTML/JSON the app legitimately renders.

**Fix.**

- Filter at the BOUNDARY, not the payload: strip/escape only where the
  content crosses into an instruction context (interpolation into a
  prompt, a tool-argument string).
- Escape, don't delete, when the downstream format demands it
  (`String.replace` to `\uXXXX` for JSON, `&lt;` for HTML).
- Keep a denylist ONLY for the narrow enforcement set; the scanner keeps
  broad patterns with a severity report instead.

**Verification.** Fixture tests: legit code snippet passes through
unescaped in normal content; the same snippet is escaped in the
instruction context.

## Enforcement points

**Symptom.** Injection works via an unexpected vector (a filename, a
record field) even though the obvious prompt field is guarded.

**Mechanism.** Enforcement was applied to one field, not to every
interpolation boundary. Data flows from many sources into the composed
prompt; the guard must sit at the COMPOSITION, not at the input.

**Fix.** Enforce at composition: a single `build_prompt/1` that takes
source data and applies escaping + the narrow denylist to every
interpolated value. Test each source type (name, description, tool
output, file content) through the same boundary.

**Verification.**

```elixir
test "tool output cannot inject instructions" do
  prompt = build_prompt(%{tool_result: "IGNORE PREVIOUS..."})
  refute prompt =~ "IGNORE PREVIOUS"
end
```

## Verification commands

```bash
mix compile --warnings-as-errors && mix test

# no lookaround/backreference regexes in scanner/enforcer
grep -rn '(?=' lib/ | wc -l        # expect 0
grep -rn '\\1' lib/ | wc -l        # expect 0 (RE2: backrefs unsupported)

# every user-data interpolation goes through build_prompt/1
grep -rn '\.prompt' lib/ | wc -l   # inspect each hit
```