# Stale tests left behind by a PAST feature removal

Symptom: `mix test` fails on a LiveView test asserting
`has_element?(view, "#some-id")` (or `refute`) for a DOM id that no longer
appears in any template. The suite was green before someone removed the UI —
you did NOT remove anything this session.

## Diagnose (confirm it's stale, not a regression)

1. `search_files(pattern="some-id", path="lib/")` → 0 template hits means the
   element is gone from the UI (it exists only in the test file).
2. `git log --oneline -S "some-id" --all` → returns the exact commit that
   removed the element; the surrounding commit message names the feature
   (e.g. `f9e8d86 monitor: remove alert tables...`).
3. `git show <sha> --stat` → if that commit touched the template but NOT the
   test file, the tests are orphans (the removal commit forgot to delete them).

## Fix: DELETE, don't patch

- Delete the stale tests. The `assert has_element?` variants fail; the sibling
  `refute has_element?` on the same removed id **passes vacuously** (refuting a
  nonexistent element) — it's green-but-dead, so sweep the whole cluster, not
  just the failing lines.
- Delete the now-unused fixtures (e.g. `broke_member_fixture`, `log_spend`)
  and any `alias` that only those fixtures/tests consumed — otherwise
  `mix compile --warnings-as-errors` flags the unused alias.
- Re-run `mix test test/…/<file>` → confirm the reduced count; `mix test` full
  → confirm the pre-existing failures are gone.

## Real case (my_app_gateway, 2026-08)

`f9e8d86 monitor: remove alert tables...` removed the circuit-breaker,
budget-exhausted, and error-credentials alert tables from the monitor page,
but left `MonitorLiveTest` asserting `#alert-budget-<id>`. Result: 2 tests
failed (`#alert-budget-…` not found), a 3rd (`refute`) passed vacuously.
Fix: deleted all 3 + the 2 fixtures + the unused `alias my_app_gateway.Accounts` →
suite went `4/6` → `3 passed`, full suite `836 passed, 0 failures`.
