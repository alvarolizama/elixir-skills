# Ecto query-construction gotchas (authoring, not tracing)

Reusable pitfalls hit while *building* Ecto queries in a Phoenix umbrella. Complements
the main skill (tracing SQL → source); these are about writing queries that compile and
return the SQL you expect.

## 1. `fragment()` + `order_by` binding → "undefined variable w"

Mixing a `fragment()` with field clauses that need the `[w]` binding in a **single
`order_by`** fails to compile:

```elixir
# BROKEN — "undefined variable w" on the fragment element, regardless of the literal
order_by(
  query,
  [w],
  fragment("CASE metadata->>'priority' WHEN 'high' THEN 0 ... ELSE 99 END"),
  asc_nulls_last: w.due_date,      # w never bound because the fragment references no column
  desc: w.inserted_at
)
```

Ecto cannot infer the source binding `w` when the first order element is a `fragment`
that doesn't reference a column. **Fix: two chained `order_by` calls** — one for the
`fragment` (no binding), one for the field clauses (with `[w]`):

```elixir
defp maybe_terminal_order(query, _) do
  query
  |> order_by(fragment("CASE metadata->>'priority' WHEN 'high' THEN 0 ... ELSE 99 END"))
  |> order_by([w], asc_nulls_last: w.due_date, desc: w.inserted_at)
end
```

### Interpolation in fragments: literals vs params
Ecto's `fragment` does **not** accept `^"string"` params the way embedded queries do —
`fragment(..., ^"priority", ^"high", ...)` errors with "misplaced operator". Two options:
- **Constant literals** (hardcoded code values, e.g. priority buckets): inline them
  directly into the fragment string. This is safe because they're not user data.
- **Runtime values** (user input): use `type(^value, :string)` or build the fragment with
  `Ecto.Query`-safe placeholders — never string-interpolate user input.

## 2. `Repo.update_all/3` needs a query, not `where:` kwargs

`Repo.update_all` does **not** accept a `where:` option. Passing the schema struct +
`where:` kwarg fails:

```elixir
# BROKEN
Repo.update_all(WorkItem, set: [completed_at: now], where: [id: old.id])
```

Build the query with `from/2` and bind the id:

```elixir
Repo.update_all(
  from(w in WorkItem, where: w.id == ^old.id),
  set: [completed_at: DateTime.add(now, -40, :day)]
)
```

Useful in tests to simulate timestamps (e.g. `completed_at`) that the schema changeset
computed automatically — set the field directly after create rather than fighting the
changeset.

## 3. Pagination functions must replicate the in-Elixir sort, or the order drifts

When adding a new SQL pagination function (e.g. `list_kanban_column(status, opts)`)
that must match an existing in-Elixir sort, **read the Elixir sort block line-by-line
first** — do not guess the priority ordering. In Hub's `kanban_live.ex:272-306`:
- Active columns sort by `{priority, due_date asc nulls last, inserted_at desc}`.
- Priority map `@priority_order %{"high" => 0, "medium" => 1, "low" => 2}` with
  unknown → 99.
- Terminal columns sort by `completed_at desc` (fallback `updated_at`), nils last.

The SQL `CASE` must reproduce the *default* value too, not just the three known buckets —
an unknown priority must sort last (99) to match the Elixir `Map.get(..., 99)` fallback.

Write a **parity test**: create items with known priorities + due dates, call the new SQL
function, assert the SQL order matches the documented Elixir sort order. This is what
catches silent drift when someone later reorders the in-memory sort.

## 4. A `fragment` CASE on `metadata->>'priority'` sorts the whole subset

The `metadata` JSONB CASE can't use a normal index; with a small `LIMIT` + a `status`
filter (which *does* use the existing partial index), the planner does index-scan +
sort on the subset — efficient. Don't add a functional index unless the EXPLAIN at
prod scale shows it matters.

## 5. OFFSET/LIMIT without a unique tiebreaker → pages overlap (suite-green invisible)

An `order_by` whose last key can tie (e.g. `inserted_at` — same transaction/second
resolution, or `completed_at` on bulk-updated rows) makes OFFSET/LIMIT pagination
**non-deterministic**: Postgres may order ties differently between page 0 and page 1,
so items appear on both pages or vanish entirely. The suite stays green (small
fixtures rarely tie); an ad-hoc pagination script with N > 2×page_size same-key
fixtures catches it instantly.

**Fix:** append a unique tiebreaker as the LAST order key on every paginated query —
`asc: w.id` works fine:

```elixir
|> order_by([w], asc_nulls_last: w.due_date, desc: w.inserted_at, asc: w.id)
# terminal: desc_nulls_last: w.completed_at, desc_nulls_last: w.updated_at, asc: w.id
```

**Ad-hoc proof pattern:** insert ~12 rows sharing the same sort keys, fetch page 0
(limit 5) + page 1 (offset 5), assert `MapSet.disjoint?` — overlap means the
tiebreaker is missing. Also assert offset-beyond-total returns `[]`, and that any
scoping filter is applied **inside** the query (WHERE), not post-LIMIT in Elixir —
filtering after the limit silently shrinks pages.

