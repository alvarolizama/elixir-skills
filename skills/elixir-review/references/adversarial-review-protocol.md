# Adversarial Review Protocol

The posture rulebook for reviewing code, plans, and fixes that will be
executed. Applies to every review, including self-review of your own work.

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