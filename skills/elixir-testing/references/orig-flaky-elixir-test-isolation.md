---
name: flaky-elixir-test-isolation
description: "Fix flaky async ExUnit tests that assert global DB counts."
version: 1.0.0
author: Álvaro Lizama
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [elixir, exunit, testing, flaky-tests, ecto, async]
    related_skills: [test-driven-development, systematic-debugging, elixir-mix-build]
---

# Flaky Elixir Test Isolation

## When to Use

- ExUnit tests with `async: true` intermittently fail (CI or local, different seeds change which tests fail)
- Failures are count/aggregate mismatches: `expected 2, got 5`, `assert results == []` that passes solo
- Tests call org-wide functions (e.g. `team_id=nil` / no scoping arg) and assert exact totals
- The shared table is RANGE-partitioned by day (e.g. `request_logs`) — async tests insert into the same partition window

## Root Cause

`async: true` runs tests concurrently against the same DB. Any test asserting an exact GLOBAL aggregate (`total == 2` over all rows) is contaminated by every other async test inserting rows into the same partition/time window. Per-test DB cleanup does not reliably isolate partitions of a range-partitioned table, so "cleanup between tests" cannot be relied on.

## Triage first: three failure classes that look alike

Classify BEFORE applying the ladder — the fix is completely different per class:

1. **Classic async count flake** (the ladder below): fails only under parallel load, green when the file runs alone, clean DB.
2. **Committed residue in the test DB**: fails with the SAME delta on every seed AND fails when the file runs ALONE. Stale rows committed outside the sandbox (ad-hoc `MIX_ENV=test mix run` / iex debug sessions) pollute a shared fixture context. Fix: delete the stale rows once, then give exact-count tests a fresh per-test context. See `references/sandbox-shared-mode-zombies.md` §A.
3. **Zombie background tasks / async-pool races**: `DBConnection.OwnershipError` ("mode reverts to :manual if its owner terminates") or `"client #PID exited"`; the failing test MIGRATES across files per seed. App-spawned `Task.Supervisor` tasks (augmenters, embedding schedulers fired by `create_page`/`update_page` when an async-schedule flag defaults to true) outlive the test and tear down the shared sandbox connection; `async: true` DataCase/ConnCase modules also race sync shared-mode windows. Fix: force sync scheduling for the suite in `test_helper.exs` + audit async DB-case modules. See `references/sandbox-shared-mode-zombies.md` §B–C.
4. **Zero-vector NaN sort trap** (pgvector semantic-search tests): test stubs a zero embedding for the query vector and its fixture row — cosine distance of a zero vector is `NaN`, and Postgres sorts `NaN` LAST. If the shared sandbox transaction carries ≥`LIMIT` other rows with embeddings (residue from earlier sync tests), the asserted row sorts out of the result window: `assert length(data) == 1` fails with `left: 0` even though the row exists and the search works. Deterministic per seed-order, green solo. Fix: fresh scoping context per test (same pattern as class 2), not a weaker assertion.

Fast discriminators: run the failing file alone (class 2 fails alone); run the full suite with 3 different seeds and compare failing test NAMES (same set every time = deterministic residue or NaN trap; migrating set = class 3); `grep -c "Task #PID" run.log` on any full run (>0 = class 3 zombies exist, even in green runs). Note `--trace` green vs parallel red is NOT proof of a race — `--trace` forces max_cases 1, which changes module scheduling order even with the same seed; identical serial order is not guaranteed.

## The Isolation Ladder (prefer the top; fall down only when blocked)