## 6. `fragment(^built_string)` → Ecto.Query.CompileError (SQL-injection guard)

`fragment()` rejects `^` on a dynamically-built first argument at compile time:

```
** (Ecto.Query.CompileError) to prevent SQL injection attacks, fragment(...) does not
allow strings to be interpolated as the first argument via the `^` operator
```

This bites when generating fragment SQL from a field list (`Enum.map` +
`Enum.join(" AND ")` then `fragment(^sql)`). **Fix:** write each fragment as a
literal and combine with `dynamic/2`:

```elixir
dynamic([w],
  fragment("TRIM(COALESCE(metadata->>'field_a', '')) <> ''") and
  fragment("TRIM(COALESCE(metadata->>'field_b', '')) <> ''")
)
```

For OR/AND across a runtime list of filter conditions, build one `dynamic` per filter
and `Enum.reduce` with `dynamic([w], ^acc or ^cond)` / `^acc and ^cond` — dynamics
compose; raw fragment strings don't.

## 7. Correlated scalar subquery + COALESCE (single-query fallback pattern)

To replace an Elixir-side merge of "direct column + fallback to another table" with a
single SQL query, use a **correlated scalar subquery** inside `COALESCE`:

```elixir
fragment("""
COALESCE(?,
  (SELECT act.inserted_at::timestamptz
   FROM work_item_activities act
   WHERE act.work_item_id = ? AND act.field = 'status'
     AND act.new_value = ANY(?) AND act.inserted_at >= ? AND act.inserted_at < ?
   ORDER BY act.inserted_at ASC
   LIMIT 1))
""", w.completed_at, w.id, type(^@completed, {:array, :string}), type(^from, :utc_datetime), type(^to, :utc_datetime))
```

Verified on TRACKER-TRAC-844823: it replaced the hybrid 2-query + merge pattern in
`TrackerStats.fetch_completions/3` and `fetch_completions_full/3`, cut queries per
metric from 2 to 1, and works in Ecto's Sandbox (a materialized view does not — see §8).

### `LEFT JOIN LATERAL` variant FAILED silently — prefer the scalar subquery

First attempt used `join(:left_lateral, ..., on: is_nil(w.completed_at))` +
`where COALESCE(w.completed_at, a.inserted_at) < ^to`. In PostgreSQL the SQL is valid
(proved with raw psql) yet **Ecto returned `[]`** for rows with `completed_at` set.
Debugging (stepwise: `JOIN_ONLY` returned the row; adding the `< to` WHERE killed it)
pointed to the **parameter type inference** for `^to` inside the fragment — see §9.
The scalar-subquery form avoids the lateral binding entirely and is more portable.

## 8. Materialized views are invisible inside Ecto Sandbox tests

A materialized view is a static snapshot: `REFRESH MATERIALIZED VIEW` is DDL that runs
outside the sandbox transaction and never sees rows inserted by the test. Tests that
assert on data written in the test (e.g. dashboard/velocity counts) fail with the MV
always empty. If the acceptance is "2 queries → 1 query", a correlated scalar subquery
(§7) achieves it without the MV lag/refresh machinery and works in tests. Only consider
an MV when the data is genuinely immutable/cached and tests don't assert on fresh rows.

## 9. Timestamp comparisons in fragments need explicit parameter types

`COALESCE(w.completed_at, a.inserted_at) < ^to` where `w.completed_at` is
`:utc_datetime` and `^to` is a `DateTime` **failed silently** (returned `[]`) until the
parameter was typed: Ecto inferred a type that didn't match `timestamptz`, so the
comparison misbehaved. Fix — wrap every datetime parameter in `type/2`:

```elixir
type(^from, :utc_datetime),
type(^to, :utc_datetime)
```

Also cast the subquery's returned column: `act.inserted_at::timestamptz` so the
`COALESCE` mixes consistent types, and wrap the final `COALESCE(...)` select with
`type(fragment(...), :utc_datetime)` so Postgrex decodes a `DateTime` (not
`NaiveDateTime`). Symptom when missing: downstream `DateTime.to_date/1` raises
FunctionClauseError on `~N[...]`.

## 10. `= ANY(?)` not `IN ?` for lists inside fragments

Inside a raw fragment string, Ecto renders a list parameter as `ARRAY['a','b']` for
`IN ?`, which is invalid PostgreSQL (`syntax error at or near "ARRAY"`). Use
`= ANY(?)` and type the param as an array:

```elixir
AND act.new_value = ANY(?)   # with type(^@completed, {:array, :string}) as the arg
```

## 11. Reusing fragment SQL: module constants, not concatenation

`fragment(@attr, ...)` works when `@attr` is a module attribute string literal —
Ecto expands it as a literal. But `fragment(@attr <> " >= ?", ...)` fails with the
SQL-injection guard (§6) because the first argument is no longer a pure literal.
To reuse the same subquery with different trailing operators, define **separate
constants** per variant (base, `_ge`, `_lt`) instead of concatenating at the call site.

