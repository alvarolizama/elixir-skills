# Adding a new tool to an existing my_app agent module

Recurring class of work: Álvaro asks to add a new tool to an existing
`my_app.Agent.*` module (QA, LinkGardenerAgent, CurationAgent, Research, Ingest,
WeeklyReview, Engine). The shape is always the same — a tool spec in
`tools/0`, an `execute_tool/3` clause, a `system_prompt` update, and a
test following the existing patterns in `test/my_app/agent/*_test.exs`.

This reference captures the workflow that avoids the three mistakes that
bite every time: guessing the `context_id` field, adding an unnecessary
`summarize_result/1` clause, and forgetting to update the `tools/0`
assertion test.

## Mandatory read-first

Before writing any code, read these in the target agent module:

1. **`tools/0`** — the list of existing tool specs. Copy the exact shape
   (`%{"type" => "function", "function" => %{"name" => ..., "description" => ...,
   "parameters" => %{"type" => "object", "properties" => ..., "required" => ...}}}`).
   Descriptions for QA and CurationAgent are in Spanish; LinkGardenerAgent and Research
   are in English. Match the surrounding agent's language.

2. **One existing `execute_tool/3` clause that hits the DB** (e.g. `get_page`,
   `search`, `propose_relation`). This is where you confirm the real
   `context_id` access path (see pitfall below).

3. **`system_prompt/1`** — note the workflow section and the language. You
   will append a step or add a new section.

4. **`summarize_result/1`** — check whether it has per-tool clauses or
   structural clauses (`{:ok, pages} when is_list(pages)`).

## The `context_id` field — VERIFY, never assume

Every my_app agent's `%State{}` struct has `session: nil` as a field, and
`%Session{}` carries `context_id`. So the access path is:

```elixir
state.session.context_id
```

This is the case for ALL current agents (QA, LinkGardenerAgent, CurationAgent,
Research, Ingest, WeeklyReview). But the user has flagged this as a
verification step every time because:

- It's easy to guess `state.context_id` (does not exist) or
  `state.session.context` (wrong field name).
- A future agent could refactor `session` away or rename the field.
- The user explicitly asks you to confirm: "VERIFICA el campo real de
  context en %State{} (mira cómo lo usan las otras execute_tool — puede
  ser state.session.context_id o state.context_id)".

**How to verify in one read:** search for `def execute_tool("get_page"` or
any DB-hitting clause in the target module and read 5 lines into the body.
You will see `Brain.get_page_by_slug(slug, state.session.context_id)` or
equivalent. That's your confirmation. Do this BEFORE writing the new
clause.

## `summarize_result/1` — check before adding a clause

`summarize_result/1` in most agents is structural, not per-tool:

```elixir
def summarize_result({:ok, pages}) when is_list(pages), do: ...
def summarize_result({:ok, %{slug: _, title: _} = page}), do: ...
def summarize_result({:ok, :done}), do: ...
def summarize_result({:error, reason}) when is_binary(reason), do: ...
```

If your new tool returns `{:ok, list}` or `{:ok, %{slug: ..., title: ...}}`,
it will fall through to an existing clause. **Do not add a new clause
unless the shape is genuinely new** (e.g. a tuple `{:ok, %{id:, relation_type:}}`
that does not match `%{slug: _, title: _}`).

The LinkGardenerAgent has a clause `def summarize_result({:ok, %{id: id, relation_type: rt}})`
because `propose_relation` returns that shape — a new tool returning the
same shape will reuse it.

Decision rule: if your tool's `{:ok, result}` matches an existing clause's
pattern, leave `summarize_result/1` alone. Note this in your report so
the user knows you checked.

## `tools/0` assertion test — update it

Most agent test files have a `describe "tools/0"` block with an assertion
like:

```elixir
test "exposes the expected tool names" do
  names = LinkGardenerAgent.tools() |> Enum.map(&get_in(&1, ["function", "name"])) |> Enum.sort()
  assert names == ["done", "get_page", "list_orphans", "propose_relation", "search"]
end
```

When you add a tool, this assertion breaks. Update the list to include
your new tool name (alphabetical, since the test sorts). Do this in the
same commit as the tool addition — it's a one-line fix that's easy to
forget until CI fails.

## Workflow the user expects

1. **Read existing patterns FIRST** — `tools/0`, an existing
   `execute_tool/3` clause, `system_prompt/1`, `summarize_result/1`.
   This is non-negotiable. The user has corrected this pattern before:
   do not write a tool spec from memory.
