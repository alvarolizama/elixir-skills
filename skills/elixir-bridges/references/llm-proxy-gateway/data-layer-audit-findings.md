# MyApp Data-Layer Audit Findings (2026-07-27)

Full audit of migrations, schemas, contexts, and Oban workers. Found 21 issues
across 6 categories. Prioritized by severity.

## Critical

### C1. `providers.name` — unique constraint declared in schema, missing in DB
- **Migration:** `20260725230001_create_providers.exs` creates the table with NO indexes.
- **Schema:** `provider.ex:31` has `unique_constraint(:name)`.
- **Impact:** Ecto expects a DB constraint named `providers_name_index` but none exists.
  Concurrent inserts can create duplicate provider names. The `unique_constraint`
  call is a silent no-op — Ecto only converts DB constraint violations into
  changeset errors; without the DB constraint, nothing is enforced.
- **Fix:** `create unique_index(:providers, [:name])` in a new migration.

### C2. `request_logs` — partitioned table with no automatic partition creation or retention
- **Migration:** `20260726000001_create_request_logs.exs` creates a RANGE-partitioned
  table on `inserted_at` (daily). Only creates `request_logs_default` + one partition
  for `2026-07-26`. The moddoc says "An Oban cron creating daily partitions ahead of
  time is post-MVP."
- **Impact:** ALL rows after 2026-07-27 fall into the DEFAULT partition — a single
  physical table with no partition pruning benefit. The table grows indefinitely
  with no retention policy. Every `cost_summary`, `list_logs`, `hourly_series`, and
  breakdown query degrades over time.
- **Fix:** (1) Oban cron to `CREATE TABLE request_logs_YYYY_MM_DD PARTITION OF
  request_logs FOR VALUES FROM (...) TO (...)` daily. (2) Retention cron to
  `DROP TABLE` partitions older than N days. (3) Consider pg_partman.

### C3. WebhookWorker queries partitioned `request_logs` by `id` without `inserted_at`
- **File:** `webhook_worker.ex:49-55` — `where: rl.id in ^log_ids`
- **Impact:** The PK is composite `(id, inserted_at)` and the table is partitioned
  by `inserted_at`. Without `inserted_at` in the WHERE, Postgres cannot prune
  partitions and must scan ALL partitions.
- **Fix:** Pass `inserted_at` (or a date range) in the job args and add it to the
  WHERE clause.

## High

### A1. CHECK constraints missing on 8 enum-like columns
Columns where the schema validates inclusion but the DB has no CHECK:
- `providers.status` (active/disabled)
- `team_members.status` (active/suspended)
- `team_members.team_role` (manager/user)
- `api_keys.status` (active/revoked)
- `users.status` (active/suspended)
- `users.global_role` (user/admin)
- `model_providers.billing_mode` (pay_per_token/included)
- `observability_destinations.type` (otlp_webhook)

**Exception:** `provider_credentials.status` DOES have a CHECK constraint
(migration `20260727041837`). It's the only one.

**Fix:** Add `CHECK (col IN (...))` for each.

### A2. `request_logs` — indexes missing for frequent filter columns
Only indexes: `(team_member_id, inserted_at)` and `(inserted_at)`.
Missing: `provider_id`, `model_alias_id`, `status_code`, `agent_type`.
Queries in `Logs.apply_log_filters/1` and `Metrics.Rollup.breakdown_by_*` filter
and group by these columns.

### A3. `request_logs` — FKs to `providers` and `model_aliases` are nullable without index
FKs without indexes degrade `DELETE` on the parent table (Postgres seq-scans
`request_logs` to validate the FK).

### A4. `audit_logs` — index missing on `action`
`list_audit_logs` filters by `action` but no index exists. Table is append-only
and grows monotonically.

### A5. WriteWorker — not idempotent; retries duplicate request logs
- **File:** `write_worker.ex:24-52`
- **Impact:** If the job fails after successful insert (e.g. `broadcast_new_log`
  or `WebhookWorker.dispatch` raises), Oban retries and re-inserts the log.
  `max_attempts: 5` amplifies the risk.
- **Fix:** (1) Generate `id` in the enqueuer and use `ON CONFLICT DO NOTHING`.
  Or (2) separate insert from dispatch into two jobs.

### A6. `model_providers` — no unique constraint on `(model_alias_id, credential_id, provider_model)`
Allows duplicate routing entries: same alias + same credential + same model
inserted twice.

## Medium

### M1. `observability_destinations` — no unique constraint on `(team_id, name)`
### M2. `list_logs_for_team` — join through `team_members` may benefit from denormalized `team_id` on `request_logs`
### M3. WebhookWorker.dispatch — 2 extra queries per request log (TeamMember lookup + destinations)
### M4. WebhookWorker.perform — `Repo.get!` crashes if destination was deleted between enqueue and perform
### M5. Budgets.SyncWorker — 2 DB aggregate queries per member per 60s window
### M6. `request_logs` cost columns are nullable but used in SUM (NULL rows silently omitted)
### M7. Metrics.Collector `push_latency` — read-modify-write ETS, not atomic (documented, accepted)

## Low

### B1. `model_pricing` — index on `(model_provider_id, effective_from)` is not unique
### B2. `api_keys` — unique index on `team_member_id` is total, not partial (comment says partial)
### B3. Schema-migration consistency check — all consistent after verification
### B4. `delete_provider`/`delete_credential` — no `foreign_key_constraint` capture in changeset
### B5. `list_logs_after` — respects `:limit` with max 500, but no lower default for polling

## Summary Table

| Category | Critical | High | Medium | Low |
|----------|----------|------|--------|-----|
| Missing indexes | C2 | A2, A3, A4 | M2 | B1 |
| Missing constraints | C1 | A1, A6 | M1, M6 | B2 |
| Inefficient queries | C3 | — | M3, M5 | B5 |
| Oban workers | — | A5 | M4, M5 | — |
| Unlimited growth | C2 | — | — | — |
| Schema vs migration | — | — | — | B3, B4 |
