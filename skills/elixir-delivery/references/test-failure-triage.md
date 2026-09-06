# Test-Failure Triage — three-way verdict, flake loop, contamination

Symptom: the full suite reports failures during a delivery wave. Mechanism:
a failing test has exactly three possible owners — the environment, a stale
expectation that encodes the CORRECT contract, or a product decision nobody
made yet. Treating it as a two-way (mine / preexisting) call gets two of the
three wrong.

## Step 1 — is it preexisting or introduced?

A failure is preexisting (not introduced by the wave) when:

- The test file AND the production code path it exercises are untouched by
  the diff (e.g. the assertion depends on a config key the wave never
  touched), or
- It reproduces on HEAD isolated:

  ```bash
  git stash -u
  mix test test/my_app/some_test.exs     # only the suspect files
  git stash pop
  ```

## Stash-baseline pitfall

If the test DB already has the wave's migrations applied, HEAD runs OLD code
against the NEW schema — HEAD then fails spuriously on anything querying
dropped columns (~a handful of dashboard/knowledge failures that exist only
under the stash). Read the individual HEAD failures and discard
schema-mismatch noise. Only same-named tests failing for the SAME reason
count as evidence.

## Step 2 — the three-way verdict on preexisting failures

1. **Environmental** — contaminated test DB, sandbox races that pass
   isolated (`DBConnection.OwnershipError` from `ExUnit.OnExitHandler` that
   passes 17/17 alone but fails under the full suite). Disposition: report,
   don't touch.
2. **Stale expectation encoding the CORRECT contract** — production drifted
   (renamed key, changed return shape) and the test still asserts the old
   behavior. The red test is the only symptom of a latent bug. Real shape of
   this: config still fires `run_scheduled(:community_summaries_nightly)`
   after a communities→clusters rename while the job runner raises
   "unknown job" — a nightly job was crashing, found only through the test.
   Disposition: fix production + test together in a SEPARATE scoped
   `fix:` commit, never mixed into the feature wave.
3. **Product decision** — the test asserts a UI element a prior refactor
   removed. Disposition: report and ask the user which side is right; don't
   guess, don't silently update the test.

Every triaged failure ends with one of these three labels and evidence for
it.

## Flake confirmation loop

One failure out of ~900:

```bash
mix test                       # run 1: 890/891, one failure
mix test --failed              # re-runs only the failure → passes
mix test                       # run 2 full: 891 passed → confirmed flake
```

Only failures reproducing in BOTH full runs enter triage. Never patch code
for a single-run failure (verified).

## Test-DB contamination

A test database keeps rows written outside the sandbox (seeds run against
it, earlier tooling). Symptom: tests tagged to expect an EMPTY instance fail
seeing leaked rows; the rendered dashboard literally shows extra workspaces
and pages.

Confirm:

```bash
psql -h localhost -U <user> -d my_app_test -t -c "select count(*) from workspaces"
```

These failures are environmental — never "fix" the tests as if they were
broken. Validated cleanup:

```bash
MIX_ENV=test mix ecto.drop
```

The next `mix test` recreates and migrates from scratch; contaminated-file
failures vanish and what remains is real drift. Re-run only the
previously-failing files afterwards to confirm (verified).

## Verification

- Every failure has a disposition label (environmental / contract-drift
  fix / product decision / confirmed flake) with evidence.
- Contract-drift fixes live in their own scoped `fix:` commit.
- After cleanup or fixes: re-run of the previously-failing files passes.
- Final full run count recorded (e.g. `892 passed / 1 skipped`).
