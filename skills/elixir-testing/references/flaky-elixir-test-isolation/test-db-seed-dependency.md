# Wiped test DB reds the whole suite (my_app Fase 3/4, 2026-08)

## Symptom

After `MIX_ENV=test mix ecto.drop && mix ecto.create && mix ecto.migrate`, the full suite goes from green to **76 failures** across many unrelated files — `BadMapError expected a map, got: nil`, `FunctionClauseError` in `page_type_enabled?/2`, etc. Looks catastrophic and like something you just broke. It isn't.

## Root cause

Some tests look up shared fixtures **without a create-fallback**, silently relying on leftover rows from previous runs (a dirty test DB). Example patterns:

```elixir
# dashboard_live_test.exs — NO fallback, assumes "personal" context exists
context = Brain.get_context_by_slug("personal")

# brain_test.exs — HAS the fallback (the house pattern to copy)
Brain.get_context_by_slug("personal") ||
  elem(Brain.create_context(%{name: "Personal", slug: "personal"}), 1)
```

The first form returns `nil` on a fresh DB and every downstream call (`page_type_enabled?(nil, ...)`, `page_counts_by_context` destructuring, etc.) blows up. Because these setup lines sit in `setup`/`__ex_unit_setup_1__`, one missing row cascades into dozens of failures across files that share the assumption.

## How to tell it's environmental, NOT your changes

Two cheap, conclusive tells:

1. **Same tests pass on the dirty DB, fail only after a reset.** If the suite was green before `ecto.drop` and red immediately after (with zero code changes in between), it's the DB state, not you.
2. **`git stash` still fails.** Stash your changes, re-run on the fresh DB — if it STILL fails, the failure predates your diff.

Isolate before concluding anything:

```bash
git stash
MIX_ENV=test mix ecto.drop && MIX_ENV=test mix ecto.create && MIX_ENV=test mix ecto.migrate
mix test test/path/to/file.exs   # still red? pre-existing / environmental
git stash pop
```

## Fix

Short term (unblock the run): re-create the assumed seed rows in the test env, e.g.

```bash
MIX_ENV=test mix run -e 'my_app.Brain.get_context_by_slug("personal") || my_app.Brain.create_context(%{name: "Personal", slug: "personal"})'
```

Long term (the real fix): give every no-fallback lookup the create-fallback pattern the passing tests already use, so no test depends on residual DB state:

```elixir
context =
  Brain.get_context_by_slug("personal") ||
    elem(Brain.create_context(%{name: "Personal", slug: "personal"}), 1)
```

## Gotcha that cost a session

Don't assume a mid-audit spike in failures is yours. In this session the count swung 5 → 10 → 76 across three runs, all from DB-state churn (debug scripts inserting users/contexts, then a full drop), not from the diff under test. The diff itself was clean: once the `"personal"` context was re-created, the suite went to **582/582**, including tests earlier mislabeled "flaky/pre-existing." What looked like flaky async tests were actually a dirty-DB dependency the whole time.
