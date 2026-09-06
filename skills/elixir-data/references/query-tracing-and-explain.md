# Query Tracing & EXPLAIN Verification

Two directions: (a) an observed slow SQL query → its Ecto call site, and
(b) proving an index serves a query. All commands verified.

## Fingerprinting an observed query to its Ecto source

Extract discriminating features before searching the codebase:

- **ORDER BY** — most discriminating; search for the exact column set + directions first.
- **WHERE shape** — `= ANY($n)` means Ecto `field in ^list`; `$n` means a scalar.
- **LIMIT/OFFSET** — presence or absence eliminates candidates with unconditional limits.
- **Table + selected columns** — full columns with no aggregates suggests `Repo.all(query)`.

Eliminate candidates:

- Filter arity/shape (`= ANY` vs scalar `=`).
- A hard `limit` applied unconditionally is eliminated if the observed query has no LIMIT.
- A different preload/join shape is eliminated if the columns don't match.

Before fixing:

- Check git history for prior partial fixes — the gap is often the real root cause.
- Quantify: avg execution time × call count. Frequency problem → cache; volume
  problem → pagination/index.

## EXPLAIN funnel (the canonical verification)

```bash
psql -d <db_name> <<'EOF'
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT <the exact observed query text>;
EOF
```

## Pitfall: Seq Scan on small dev tables ≠ missing index

On a table with a few thousand rows the planner prefers Seq Scan even with a
perfect index — at that scale it's genuinely cheaper:

```
Sort  (cost=180.35..183.63 rows=1312) (actual time=2.788..2.878 rows=1899)
  ->  Seq Scan on work_items w0  (actual time=0.016..0.853 rows=1899)
```

Do NOT conclude the index is useless. Instead:

1. **Confirm existence:**

```sql
SELECT indexname, indexdef FROM pg_indexes
WHERE tablename = 'work_items' AND indexname = 'work_items_kanban_index';
```

2. **Force index usage to see planner preference at scale:**

```sql
SET enable_seqscan = off;
EXPLAIN (ANALYZE) <query>;
RESET enable_seqscan;
```

This reveals which index the planner prefers among several overlapping ones
(e.g. an existing `(app_name, type, status)` partial index vs your new
composite covering the ORDER BY columns). An existing index winning in dev is
fine — your composite earns its cost in prod where the Sort over tens of
thousands of rows dominates.

## Expected plan shapes

- **Index exists and is used:** `Index Scan using <idx> on <table>` with
  `Index Cond: (...)`. For rollups: `HashAggregate → Index Scan`.
- **Covering index (index-only):** `Index Only Scan` + `Heap Fetches: 0`
  (requires a clean visibility map — run `VACUUM ANALYZE` first).
- **Partitioned table, healthy:** `Aggregate → Append → Index Only Scan` per
  partition node; each child scan narrow (`Index Cond` on `inserted_at`).
- **Index missing / not useful:** `Seq Scan` per matched partition → the
  missing-index finding; for partitioned parents, remember partial indexes are
  NOT auto-propagated and `CONCURRENTLY` is a hard error there.

## Idempotency check for index migrations

Follow the repo's migration pattern (`execute` + `CREATE INDEX IF NOT EXISTS`),
then verify round-trip:

```bash
mix ecto.migrate
mix ecto.rollback --to <previous_migration_ts>
mix ecto.migrate   # must succeed again
```

## Scripting gotchas

- `Repo.query("SELECT ...")` returns `{:ok, %Postgrex.Result{rows: rows}}` —
  pattern-match `{:ok, %{rows: rows}}`, not `%{rows: rows}`.
- `mix run -e '...'` with heredoc-escaped SQL is brittle (quoting gets eaten).
  Prefer `psql` for EXPLAIN work, or write the script to a temp `.exs` file and
  `mix run file.exs`.
- EXPLAIN through `Ecto.Adapters.SQL.query(Repo, sql, [param])` fails when the
  param is a UUID — Postgrex expects 16 bytes for `binary_id` and rejects the
  canonical string form
  (`(DBConnection.EncodeError) Postgrex expected a binary of 16 bytes, got "00000000-..."`).
  Use `psql` with a `::uuid` cast instead.

## Window-function index matching

For last-per-group queries (`ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...)`),
the composite index must match the PARTITION + ORDER shape:
`(work_item_id, field, inserted_at DESC)` serves both the
`WHERE ... field = 'status'` predicate and the per-partition
`ORDER BY inserted_at DESC` — verified as `Index Scan` in the plan.

Confirm by the index NAME in the Scan node — Postgres may pick an equivalent
index by a different name than the migration file uses.

## Verification

- Plan shows the expected node type after `SET enable_seqscan = off`.
- `pg_indexes` lists the index (and for partials, per-partition on partitioned tables).
- `mix ecto.migrate` succeeds after rollback.