# Partitioned-Table Maintenance

The full playbook for native Postgres RANGE-partitioned tables (daily
`inserted_at` partitions are the common case). Verified on Postgres 16 / Ecto
3.14 / Postgrex 0.22 / Oban 2.19.

## The rot

A migration declares `PARTITION BY RANGE (inserted_at)` plus one initial
partition and a DEFAULT partition — but nothing creates daily partitions at
runtime. Every subsequent insert lands in the DEFAULT partition, partition
pruning never kicks in (the DEFAULT matches everything, so there's nothing to
exclude), and every query scans the whole default partition. The partitioned
architecture exists on paper.

Audit for it:

```bash
grep -rn 'PARTITION BY\|PARTITION OF' priv/repo/migrations/
# If the only partition creation is in the migration → critical finding
```

## Error-code table (what ATTACH/CREATE tell you)

| Postgrex `postgres.code` | Meaning | Reaction |
|---|---|---|
| `:check_violation` | Range has rows in the default partition (or another partition being split) | Run the backfill recipe below |
| `:invalid_object_definition` | New partition would overlap an existing named partition | Already handled — partition exists; nothing to do |
| `:undefined_table` | Parent or default partition missing | Table isn't partitioned as expected; stop |

Probe cheaply:
`try do Repo.query!(...) rescue e in Postgrex.Error -> e.postgres.code end`.

Direct `CREATE TABLE x PARTITION OF ... FOR VALUES ...` while the default
holds that range fails with:
`ERROR: updated partition constraint for default partition "<default>" would be violated by some row`.

## Backfill recipe (move stranded rows out of the default)

Atomic as one `Repo.transaction` — Postgres DDL is transactional, so steps 1-3
roll back together on ATTACH failure:

```sql
-- 1. Standalone twin of the default partition: PK + ALL indexes (incl. INCLUDE)
CREATE TABLE events_2026_08_05 (LIKE events_default INCLUDING ALL);

-- 2. Atomic move (single statement = single transaction with step 3)
WITH moved AS (
  DELETE FROM events_default
  WHERE inserted_at >= '2026-08-05' AND inserted_at < '2026-08-06'
  RETURNING *
)
INSERT INTO events_2026_08_05 SELECT * FROM moved;

-- 3. Attach (default no longer holds the range, so this succeeds)
ALTER TABLE events ATTACH PARTITION events_2026_08_05
  FOR VALUES FROM ('2026-08-05') TO ('2026-08-06');

ANALYZE events_2026_08_05;
```

Verified semantics:

- `LIKE ... INCLUDING ALL` copies the composite PK and every index
  (name-mangled child names).
- Concurrent writers between DELETE and ATTACH land back in the default and
  ATTACH fails with `:check_violation` again → return a retryable status; the
  next run picks them up. Nothing is lost.
- Recovery of a half-finished run: standalone table exists but isn't attached →
  `CREATE TABLE IF NOT EXISTS` then redo steps 2-3.

## Maintenance worker shape (Oban)

```
perform/1
  ├─ ensure_upcoming_partitions(lookahead_days=3, base=Date.utc_today())
  │     for each day: attached? → :exists
  │                   standalone table exists? → attach_with_backfill
  │                   else → fast CREATE PARTITION OF, rescue :check_violation → attach_with_backfill
  ├─ backfill_default_partitions(retention_days: 90)
  │     SELECT min/max(inserted_at)::date FROM <default>
  │     days = clamp(min, today-retention) .. max, capped (e.g. 2000 days/run)
  │     → ensure_partition(day) for each      # never creates partitions for days past retention
  └─ cleanup_old_partitions(retention_days)
        parse <table>_YYYY_MM_DD names back to Date (nil → skip: protects default)
        DROP TABLE each named partition strictly older than cutoff
```

Key guards:

- **Retention clamp on backfill** — days older than the cutoff stay in the
  default partition. If you backfilled them, cleanup would immediately DROP
  TABLE them, deleting data.
- **Name-parse guard on cleanup** — with `"<table>_" <> ymd <- name`,
  `[y, m, d] <- String.split(ymd, "_")`, `{:ok, date} <- Date.new(...)`;
  anything unparseable (the DEFAULT partition) returns nil and is never
  dropped. Rescue `ArgumentError` from `String.to_integer/1`.

