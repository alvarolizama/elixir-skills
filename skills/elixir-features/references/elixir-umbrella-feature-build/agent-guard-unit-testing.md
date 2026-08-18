# Unit-testing agent `execute_tool/3` guards without a DB sandbox

my_app agent modules (`my_app.Agent.Research`, `my_app.Agent.Ingest`, etc.) implement
`execute_tool/3` which often mixes pure limit/validation guards with side-effecting
calls into `Brain.*` / `Firecrawl.*` / the DB. When TDD'ing a new guard
(e.g. page-limit-per-session), you want to test the guard logic in isolation
without spinning up the Ecto SQL sandbox, stubbing inference, or mocking HTTP.

This reference covers the in-memory state construction and the
`assert_raise DBConnection.OwnershipError` technique used in
`test/my_app/agent/research_test.exs` (Task 1.2: page-limit guard).

## When to use this pattern

- You added a guard at the TOP of an `execute_tool/3` clause that should
  short-circuit BEFORE any DB / external call.
- The guard depends only on struct fields (`pages_created`, `search_queries`,
  `scraped_urls`, `opts`).
- You want fast `async: true` tests with no `my_app.DataCase` / sandbox.

## Building an in-memory `State` + `Session`

`my_app.Agent.Research.State` is a plain `defstruct` (NOT an Ecto schema), and
`my_app.Agent.Session` IS an Ecto schema struct but can be constructed in memory
with `struct/2` — no DB checkout required as long as you never persist it.

```elixir
defmodule my_app.Agent.ResearchTest do
  use ExUnit.Case, async: true   # NOT my_app.DataCase — no DB needed

  alias my_app.Agent.Research
  alias my_app.Agent.Research.State
  alias my_app.Agent.Session

  defp build_session(attrs \\ []) do
    struct(
      %Session{
        id: Ecto.UUID.generate(),
        context_id: Ecto.UUID.generate(),
        agent_type: "research",
        input: "test topic",
        status: "running"
      },
      attrs
    )
  end

  defp build_state(attrs) do
    struct(
      %State{session: build_session(), pages_created: 0, opts: []},
      attrs
    )
  end
end
```

**Pitfall:** `defp build_state(attrs \\ [])` triggers a "default never used"
warning if every caller passes an argument. Drop the default (`defp build_state(attrs)`)
or always call it without args at least once.

## Asserting the guard FIRES (limit reached)

Straightforward — the guard returns `{{:error, msg}, state}` without touching
the DB, so no sandbox is needed:

```elixir
test "returns error when default page limit (10) is reached" do
  state = build_state(pages_created: 10)

  {{:error, msg}, new_state} =
    Research.execute_tool("create_page", %{"title" => "x", "body" => "y"}, state)

  assert msg =~ "maximum" or msg =~ "page limit"
  assert new_state.pages_created == 10   # state returned unchanged
end
```

## Asserting the guard does NOT fire (under the limit) — the OwnershipError trick

The non-guard branch calls `Brain.create_page/1`, which needs a DB sandbox.
Without `my_app.DataCase`, `Brain.create_page` raises `DBConnection.OwnershipError`.
That exception is actually the PROOF that the guard did not short-circuit
(the guard returns `{:error, _}`, never raises). Assert on the raise:

```elixir
test "does not block when under the limit" do
  # pages_created strictly below max_pages → guard must NOT fire,
  # execution proceeds into Brain.create_page.
  state = build_state(pages_created: 9, opts: [max_pages: 10])

  assert_raise DBConnection.OwnershipError, fn ->
    Research.execute_tool("create_page", %{"title" => "x", "body" => "y"}, state)
  end
end
```

**Why this works:** the limit guard returns a tuple; only the real create path
reaches `Repo.insert` → `DBConnection.OwnershipError`. So `assert_raise`
positively proves the guard was bypassed. This avoids adding Mox/stubs just to
test guard logic.