2. **Respect the explicit scope.** The user lists files to touch and
   files NOT to touch (e.g. "NO toques: brain.ex, graph.ex,
   page_meta.ex"). If the backend function you need does not exist,
   STOP and report — do not edit the forbidden file.
3. **Update `system_prompt` with the workflow** — where the new tool
   fits in the sequence. Be concrete: "step 0 = transitive_candidates",
   "search → expand_neighbors → get_page → responder".
4. **Add tests following existing patterns** — usually calling
   `execute_tool/3` directly with a `%State{}` built via the test's
   `build_state/1` helper, no LLM. Cover: error case (unknown slug /
   empty input), success case (returns the expected shape), and a
   `tools/0 exposes <new_tool>` assertion.
5. **Verify and report:**
   - `mix compile --warnings-as-errors` clean.
   - `PORT=4099 mix test test/my_app/agent/` green (dev server occupies
     4000; `PORT=4099` is the established convention).
   - Report: the real `context_id` field, the tests added, the output.

## Where the tool spec goes in `tools/0`

Insert the new tool spec in the position that matches its workflow order,
not alphabetically. The list is read by the LLM as the available toolset;
order is not semantically meaningful but keeping related tools together
(search → expand_neighbors → get_page → create_query_page → done) makes
the system prompt and the tool list tell the same story.

## Backend function shape — verify before wiring

If the tool wraps a `Brain.*` function, read the function's actual return
shape before mapping in the clause. Example (QA `expand_neighbors`):

- `Brain.expand_neighbors/1` returns `[%{id, slug, title, page_type,
  relation_type, direction, summary}]` (maps, not structs).
- The tool clause maps each to `%{slug, title, relation_type, direction,
  summary}` — dropping `id` and `page_type` because the LLM doesn't need
  them, keeping `summary` even though it may be `nil`.

Same for `Brain.transitive_part_of_candidates/1`: returns
`[%{source_slug, target_slug, via_slug}]` — the tool passes it through
unchanged because the shape is already LLM-friendly.

Do not reshape in the tool clause unless the backend returns something
the LLM shouldn't see (e.g. internal ids, raw DB rows).

## Test patterns for the new tool

Follow the existing `describe` blocks in the target agent's test file.
Two patterns cover most cases:

### Pattern A — guard / error case (no DB needed, but use DataCase anyway)

Most agent tests use `use my_app.DataCase, async: false` for the whole
file, so just add a `describe` block. Build state with the file's
`build_state/1` helper:

```elixir
describe "expand_neighbors tool" do
  setup do
    original = no_inference_env()
    context = seed_context()
    on_exit(fn -> restore_env(original) end)
    {:ok, context: context}
  end

  test "returns error for unknown slug", %{context: ctx} do
    state = build_state(session: build_session(context_id: ctx.id))
    {{:error, msg}, _} = QA.execute_tool("expand_neighbors", %{"slug" => "nope"}, state)
    assert msg =~ "not found"
  end
end
```

### Pattern B — success case with seeded pages + relations

```elixir
test "returns neighbors with relation_type and direction for a valid slug",
     %{context: ctx} do
  {:ok, a} = Brain.create_page(%{context_id: ctx.id, title: "A", slug: "a", ...})
  {:ok, b} = Brain.create_page(%{context_id: ctx.id, title: "B", slug: "b", ...})
  {:ok, _} = Brain.create_relation(%{source_id: a.id, target_id: b.id, relation_type: "part_of"})

  state = build_state(session: build_session(context_id: ctx.id))
  {{:ok, neighbors}, _} = QA.execute_tool("expand_neighbors", %{"slug" => "a"}, state)

  neighbor = Enum.find(neighbors, &(&1.slug == "b"))
  assert neighbor.relation_type == "part_of"
  assert neighbor.direction == "outbound"
end
```

### Pattern C — anti-case (candidate should NOT appear)

For tools that filter (e.g. `transitive_candidates` excludes pairs where
the direct edge already exists):

```elixir
test "does not return a candidate when the direct edge already exists" do
  # ... seed A→B→C AND A→C
  {{:ok, candidates}, _} = LinkGardenerAgent.execute_tool("transitive_candidates", %{}, state)
  refute %{source_slug: "a", target_slug: "c", via_slug: "b"} in candidates
end
```

## Verification gate

```bash
mix compile --warnings-as-errors
PORT=4099 mix test test/my_app/agent/
```

The `PORT=4099` is required because the dev server occupies 4000 and
`runtime.exs` sets the server port unconditionally. This is documented
in the plan and in `references/my_app-agent-e2e-testing.md`.

## Cross-references

- `references/my_app-agent-guard-unit-testing.md` — testing limit/validation
  guards in isolation (no DB sandbox). Covers the
  `assert_raise DBConnection.OwnershipError` trick and when it breaks.
- `references/my_app-agent-e2e-testing.md` — testing a full tool-call
  sequence with a `Req.Test` stub for the LLM. Covers the
  `create pages BEFORE enabling inference` pitfall.
- `references/brain-context-relation-lifecycle.md` — how `Brain.create_relation/1`,
  `expand_neighbors/2`, and `transitive_part_of_candidates/1` behave.