1. **Scope with an existing parameter.** Production rollup/aggregate functions almost always accept a scoping id (`team_id`, `user_id`, `model_alias_id`, ...). Fixtures create unique parent rows per test (`{tm, team} = team_member_fixture()`), so pass `team.id` instead of `nil`. This is the proven house pattern — before editing, read the file and copy it from already-passing tests that isolate (they often carry a comment explaining why, e.g. "Aislar por team_id: ... no contaminan el conteo").
2. **Org-wide path tests.** If a test SPECIFICALLY exercises the nil/org-wide behavior, do NOT scope it — that would delete the coverage. Instead flip exact-count assertions to INCLUSION assertions: `assert total >= 2` (the fixture's own rows must appear), or find the fixture's unique row (anchor on its unique model/cost/agent_type) and assert on that row's aggregate only.
3. **Empty-list tests with no scoping param.** Some functions (e.g. `breakdown_by_team/1`) take only keyword opts and are always org-wide. A fresh fixture does not help there. Use a far-future `:from` (`~U[2099-01-01 00:00:00Z]`) so no concurrent test's rows can land inside the window. Exact-empty assertions are the sneakiest failures: green solo, red under load — always scope or time-shift them.
4. **Never** `async: false` just to pass a COUNT flake (throws away parallelism; the fix is isolation, not serialization) and **never** change production code to satisfy a test (semantics stay untouched — this is test-only work). **One legitimate exception:** pool-level ownership races (triage class 3) — the sandbox docs themselves say "if using shared mode in tests, make sure your tests are not async". Flipping a DB-touching async module to `async: false` (or to `ExUnit.Case` when it never queries) IS the documented fix there, and cheap when the suite's async runtime is already ~0s.

## Workflow

1. Read the failing test file first. Locate already-passing tests in the SAME file that isolate by scoping — they define the house pattern to copy exactly (destructure the fixture, pass the scoped id).
2. Classify each failing test: global-aggregate (scope it), org-wide-path (inclusion assert), or empty-list (scope or future `:from`).
3. Check the production function's actual signature (`def breakdown_by_team(opts \\\\ [])` has NO team param, `breakdown_by_model(team_id, opts)` does) before assuming scoping exists.
4. Apply the ladder; keep every test `async: true`.
5. Verify determinism: run the whole file 3× with different seeds:
   `mix test test/path/to/file.exs --seed 1`, `--seed 12345`, `--seed 99999`
   All green every run = deterministic. Each run takes ~10s, so this is cheap and conclusive.
6. Report which tests changed and the 3 clean tails — do not commit (parent agent verifies + commits).

## Pitfalls

- Don't delete org-wide tests when they flake — adapt them with inclusion asserts. Org-wide behavior is real behavior worth keeping covered.
- `assert results == []` with a wide `:from` is a time bomb in async suites; the fix is a future `:from` or a scoped id, not a weaker assertion.
- The same test can appear multiple times in a file with different shapes (aggregate vs empty vs timezone) — fix each occurrence, don't assume one pattern covers all.
- A shared helper like `hours_ago/1` relative to `DateTime.utc_now()` keeps window tests stable across wall-clock time — preserve it when rewriting.
- **LiveView `html =~ value` collides with form chrome.** If the asserted string is ALSO rendered inside a `<select>`/`<option>` (model names, team names), `refute html =~ ...` can never pass — the option always contains it. Anchor on a row-only string (owner email, unique id, `has_element?` on an id-scoped element). See `references/liveview-and-list-patterns.md`.
- **Org-wide LiveView empty states** (`#teams-empty`) can't be deterministic while async tests insert — drive the page's search box to a no-match term (preserves the empty-state path) or invert to a positive assertion on the fixture's own item. Same reference.
- **Global list/delete/order asserts** (`assert list == []`, `length == 2`, full-list equality) → membership/`Enum.any?` by id, `refute Enum.any?` for deletes, and scope ordering queries to the fixture's `team_member_id`. Same reference.
- **Named singleton Registries/ETS leak across test FILES, not just tests.** A `Registry` with a fixed name (e.g. `CircuitBreakerRegistry`) started by one test file is shared VM-wide; breakers/entries it registers never get cleaned up and can poison a DIFFERENT file that later sweeps it. Classic symptom: `Ecto.Query.CastError ... cannot be dumped to type :binary_id` in a LiveView test whose mount calls a Registry sweep (`status_all/1`, `open_breakers/1`) — the leaked ids are non-UUID strings. **Fix is in the leaking file, not the failing one, and it's test-only**: use real domain-shaped ids (`Ecto.UUID.generate()`) for anything registered into a shared named singleton, since production `:binary_id` columns are UUIDs. Then any leaked entry stays castable by Ecto and just matches no row (harmless) instead of crashing the sweep. See `references/registry-singleton-leak.md`.

## References

- `references/MyApp-rollup-example.md` — full worked example: 7 flaky tests in a Phoenix rollup suite, before/after, exact lines of the passing pattern.
- `references/baseline-worktree-diff.md` — honest failure attribution: how to prove which failures are yours vs pre-existing by diffing the suite against a baseline worktree. Use whenever you fix tests on a repo that was already red.
- `references/liveview-and-list-patterns.md` — LiveView `html =~` false positives from `<option>` collisions, org-wide empty-state strategies (search no-match vs positive assertion), and global list/delete/ordering assertion fixes.
- `references/test-db-seed-dependency.md` — wiped test DB reds the whole suite (76 failures) because some tests look up shared fixtures without a create-fallback. How to tell it's environmental (not your diff), the unblock command, and the house-pattern fix. **Read this before concluding a mid-session spike in failures is yours.**
- `references/sandbox-shared-mode-zombies.md` — three look-alike failure classes from one hunt: committed test-DB residue (fails alone, same delta every seed), `Task.Supervised` zombie tasks tearing down the shared sandbox connection (migrating `OwnershipError`/"client exited"; fix = force `schedule_async: false` in `test_helper.exs`), and `async: true` DB-case modules racing shared-mode windows. Includes the grep/`--trace` hunt recipe and the rule that one green run proves nothing for probabilistic classes.
