# Ecto Query Pitfalls — traps with error signatures

Symptom-first catalog of the non-obvious Ecto/Postgres query failures. Each
entry: symptom → mechanism → fix. Verified on Ecto 3.13-3.14 / Postgrex 0.22.
## JSONB containment `@>` with a parameter: type it
An untyped param fails: `fragment(\"? @> ?::jsonb\", p.meta, ^json)` returns
`false` through Postgrex for rows that visually match exactly — Postgrex sends
the JSON string as a `text` param and containment doesn't match the stored
jsonb (identical value: literal returns `true`, untyped param returns `false`).
Fix — type the param, either form (verified Ecto 3.14 / Postgres 16-18):
`fragment(\"? @> ?::jsonb\", p.meta, type(^json, :string))` or pass a decoded
map: `fragment(\"? @> ?\", p.meta, ^Jason.decode!(json))`.

Per-key text comparison remains the option when each hot key needs its own
partial expression index: one `where` per key/value pair (AND logic),
pagination-safe, and can hit partial expression indexes:

```elixir
Enum.reduce(props, query, fn {key, value}, q ->
  text_value = if is_binary(value), do: value, else: Jason.encode!(value)
  where(q, [p], fragment(\"?->'props'->>? = ?\", p.meta, ^to_string(key), ^text_value))
end)
```
The post-query Elixir filter is the fallback ONLY for small, non-paginated
datasets — it filters after LIMIT/OFFSET and breaks pagination correctness.
## JSONB string keys inside fragments get mangled
`fragment(\"?->'props' @> ?\", p.meta, ^json)` strips the quotes during macro
expansion → `meta->props` → column reference → `ERROR 42703 (undefined_column)
column \"props\" does not exist`. Fix: pass the key as a parameter and type
the value —
`fragment(\"?->? @> ?::jsonb\", p.meta, \"props\", type(^json, :string))`.
## `==` inside a fragment is Elixir, not SQL
`fragment(\"?->>'key' == ?\", ...)` fails — Postgres equality is `=`. Always
`fragment(\"?->>'key' = ?\", ...)`.
## Fragments reject `^\"string\"` args (misplaced operator)
Ecto `fragment` does not accept `^\"string\"` params the way embedded queries
do — errors with "misplaced operator". Inline safe constant literals, or
`type(^value, :string)` for runtime values; never string-interpolate user input.
## `fragment(^built_string)` — SQL-injection guard
Building fragment SQL from a field list (`Enum.map` + `Enum.join(\" AND \")` →
`fragment(^sql)`) fails at compile time: `(Ecto.Query.CompileError) to prevent
SQL injection attacks, fragment(...) does not allow strings to be interpolated
as the first argument via the \`^\` operator`.

Fix — one literal fragment per condition, combined with `dynamic/2`:

```elixir
dynamic([w],
  fragment(\"TRIM(COALESCE(metadata->>'field_a', '')) <> ''\") and
  fragment(\"TRIM(COALESCE(metadata->>'field_b', '')) <> ''\"))
```
Across a runtime list of filters: build one `dynamic` per filter and reduce
with `dynamic([w], ^acc or ^cond)`. Module-attribute reuse works for pure
literals (`fragment(@attr, ...)`) but `fragment(@attr <> \" >= ?\", ...)` hits
the same guard — define one constant per variant.
## Raw queries with UUID PKs
`Repo.query!` with the canonical UUID string raises `(DBConnection.EncodeError)
Postgrex expected a binary of 16 bytes, got \"845571d9-...\"`. Fix:
`Ecto.UUID.dump!(id)` — binary form — for every UUID bind param (including
partitioned-table fixtures).
## `timestamp` decodes as NaiveDateTime
Raw `Repo.query!` results decode `timestamp` columns as `%NaiveDateTime{}`.
Cast `::date` in SQL for `%Date{}` (`min(inserted_at)::date`).
`DateTime.to_date/1` on a `~N[...]` raises `FunctionClauseError` — wrap final
fragment selects in `type(fragment(...), :utc_datetime)` when downstream code
expects a `DateTime`.
## Datetime params in fragments need explicit types
`COALESCE(w.completed_at, a.inserted_at) < ^to` with `^to` a `DateTime`
failed silently (returned `[]`) until typed — Ecto inferred a type that didn't
match `timestamptz`. Fix: `type(^from, :utc_datetime), type(^to, :utc_datetime)`;
also cast the subquery column (`act.inserted_at::timestamptz`) so a `COALESCE`
mixes consistent types.
## List params inside fragments: `= ANY(?)`, not `IN ?`
Inside a raw fragment, Ecto renders a list parameter as `ARRAY['a','b']` for
`IN ?` — invalid PostgreSQL (`syntax error at or near \"ARRAY\"`). Use
`= ANY(?)` with the param typed as an array: `type(^list, {:array, :string})`.
## `union_all` with interpolated queries: pipe into the macro
Supported on the pinned stack (Ecto 3.14): `q1 |> union_all(^q2)` compiles and
renders UNION ALL with the param. What fails is calling it as a two-argument
function — `union_all(^q1, ^q2)` — "misplaced `^`". Both sides need matching
projections; when the SELECT shapes differ, merge two lean queries in Elixir:
`(Repo.all(a) ++ Repo.all(b)) |> Enum.frequencies() |> Enum.sort_by(fn {_id, d} -> d end, :desc) |> Enum.take(limit)`.
## Keyword lists must be the last argument
`Repo.aggregate(from(r in R, ...), :count)` fails. Bind first:
`q = from(...); Repo.aggregate(q, :count)`.
## Nullable JSONB columns need nil guards
`fragment(...)` on a nullable column crashes on NULL rows. Guard:
`not is_nil(p.meta) and fragment(...)`.
## Conditional filter composition
Never `^list == [] or ...` inside `where:`. Build the base query, then append
the optional filter:

