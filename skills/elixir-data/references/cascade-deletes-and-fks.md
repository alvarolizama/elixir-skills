# Cascade Deletes & FK Design

When a delete raises a constraint error, or you are choosing `on_delete`
policy. Symptom first, then the three layers, the decision table, and the
special shapes (discriminated subjects, mixed FK types, confirmation modal).

## Symptom

```elixir
** (Ecto.ConstraintError) constraint error when attempting to delete struct:
* "pricing_provider_id_fkey" (foreign_key_constraint)
```

This means a missing cascade rule at one of the three layers. Fixing only one
layer leaves the DB unprotected — always enforce at the migration level too.

## The three layers of a correct cascade

1. **Context function** — delete dependents in `Repo.transaction`, or rely on
   schema `on_delete`.
2. **Ecto schema** — `on_delete: :delete_all` (or `:nilify_all`) on
   `has_many`/`has_one`. Schema-only `on_delete` works for `Repo.delete` but
   NOT `Repo.delete_all`, raw SQL, or direct DB operations.
3. **Migration FK** — `on_delete: :delete_all` in the child's
   `references(...)` — the ground truth.

## Decision table

| Child table type | `on_delete` | When |
|---|---|---|
| Join tables (M:N) | `:delete_all` | Rows have no meaning without both parents |
| Owned children | `:delete_all` | Entirely owned by parent |
| Append-only / audit | `:nilify_all` | Must preserve row for history |
| Referential only | `:restrict` | Force explicit cleanup |

History tables use `SET NULL`, not `DELETE` — the parent disappears but the
audit row survives (attribution may be lost, which is acceptable).

## Workflow

1. Read the stack trace → note the constraint name.
2. Search the codebase for the constraint name → find the deletion path.
3. Decide delete vs nilify vs restrict (decision table above).
4. Add a regression test: create the child, assert parent delete succeeds.
   A test that creates only the parent won't catch a missing cascade — the
   test must create the parent + child + grandchild rows first.
5. Update the migration FK.
6. Add `on_delete` to the schema association.
7. `mix test && mix precommit`.

## Pitfalls

- **Schema-only `on_delete`** — passes tests, fails production raw deletes.
- **Missing transaction** — orphaned rows if parent delete fails after child delete.
- **Wrong direction** — `on_delete` goes on `has_many`/`has_one`, NOT `belongs_to`.
- **Partitioned tables** — Ecto's `references(on_delete: ...)` in `alter table`
  doesn't work; use raw two-argument `execute/2` for reversibility:
  `ALTER TABLE <child> DROP CONSTRAINT IF EXISTS ...;` +
  `ALTER TABLE <child> ADD CONSTRAINT ... FOREIGN KEY (...) REFERENCES ... ON DELETE CASCADE;`
- **Composite PKs break `Repo.get/2`** — use `Repo.get_by/2` with all PK fields.
- **User deletion with NOT NULL FKs** — present the tradeoff: hard cascade
  (loses history) vs soft-delete/anonymize (preserves history) vs transferring the rows to an anonymous owner. This is a product decision, not a plumbing one.
- **Destructive cascades need a confirmation modal** — `data-confirm` is
  insufficient; use a `<dialog>` modal listing exactly what gets deleted, with
  a two-event handler pattern:

```elixir
def handle_event("open_delete_modal", %{"id" => user_id, "email" => email}, socket) do
  {:noreply,
   socket
   |> assign(:delete_target_id, user_id)
   |> assign(:delete_target_email, email)
   |> push_event("open_modal", %{id: "delete-user-modal"})}
end

def handle_event("confirm_delete_user", %{"id" => user_id}, socket) do
  user = Accounts.get_user!(user_id)
  cond do
    root_admin?(user) -> {:noreply, put_flash(socket, :error, "...")}
    user.id == socket.assigns.current_user.id -> {:noreply, put_flash(socket, :error, "...")}
    true ->
      case Accounts.delete_user(user) do
        {:ok, _} -> {:noreply, socket |> put_flash(:info, "...") |> push_event("close_modal", %{id: "delete-user-modal"}) |> load_users()}
        {:error, _} -> {:noreply, put_flash(socket, :error, "...")}
      end
  end
end
```

