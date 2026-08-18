# Postgres partition lifecycle cookbook

How to audit and fix native Postgres RANGE partitioning for Phoenix/Elixir
log tables (the canonical `request_logs` pattern). The audit class is
`PT-NN` in the `phoenix-performance-audit` skill.

## The core problem: partitions without a creation cron

A migration creates the parent table partitioned by RANGE on
`inserted_at` (daily granularity), plus one explicit partition for
the initial day and a `DEFAULT` partition:

```sql
CREATE TABLE request_logs (
  id uuid NOT NULL,
  inserted_at timestamp(0) NOT NULL,
  PRIMARY KEY (id, inserted_at)
) PARTITION BY RANGE (inserted_at);

CREATE TABLE request_logs_default PARTITION OF request_logs DEFAULT;
CREATE TABLE request_logs_2026_07_26 PARTITION OF request_logs
  FOR VALUES FROM ('2026-07-26') TO ('2026-07-27');
```

Without an Oban cron (or pg_partman, or a scheduled function) that
creates daily partitions ahead of time, **every subsequent insert falls
into `request_logs_default`**. Partition pruning never kicks in because
Postgres can only prune when the constraint-exclusion validator can
match the WHERE clause to a specific partition's range — the DEFAULT
partition matches everything, so there's nothing to exclude.

**Impact:** every query — even `WHERE inserted_at >= now() - interval '5 min'`
— scans the entire default partition. Indexes on the parent propagate
to the default partition, but it's a single index over all historical
data. The partitioned architecture exists on paper but provides zero
performance benefit.

## Audit recipe

```bash
# 1. Find the partition creation migration
grep -rn 'PARTITION BY\|PARTITION OF' priv/repo/migrations/

# 2. Check for a partition creation cron/worker
grep -rn 'PARTITION OF\|CREATE TABLE.*request_logs_' config/ lib/
grep -rn 'partition' config/config.exs config/runtime.exs

# 3. If step 2 returns nothing beyond the migration = critical finding
```

## Fix: Oban partition creation worker

```elixir
defmodule MyApp.PartitionWorker do
  use Oban.Worker, queue: :maintenance

  @impl true
  def perform(_job) do
    # Create partitions for the next 3 days (lookahead)
    for offset <- 0..3 do
      date = Date.utc_today() |> Date.add(offset)
      create_daily_partition(date)
    end
    :ok
  end

  defp create_daily_partition(date) do
    name = "request_logs_#{Calendar.strftime(date, "%Y_%m_%d")}"
    start_date = Date.to_iso8601(date)
    end_date = Date.add(date, 1) |> Date.to_iso8601()

    # IF NOT EXISTS makes it idempotent
    sql = """
    CREATE TABLE IF NOT EXISTS #{name}
      PARTITION OF request_logs
      FOR VALUES FROM ('#{start_date}') TO ('#{end_date}')
    """

    MyApp.Repo.query!(sql)
  rescue
    # Already exists or partition name conflict — idempotent
    DBConnection.ConnectionError -> :ok
  end
end
```

Schedule in `config/config.exs`:
```elixir
config :MyApp, Oban,
  crontab: [
    {"0 1 * * *", MyApp.PartitionWorker}  # 1 AM daily
  ]
```

## Fix: partition cleanup (old data)

For retention without losing the ability to query recent data:

```elixir
defmodule MyApp.PartitionDropWorker do
  use Oban.Worker, queue: :maintenance

  @impl true
  def perform(_job) do
    cutoff = Date.utc_today() |> Date.add(-90)
    drop_old_partitions(cutoff)
    :ok
  end

  defp drop_old_partitions(cutoff) do
    # List all partitions, drop those older than cutoff
    result = MyApp.Repo.query!(
      "SELECT tablename FROM pg_tables WHERE tablename LIKE 'request_logs_%'"

    )

    for [name] <- result.rows,
        date_str = parse_partition_date(name),
        not is_nil(date_str),
        Date.compare(date_str, cutoff) == :lt do
      MyApp.Repo.query!("DROP TABLE IF EXISTS #{name} CASCADE")
    end
  end

  defp parse_partition_date("request_logs_" <> rest) do
    case Date.from_iso8601(String.replace(rest, "_", "-")) do
      {:ok, date} -> date
      _ -> nil
    end
  end

  defp parse_partition_date(_), do: nil
end
```