```elixir
q = if types == [], do: q, else: from([r, s] in q, where: s.type not in ^types)
```
## `COALESCE` in select breaks GROUP BY
`select` with `fragment(\"COALESCE(?, ?)\", a.col, b.col)` plus `group_by` →
`ERROR 42803` (column must appear in GROUP BY). Select the primary column raw,
apply the fallback in Elixir after `Repo.all`.
## Mixing `as:` names with positional bindings
Positional bindings resolve by JOIN ORDER, not `as:` name — and must enumerate
EVERY preceding join. `[rl, mp]` binds the first two joins, regardless of the
`as:` you wrote. Use `as:` names consistently, or full positional order; never
mix.
## Composite `unique_constraint` reports the first field
`unique_constraint([:ctx_id, :slug])` reports the violation on `:ctx_id`.
Match constraint type, not field name: `opts[:constraint] == :unique`.
## `utc_datetime` truncates to seconds
Timestamps tie at second precision — never `Process.sleep/1` in tests. Backdate
deterministically: `Repo.update!(Ecto.Changeset.change(old, inserted_at: DateTime.add(old.inserted_at, -10, :second)))`.
## `put_change` silently skips decimal scale changes
`Ecto.Type.equal?/3` compares decimals numerically, so
`put_change(cs, :amount, Decimal.round(d, 2))` is a no-op when the value is
numerically equal. Use `force_change/3`.
## JSONB map key round-trip: atoms → strings
`Repo.insert` returns the map as given (atom keys); the next DB read returns
string keys. Normalize after every DB read — template dot syntax on atom-keyed
maps crashes; normalize with `Map.get(p, \"slug\") || Map.get(p, :slug)` per
key. `{:array, :map}` values round-trip the same way — HEEx dot access crashes.
## `Repo.update_all` needs a query, not kwargs
`Repo.update_all(WorkItem, set: [...], where: [...])` fails — no `where:`
option. Build the query: `Repo.update_all(from(w in WorkItem, where: w.id == ^old.id), set: [completed_at: ...])`.
## `fragment` + `order_by` "undefined variable w"
A fragment as the FIRST order element prevents Ecto from inferring the `[w]`
binding. Fix: two chained `order_by` calls — fragment without binding, then
fields with `[w]`:

```elixir
query
|> order_by(fragment(\"CASE metadata->>'priority' WHEN 'high' THEN 0 ... ELSE 99 END\"))
|> order_by([w], asc_nulls_last: w.due_date, desc: w.inserted_at)
```
## OFFSET/LIMIT without a unique tiebreaker → pages overlap
An `order_by` whose last key can tie (second-precision timestamps, bulk-updated
`completed_at`) makes pagination non-deterministic — items appear on both pages
or vanish; the suite stays green (small fixtures rarely tie). Fix: append a
unique tiebreaker as the LAST order key:
`|> order_by([w], asc_nulls_last: w.due_date, desc: w.inserted_at, asc: w.id)`.

Proof: ~12 rows sharing the same sort keys, fetch page 0 (limit 5) + page 1
(offset 5), assert `MapSet.disjoint?`; assert offset-beyond-total returns `[]`
and scoping filters are applied INSIDE the query (WHERE), not post-LIMIT.
## Correlated scalar subqueries (single-query fallback)
Replace an Elixir-side merge of "direct column + fallback to another table"
with one SQL query:

```sql
COALESCE(?,
  (SELECT act.inserted_at::timestamptz FROM work_item_activities act
   WHERE act.work_item_id = ? AND act.field = 'status'
     AND act.new_value = ANY(?) AND act.inserted_at >= ? AND act.inserted_at < ?
   ORDER BY act.inserted_at ASC LIMIT 1))
```
with args `w.completed_at, w.id, type(^@completed, {:array, :string}),
type(^from, :utc_datetime), type(^to, :utc_datetime)`. Verified: cut queries
per metric from 2 to 1 and works in Ecto Sandbox. A `LEFT JOIN LATERAL` variant
failed silently (param type inference) — prefer the scalar subquery.
## Materialized views go stale inside Ecto Sandbox tests
Postgres DDL is transactional — a `CREATE`/`REFRESH MATERIALIZED VIEW` run
through the Repo participates in the sandbox transaction (verified:
BEGIN / CREATE MV / SELECT / ROLLBACK). Tests see stale MVs for snapshot
reasons: the MV holds whatever was committed when it was last refreshed
(migrations or an external process), so rows the test just inserted never
appear unless the code path refreshes it. If the acceptance is
"2 queries → 1 query", a correlated scalar subquery achieves it without MV
lag/refresh machinery and stays correct under the sandbox. Only consider an MV
for genuinely immutable data that tests don't assert on.
## Schema gotchas
- Virtual fields cannot be `{:array, :atom}`: `(ArgumentError) unknown type
  :atom for field :sources` — declare `{:array, :string}` and match strings.
- `Repo.all(query_with_custom_select_and_preload)` won't preload a non-struct
  projection — select the struct, then `Repo.preload/3` in a second statement;
  add classification as virtual fields AFTER the query.
## Probe before baking
Before writing tests around a new fragment, run a throwaway probe inserting a
real row and verifying the query; wrap in a sandbox owner for zero residue:
`Ecto.Adapters.SQL.Sandbox.start_owner!(Repo, shared: false)` ... `Sandbox.stop_owner(owner)`.
## Verification
- `mix test` (full suite) — each pitfall above ships with a regression test.
- `Repo.to_sql(:all, query)` shows the rendered SQL — confirm the fragment
  landed in the WHERE before assuming the filter is applied.