**When NOT to use this:** if the non-guard branch does NOT hit the DB (e.g.
returns a pure value), don't fake a raise — assert on the return value directly.
Only use the OwnershipError trick when the downstream call genuinely needs a
sandbox you deliberately didn't set up.

### The OwnershipError trick breaks when the code grows a DB dependency (CRITICAL)

This pattern has a sharp edge: it only works as long as the code path under
test touches the DB **only** at the final `Repo.insert`. The moment you wire
any *runtime* value into the guard or the create path — e.g. a limit that now
reads `my_app.Settings.get("agent_max_pages")` from a DB-backed settings store —
the OwnershipError fires at the *settings read*, BEFORE the guard even runs.
The test then either:

- raises `DBConnection.OwnershipError` on the *limit-check* line instead of the
  insert line (your `assert_raise` passes for the wrong reason and the guard is
  never actually exercised), or
- fails outright if the test module is `use ExUnit.Case` (no sandbox checkout).

**Real case (my_app, 2026-07-17):** wiring `agent_max_pages` to `my_app.Settings`
turned three green "pure unit" tests red. The fix is not to mock the settings
store — switch the module to `use my_app.DataCase` (keeps `async: true` if no
shared rows), and rewrite the "does not block" test to assert the real outcome
instead of the error-as-proof:

```elixir
defmodule my_app.Agent.ResearchTest do
  # Was `use ExUnit.Case` — switched when limits started reading my_app.Settings.
  use my_app.DataCase, async: true

  test "does not block when under the limit" do
    # Seed a real context so Brain.create_page passes the FK.
    {:ok, ctx} = my_app.Brain.create_context(%{name: "Limit Test", slug: "limit-test"})

    session = build_session(context_id: ctx.id)
    state = build_state(pages_created: 9, opts: [max_pages: 10], session: session)

    {{:ok, page}, new_state} =
      Research.execute_tool("create_page", %{"title" => "x", "body" => "y"}, state)

    assert page.title == "x"
    assert new_state.pages_created == 10
  end
end
```

**Rule:** error-as-proof (`assert_raise DBConnection.OwnershipError` meaning
"we reached the guarded path") is a *test smell*. The moment any production
dependency of that path gains a legitimate DB read, the proof inverts and the
test lies to you. Assert the real outcome (the row exists, the counter moved).
If a guard truly has zero DB dependencies, the OwnershipError trick is still
valid — but re-verify that assumption every time you wire a new runtime config
into the agent module.

## Reading `state.opts` that may be a keyword list OR a map

`init_state/3` stores `opts` as whatever keyword list the caller passed, but
tests or callers may hand in a map. A polymorphic read keeps the guard robust:

```elixir
max_pages =
  case state.opts do
    opts when is_list(opts) -> Keyword.get(opts, :max_pages, @max_pages_per_session)
    opts when is_map(opts)  -> Map.get(opts, :max_pages, @max_pages_per_session)
    _                       -> @max_pages_per_session
  end
```

Test BOTH shapes:

```elixir
test "respects custom :max_pages from keyword opts" do
  state = build_state(pages_created: 3, opts: [max_pages: 3])
  {{:error, msg}, _} = Research.execute_tool("create_page", %{"title" => "x", "body" => "y"}, state)
  assert msg =~ "maximum of 3"
end

test "respects custom :max_pages when given as a map" do
  state = build_state(pages_created: 2, opts: %{max_pages: 2})
  {{:error, msg}, _} = Research.execute_tool("create_page", %{"title" => "x", "body" => "y"}, state)
  assert msg =~ "maximum of 2"
end
```

## Guard placement rule

Always put the limit guard as the FIRST clause body in `execute_tool/3`, before
constructing `page_attrs` or calling `Brain.*`. The error tuple must be returned
with the state UNCHANGED (no increment, no broadcast), so the LLM can retry
without side effects once it calls `done`.

## Verification gate

```bash
mix compile --warnings-as-errors
mix test test/my_app/agent/research_test.exs
```

Both must be clean. The whole suite for a pure-guard test file runs in
~0.02s with `async: true` because no sandbox checkout happens.
