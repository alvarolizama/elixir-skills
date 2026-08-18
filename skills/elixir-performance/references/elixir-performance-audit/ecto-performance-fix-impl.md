# Implementing the "detail-view scoping" + "last-per-group window function" fix classes (Ecto 3.13)

Concrete implementer notes from tracking/executing a P1 performance track in the Hub umbrella
(TRACKER-TRAC-763487). These are the *gotchas* a future session hits when actually coding
the fix classes that `elixir-performance-audit` only identifies. "Verified" = observed on
Ecto 3.13.5 / Postgrex 0.22 / Postgres.

## 1. Ecto schema cannot hold a virtual `{:array, :atom}` field — use `{:array, :string}`

To tag each item with source atoms after a query, the natural idea is a virtual field:

```elixir
field :sources, {:array, :atom}, virtual: true, default: []
```

Compiles to a hard error:

```
** (ArgumentError) unknown type :atom for field :sources
    (ecto 3.13.5) lib/ecto/schema.ex:2567: Ecto.Schema.check_field_type!/4
```

Fix: declare `{:array, :string}` and carry string source tags (`"owner"`, `"following"`,
`"created"`, `"squad"`), then match against those strings when grouping. Verified compile fix.

## 2. Do not combine a custom `select : %{...}` with an in-query preload

You cannot run `Repo.all(query_with_select_and_preload)` when the select is a map projection
AND you want each selected item preloaded — Ecto won't preload a non-struct projection.

Clean pattern (verified): build the query selecting **the WorkItem struct** (no custom select),
then preload in a second statement:

```elixir
items =
  query
  |> Repo.all()
  |> Repo.preload(preloads)
```

If you need per-item classified metadata (like a `sources` list), keep the struct as-is and
add the classification as a virtual field on the struct AFTER the query (see #1).

## 3. Composite index must match the window function's PARTITION + ORDER for Index Scan

For last-per-group, the index needs `(work_item_id, field, inserted_at DESC)` so both the
`WHERE ... field = "status"` predicate and the `ORDER BY inserted_at DESC` within a partition
resolve to an Index Scan. Verify with EXPLAIN ANALYZE, not by assuming (see #5).

Verified plan output after building the matching index:

```
->  Index Scan using work_item_activities_work_item_id_field_index on work_item_activities a0
    (cost=0.14..8.16 rows=1 width=40)
```

(Note: Postgres may pick an equivalent index by a different name than the one in the
migration — confirm by the *index name in the Scan node*, not the migration file name.)

## 4. `EXPLAIN ANALYZE` is easiest via `psql`, not through Ecto.Adapters.SQL

Running EXPLAIN through `Ecto.Adapters.SQL.query(Repo, sql, [param])` fails when the param is
a UUID because Postgrex expects 16 bytes for a `binary_id` column and rejects the canonical
`"00000000-..."` string:

```
** (DBConnection.EncodeError) Postgrex expected a binary of 16 bytes, got "00000000-..."
```

Read-only probe that works (Verified):

```bash
psql <dbname> -c "
EXPLAIN ANALYZE
SELECT ... WHERE (a0.work_item_id IN ('00000000-0000-0000-0000-000000000000'::uuid) AND ...)
"
```

Cast the fake UUID with `::uuid`. On a small dev table a Seq Scan does NOT prove a missing
index — the planner prefers Seq Scan on tiny tables; check index *existence* in migrations
(`pg_indexes`) and consider `SET enable_seqscan = off`.

## 5. Consolidating N relationship queries into 1 with source tagging

Pattern: replace 4 separate `my_work` / `following_work` / `created_work` / `squad_work`
queries (each a full `Repo.all` of item structs) with a single query whose `WHERE` is an OR of
all relationship predicates. Keep the public per-source functions as thin wrappers for
backward compatibility; a `my_work_data`-style caller should call the unified function and
group by `item.sources` in Elixir.

Practical cost note: the unified items query plus two small "relationship id set" subqueries
(used to tag sources correctly) replaces N full queries with ~1 full + 2 cheap id queries.
That is a real win when the full queries preload heavy associations. Behavior-true tagging:
for the `:following` / `:squad` sources, derive membership from the id sets, NOT from
`item.followers` / `item.squads` preloads — an item having any followers/squads does NOT mean
the subject user is among them.
