# Adversarial Review Protocol

The posture rulebook for reviewing code, plans, and fixes that will be
executed. Applies to every review, including self-review of your own work.

> Scope: this is the general reviewer protocol. The delivery-side
> pre-commit dispatch gate built on it (delegation, death protocol,
> verdict recovery) lives in
> `skills/elixir-delivery/references/adversarial-review-gate.md`.

## Core principle: who writes does not self-approve

The author's own plan/code gets the same adversarial pass as anyone else's.
The reviewer's loyalty is to the repository and its decision pages, not to
the author's confidence. If you wrote it, review it as a stranger would:
read the real files, don't rely on memory of what you intended.

## Blocking criteria (any one = reject or hold the change)

1. **Secrets or credentials** — passwords, API keys, tokens, or URLs
   containing credentials in code, config, or tests. Includes hardcoded
   test creds.
2. **Debug leftovers** — `IO.inspect`, `dbg`, `Logger.info` noise,
   commented-out blocks that look like scratch work.
3. **Migration/structure.sql drift** — the schema changed but
   `priv/repo/structure.sql` is stale, or a migration references a
   table/column another migration in the same wave drops/renames.
4. **Missing module references** — code calling modules, functions, or
   fields that don't exist in the diff or in the codebase.

## Validate-and-extend before fixing

When a buggy function must be fixed, never fix from inspection alone:

1. **Reproduce the bug yourself** — run the failing scenario (test,
   `iex -S mix` call, or query) and confirm the failure signature.
2. **Grep the consumers of the buggy function** — all arities, across
   `lib/`, `test/`, and templates:
   ```bash
   grep -rn "buggy_fn" lib/ test/ | grep -v 'def buggy_fn'
   ```
   A "fix" that changes behavior callers depend on is a new bug.
3. Fix, then re-run the reproduction and the consumers' tests.

## Blast-radius enumeration

Before proposing any change, enumerate:

- every consumer of the changed function/module (callers across apps in an
  umbrella; template usages);
- every test touching the changed surface;
- every config/key/DB column affected.

The blast radius is part of the finding: a one-line fix that touches 11
callers is a medium-sized refactor, not a nit.

## Read-before-conclude

Never answer from search excerpts, diffs alone, or summaries. Read the
FULL page/file before judging it. A half-read file produces
not-confirmed findings; a confirmed finding needs the evidence in hand.

## From findings to the fix plan

When a review ends with "here's what to change", the deliverable is an
executable fix plan, not a prose list:

1. **Prioritize into three tiers** — **A: compile/design blockers**
   (crashes, dead code that hides bugs, schema/decision violations) fix
   first; **B: gaps** (referenced decisions with no implementing todo);
   **C: housekeeping** (missing specs, backlog hygiene, nits).
2. **Order by decision dependency, not by finding number** — a schema
   change comes before the code that consumes it.
3. **Exact fix shape per finding** — exact file:line as found in the read;
   the exact code/snippet/SQL change (not a description of one); one
   verification command per fix with its expected output shape
   (`mix test path/to/test.exs`, `mix compile --warnings-as-errors`, hash
   check, `iex -S mix` reproduction).

| Finding | File:line | Fix | Verify |
|---|---|---|---|
| ERR-04 unreachable branch | `lib/my_app/accounts.ex:12` | Replace `case` with `with %Account{} = cr <- Repo.get(...)` | `mix test test/my_app/accounts_test.exs` → 3 passing |
| PF-01 missing index | `priv/repo/migrations/20260101_migration.exs:9` | Add `create index(:context_templates, [:workflow_config_id])` | `mix ecto.migrations` applies; `mix ecto.rollback && mix ecto.migrate` clean |

Report by tier, not by file — "1 compile blocker, 3 gaps, 2 housekeeping"
reads better than six file-by-file entries. State explicitly what is NOT
being changed and why, and end with the confirm step: the plan is applied
only after explicit approval. When the plan carries 3+ fixes to documents,
apply them with the bulk-edit recipe (`bulk-edit-safety.md`): batch by
region, hash-verify each pass, and after 2 failed patch attempts on the
SAME region rewrite the whole file in one pass — repeated partial edits
compound risk.

## Confirm before applying

Review output is advisory until the requester approves. Present findings
prioritized (A: compile/design blockers, B: gaps, C: housekeeping), wait
for confirmation, then apply. Applying unconfirmed corrections is itself a
review violation.

## Reporting shape

Per finding: `RULE-ID (severity) + file:line + one-line why + the fix`.
Only verified findings — never guess, never invent file:line. If a
suspicion can't be verified, label it as unverified suspicion, not a
finding.