## Duplicate index detection

Two migrations an hour apart created the same composite index with
different sort directions:

```sql
-- Migration A (08:55):
CREATE INDEX request_logs_model_alias_inserted_idx
  ON request_logs (model_alias_id, inserted_at)      -- ASC

-- Migration B (09:22):
CREATE INDEX request_logs_model_alias_inserted_desc_idx
  ON request_logs (model_alias_id, inserted_at DESC) -- DESC
```

When all queries use `ORDER BY inserted_at DESC`, the ASC index is never
used — pure write amplification. Postgres B-tree indexes are forward
and backward scannable, but the DESC index is strictly better for
DESC-order queries and the ASC adds nothing.

**Fix:** `DROP INDEX IF EXISTS request_logs_model_alias_inserted_idx`

**Detection:**
```bash
grep -rn 'CREATE INDEX.*request_logs' priv/repo/migrations/ | sort
# Any two indexes on the same columns = review for duplication
```

## Legacy column / FK detection

After a feature is removed, the columns and FKs often survive in the
DB even though the Ecto schema no longer declares them. Each is wasted
space per row (16 bytes for a uuid, 8-24 bytes for a numeric).

**Detection:**
```bash
# 1. Find all columns in CREATE TABLE + ADD COLUMN for the hot table
grep -rhn 'ADD COLUMN\|CREATE TABLE.*request_logs' priv/repo/migrations/

# 2. Compare with the Ecto schema
grep 'field \|belongs_to ' lib/*/logs/request_log.ex

# 3. Columns in DB but not in schema = legacy candidates for DROP
```

**Fix migration template:**
```elixir
defmodule MyApp.Repo.Migrations.DropLegacyRequestLogColumns do
  use Ecto.Migration

  @disable_ddl_transaction true
  @disable_migration_lock true

  def up do
    # Drop FK first if it exists (check \d request_logs in psql)
    execute "ALTER TABLE request_logs DROP COLUMN IF EXISTS subscription_id"
    execute "ALTER TABLE request_logs DROP COLUMN IF EXISTS cost_usd"
    execute "ALTER TABLE request_logs DROP COLUMN IF EXISTS savings_usd"
    execute "ALTER TABLE request_logs DROP COLUMN IF EXISTS estimated_cost_usd"
  end

  def down do
    # Re-add is possible but data is lost — document in moduledoc
  end
end
```

**Note:** `ALTER TABLE ... DROP COLUMN` on a partitioned table is
metadata-only in Postgres 11+ (doesn't rewrite the table). But the
physical space is not reclaimed until a `VACUUM FULL` or `pg_repack`.
For a large default partition, consider scheduling the `VACUUM FULL`
in a maintenance window after the migration.

## Index gaps on filtered columns (partial indexes)

Columns used in `WHERE status_code >= 400` (error queries) benefit
from partial indexes. On a partitioned table, partial indexes are NOT
propagated automatically — they must be created on each partition:

```sql
-- On the parent: does NOT propagate partial indexes
CREATE INDEX request_logs_errors_idx
  ON request_logs (status_code) WHERE status_code >= 400;
-- This creates the index only on the parent, not partitions.

-- Per-partition approach (required for partial indexes):
CREATE INDEX request_logs_default_errors_idx
  ON request_logs_default (inserted_at) WHERE status_code >= 400;
CREATE INDEX request_logs_2026_07_26_errors_idx
  ON request_logs_2026_07_26 (inserted_at) WHERE status_code >= 400;
-- ... for every partition
```

Alternatively, a non-partial composite index
`(credential_name, inserted_at)` on the parent DOES propagate and
covers most filter patterns.
