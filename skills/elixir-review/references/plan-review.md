# Implementation Plan Review

Audit a plan (with its linked todos/specs) BEFORE executing it, to catch
inconsistencies between the code snippets each todo carries and against the
authoritative design. Snippets are written independently and drift: the
plan looks perfect until one todo's code contradicts another's or the
decisions.

## When to use

- "Review the plan and todos to see if something is missing or could
  improve"
- Before starting a multi-todo plan where each todo carries code snippets
- After a plan was created by another agent, before approving/executing it

## Guiding principle

The design pages linked to the plan (architecture decisions, security,
performance, feature concepts) are the **source of truth**. Each todo's
snippet is cross-checked against them AND against sibling todos. A todo
snippet NEVER wins over the decision page.

## Flow

1. Read project + plan.
2. Read ALL linked todos (full pages — never search excerpts).
3. Read authoritative design pages (decisions, security, performance).
4. Cross-check snippets by drift class (below).
5. Check plan deliverable vs todos — a referenced decision with no todo
   implementing it = gap.
6. Check kanban hygiene: one `in_progress` per person; `done` only with
   real verification; new todos in `backlog` (not auto-moved) while the
   plan is pending approval.
7. Present prioritized findings (A: compile/design, B: gaps, C:
   housekeeping). Confirm before applying.

## Snippet drift classes (concrete checklist)

For each snippet, compare against the decision AND against siblings:

1. **Hashing/auth libraries** — Argon2 vs Bcrypt vs Comeonin drift
   (`Bcrypt.verify_pass` in one todo, `Comeonin.Argon2.hashpwd` in
   another). Unify on ONE, per the decision.
2. **Schema field names vs code** — `role` vs `community_role`,
   `verification_token` vs `token`. The schema is the truth.
3. **Status enums conflated** — parent-domain status (`active/blocked`)
   vs child-resource status (`active/suspended/deleted/maintenance/draft`)
   must NOT be conflated; branch on the resolved resource's status via its
   `target_id`.
4. **ID types** — `binary_id` (UUID string) vs `integer`; `is_integer`
   checks on a binary_id fail. Validate with `is_binary` for UUIDs.
5. **Duplicate artifacts** — the same table/schema/migration created in 2
   different todos, possibly with different schemas. Never re-create; use
   the one from the data-model todo.
6. **otp_app / nonexistent apps** — `otp_app` pointing at the umbrella
   root (`:root_app` doesn't exist) or a nonexistent app instead of the
   real owning app (e.g. gettext config with `otp_app: :umbrella_root` —
   should be `:core`).
7. **Module namespaces** — mixing `AppWeb.*` with a nonexistent shared
   namespace. Shared plugs live in core (`X.Plugs.*`); each web app has
   its own namespace; routers per app.
8. **Verification prerequisites** — a VERIFY step depending on something
   no todo creates (e.g. `MIX_ENV=prod mix release` without a `releases:`
   section in mix.exs). That's a new todo, not a working VERIFY.
9. **Inconsistent thresholds/flags** — rate limits (10/min vs ">100
   requests"), session limits, TTLs differing between todos, and between
   todo and concept.
10. **Env-sensitive flags** — `secure: true` cookies break localhost dev;
    must be conditional: `secure: config_env() == :prod`.
11. **Role mapping errors** — roles conflated across dimensions:
    `org_role in [:manager, :admin]` when org_role is owner/collaborator
    and manager/admin belong to platform_role.

## Gaps: plan deliverable vs todos

The plan's deliverable lists what it produces. If a decision is REFERENCED
(in deliverable, gotcha) but no todo implements it → gap. Classics:
telemetry, email/confirmation/password reset, session limits, `bin/migrate`,
prod seeds. Decide: new todo, or merge into an existing one.

## Kanban hygiene

- One `in_progress` at a time PER PERSON. If the plan is "pending
  approval", todos auto-moved to `in_progress` when created must go back
  to `backlog`.
- `done` only with real verification (tests/compile/hash match — not "I
  think it works").
- New todos land in `backlog` while the plan isn't approved.

## Applying corrections

- **Bodies**: when a review fix touches a document body, pass ONLY the
  body (never meta+body together — a rich editor re-parses and strips
  mermaid blocks). Reconstruct the full body with the fixes; any footer
  the read API appends (e.g. a `--- Type: ... | Tags: ... | Version: N`
  line) is NOT part of the body.
- **Create todos**: `slug` is mandatory; new ones go to `backlog`.
- **Status**: update todo status with the todo update API (merged meta),
  never by rewriting the page body.
- **Verify**: re-read every edited page → confirm mermaid preserved and
  content correct.

## Pitfalls

- **Answering from search excerpts** — read the full pages first.
- **Trusting a todo's snippet over the decision page** — snippets drift;
  the decision wins.
- **Reconstructing bodies with a footer** that isn't part of the body.
- **List-API filter combinations** — some list endpoints ignore a status
  filter when combined with another filter (e.g. `status` + `project_slug`
  returned all todos for `status: done`); verify with the query without
  the second filter.
- **Applying corrections without verifying** — re-read each edited page,
  confirm mermaid preserved and content correct.
- **Body size fear** — bodies of ~10-15KB pass fine in one tool call;
  batching parallel edits is OK.