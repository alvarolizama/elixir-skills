# Ecto Migration & Schema Pitfalls

Generic Ecto/PostgreSQL pitfalls encountered while implementing domain
schemas, migrations, and context functions. These apply to any Ecto
project, not just umbrella apps.

## 1. Partial unique indexes block same-transaction UPDATE→INSERT (CRITICAL)

**Symptom:** You have a partial unique index like:

```elixir
create unique_index(:api_keys, [:team_member_id], where: "status = 'active'")
```

You write a `replace_api_key/1` function that uses `Ecto.Multi` to:
1. `update_all` — set existing active key's `status` to `"revoked"`
2. `insert` — create a new row with `status = "active"` for the same `team_member_id`

Both inside a single `Repo.transaction`. The INSERT fails with:

```
ERROR 23505 (unique_violation) duplicate key value violates unique constraint "api_keys_team_member_id_index"
```

**Even though** the `update_all` matched and revoked 1 row, and `psql` confirms
the status is now `"revoked"`.

**Root cause:** PostgreSQL's partial unique index does NOT immediately free
the index entry when you UPDATE the row's `status` from `"active"` to
`"revoked"` within the same transaction. The old row version's index entry
persists until the transaction commits and HOT-update pruning runs. So the
new INSERT's `WHERE status = 'active'` predicate matches the *intent* but
the index still has the old entry blocking it.

This is NOT a sandbox artifact — it reproduces in `:auto` sandbox mode,
`:manual` sandbox mode, and even outside tests (verified in `iex -S mix`).
Raw `psql` with a standalone `BEGIN/COMMIT` transaction works because
there's no enclosing sandbox transaction — but that's not how Ecto tests work.

**Fix — three options, pick based on your constraint requirements:**

### Option A: In-place UPDATE (recommended when one row per parent is acceptable)