## Wiring (both surfaces required)

```elixir
# config.exs — nightly maintenance
{Oban.Plugins.Cron, crontab: [
  {"5 0 * * *", MyApp.Logs.PartitionWorker}
]}
config :my_app, :partition_boot_ensure, true

# application.ex — one-shot boot ensure AFTER {Oban, ...} in the children list
Supervisor.child_spec(
  {Task, fn -> MyApp.Logs.PartitionWorker.ensure_on_boot() end},
  id: :partition_boot_ensure,
  restart: :temporary)

# test.exs — fixtures insert arbitrary historical dates that must stay in default
config :my_app, :partition_boot_ensure, false
```

`ensure_on_boot/0` must never raise (rescue + log) — a DB hiccup at boot must
not kill the app; the nightly cron catches up. With `restart: :temporary` the
finished Task disappears from `Supervisor.which_children` (returns nil — that
is the expected steady state, not a failure).

Skipping the boot ensure = the first request of the day after a deploy lands
in the default partition until the nightly cron runs.

## Covering index for index-only aggregates

```sql
CREATE INDEX IF NOT EXISTS events_owner_inserted_covering_idx
ON events (owner_id, inserted_at)
INCLUDE (id, /* every column the aggregate reads or returns */);
DROP INDEX IF EXISTS events_owner_inserted_idx;  -- fully superseded
```

- `id` in INCLUDE is mandatory when the query has `count(id)` — without it the
  scan stays Index (not Index Only) because the column isn't covered.
- Propagation to attached partitions is automatic; each child gets a mangled
  child index.
- Do NOT run `CREATE INDEX ... CONCURRENTLY` — hard error on partitioned
  parents (`ERROR 0A000 feature_not_supported`), fires in `mix test`
  migrations too. Plain `CREATE INDEX IF NOT EXISTS` on the parent; schedule a
  window for big tables (blocking).
- Partial indexes (`WHERE status_code >= 400`) are NOT propagated — create
  them per partition, or use a non-partial composite on the parent instead.

## Verification funnel (must pass all)

```sql
VACUUM ANALYZE events;                     -- visibility map → Heap Fetches 0
SET enable_seqscan = off;
EXPLAIN ANALYZE SELECT coalesce(sum(cost_usd), 0), ..., count(id)
  FROM events
  WHERE owner_id = ANY(ARRAY[<uuid>]::uuid[]) AND inserted_at >= ... AND inserted_at <= ...;
-- expect: Aggregate → Append → Index Only Scan per partition, Heap Fetches: 0
```

On a near-empty dev table the planner picks Seq Scan on its own — the
`enable_seqscan = off` probe is what proves the index path exists.

## Test patterns

- `use MyApp.DataCase, async: false` — partition structure is shared state.
- Partition DDL rolls back in the Ecto sandbox (transactional DDL) — no cleanup.
- Use far dates (`~D[2099-03-01]`, `~D[2020-06-15]`) so tests never collide
  with real-date partitions.
- Direct row inserts without the FK fixture chain:
  `Repo.query!("INSERT INTO events (id, inserted_at) VALUES ($1, $2)", [Ecto.UUID.dump!(Ecto.UUID.generate()), DateTime.new!(date, ~T[12:00:00])])`
  — `Ecto.UUID.dump!/1` (binary form) or Postgrex raises
  `DBConnection.EncodeError`; `timestamp` literals via `DateTime.new!/2`.
- Assertions worth having: create + idempotent re-ensure (`:exists`); backfill
  moves rows (default count N→0, partition count N); empty-default no-op;
  old-day skipped past retention; cleanup drops old partitions but never
  `<default>`; full `perform/1` returns `:ok`.

## Ops hygiene

- After any migration touching partitions/indexes: `mix ecto.dump` —
  `priv/repo/structure.sql` must carry the new partitions and indexes.
- Confirm live state:
  `SELECT inhrelid::regclass FROM pg_inherits WHERE inhparent = '<parent>'::regclass ORDER BY 1;`
  and `SELECT count(*) FROM <default>;` (should stay ≈ 0).
- `min(inserted_at)::date` in raw queries decodes to `%Date{}`; without the
  cast it's `NaiveDateTime`.