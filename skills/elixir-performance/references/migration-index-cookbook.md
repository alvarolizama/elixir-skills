# Migration / Postgres index cookbook

How to audit and add indexes for Phoenix/Elixir apps that have
partitioned log tables and rollup-style dashboards. The audit
class is `IX-NN` in the `phoenix-performance-audit` skill.

## Why indexes matter for rollups

When a rollup query does `group_by: rl.model_alias_id` with a
filter `where: rl.inserted_at >= ^from`, Postgres can use an
index *only if* the index covers both the group key and the filter.
Without it, Postgres does a sequential scan inside each partition
that matches the `inserted_at` filter.

For a table partitioned by day with 30 partitions × 1M rows each
(30M rows), every rollup query without the right index scans every
matched partition in full. A `group_by model_alias_id` with no
matching index takes 5-30s; with `(model_alias_id, inserted_at)` it
returns in <100ms.

## What to grep for

### Indexes that already exist

```bash
# Find all CREATE INDEX statements in migrations
grep -rn 'create index\|CREATE INDEX' priv/repo/migrations/

# Find raw SQL CREATE INDEX (often used for partitioned tables
# because the Ecto create_index macro doesn't propagate to all
# partitions)
grep -rn 'CREATE INDEX' priv/repo/migrations/
```

### Columns used in GROUP BY / WHERE across rollup queries

For each rollup function in `lib/<app>/metrics/` (or equivalent),
collect:

```bash
grep -rn 'group_by\|group:\|where:' lib/<app>/metrics
```

Cross-reference the `group_by` columns against the existing
indexes. Any column that appears in `group_by` or `where` *and* is
on the hot table but NOT in any index is a candidate index.

For the MyApp audit the missing indexes were:

| Column | Used in |
|--------|---------|
| `model_alias_id` | `breakdown_by_model`, `breakdown_by_member_for_model`, `model_usage_stats_*` |
| `provider_id` | `provider_ranking`, `Metrics.Collector`, rollups |
| `status_code` | `Logs.realtime_summary` (with `>= 400` filter), `alerts_live.cred_error_counts` |
| `api_key_prefix` | `alerts_live.cred_error_counts` |
| `agent_type` | `Metrics.Collector`, `agent_breakdown` |

## Partitioned tables need indexes propagated to every partition

A native Postgres partitioned table only enforces indexes defined
on the parent (or attached indexes that span partitions). If the
migration creates the partition table and the indexes separately,
the indexes must be added to *each* partition, including the
default partition (`request_logs_default`) that catches everything
not in an explicit date range.

**`CREATE INDEX CONCURRENTLY` is NOT supported on partitioned
tables.** Postgres raises
`(Postgrex.Error) ERROR 0A000 (feature_not_supported) cannot create
index on partitioned table "..." concurrently` — and this fires in
`mix test` migrations too, not just prod. Verified on request_logs
2026-08. On partitioned parents use a plain `CREATE INDEX IF NOT
EXISTS` (fast on empty/small partitions, but blocking on a large
prod table — schedule a window). CONCURRENTLY is only safe on
regular (non-partitioned) tables or on individual partitions, one
by one.

Two approaches:

1. **`CREATE INDEX ... ON ONLY <parent>`** — Postgres 11+ auto-
   propagates to existing and future partitions, but ONLY if the
   index is created on the parent.
2. **Per-partition `CREATE INDEX`** — explicit, more verbose,
   required if you used `CREATE TABLE ... PARTITION OF` and want
   non-propagated indexes (e.g. partial indexes like
   `WHERE status_code >= 400`).

For partial indexes (e.g. `WHERE status_code >= 400`), approach (2)
is required — Postgres does not propagate partial indexes to
partitions automatically.

## Concrete migration template (MyApp audit suggestion)

```elixir
defmodule MyApp.Repo.Migrations.AddRequestLogRollupIndexes do
  use Ecto.Migration

  def up do
    # Index on the partitioned parent — auto-propagated
    execute "CREATE INDEX request_logs_model_alias_inserted_idx " <>
            "ON request_logs (model_alias_id, inserted_at)"
    execute "CREATE INDEX request_logs_provider_inserted_idx " <>
            "ON request_logs (provider_id, inserted_at)"
    execute "CREATE INDEX request_logs_agent_inserted_idx " <>
            "ON request_logs (agent_type, inserted_at)"

    # Partial index on errors — needs to be added to each partition
    # explicitly because Postgres does not propagate partial indexes.
    flush()
    for partition <- partitions() do
      execute "CREATE INDEX request_logs_errors_#{partition}_idx " <>
              "ON request_logs_#{partition} (inserted_at) " <>
              "WHERE status_code >= 400"
    end
  end

  def down do
    execute "DROP INDEX IF EXISTS request_logs_model_alias_inserted_idx"
    execute "DROP INDEX IF EXISTS request_logs_provider_inserted_idx"
    execute "DROP INDEX IF EXISTS request_logs_agent_inserted_idx"
    # drop partial indexes per partition
  end

  defp partitions, do: ~w(default 2026_07_26 2026_07_27 ...]
end
```

## Verifying with EXPLAIN

Before recommending an index, prove it's needed:

```sql
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT model_alias_id, COUNT(*) AS n
FROM request_logs
WHERE inserted_at >= '2026-08-01'
GROUP BY model_alias_id;
```

If the plan shows `HashAggregate` over `Seq Scan on
request_logs_*`, the index is missing. After adding it, the plan
should show `Index Scan` or `Index Only Scan` followed by a much
smaller `HashAggregate`.

Sample expected output:

```
HashAggregate  (cost=… rows=… width=…)
  Group Key: model_alias_id
  ->  Index Scan using request_logs_model_alias_inserted_idx on request_logs
        Index Cond: (inserted_at >= '2026-08-01'::date)
```

## Detection recipe (concrete commands)

```bash
# 1. List migrations that touch the hot table
ls priv/repo/migrations/ | xargs -I {} grep -l 'request_logs' priv/repo/migrations/{}

# 2. Dump every CREATE INDEX
grep -rn 'CREATE INDEX' priv/repo/migrations/

# 3. List rollup queries and their group_by / where columns
grep -rn 'group_by\|where:' lib/<app>/metrics lib/<app>/logs

# 4. Compare (2) vs (3) — any GROUP BY column not in an index is a finding.
```

## Common false positives

- An index on `team_member_id` covers `team_member_id`-only queries;
  adding `(team_member_id, inserted_at)` only helps if a query
  filters on `inserted_at`. Don't recommend adding `inserted_at` to
  every index blindly.
- Partial indexes (`WHERE ...`) only help for the filtered subset;
  if the rollup queries always scan all rows, a partial index
  doesn't apply.
- `request_logs` already has `(inserted_at)` — a query that filters
  *only* on `inserted_at` doesn't need another index. Only the
  GROUP BY columns matter.

## When NOT to add indexes

- If the rollup queries already run in <100ms on production data,
  no index needed — adding one has write-amplification cost.
- If the table is read-once-cold (e.g. a daily ETL), an index is
  wasted write cost; let the Seq Scan happen.
- For a small table (<100K rows), Postgres will choose a Seq Scan
  over an Index Scan anyway. Don't add indexes for tables that
  won't outgrow the threshold.