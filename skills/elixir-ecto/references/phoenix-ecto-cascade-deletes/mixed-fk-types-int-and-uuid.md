# Mixed Foreign-Key Types in a Join Table (int parent + uuid parent)

When one parent table uses the default `:id` (bigint) primary key and the other uses
`:binary_id` (uuid), a join schema in between must handle THREE separate type declarations
that Ecto does NOT auto-reconcile. Forget any one and you get a distinct failure.

## The situation

```elixir
# Parent A — default PK (bigint)
defmodule MyApp.Accounts.User do
  use Ecto.Schema
  schema "users" do ... end            # @primary_key :id (bigint)
end

# Parent B — binary_id PK (uuid, gen_random_uuid())
defmodule MyApp.Brain.Context do
  use Ecto.Schema
  @primary_key {:id, :binary_id, read_after_writes: true}
  @foreign_key_type :binary_id
  schema "contexts" do ... end        # id = uuid
end

# Join schema — the one that breaks
defmodule MyApp.Accounts.UserContext do
  use Ecto.Schema
  schema "user_contexts" do
    belongs_to :user, my_app.Accounts.User          # user_id → bigint
    belongs_to :context, my_app.Brain.Context        # context_id → uuid
  end
end
```

## Two independent failures and their fixes

### Failure 1 — Migration `datatype_mismatch` (bigint vs uuid)

```sql
ERROR 42804 (datatype_mismatch) foreign key constraint "user_contexts_context_id_fkey"
cannot be implemented
Key columns "context_id" of the referencing table and "id" of the referenced table
are of incompatible types: bigint and uuid.
```

`references(:contexts)` in a migration infers the column type from the parent schema's
`@foreign_key_type`. If the join schema's own `@foreign_key_type` is the default `:id`
(or the type isn't picked up), the FK column is created as `bigint` and can't reference
a `uuid` PK.

**Fix (migration):** pass the type explicitly:

```elixir
add :context_id, references(:contexts, type: :binary_id, on_delete: :delete_all), null: false
```

This failure appears EVERY test run / sandbox setup, because tests replay migrations,
so it may surface as a `Postgrex.Error` during `mix test` in `Ecto.Migration.Runner`
rather than at app startup.

### Failure 2 — Changeset cast failure (`is invalid, type: :id`)

After the migration is fixed, inserts still fail at the Ecto layer:

```
errors: [context_id: {"is invalid", [type: :id, validation: :cast]}]
```

`belongs_to` field types come from the DEFINING schema's `@foreign_key_type`
(default `:id`), NOT from the referenced schema's PK. So `context_id` gets `:id`
(bigint) and refuses to cast the binary uuid value you pass in.

**Fix (join schema):** `@foreign_key_type` is module-wide, so you can't set it to
`:binary_id` (that would wrongly re-type `user_id` too). Instead, declare the field
type explicitly and tell `belongs_to` not to redefine it:

```elixir
schema "user_contexts" do
  belongs_to :user, my_app.Accounts.User               # stays :id (bigint)
  field :context_id, :binary_id                       # declare the mixed type first
  belongs_to :context, my_app.Brain.Context, define_field: false  # reuse it
end
```

Both `belongs_to` associations still work normally; only the join-column field type is
overridden. `cast(attrs, [:user_id, :context_id])` then accepts the uuid. Keep
`unique_constraint([:user_id, :context_id])` untouched.

## Key takeaways

- One schema mixing FK types needs **three** coordinated declarations: the migration
  `references(..., type: :binary_id)`, the `field :context_id, :binary_id`, and
  `belongs_to ..., define_field: false`.
- `@foreign_key_type` is per-module — use it to set the common case, and `define_field: false`
  + explicit `field` for the outlier.
- Distinguish the two errors by where they originate: DDL/migration error = migration
  type hint; changeset cast error = schema field type.
- Tests are the fastest way to catch these: a join/assoc test (`add_user_to_context`)
  exercising an actual insert exercises both the migration and the schema cast.
