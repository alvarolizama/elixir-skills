# EXPLAIN ANALYZE verification for Ecto-generated queries

Recipes distilled from a real session: verifying a composite partial index on
`work_items` in a Phoenix umbrella (dev DB via `psql`, prod observation via RDS
Performance Insights).

## Run EXPLAIN against the dev DB

Find the dev DB name in `config/dev.exs` (`database: System.get_env("DATABASE_NAME") || "<name>"`),
then paste the observed query text into `psql`:

```bash
psql -d <db_name> <<'EOF'
EXPLAIN (ANALYZE, FORMAT TEXT)
SELECT w0."id", w0."app_name", w0."type", w0."code", w0."name", w0."status",
  w0."position", w0."pinned", w0."metadata", w0."due_date"
FROM "work_items" AS w0
WHERE ((w0."app_name" = 'tracker') AND (w0."archived_at" IS NULL))
  AND (w0."type" = ANY('{project,track,task,discovery}'))
ORDER BY w0."position", w0."pinned" DESC, w0."inserted_at" DESC;
EOF
```

## Pitfall: Seq Scan on small dev tables does NOT mean the index is wrong

On a dev table with ~2k rows, the planner often prefers a Seq Scan + quicksort
even when a perfect index exists — at that scale it's genuinely cheaper:

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
composite that also covers ORDER BY columns). An existing index winning in dev
is fine — your composite earns its cost in prod where the Sort step over tens
of thousands of rows dominates.

## Idempotency check for index migrations

Follow the repo's migration pattern (`execute` + `CREATE INDEX IF NOT EXISTS`),
then verify round-trip:

```bash
cd apps/contexts && mix ecto.migrate
mix ecto.rollback --to <previous_migration_ts>
mix ecto.migrate   # must succeed again
```

## Ecto script gotchas

- `Repo.query("SELECT ...")` returns `{:ok, %Postgrex.Result{rows: rows}}` —
  match `{:ok, %{rows: rows}}`, not `%{rows: rows}`.
- `mix run -e '...'` with heredoc-escaped SQL is brittle (quoting gets eaten).
  Prefer `psql` for EXPLAIN work, or write the script to a temp `.exs` file and
  `mix run file.exs` instead of `mix run -e`.
