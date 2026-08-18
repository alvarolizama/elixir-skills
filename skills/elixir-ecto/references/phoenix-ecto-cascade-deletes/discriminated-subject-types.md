# Discriminated subject types: fixing an overloaded FK column

Worked example from my_app_gateway (`request_logs`): the column `team_member_id`
was overloaded to hold **either** a real `team_members.id` **or** a
`services.id` (services were modeled as "virtual team members" via
`service_to_virtual_member/1` with `id: service.id`).

## The bug

`request_logs.team_member_id` had a real FK:

```sql
CONSTRAINT request_logs_team_member_id_fkey
  FOREIGN KEY (team_member_id) REFERENCES team_members(id) ON DELETE CASCADE
```

For a service request, `team_member_id = service.id`, but that id is **not**
in `team_members`, so every insert violated the FK. Because writes went
through an async Oban `WriteWorker` (5 retries, then drop), the failure was
silent — nothing raised in the proxy hot path, the "log" simply never
appeared, and downstream stats showed zero service traffic.

### Diagnosis

Never trust "it should be logged" — probe the DB directly:

```bash
psql "$DATABASE_URL" -c \
  "INSERT INTO request_logs (id, team_member_id, model_requested, inserted_at)
   VALUES (gen_random_uuid(), '<service_id>', 'test', now());"
# ERROR: violates foreign key constraint "request_logs_team_member_id_fkey"
# DETAIL: Key (team_member_id)=(<service_id>) is not present in table "team_members".
```

Also confirm the silent-drop shape: `SELECT count(*) FROM request_logs rl
WHERE rl.team_member_id NOT IN (SELECT id FROM team_members)` returns 0
(because those rows could never be inserted).

## The fix (discriminated subject pattern)

The user picked the clean option: a dedicated `service_id` FK + a
`subject_type` discriminator + making the overloaded column nullable.

### 1. Migration (request_logs is a native RANGE-partitioned table → raw SQL)

```sql
ALTER TABLE request_logs ALTER COLUMN team_member_id DROP NOT NULL;
ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS service_id uuid
  REFERENCES services(id) ON DELETE CASCADE;
ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS subject_type varchar(255)
  NOT NULL DEFAULT 'user';
CREATE INDEX IF NOT EXISTS request_logs_service_inserted_idx
  ON request_logs (service_id, inserted_at DESC);
```

Key insight: **the original `team_member_id` FK is NOT dropped** — FKs allow
NULL, so it still cascades for user rows and simply passes (NULL) for service
rows. This preserves user-delete cascade with zero extra work.

### 2. Ecto schema (`RequestLog`)

```elixir
field :subject_type, :string, default: "user"
belongs_to :service, my_app_gateway.Accounts.Service, foreign_key: :service_id, type: :binary_id

@required ~w(model_requested inserted_at subject_type)a

def changeset(request_log, attrs) do
  request_log
  |> cast(attrs, @permitted)   # add :subject_type and :service_id
  |> validate_required(@required)
  |> validate_inclusion(:subject_type, ["user", "service"])
  |> validate_subject_id()
end

# DB no longer enforces NOT NULL, so enforce the conditional requirement here.
defp validate_subject_id(changeset) do
  case get_field(changeset, :subject_type) do
    "user"    -> validate_required(changeset, [:team_member_id])
    "service" -> validate_required(changeset, [:service_id])
    _         -> changeset
  end
end
```

### 3. Write path (proxy → Oban worker)

Thread the discriminator through. A helper derives the triple from the member
struct (services arrive as "virtual members" with `user_id: nil`):

```elixir
defp log_subject(%TeamMember{user_id: nil} = m),
  do: %{subject_type: "service", team_member_id: nil, service_id: m.id}
defp log_subject(%TeamMember{} = m),
  do: %{subject_type: "user", team_member_id: m.id, service_id: nil}
```

The Oban worker must also carry `service_id` + `subject_type` through its
`args` and `preload(:service)` so the UI can show the service name.

### 4. Consumers that key by a single binary id

Anything that keys spend/aggregates by one id (members AND services share a
binary subject id, e.g. the budget manager) can no longer filter by
`team_member_id = $id` alone. Add a combined filter:

```elixir
defp maybe_where_subject_id(query, filters) do
  case Map.get(filters, :subject_id) do
    nil -> query
    id  -> where(query, [rl], rl.team_member_id == ^id or rl.service_id == ^id)
  end
end
```

…and change `subject_filters(subject) when is_binary(subject)` from
`%{team_member_id: subject}` to `%{subject_id: subject}`.

### 5. Blast radius of `team_member_id → service_id`

Every query that assumed `team_member_id = service_id` must switch to
`service_id`: the services LiveView monthly-stats query, `Rollup.breakdown_by_service`
(join `on rl.service_id == s.id`), `Rollup.daily_series_by_model_for_service`
(`where rl.service_id == ^service_id`), and any `:team_member_id` option that
was really a service drill-down (rename to `:service_id`). Member/team-scoped
queries that `join` on `team_members` are naturally correct — service rows have
`team_member_id = NULL`, so the inner join excludes them.
