# Sandbox Shared-Mode Zombies & Committed Test-DB Residue (Phoenix/ECTO)

Session detail from a my_app suite hunt: 5 reported "isolation" failures turned out to be
THREE different root causes, only one of which matched the classic async-count-flake model.

## Failure class A — committed residue in the test DB (deterministic, NOT a flake)

**Signature:** exact-count assertions fail with the same delta on every seed, and the
failing file FAILS EVEN WHEN RUN ALONE (`mix test test/path/file.exs`). That isolated
failure is the discriminator: sandbox rollback isolation is fine; the DB itself is dirty.

**Cause:** rows committed OUTSIDE the sandbox — ad-hoc `MIX_ENV=test mix run -e ...`,
`MIX_ENV=test iex -S mix` debug sessions, or seeds. Sandbox rolls back per-test writes,
so nothing in the suite created them; they persist across runs forever.

**Diagnose:**
```bash
MIX_ENV=test mix run -e '
  import Ecto.Query
  IO.inspect(Repo.all(from p in my_app.Brain.Page, select: {p.slug, p.page_type, p.created_by}))
  IO.inspect(Repo.all(from c in my_app.Brain.Context, select: c.slug))'
```
In the session: 2 stale `report` pages (`meta-debug-*`, `created_by: "system"`) plus a
committed `personal` context. The context row was LOAD-BEARING (~20 test files call
`get_context_by_slug("personal")` with no create-fallback) — delete stray rows, keep
fixtures other tests depend on.

**Fix:** delete the stale rows once, then harden the victim tests so residue can't recur:
tests asserting exact counts against a shared context should run against a FRESH context
created per test (unique slug via `System.unique_integer([:positive])`) in an inner
`setup` inside the `describe` block — it overrides the module-level `context:` key.

## Failure class B — zombie background tasks kill the shared sandbox connection

**Signature:** `DBConnection.OwnershipError: cannot find ownership process for #PID<...>
({TestModule, :"test name"}) using mode :manual (Note that a connection's mode reverts
to :manual if its owner terminates.)` or `(EXIT) shutdown: %DBConnection.ConnectionError
{message: "client #PID<...> exited"}`. The failing test MIGRATES between files across
seeds; each run fails 0–4 unrelated tests (LiveView tests, controller tests, agent E2E
tests — whatever happens to own the connection next).

**Cause (captured in stacktrace):** the app spawns `Task.Supervisor` tasks that touch the
DB — e.g. `PageAugmenter.schedule/1` / `Embeddings.schedule/1` fired by
`Brain.create_page`/`update_page` when inference is enabled and `schedule_async` is true
(the runtime default). During a sync test the pool is in SHARED mode, so the task uses
the test's connection; the task OUTLIVES the test, and when `stop_owner` runs the
connection is torn down under it. A task mid-checkout takes the shared connection down
with it — the next test's owner dies and its next Repo call raises OwnershipError.
Smoking-gun log lines to grep:

    [error] Task #PID<...> started from #PID<...> terminating
    ** (EXIT) shutdown: ... "owner #PID<...> exited\n\nClient #PID<...> (Task.Supervised)
    is still using a connection from owner at location: ..."

**Correlate the zombie with the in-flight test:** run `mix test --seed N --trace`, find
the `[error] Task #PID` lines, and the nearest `* test ...` line above is the test that
was running (not necessarily the one that SPAWNED the task — tasks accumulate across
many tests and die in a batch when one owner stops; ~17 died within 50ms in the session).

**Fix (test-only, suite-wide):** force synchronous scheduling in `test/test_helper.exs`
so no supervised task ever spawns in the suite:

```elixir
# After Sandbox.mode(my_app.Repo, :manual)
base = Application.get_env(:MyApp, :inference) || []
Application.put_env(:MyApp, :inference, Keyword.put(base, :schedule_async, false))
```

Per-test `Application.put_env` blocks that omit `schedule_async` still re-open the window
(default is `true`) — grep every `put_env(:app, :inference,` block and add
`schedule_async: false` to the ones missing it. Verify no test asserts the async path
first (`grep -n "schedule(" test/...`).

## Failure class C — async:true DB-case modules race sync shared-mode windows

Any `async: true` module using DataCase/ConnCase calls `start_owner!` in its setup even
with zero Repo calls; that pool activity during a sync test's shared-mode window corrupts
ownership (same OwnershipError family). The sandbox docs themselves say: "If using shared
mode in tests, make sure your tests are not async." This is the ONE legitimate exception
to "never flip async: false to pass": pool-level races, not count flakes. Audit with:

    grep -rn "async: true" test/   # then check each file for DataCase/ConnCase usage

- Async module touches the DB → `async: false` (cheap if async runtime is ~0.3s anyway).
- Async module NEVER touches the DB but uses DataCase/ConnCase only for imports
  (changeset tests, template rendering) → switch to `use ExUnit.Case, async: true`
  (keeps parallelism, drops the pool checkout).
- Pure `ExUnit.Case` async modules (no case template) are safe — leave them.

## Hunt recipe that worked

1. Run failing file alone → if it fails, class A (residue); dump the DB.
2. Full suite with 3+ different seeds; collect failing test names per run. Same set every
   seed = deterministic; migrating set = concurrency (class B/C).
3. `grep -c "Task #PID" full_run.log` — zombie task crashes are visible even in GREEN
   runs; >0 means class B exists even when luck made it pass.
4. `--trace` run to correlate crash timestamps with the in-flight test.
5. Fix, then re-hunt with 5 fresh seeds (not just the 3 that failed before) — the zombie
   class is probabilistic; one green run proves nothing.
