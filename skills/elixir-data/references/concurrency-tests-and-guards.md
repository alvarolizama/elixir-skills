# Concurrency Tests & Constraint Guards Under the Sandbox

Honest testing of row locks and constraint behavior when the Ecto SQL Sandbox
serializes concurrent work. The trap: a race test that "passes" proves the
path, not the race.

## Locks: verified by construction, not by a serialized test

The sandbox gives every test the SAME single connection; concurrent Tasks in a
`async: false` test are serialized onto that one connection. A race test with
two parallel "closes" passes WITH AND WITHOUT the
`lock: "FOR UPDATE"` clause — it validates the code path, not the locking.

What to do instead:

1. **Verify by construction**: analyze the interleaving on paper — two
   transactions, both read the row, both pass the guard, first commits, second
   tries to write → without `FOR UPDATE` the second overwrites the first's
   decision; with `FOR UPDATE` the second blocks until the first commits, then
   re-reads the row.
2. Document that reasoning IN the test:
   `# row lock verified by construction (interleaving A/B below) — the sandbox
   # serializes concurrent queries, so this test exercises the path, not the race`.
3. Never claim "the test proves the lock". Claim "the lock is correct by
   construction; the test guards the path against regressions".

If you truly need to exercise a race against real Postgres concurrency,
that requires parallel connections outside the sandbox (separate DB or a
postgres-backed runner) — the sandbox cannot do it.

## Deck-style constraint tests are fine — assert the mechanism

- **DDL is transactional in Postgres** — sandbox rollback covers partition DDL;
  no cleanup needed after partition tests (`async: false`).
- **FK constraint errors** surface through `Ecto.ConstraintError` /
  changeset `constraint/3` checks — a test that only creates the parent won't
  catch a missing cascade; build the child + dependents first.

## Dead-guard detection

A `foreign_key_constraint/3` naming a `SET NULL`/`nilify` FK can never fire.
The test suite passing with the old "id was nulled" assertion was the evidence
the FK never protected anything — when you remove the FK, flip the assertions
to "id preserved" and re-run the full suite.

## Partition test specifics

- `async: false` — partition structure is shared state.
- Far dates (`~D[2099-03-01]`, `~D[2020-06-15]`) — never collide with
  real-date partitions.
- Boot ensure disabled in test env (`config :my_app, :partition_boot_ensure, false`)
  — fixtures insert arbitrary historical dates that must stay in the default
  partition.
- Direct row inserts without the FK fixture chain must use
  `Ecto.UUID.dump!(Ecto.UUID.generate())` (binary form) — the canonical string
  raises `DBConnection.EncodeError`.

## Verification

- Race tests note "verified by construction" in a comment and pass on the path.
- Full suite green after flipping constraint assertions.
- `mix test` clean with the boot-ensure-disabled config.