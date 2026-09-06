# Named singleton Registry/ETS leak across test files

## Symptom

The full suite fails N tests in a LiveView file with:

```
** (Ecto.Query.CastError) value `["cred-fail-new", "cred-open"]` cannot be
   dumped to type {:in, :binary_id} in query: ... where: c.id in ^[...]
```

The failing tests are green when run solo, red only when the whole suite runs.
The stack points at the LiveView's `mount/3` calling a Registry sweep.

## Mechanism

- A `Registry` with a fixed name is a VM-wide singleton shared across ALL test
  files. It is NOT reset between files — `Process.whereis(Registry) ||
  start_supervised!(Registry)` in one file's `setup` just reuses whatever
  earlier files registered.
- The leaking file registers entries with hand-written non-UUID strings
  (`"cred-open"`, `"cred-fail-new"`, ...) as keys, and can leave some in a
  non-default state that never gets cleaned up.
- Later, a DIFFERENT test file's LiveView mount calls a Registry sweep
  (`status_all/1`, `open_breakers/1`) that reads those keys and feeds them into
  `c.id in ^keys`. A `:binary_id` column refuses to dump non-UUID strings →
  CastError.
- The bug appears only after production adds the sweep; before that, the
  LiveView loaded credentials from the DB and filtered in memory, so leaked
  junk never reached Ecto.

## Why this is sneaky

- It's **cross-file**, not just cross-test — no `async` scoping, DB cleanup,
  or `on_exit` in the failing file can help. The fix lives in a DIFFERENT
  file.
- It's a **regression by unrelated change**: the "broken" test didn't change;
  production code added a Registry sweep that started reading shared state.

## Fix (test-only — never change production code to satisfy tests)

Edit the **leaking** file so every key it registers is domain-shaped,
matching what production actually uses. For `:binary_id` credentials that's
`Ecto.UUID.generate()`:

```elixir
# Credential ids are :binary_id (UUIDs) in production, and the breaker
# Registry is a named singleton shared across test files. Using real UUIDs
# here means any breaker left registered (e.g. left open by a test) stays
# castable by Ecto in other LiveView tests that sweep the Registry
# (status_all/open_breakers) — a string like "cred-open" would fail to dump
# to :binary_id and poison those tests.
defp credential, do: Ecto.UUID.generate()
```

Then replace every `credential = "cred-foo"` / inline `"cred-foo"` in that
file with `credential()`. Where one credential is reused across assertions in
a test, bind it once (`credential = credential()`) so all calls share the
same id.

## Why it works

A leaked UUID is still a valid `:binary_id`, so `c.id in ^[uuid]` casts fine
and simply matches no DB row → the sweep returns nothing → harmless. A leaked
non-UUID string crashes the query.

## Verification

```bash
mix test test/<leaking>_manager_test.exs test/.../live/<page>_live_test.exs
# cross-file contamination gone: both green when run TOGETHER
mix test          # full suite green
```

Run the two involved test files together (the leaking one + the LiveView one)
to confirm the cross-file contamination is gone, then the full suite.