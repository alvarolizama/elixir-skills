# Flaky async test isolation — triage, ladder, worked fixes

Symptom: ExUnit tests marked `async: true` pass solo but intermittently fail in
the full suite; failures are count/aggregate mismatches (`expected 2, got 5`,
`assert results == []` that only fails under load) or migrate between files as
the seed changes.

## Mechanism

`async: true` runs tests concurrently against the same database. Any assertion
on a GLOBAL aggregate (`total == 2` over all rows, full-list equality, exact
ordering of an unscoped query) is contaminated by every other async test
inserting rows into the same table/partition/time window. Per-test sandbox
rollback does not reliably isolate partitions of a range-partitioned table, so
"cleanup between tests" cannot be relied on.

## Triage first: four look-alike failure classes

The fix differs completely per class, so classify BEFORE the ladder:

1. **Classic async count flake** — fails only under parallel load, green when
   the file runs alone, clean DB → isolation ladder below.
2. **Committed residue in the test DB** — fails with the SAME delta on every
   seed AND fails when the file runs ALONE. Stale rows committed outside the
   sandbox (ad-hoc `MIX_ENV=test mix run -e`, iex debug sessions) pollute a
   shared fixture context. Fix: delete the stale rows once, then give
   exact-count tests a fresh per-test context. See
   `sandbox-and-seed-dependency.md` §residue.
3. **Zombie background tasks / async-pool races** —
   `DBConnection.OwnershipError` ("mode reverts to :manual if its owner
   terminates") or `client #PID exited`; the failing test MIGRATES across files
   per seed. App-spawned `Task.Supervisor` tasks outlive the test and tear down
   the shared sandbox connection; `async: true` DataCase/ConnCase modules also
   race sync shared-mode windows. See `sandbox-and-seed-dependency.md` §zombies.
4. **Zero-vector NaN sort trap** (pgvector) — a stubbed zero embedding gives
   cosine distance `NaN`, and Postgres sorts `NaN` last. If the shared
   transaction carries ≥`LIMIT` other rows with embeddings, the asserted row
   sorts out of the window: `assert length(data) == 1` fails with `left: 0`
   even though the row exists. Deterministic per seed-order, green solo. Fix:
   fresh scoping context per test, not a weaker assertion.

**Fast discriminators:**

```bash
mix test test/path/file_test.exs            # class 2 fails alone
mix test --seed 1      # collect failing test NAMES
mix test --seed 12345  # same set every seed = residue/NaN; migrating = class 3
mix test --seed 99999
grep -c "Task #PID" full_run.log            # >0 = class 3 zombies, even in green runs
```

`--trace` green vs parallel red is NOT proof of a race — `--trace` forces
`max_cases 1`, which changes module scheduling order even with the same seed.

## The isolation ladder (top first; fall only when blocked)

1. **Scope with an existing parameter.** Production aggregate/rollup functions
   almost always accept a scoping id (`team_id`, `user_id`, `model_id`, ...).
   Fixtures create unique parent rows per test — pass the scoped id instead of
   `nil`. Before editing, read the file and copy the pattern from
   already-passing tests that isolate.

   ```elixir
   # BEFORE — flaky: counts rows for ALL teams
   results = MyApp.Metrics.breakdown(nil, from: hours_ago(72))
   assert length(results) == 1

   # AFTER — deterministic: only the fixture's parent
   team = parent_fixture()
   results = MyApp.Metrics.breakdown(team.id, from: hours_ago(72))
   assert length(results) == 1
   ```

2. **Org-wide path tests.** If the test SPECIFICALLY exercises the nil/org-wide
   behavior, do NOT scope it — that deletes coverage. Flip exact-count
   assertions to INCLUSION assertions:

   ```elixir
   # BEFORE: assert total == 2   ← flaky: other async tests add rows
   series = MyApp.Metrics.Rollup.hourly_series(nil, from: hours_ago(72))
   total = series |> Enum.map(& &1.request_count) |> Enum.sum()
   assert total >= 2    # the fixture's own rows must appear
   ```

3. **Empty-list tests with no scoping param.** Functions taking only keyword
   opts are always org-wide; a fresh fixture does not help. Use a far-future
   `:from` so no concurrent test's rows can land in the window:

   ```elixir
   results = MyApp.Metrics.Rollup.breakdown_by_team(from: ~U[2099-01-01 00:00:00Z])
   assert results == []
   ```

   Exact-empty asserts are the sneakiest failures: green solo, red under load.

4. **Never** flip `async: false` just to pass a count flake, and **never**
   change production code to satisfy a test — this is test-only work. The one
   legitimate exception is pool-level ownership races (class 3): the Ecto
   sandbox docs themselves say shared-mode tests should not be async.

## Membership fixes for list/delete/ordering asserts

```elixir
# list: membership, not equality
assert Enum.any?(MyApp.Catalog.list_providers(), &(&1.id == p1.id))

# delete: the specific id is gone, not "the list is empty"
refute Enum.any?(MyApp.Catalog.list_providers(), &(&1.id == provider.id))

# ordering: scope the query to the fixture so concurrent rows never enter
logs = MyApp.Audit.list_logs(%{owner_id: owner.id})
assert [%{first: true}, second] = logs
assert first.inserted_at >= second.inserted_at
```

A shared helper like `hours_ago/1` (relative to `DateTime.utc_now()`) keeps
window tests stable across wall-clock time — preserve it when rewriting.

## Workflow

1. Read the failing file; locate already-passing tests that isolate and copy
   their scoping pattern exactly (destructure the fixture, pass the scoped id).
2. Classify each failing test: global-aggregate (scope it), org-wide-path
   (inclusion assert), or empty-list (scope or future `:from`).
3. Check the production function's actual signature before assuming scoping
   exists (`def f(opts \\ [])` has no param; `def f(team_id, opts)` does).
4. Apply the ladder; keep every test `async: true`.
5. The same test name can appear multiple times in a file with different shapes
   (aggregate vs empty vs timezone) — fix each occurrence.

## Verification

```bash
mix test test/path/file_test.exs --seed 1       # green
mix test test/path/file_test.exs --seed 12345   # green
mix test test/path/file_test.exs --seed 99999   # green
# plus one CONTENTION run pairing the fixed file with heavy async files:
mix test test/a_live_test.exs test/b_live_test.exs test/heavy_async_test.exs --seed 7
```

All green every run = deterministic. Don't weaken assertions to hide a flake —
the fix is isolation/scoping, never a weaker assert.
