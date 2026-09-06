# Review-Fix Recommendations

How to turn confirmed review findings into an executable fix plan — the
output shape when a review ends with "here's what to change".

## Structure

1. **Prioritized findings** in three tiers:
   - **A — Compile/design blockers**: crashes, dead code that hides bugs,
     schema/decision violations. Fix first.
   - **B — Gaps**: referenced decisions with no implementing todo.
   - **C — Housekeeping**: hygiene that doesn't block (backlog statuses,
     missing specs, nits).
2. **Ordering** — by decision dependency, not by finding number: a schema
   change comes before the code that consumes it.
3. **Verification command per fix** — each fix carries the command that
   proves it (`mix test path/to_test.exs`, `mix compile
   --warnings-as-errors`, hash check, `iex -S mix` reproduction).

## Fix shape per finding

- **Exact file**: as found in the read, with line numbers.
- **Exact fix**: a code/snippet/SQL change, not a description of one.
- **Verification**: command + expected output shape.

Example:

| Finding | File:line | Fix | Verify |
|---|---|---|---|
| ERR-04 unreachable branch | `lib/my_app/accounts.ex:12` | Replace `case` with `with %Account{} = cr <- Repo.get(...)` | `mix test test/my_app/accounts_test.exs` → 3 passing |
| PF-01 missing index | `priv/repo/migrations/2026_migration.exs:9` | Add `create index(:context_templates, [:workflow_config_id])` | `mix ecto.migrations` applies; `mix ecto.rollback && mix ecto.migrate` clean |

## Writing the fix plan (bulk)

When the review produced 3+ fixes, don't apply them one by one with
re-reads in between — batch by region and verify by hash:

- Apply per region: all fixes to one file/section in one pass.
- After each pass, re-read the region and confirm every needle is present
  and the structure (mermaid blocks, headers) is intact.
- After 2 failed patch attempts on the SAME region, stop patching and
  rewrite the whole function/file in one pass — repeated partial edits
  compound risk.

## Reporting the plan to the requester

- Summarize by tier, not by file: "1 compile blocker, 3 gaps, 2
  housekeeping" reads better than 6 file-by-file entries.
- Explicitly state what is NOT being changed and why, so the requester can
  object.
- Always end with the confirm step: the plan is applied only after
  explicit approval.