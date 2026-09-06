# Plan Review — Worked Example

A real plan review (umbrella foundation, 9 todos + 5 gaps) checked against
decisions D1-D20. Use it as a concrete checklist of how each drift class
looks in the wild.

## Sources of truth read

- Project + plan + every todo (full pages, not excerpts)
- Linked concept pages: architecture decisions (D1-D20 + schemas),
  security kickoff, performance kickoff, feature-flags

## Findings by drift class

| Class | Concrete example | Fix |
|---|---|---|
| Hashing | auth-portal used `Bcrypt.verify_pass`/`no_user_verify`; auth-communities used `Comeonin.Argon2.hashpwd`; D7 = Argon2 | Unify on `Argon2` (`hash_pwd_salt`/`verify_pass`/`no_user_verify`) |
| Schema field vs code | schema `Member.community_role` vs code `role` | Use `community_role` |
| Parent vs child status | a todo branched `%Domain{status: :suspended...}` — but Domain is only active/blocked; suspended/deleted/maintenance/draft belong to the RESOURCE community/landing | Branch on the resolved resource's status via `target_id` |
| ID type | `is_integer(member_id)` vs binary_id (UUID string) | `is_binary` + validate as binary_id |
| Duplicate artifact | `feature_flags` created in data-model (010) AND re-created in feature-flags-i18n with a different schema (`scope` vs D17 `target_type/target_id/meta`) | Don't re-create; use the data-model one |
| Nonexistent otp_app | Gettext `otp_app: :my_app` — no `:my_app` app exists (umbrella root) | `otp_app: :core` |
| Namespace | Mix of core, `OwnersWeb.*` (domains/flags), `AuthWeb.*` (auth-portal); D11 = plugs in core | Plugs in `Core.Plugs.*`; routers per app |
| Missing prerequisite | `MIX_ENV=prod mix release` in a VERIFY step without a `releases:` section in mix.exs | New todo for release infra |
| Inconsistent threshold | Rate limit 10/min (security) vs ">100 requests" in a verification step | 10/min |
| Env-sensitive flag | `secure: true` cookie breaks localhost dev | `secure: config_env() == :prod` |
| Role mapping | `RequireRole` matched `org_role in [:manager, :admin]` — but org_role is owner/collaborator; manager/admin are platform_role | Separate platform_role vs org_role |

## Gaps (decision referenced, no todo)

- Telemetry — in deliverable and gotcha, no todo → new todo
- Email/confirmation/password reset (`confirmed_at` exists in schema, no
  mailer) → new todo
- Concurrent sessions (schema exists, no logic) → new todo
- `bin/migrate` → new todo
- Prod seeds → new todo

## Hygiene

- 9 todos were in `in_progress` at once (auto-moved at creation) while the
  plan was "pending approval" → reset all to `backlog`.

## Tool quirks discovered (apply to your repo's equivalents)

- Creating a todo REQUIRES a `slug` even when the documented recipe lists
  only other fields.
- A list API combined `status` + `project_slug` filters and SILENTLY
  ignored the status filter — it returned all todos for `status: done`.
  Verify with the query without `project_slug`.
- The read API appends a footer (`--- Type: ... | Tags: ... | Version: N`)
  that is NOT part of the body — don't include it when reconstructing.
- Default context for the profile is `personal`; other named contexts
  belong to a different profile.

## Lesson

The plan looked perfect: 9 todos, consistent-looking snippets. Every
inconsistency surfaced only by holding each snippet against D1-D20 and
against siblings — which is exactly why plan review runs BEFORE execution,
not after.