Repeated protection checks in the confirm handler (defense-in-depth): root
admin cannot be deleted, self-delete prevented, both re-validated server-side.

## Discriminated subject types — never overload one FK column

The rule: one FK column references exactly ONE table. When a row can belong
to two kinds of subjects, overloading the column (primary id OR secondary
id) breaks silently:

- Inserts for the secondary kind violate the real FK.
- If writes go through an async worker with retries-then-drop, nothing
  raises in the hot path: rows simply never appear and downstream stats
  show zero for that kind.

Diagnose by probing the DB directly — never trust "it should be logged":

```sql
-- reproduce with a manual INSERT of the suspect id into the FK column
INSERT INTO events (id, owner_id, inserted_at)
VALUES (gen_random_uuid(), '<suspect_id>', now());
-- ERROR: violates foreign key constraint "events_owner_id_fkey"
```

Fix — the discriminated subject pattern:

1. Migration (partitioned tables → raw SQL): `DROP NOT NULL` the overloaded
   FK; add one uuid FK column per secondary subject kind (each
   `ON DELETE CASCADE`); add a `subject_type varchar NOT NULL DEFAULT
   '<primary kind>'` discriminator; index each secondary column with the
   usual sort column. KEEP the original FK — FKs allow NULL, so it still
   cascades for primary-kind rows and passes for secondary-kind rows.
2. Schema: `field :subject_type` (default primary kind) plus `belongs_to`
   per secondary kind. The DB no longer enforces NOT NULL, so the changeset
   must: conditional `validate_required` per `subject_type` value.
3. Write path: derive `{subject_type, owner_id, secondary_id}` from the
   subject struct; thread them through async worker args and preloads.
4. Consumers keying by a single shared id space must combine filters:
   `where(r, r.owner_id == ^id or r.secondary_id == ^id)`.
5. Blast radius: every query that assumed the overloaded column switches to
   the right column. Queries JOINing on the primary table stay naturally
   correct — secondary rows have NULL there and inner joins exclude them.

## Mixed FK types (int parent + uuid parent) in a join schema

One schema mixing FK types needs THREE coordinated declarations — Ecto does not
auto-reconcile them, and forgetting any one yields a distinct failure:

1. **Migration** — `references(:contexts)` infers the column type from the
   parent schema; without an explicit type the FK column is `bigint` and can't
   reference a `uuid` PK:
   `add :context_id, references(:contexts, type: :binary_id, on_delete: :delete_all), null: false`
   Missing → `ERROR 42804 (datatype_mismatch) foreign key constraint
   "user_contexts_context_id_fkey" cannot be implemented ... bigint and uuid`.
2. **Join schema field** — `belongs_to` field types come from the DEFINING
   schema's `@foreign_key_type` (default `:id`), NOT from the referenced
   schema. Declare the outlier first:
   `field :context_id, :binary_id`, then `belongs_to :context, Context, define_field: false`.
   Missing → changeset `{context_id: {"is invalid", [type: :id, validation: :cast]}}`.
3. `@foreign_key_type` is module-wide — it sets the common case; the outlier
   uses explicit `field` + `define_field: false`.

Distinguish the errors by origin: DDL/migration error = migration type hint;
changeset cast error = schema field type. Tests replay migrations on every
sandbox setup, so the DDL failure surfaces as `Postgrex.Error` during
`mix test` — a join test that actually inserts exercises both layers.

## Verification

- Regression test creates parent + child + dependent rows, then asserts:
  parent gone, children gone (`refute Repo.get(Child, id)`).
- `mix ecto.migrate` (test env auto-migrates).
- `mix test <file>` then full `mix precommit`.