If the spec says "UNIQUE — one key per team_member" (not "one *active*
key"), use a non-partial unique index on `team_member_id` and implement
`replace_api_key` as an in-place UPDATE of the existing row's `key_hash`
and `key_prefix`:

```elixir
def replace_api_key(%TeamMember{} = team_member) do
  {new_token, new_hash, new_prefix} = generate_api_key_material()
  team_member = Repo.preload(team_member, [:api_key])

  Ecto.Multi.new()
  |> Ecto.Multi.update(:api_key, fn _ ->
    team_member.api_key
    |> ApiKey.changeset(%{
      "key_hash" => new_hash,
      "key_prefix" => new_prefix,
      "status" => "active"
    })
  end)
  |> Repo.transaction()
end
```

The old token is invalidated (its hash is overwritten), new token is returned.
No second row, no index conflict. Loses audit history of revoked keys but
satisfies "one key per member" cleanly.

### Option B: DELETE old + INSERT new

If you need audit history (revoked keys kept for records), DELETE the old
row instead of UPDATEing its status, then INSERT the new one:

```elixir
Ecto.Multi.new()
|> Ecto.Multi.delete(:old_key, team_member.api_key)
|> Ecto.Multi.insert(:new_key, fn _ ->
  %ApiKey{} |> ApiKey.changeset(%{...new material...})
end)
```

A DELETE immediately frees the index slot. But you lose the revoked row
unless you move it to an audit table first.

### Option C: DEFERRABLE constraint

Make the unique constraint `DEFERRABLE INITIALLY DEFERRED` so the index
check happens at COMMIT, not at INSERT time. This works but requires
raw SQL in the migration:

```elixir
execute "CREATE UNIQUE INDEX api_keys_team_member_id_active_idx ON api_keys (team_member_id) WHERE status = 'active' DEFERRABLE INITIALLY DEFERRED"
```

Note: PostgreSQL does NOT support `DEFERRABLE` on partial indexes directly
(this was rejected in PG 12+). You'd need a trigger-based constraint or
a different schema design. Option A or B is more practical.

**Decision rule:** if the spec says "one key per X" (not "one active key"),
use Option A (non-partial unique + in-place update). If the spec says
"keep revoked keys for audit," use Option B (delete + insert) or a
separate audit table.

## 2. `references/2` does not accept `:null` option

**Wrong:**
```elixir
add :organization_id, references(:organizations, type: :binary_id, null: false)
```

This raises a `Map.update(:null, false, ...)` error at migration time.

**Right:**
```elixir
add :organization_id, references(:organizations, type: :binary_id), null: false
```

The `null: false` goes on the `add/3` call, not inside `references/2`.
The `references/2` function accepts `:type`, `:on_delete`, `:on_update`,
`:validate`, `:prefix`, `:with`, `:match`, `:options` — but NOT `:null`.

## 3. `assoc_constraint` errors appear under the association name, not the FK column

When `assoc_constraint(:organization)` in a changeset catches a missing
parent record, the error is added to `:organization`, not `:organization_id`:

```elixir
# In the changeset:
|> assoc_constraint(:organization)

# In the test — WRONG:
assert "does not exist" in errors_on(changeset).organization_id  # KeyError!

# In the test — RIGHT:
assert "does not exist" in errors_on(changeset).organization
```

The `assoc_constraint` uses the association name (`:organization`) as the
error key, which is the `belongs_to` field name without `_id`. Same applies
to `:team`, `:user`, `:team_member` — always the association name.

## 4. Ecto sandbox `:manual` mode and nested `Repo.transaction`

When the test helper sets `Ecto.Adapters.SQL.Sandbox.mode(Repo, :manual)`
and `DataCase.setup_sandbox/1` starts a sandbox owner, each `Repo.transaction`
call inside a test creates a savepoint within the sandbox transaction. This
is normally transparent, but:

- `Repo.update_all` + `Repo.insert` called **sequentially** (not in a Multi)
  each get their own implicit transaction checkout. With `:manual` sandbox
  mode, they share the sandbox connection, so the `update_all`'s changes ARE
  visible to the subsequent `insert`. This is fine.
- Inside an `Ecto.Multi` + `Repo.transaction`, all operations share one
  connection and one savepoint. The partial unique index issue (§1) is NOT
  a sandbox artifact — it reproduces identically in `:auto` mode and in
  `iex -S mix` outside tests.

If you suspect a sandbox visibility issue, test with
`Ecto.Adapters.SQL.Sandbox.mode(Repo, :auto)` in the test. If the failure
persists, the problem is in your SQL/index design, not the sandbox.

## 5. `mix ecto.rollback` + `mix ecto.migrate` to re-apply a fixed migration

When you fix a migration that already ran (e.g., changing an index from
partial to non-partial), you must rollback first, then re-migrate:

```bash
mix ecto.rollback --quiet   # undoes the last migration
mix ecto.migrate --quiet    # re-applies with the fix
```

Verify the index changed with `psql`:
```bash
psql -d myapp_dev -c "\d table_name"
# or
psql -d myapp_dev -c "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'api_keys';"
```

## 6. API key generation pattern (sha256 + base64url + prefix)

A clean pattern for generating API key tokens with a display prefix and
a stored hash:

```elixir
def generate_api_key_material do
  token = "tg-" <> Base.url_encode64(:crypto.strong_rand_bytes(24), padding: false)
  key_hash = hash_api_key(token)
  key_prefix = String.slice(token, 0, 8)
  {token, key_hash, key_prefix}
end

def hash_api_key(token) when is_binary(token) do
  :crypto.hash(:sha256, token) |> Base.encode16(case: :lower)
end
```

- `token` is returned to the user ONCE (never stored).
- `key_hash` is the sha256 hex of the token (stored, used for lookup).
- `key_prefix` is the first 8 chars (stored, for display in UIs).

Lookup by token: hash the presented token, query `WHERE key_hash = ^hash`.
Never store the plaintext token.

## 7. Native PG RANGE-partitioned tables with Ecto

When a table needs daily partitioning (high-volume append-only log tables,
request_logs, etc.), use a native Postgres `PARTITION BY RANGE` table.

### Migration — raw SQL, not Ecto DSL

Ecto's migration DSL does not support `PARTITION BY`. Write the `CREATE TABLE`
as raw SQL via `execute/1`:

```elixir
def up do
  execute """
  CREATE TABLE request_logs (
    id uuid NOT NULL,
    team_member_id uuid NOT NULL REFERENCES team_members(id),
    model_requested varchar(255) NOT NULL,
    status_code integer,
    prompt_tokens integer NOT NULL DEFAULT 0,
    cost_usd numeric(12,6),
    inserted_at timestamp(0) NOT NULL,
    PRIMARY KEY (id, inserted_at)
  ) PARTITION BY RANGE (inserted_at)
  """

  # Default partition catches any date without an explicit partition
  execute "CREATE TABLE request_logs_default PARTITION OF request_logs DEFAULT"

  # Explicit partition for a known date range (e.g. test date)
  execute "CREATE TABLE request_logs_2026_07_26 PARTITION OF request_logs FOR VALUES FROM ('2026-07-26') TO ('2026-07-27')"

  execute "CREATE INDEX request_logs_team_member_inserted_idx ON request_logs (team_member_id, inserted_at)"
end

def down do
  execute "DROP TABLE IF EXISTS request_logs CASCADE"
end
```

**Key points:**
- The partition column (`inserted_at`) MUST be part of the primary key.
- Create a `DEFAULT` partition so inserts with any `inserted_at` value land
  somewhere — otherwise out-of-range dates raise `no partition found`.
- For tests, create an explicit partition for the test date range so rows
  land in a real partition (not just the default catch-all).
- `CASCADE` in `DROP TABLE` drops all partitions automatically.

### Schema — composite primary key, no `timestamps()`

```elixir
@primary_key false

schema "request_logs" do
  field :id, :binary_id, primary_key: true, autogenerate: true
  field :inserted_at, :utc_datetime, primary_key: true

  field :team_member_id, :binary_id
  field :model_requested, :string
  # ... other fields
end
```

**CRITICAL gotcha:** `field :id, :binary_id, autogenerate: true` WITHOUT
`primary_key: true` fails with:
```
(ArgumentError) only primary keys allow :autogenerate for type :binary_id
```
When using `@primary_key false` (required for composite PKs), EVERY field
that uses `autogenerate:` MUST also have `primary_key: true`.

### `inserted_at` must be in `@permitted` and `@required`

Partitioned tables have NO `timestamps()` macro (no `updated_at`, and
`inserted_at` is a partition key that must be explicitly provided). The
`inserted_at` field must be in the changeset's `cast/3` permitted list AND
in `validate_required/2`, otherwise it's nil and the NOT NULL constraint
on the partition column fails:

```
ERROR 23502 (not_null_violation) null value in column "inserted_at"
```

The context function should default `inserted_at` to
`DateTime.utc_now() |> DateTime.truncate(:second)` when not provided.

## 8. Append-only tables (`timestamps(updated_at: false)`)

For audit logs and other append-only tables (no `updated_at` column):

```elixir
# Migration
timestamps(type: :utc_datetime, updated_at: false)

# Schema
timestamps(type: :utc_datetime, updated_at: false)
```

The struct will NOT have an `updated_at` field. In tests, do NOT use
`refute log.updated_at` — it raises `KeyError`. Use:

```elixir
refute Map.has_key?(log, :updated_at)
```

## 9. `:map` fields preserve atom keys

When you pass a map with atom keys to Ecto and store it in a `:map` column
(JSONB), Ecto returns the map with **atom keys** (not string keys) on read.
Tests must assert with atom keys:

```elixir
# In the changeset call:
|> cast(attrs, [:changes])
# attrs = %{changes: %{name: "Acme", slug: "acme"}}

# On read — atom keys:
assert log.changes == %{name: "Acme", slug: "acme"}
# NOT: assert log.changes == %{"name" => "Acme", "slug" => "acme"}
```

## 10. Fields with DB defaults never fail `validate_required`

When a column has a `default:` in the migration (e.g. `type` defaulting to
`"otlp_webhook"`), the changeset's `validate_required([:type])` will ALWAYS
pass — the default value satisfies the validation. Do not write tests that
assert `errors_on(changeset).type` is present when the field has a DB default.
Only test `validate_inclusion` failures for such fields.

## 11. Test ordering nondeterminism with same-second inserts

When multiple records are inserted within the same second, ordering by
`inserted_at DESC` alone is nondeterministic — all rows have the same
timestamp. Add a secondary sort key (e.g. `desc: id`) for stable ordering:

```elixir
|> order_by([al], desc: al.inserted_at, desc: al.id)
```

In tests, avoid asserting an exact `[id1, id2, id3]` order for same-second
inserts. Instead assert that the first element has the greatest-or-equal
`inserted_at` compared to the last:

```elixir
assert DateTime.compare(hd(logs).inserted_at, List.last(logs).inserted_at) in [:gt, :eq]
```

## 12. Bcrypt password hashing in registration changeset

Standard pattern for a `User` schema with a virtual `password` field:

```elixir
schema "users" do
  field :email, :string
  field :password_hash, :string
  field :password, :string, virtual: true  # never persisted
end

def registration_changeset(user, attrs) do
  user
  |> cast(attrs, ~w(email password)a)
  |> validate_required(~w(email password)a)
  |> validate_password()
  |> put_password_hash()
end

defp put_password_hash(changeset) do
  case get_change(changeset, :password) do
    nil -> changeset
    password -> put_change(changeset, :password_hash, Bcrypt.hash_pwd_salt(password))
  end
end
```

Authentication with timing-safe unknown-user handling:

```elixir
def authenticate_user(email, password) do
  case Repo.get_by(User, email: String.downcase(email)) do
    %User{password_hash: hash} = user when is_binary(hash) ->
      if Bcrypt.verify_pass(password, hash), do: {:ok, user}, else: {:error, :unauthorized}
    _user ->
      Bcrypt.no_user_verify()  # prevents timing oracle on email existence
      {:error, :unauthorized}
  end
end
```

`Bcrypt.no_user_verify/1` is critical — without it, an attacker can enumerate
valid emails by measuring response time (existing users do a real Bcrypt
comparison; non-existent users return instantly).

## 13. Decimal `==` compares representation, not value — use `Decimal.equal?/2`

`Decimal.round(x, 6)` normalizes to 6 decimal places, so a computed
`Decimal.new("0.012500")` fails `== Decimal.new("0.0125")` even though the
values are identical — `==` on Decimal structs compares coefficient + exponent
(the internal representation), not numeric value.

```elixir
# WRONG — fails when the left side was rounded to more places:
assert CostCalculator.market_cost(alias, usage) == Decimal.new("0.0125")

# RIGHT — numeric comparison:
assert Decimal.equal?(CostCalculator.market_cost(alias, usage), Decimal.new("0.0125"))
```

Any function that rounds (`Decimal.round/2`), divides (`Decimal.div/2`), or
pads to fixed scale will produce representations that differ from hand-written
test literals. Use `Decimal.equal?/2` (or `Decimal.compare/2 == :eq`) in every
assertion on computed Decimals.

## 14. `unique_constraint([:a, :b])` puts the error on the FIRST field

For a composite unique index like `unique_index(:model_aliases, [:organization_id, :name])`,
a changeset written as:

```elixir
|> unique_constraint([:organization_id, :name], name: :model_aliases_organization_id_name_index)
```

adds the "has already been taken" error to `:organization_id` (the first field
in the list) — not `:name`. Tests asserting `errors_on(changeset).name` then
raise `KeyError`. To place the error on the human-meaningful field, pass the
field as the first arg and the index name explicitly:

```elixir
|> unique_constraint(:name, name: :model_aliases_organization_id_name_index)
```

The `name:` option is required either way for composite indexes (Ecto can't
guess the index name from multiple fields).

## 15. `union_all` duplicates rows that appear in both branches

When combining two grant/list queries (e.g. team-granted aliases + individually
granted extra aliases), `union_all/2` returns the overlapping rows TWICE — a
downstream `length(accessible)` will disagree with the user's expectation of a
distinct set:

```elixir
# WRONG — alias granted both ways appears twice:
all_ids = team_alias_ids |> union_all(^member_alias_ids)

# RIGHT — UNION dedupes:
all_ids = team_alias_ids |> union(^member_alias_ids)
```

Reach for `union_all` only when duplicates are meaningful (event streams,
multi-source logs). For "the set of X this actor can access", it's always
`union`.

## 16. `Map.put/3` on Ecto structs for transient (non-schema) fields

When you need to attach a computed/derived value to a struct for pass-through
in a return value — e.g. attaching an active `credential` to an
`AliasProvider` so the caller can read `ap.credential.id` — the struct update
syntax `%{struct | field: value}` raises a compile warning if the field is not
declared in the schema:

```
warning: the following fields are unknown to struct AliasProvider: [:credential]
```

This fails compilation under `--warnings-as-errors`.

**Fix:** use `Map.put/3` instead of the update syntax. Ecto structs are maps
under the hood; `Map.put` adds a key that isn't in the `__struct__` field list
without complaint, and the value round-trips normally:

```elixir
# WRONG — compile warning under --warnings-as-errors:
%{alias_provider | credential: credential}

# RIGHT — transient key, no warning:
Map.put(alias_provider, :credential, credential)
```

The transient key is accessible as `struct.credential`, serializes in `IO.inspect`,
and is dropped on the floor if the struct is ever re-cast through its changeset
(`cast/3` ignores unknown keys). Use this for join-derived convenience fields
("the selected credential for this alias_provider") that you never want to
persist or validate — the route map should still carry the authoritative value
at its own top-level key for consumers that don't know about the attachment.

## 17. `Repo.preload/3` skips associations explicitly set to `nil` — use `force: true`

When a struct arrives with an association field already set to `nil` (e.g. you
manually stripped a preloaded team to test a lazy-load path), `Repo.preload/3`
treats `nil` as "already loaded" and does NOT re-fetch it — even when the
foreign key (`team_id`) is present and points at a real row. Downstream code
that reads `team_member.team.id` then crashes with `BadMapError: expected a
map, got: nil`.

```elixir
member = %TestTeamMember{member | team: nil}   # team_id still set
member = Repo.preload(member, [:team])         # team STAYS nil — preload is a no-op
member.team.id                                  # 💥 BadMapError
```

**Fix:** pass `force: true` so preload re-loads the association regardless of
its current value:

```elixir
member = Repo.preload(member, [:team], force: true)
```

This matters whenever you write a defensive "ensure the association is loaded"
helper: a guard like `if team_member.team != nil do ... else preload ... end`
needs `force: true` on the preload branch, because the `else` only fires when
`team` is nil — exactly the case where plain preload does nothing.

A robust check that works whether the association is a struct or nil:

```elixir
team = Map.get(team_member, :team)

if is_map(team) and Map.has_key?(team, :id) and team.id != nil do
  team_member
else
  Repo.preload(team_member, [:team], force: true)
end
```

**Pattern match caveat:** don't guard with `%MyApp.Team{}` on the loaded
association — if the struct's association module differs (e.g. a test-only
schema module like `TestTeam`), the guard fails and you re-preload every
call. The `is_map(team) and Map.has_key?(team, :id)` form is
module-agnostic.
