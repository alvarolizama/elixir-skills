---
name: phoenix-ecto-cascade-deletes
description: "Handle Ecto/Postgres FK cascade deletes in Phoenix apps."
version: 1.0.0
author: Álvaro Lizama
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [elixir, phoenix, ecto, postgres, foreign-key, cascade, delete, data-integrity]
    related_skills: [systematic-debugging, phoenix-feature-removal, elixir-build-troubleshooting]
---

# Phoenix/Ecto Cascade Deletes

Use when deleting Ecto records that may have dependent children, when you see `Ecto.ConstraintError` mentioning a `*_fkey` constraint, when a `*_fkey` comment shows `datatype_mismatch` (FK type mismatch), or when designing a schema where parent removal must also clean up child rows. Also covers join tables connecting two parents with different primary-key types (int + uuid).

## Triggers

- `Ecto.ConstraintError` on delete with a `*_fkey` constraint name
- Need to delete a parent and its children in one operation
- Refactoring/removing a feature with dependent DB tables
- Auditing whether an existing `on_delete` is schema-only or also enforced at the DB level

## The Three Layers of a Correct Cascade

Ecto deletes pass through three independent layers. A robust fix touches all three when possible:

1. **Context function** — Explicitly delete dependent rows in a `Repo.transaction`, or rely on the schema's `on_delete`.
2. **Ecto schema** — Add `on_delete: :delete_all` (or `:nilify_all`) to the parent's `has_many`/`has_one`.
3. **Migration FK** — Add `on_delete: :delete_all` to the child's `references(...)` clause so the database enforces the cascade independently of Ecto.

A schema-only `on_delete` works for normal `Repo.delete` calls, but it does **not** protect against `Repo.delete_all`, raw SQL, future migrations, or direct DB operations. The migration FK is the ground truth.

## Workflow

When you hit a foreign-key constraint on delete:

1. Read the full stack trace and note the exact constraint name.
2. `search_files` the constraint name (or the failing event/handler) to find the deletion path.
3. Read the handler/context function, the parent schema, and the child migration.
4. Decide whether child rows should be deleted (`:delete_all`) or disowned (`:nilify_all`). Use this table:

   | Child table type | `on_delete` | Ecto atom | When |
   |---|---|---|---|
   | Join tables (M:N grants) | `CASCADE` | `:delete_all` | Join rows have no meaning without both parents |
   | Owned children (pricing, configs) | `CASCADE` | `:delete_all` | Child is entirely owned by parent |
   | Append-only / history / logs | `SET NULL` | `:nilify_all` | Must preserve the row for audit/analytics |
   | Referential integrity only | `RESTRICT` | `:restrict` | Prevent delete if children exist (force explicit cleanup) |
5. If history matters, prefer `:nilify_all` and archive manually; otherwise use `:delete_all`.
6. Implement the fix in this order:
   - Add a regression test that creates a child row and asserts the parent delete succeeds.
   - Update the migration to enforce the cascade at the DB level.
   - Add `on_delete` to the schema association.
   - Optionally wrap the context delete in a `Repo.transaction` that deletes children first for clarity.
7. Run `mix test` and `mix precommit` before declaring done.

## Pitfalls

- **Schema-only `on_delete`** — Will pass unit tests but fails in production when someone runs a raw delete or `delete_all`.
- **Missing transaction** — If you delete children in the context and the parent delete fails, you may leave orphaned rows. Use `Repo.transaction` or rely on the DB FK cascade.
- **Wrong direction** — Don't add `on_delete` to the `belongs_to` side; it belongs on the `has_many`/`has_one` side or the migration FK.
- **Migration order in `down`** — When writing a reversible migration that drops and re-adds the FK, make sure the `down` path restores the original constraint (or no constraint) exactly.
- **Tests without children** — A delete test that only creates the parent will not catch a missing cascade. Always create at least one dependent child in the regression test.
- **Partitioned tables need raw SQL** — Postgres partitioned tables (e.g. `PARTITION BY RANGE`) cannot use Ecto's `references(on_delete: ...)` in an `alter table` migration. You must drop and re-add the FK constraint with raw `execute` SQL: `ALTER TABLE t DROP CONSTRAINT IF EXISTS fk; ALTER TABLE t ADD CONSTRAINT fk FOREIGN KEY (...) REFERENCES (...) ON DELETE SET NULL;`. Use the two-argument `execute(up, down)` form so the migration is reversible.
- **Append-only/history tables — use `SET NULL`, not `DELETE`** — For log/audit tables that must never lose rows, use `ON DELETE SET NULL` (Ecto `:nilify_all`) instead of `ON DELETE CASCADE`. The parent record disappears but the historical row survives with a null FK. This is the right default for any table described as "append-only" or "source of truth".
- **Composite primary keys break `Repo.get/2`** — Partitioned tables often have composite PKs (e.g. `id` + `inserted_at`). `Repo.get/2` won't find a row by a single column. Use `Repo.get_by/2` with all PK fields, or `from(r in RequestLog, where: r.id == ^id and r.inserted_at == ^ts)`.
- **Deleting users with historical data (NOT NULL FK + partitioned append-only)** — a User → TeamMember → RequestLog chain where `request_logs.team_member_id` is `NOT NULL` and the table is partitioned (can't easily alter FK to `SET NULL`) makes hard-delete impossible without losing history. The cascade chain: `users` RESTRICT `team_members` RESTRICT `request_logs` (NOT NULL, partitioned). You can't `SET NULL` a NOT NULL column, and you can't `CASCADE` without losing all cost/analytics history. **Three options:** (1) **Soft-delete/anonymize** — set `status: "deleted"`, anonimize email/name, revoke API keys, suspend memberships. Logs keep pointing to the team_member which still exists. This is the safest default for apps with cost/usage analytics. (2) **Hard cascade** — change FK constraints to `ON DELETE CASCADE` on `team_members.user_id`, `api_keys.team_member_id`, and `request_logs.team_member_id` (raw SQL for partitioned tables). Use `ON DELETE SET NULL` for `audit_logs.user_id` (nullable — keeps audit trail, loses attribution). After migration, `Repo.delete(user)` cascades automatically at the DB level. Loses all cost history. Only if history doesn't matter. (3) **Transfer to ghost member** — reassign `request_logs.team_member_id` to a placeholder team_member before deleting the user. Complex and rarely worth it. **Before implementing, always present the tradeoff to the user** — "borrar usuario pierde todo el historial de consumo" vs "anonimizar conserva historial pero el user sigue en la DB".
- **Destructive cascade deletes need a modal, not `data-confirm`** — when a delete cascades across multiple tables (user + team_members + api_keys + request_logs), `data-confirm="¿Seguro?"` is insufficient. Use a DaisyUI `<dialog>` modal with: (1) an explicit list of what gets deleted, (2) "Esta acción es irreversible" warning, (3) two-event handler pattern: `open_delete_modal` (sets target assigns + `push_event("open_modal", ...)`) → `confirm_delete_user` (validates + deletes + `push_event("close_modal", ...)`). Add a `Modal` JS hook in `app.js` that listens for `open_modal`/`close_modal` events and calls `el.showModal()`/`el.close()`. Put `phx-hook="Modal"` on the `<dialog>` element. Full pattern in `references/MyApp-user-cascade-delete.md`.

## Reference Examples

See `references/mixed-fk-types-int-and-uuid.md` for join tables connecting different PK types (bigint vs uuid).

See `references/model-provider-pricing.md` for a worked example of cascade delete on a parent with pricing children.
