# Sandbox shared-mode zombies & committed test-DB residue

Symptom: a suite hunt reports "isolation failures" that turn out to be three
DIFFERENT root causes — only one matches the classic async-count-flake model.
Each class has its own signature, diagnosis command, and fix.

## Class A — committed residue in the test DB (deterministic, NOT a flake)

**Signature:** exact-count assertions fail with the same delta on every seed,
and the failing file FAILS EVEN WHEN RUN ALONE:
`mix test test/path/file_test.exs` is red. That isolated failure is the
discriminator: sandbox rollback is fine; the DB itself is dirty.

**Cause:** rows committed OUTSIDE the sandbox — ad-hoc `MIX_ENV=test mix run
-e ...`, `MIX_ENV=test iex -S mix` debug sessions, or seeds. Sandbox rolls
back per-test writes, so nothing in the suite created them; they persist
across runs forever.

**Diagnose:**

```bash
MIX_ENV=test mix run -e '
  import Ecto.Query
  IO.inspect(Repo.all(from p in MyApp.Content.Page, select: {p.slug, p.page_type, p.created_by}))
  IO.inspect(Repo.all(from c in MyApp.Content.Context, select: c.slug))'
```

A load-bearing committed row is one many test files look up with no
create-fallback (e.g. `get_context_by_slug("personal")`) — deleting it would
red the suite, keeping it masks the residue. Delete stray rows; keep rows
other tests depend on, then harden the dependents (below).

**Fix:** delete the stale rows once, then harden the victim tests so residue
can't recur — exact-count tests against a shared context should run against a
FRESH context created per test (unique slug via
`System.unique_integer([:positive])`) in an inner `setup` inside the
`describe` block; it overrides the module-level `context:` key.

## Class B — zombie background tasks kill the shared sandbox connection

**Signature:**

```
DBConnection.OwnershipError: cannot find ownership process for #PID<...>
using mode :manual (Note that a connection's mode reverts to :manual if its
owner terminates.)
```

or `(EXIT) shutdown: %DBConnection.ConnectionError {message: "client #PID<...> exited"}`.
The failing test MIGRATES between files across seeds; each run fails 0–4
unrelated tests — whatever happens to own the connection next.

**Cause:** the app spawns `Task.Supervisor` tasks that touch the DB when an
async-schedule flag defaults to true. During a sync test the pool is in SHARED
mode, so the task checks out the test's connection; the task OUTLIVES the test,
and when `stop_owner` runs the connection is torn down under it. A task
mid-checkout takes the shared connection down with it — the next test's owner
dies and its next Repo call raises OwnershipError.

Smoking-gun log lines:

```
[error] Task #PID<...> started from #PID<...> terminating
** (EXIT) shutdown: ... "owner #PID<...> exited\n\nClient #PID<...> (Task.Supervised)
is still using a connection from owner at location: ..."
```

**Correlate the zombie with the in-flight test:** `mix test --seed N --trace`,
find the `[error] Task #PID` lines, and the nearest `* test ...` line above is
the test that was running (not necessarily the one that SPAWNED the task —
tasks accumulate across many tests and die in a batch when one owner stops).

**Fix (suite-wide, test-only).** Disable the app's background-task scheduling
via its OWN config key — this is project-specific app config, not an ExUnit
option (this example project calls it `:schedule_async` under `:inference`;
find the equivalent flag in your app before copying the shape):

```elixir
# test/test_helper.exs, after Sandbox.mode(MyApp.Repo, :manual)
base = Application.get_env(:my_app, :inference) || []
Application.put_env(:my_app, :inference, Keyword.put(base, :schedule_async, false))
```

Per-test `Application.put_env` blocks that omit `schedule_async` re-open the
window (the runtime default is `true`) — grep every `put_env(:my_app,
:inference, ...)` block and add `schedule_async: false` to the missing ones.
Verify no test asserts the async path first (`grep -n "schedule(" test/`).

## Class C — `async: true` DB-case modules race sync shared-mode windows

Any `async: true` module using DataCase/ConnCase calls `start_owner!` in its
setup even with zero Repo calls; that pool activity during a sync test's
shared-mode window corrupts ownership (same OwnershipError family). The sandbox
docs say: "If using shared mode in tests, make sure your tests are not async."
This is the ONE legitimate exception to "never flip async: false": pool-level
races, not count flakes.

Audit:

```bash
grep -rn "async: true" test/   # then check each file for DataCase/ConnCase usage
```

- Async module touches the DB → `async: false`.
- Async module NEVER touches the DB but uses DataCase/ConnCase only for
  imports (changeset tests, template rendering) → switch to
  `use ExUnit.Case, async: true` (keeps parallelism, drops the pool checkout).
- Pure `ExUnit.Case` async modules (no case template) are safe — leave them.

## Hunt recipe that worked

1. Run failing file alone → if it fails, class A (residue); dump the DB.
2. Full suite with 3+ different seeds; collect failing test names per run.
   Same set every seed = deterministic; migrating set = concurrency (B/C).
3. `grep -c "Task #PID" full_run.log` — zombie crashes are visible even in
   GREEN runs; >0 means class B exists even when luck made it pass.
4. `--trace` run to correlate crash timestamps with the in-flight test.
5. Fix, then re-hunt with 5 fresh seeds (not just the 3 that failed before) —
   the zombie class is probabilistic; one green run proves nothing.

## Verification

```bash
MIX_ENV=test mix ecto.drop && MIX_ENV=test mix ecto.create && MIX_ENV=test mix ecto.migrate
mix test                              # green again, same counts as before the wipe
grep -c "Task #PID" run.log           # expect 0
```