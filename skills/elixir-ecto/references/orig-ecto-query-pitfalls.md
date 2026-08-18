---
name: ecto-query-pitfalls
author: Álvaro Lizama
description: Use when Ecto fragments, JSONB, or unions misbehave. Fixes.
---

# Ecto Query Pitfalls (Postgres)

Hard-won traps when writing non-trivial Ecto queries, each verified against a real Postgres-backed app. Probe first with a `mix run` script before baking assumptions into code or tests.

## 1. JSONB containment `@>` can silently return false with `:map` fields

`field :meta, :map` serializes to JSONB, but `where: fragment("? @> ?::jsonb", p.meta, ^json)` can return `false` even when the row visually matches. The root cause is **Postgrex parameter encoding**: it sends the value as a text string, and even though `::jsonb` cast is in the SQL, the `@>` operator returns false for a parameterized value that works correctly as a literal (`'{"role":"sales"}'::jsonb` → true; `$1::jsonb` with same value → false).

### Working SQL alternative — per-key `->>` text comparison (PREFERRED)

Instead of `@>` containment or post-query Elixir filtering, use per-key `->>` text comparison. This pushes the filter into SQL (keeps limit/offset pagination correct) and works reliably through Postgrex:

```elixir
# BROKEN — @> with parameter returns false even when rows match
fragment("COALESCE(?, '{}'::jsonb) -> 'props' @> ?::jsonb", p.meta, ^Jason.encode!(props))

# WORKING — per-key text comparison with parameterized key AND value
Enum.reduce(props, query, fn {key, value}, q ->
  text_value = if is_binary(value), do: value, else: Jason.encode!(value)
  where(q, [p], fragment("?->'props'->>? = ?", p.meta, ^to_string(key), ^text_value))
end)
```

This works because `->>` (text extraction) accepts parameterized keys, and `=` comparison with text parameters works correctly through Postgrex. The pattern matches what the MyApp codebase already uses for `kanban_status`, `assignee`, `plan_slug`, etc.

### Post-query Elixir filter (FALLBACK only)

If you need `@>` semantics (nested containment, not just key-value equality), filter post-query in Elixir — but this breaks pagination correctness (limit/offset applies before the filter):

```elixir
pages = Repo.all(query)
if is_map(props) and map_size(props) > 0 do
  Enum.filter(pages, fn page ->
    page_props = get_in(page.meta || %{}, ["props"]) || %{}
    Enum.all?(props, fn {k, v} -> Map.get(page_props, k) == v end)
  end)
else
  pages
end
```

Use the SQL `->>` approach when possible; fall back to Elixir filtering only when the filter logic can't be expressed as key-value equality.

## 2. JSONB string keys inside fragments get mangled

`fragment("?->'props' @> ?::jsonb", p.meta, ^json)` compiles to `meta->props` (quotes stripped) → **ERROR 42703 column "props" does not exist**. Pass the key as a parameter instead:

```elixir
fragment("?->? @> ?::jsonb", p.meta, "props", ^props_json)
```

…or avoid the fragment entirely (see pitfall 1).

## 3. `union_all` refuses plain variables inside `from`

`from x in subquery(union_all(outbound, inbound))` → `` `inbound` is not a valid union_all. union_all must always be an interpolated query, such as ^existing_query ``. But `union_all(^outbound, ^inbound)` then fails with "misplaced operator ^" because the pin only works inside matches/custom macros. The robust escape hatch: **skip the union** — run two lean id-only queries and merge in Elixir:

```elixir
(Repo.all(outbound_ids) ++ Repo.all(inbound_ids))
|> Enum.frequencies()
|> Enum.sort_by(fn {_id, degree} -> degree end, :desc)
|> Enum.take(limit)
```

Linear, no SQL gymnastics, and the ids are cheap to move.

## 4. Keyword lists must be the last argument

`Repo.aggregate(from(r in R, join: ..., where: ..., :count))` → "unexpected expression after keyword list" syntax error. Bind the query to a variable first, then `Repo.aggregate(q, :count)`.

## 5. Nullable JSONB columns need a nil guard

Operator fragments on a nullable map column blow up on NULL rows. Guard: `not is_nil(p.meta) and fragment(...)`.

## 6. Composing filters conditionally

`^exclude_types == [] or ...` inside a `where:` is fragile. Instead build the base query in a helper and apply the optional filter with an `if` re-pipe:

```elixir
q = if exclude_types == [], do: q, else: from([r, s, t] in q, where: s.page_type not in ^exclude_types)
```

Binding positional aliases (`[r, s, t]`) must match the join order of the original query.

## 7. `COALESCE(col, rl.other_col)` in a SELECT breaks GROUP BY

Putting a column from another binding inside `COALESCE` in `select:` with `group_by:` → **ERROR 42803 (grouping_error) column "r0.model_requested" must appear in the GROUP BY clause**. Postgres rejects it because the fallback column isn't grouped or aggregated. Don't fight it in SQL — select the primary column raw, then apply the fallback in Elixir after `Repo.all/1`:

```elixir
# BAD — 42803
|> select([rl, ma], %{model_name: fragment("COALESCE(?, ?)", ma.name, rl.model_requested)})
|> group_by([rl, ma], [ma.id, ma.name])

# GOOD — select ma.name raw, COALESCE in Elixir
|> select([rl, ma], %{model_name: ma.name})
|> group_by([rl, ma], [ma.id, ma.name])
# after Repo.all:
row.model_name || "—"
```

## 8. Mixing `as:` join names with positional bindings silently binds wrong

When you name joins with `as:` but reference bindings positionally in a LATER join's `on:`, Ecto resolves the positional list by JOIN ORDER, not by the `as:` name. Symptom: SQL like `LEFT JOIN provider_credentials AS p3 ON m1.credential_id = p3.id` where `m1` is `model_aliases` — the join went to the wrong table's FK. Example:

```elixir
# BAD — [rl, mp] here is positional: rl=RequestLog(0), mp=ModelAlias(1), NOT ModelProvider(2)
|> join(:left, [rl], ma in ModelAlias, on: rl.model_alias_id == ma.id, as: :model_alias)
|> join(:left, [rl], mp in ModelProvider, on: rl.model_provider_id == mp.id, as: :model_provider)
|> join(:left, [rl, mp], c in Credential, on: mp.credential_id == c.id)  # mp → model_aliases!

# GOOD — positional bindings must include EVERY preceding join in order
|> join(:left, [rl], ma in ModelAlias, on: rl.model_alias_id == ma.id)
|> join(:left, [rl, ma], mp in ModelProvider, on: rl.model_provider_id == mp.id)
|> join(:left, [rl, ma, mp], c in Credential, on: mp.credential_id == c.id)
```

Rule: either reference everything by `as:` name (consistent) or by full positional order (consistent). Never mix — or if you do, the positional list must enumerate every join so far, including the ones you named.

## 11. `==` inside a fragment is Elixir, not SQL

`fragment("?->>'job_key' == ?", p.meta, ^key)` → **ERROR 42883 (undefined_function) operator does not exist: text == unknown**. Muscle memory writes Elixir's `==` into the SQL string; Postgres equality is `=`. Every `->>` text comparison in a fragment is `fragment("?->>'key' = ?", ...)`. The codebase's own examples (`kanban_status`, `assignee`) all use single `=` — copy them exactly.

## 12. `Repo.insert` return keeps map fields as-given (atom keys) — jsonb string keys only after a DB read

`field :meta, :map` over jsonb: the struct returned by `Repo.insert(changeset)` carries the changeset-applied value verbatim — if you cast `meta: %{kind: "log"}`, you get back `%{kind: "log"}` with ATOM keys. The jsonb dump/load round trip (which produces `%{"kind" => "log"}`) only happens on an actual read. Tests asserting `page.meta["kind"]` against the insert-returned struct get `nil` and look like "meta was dropped". Two fixes: reload before asserting (`Repo.get!(Schema, page.id)`), or have the creating function reload so every caller gets string keys (what `MyApp.Jobs.execute/3` does). `Brain.create_page/1` in MyApp returns the un-reloaded insert struct — always reload if you need `meta["..."]`.

## 12b. `{:array, :map}` round-trips maps with STRING keys — HEEx dot access crashes

`field :top_pages, {:array, :map}, default: []` (as in `community_summaries`): when you `Repo.insert` a struct with `top_pages: [%{slug: "x", title: "Y"}]` (atom keys), the **next read from the DB** returns `[%{"slug" => "x", "title" => "Y"}]` — **all string keys**. HEEx templates that access `page.title` (dot syntax = atom key) crash with `KeyError: key :title not found in %{"title" => "Y", ...}`.

This is the SAME root cause as pitfall 12 (jsonb round-trip converts atom → string keys), but inside an array of maps. The fix: **normalize after every DB read**, before passing to the template:

```elixir
defp normalize_summary(summary) do
  top_pages =
    Enum.map(summary.top_pages || [], fn page ->
      %{
        slug: Map.get(page, "slug") || Map.get(page, :slug),
        title: Map.get(page, "title") || Map.get(page, :title),
        pagerank: Map.get(page, "pagerank") || Map.get(page, :pagerank)
      }
    end)

  %{summary | top_pages: top_pages}
end
```

Apply in EVERY code path that loads summaries from the DB: `apply_action(:index)`, `apply_action(:show)`, `handle_info` reloads. Use `Map.get(page, "string") || Map.get(page, :atom)` so it works whether the map came from a fresh insert (atoms) or a DB read (strings).

**Pitfall:** the `Ecto.Type.equal?/3` silent-skip from pitfall 15 does NOT apply here — `{:array, :map}` changes always register because the whole array is replaced, not compared element-by-element.

## 13. Composite `unique_constraint` error lands on the FIRST field

`unique_constraint([:context_id, :slug], name: :pages_context_id_slug_index)` reports the violation on `:context_id`, not `:slug` (Ecto attaches to the first field of the list unless `:error_key` is given). When matching changeset errors to detect a collision and retry (e.g. generate a new slug), match on the constraint type — `Enum.any?(cs.errors, fn {_f, {_msg, opts}} -> opts[:constraint] == :unique end)` — not on a specific field name.

## 14. `utc_datetime` timestamps tie at second precision — backdate, never sleep, in tests

`timestamps(type: :utc_datetime)` truncates to seconds, so `order_by: [desc: :inserted_at]` ties for rows written within the same second and "latest record" queries (`Enum.uniq_by` after desc sort, `LIMIT 1`) are non-deterministic. In tests, don't `Process.sleep(1_100)` to force ordering — backdate the older row deterministically:

```elixir
Repo.update!(Ecto.Changeset.change(old, inserted_at: DateTime.add(old.inserted_at, -10, :second)))
```

Explicitly set `inserted_at` on insert is honored (timestamp autogenerate only fills nil), which also enables cheap retention-test fixtures with staggered timestamps.

## 15. `put_change` silently skips decimal scale-only changes

`Ecto.Type.equal?/3` compares `:decimal` fields **numerically**, not structurally. When a `numeric(12,6)` column loads as `Decimal("25.500000")` and you try to normalize its display scale with `put_change(cs, :amount, Decimal.round(d, 2))`, the change is silently dropped (`changeset.changes` stays `%{}`) because 25.50 "equals" 25.500000 — and the form input renders the full scale (`value="25.500000"`). Use `force_change/3` to bypass the equality check:

```elixir
# put_change → silent no-op for scale-only decimal differences
# force_change → always records the change
Ecto.Changeset.force_change(changeset, :daily_limit_usd, Decimal.round(d, 2))
```

Symptom: number inputs in edit forms showing full numeric scale instead of rounded cents. Verified on a Phoenix edit-form changeset (2026-08): `put_change` left `changes: %{}`, `force_change` rendered `value="25.50"`.

## Probe pattern

Before writing tests around a new fragment/operator, run a throwaway script: `MIX_ENV=test mix run /tmp/probe.exs` that inserts a real row, runs the query, and `IO.inspect`s both the raw stored value (`fragment("?::text", p.meta)`) and the operator result. Ten minutes of probing beats an hour of guessing why a test returns 0 rows. See `references/jsonb-containment-probe.md` for the full debugging transcript that produced pitfall 1.

For probes/verification scripts that must leave ZERO residue (ad-hoc feature verification against a real app), wrap the whole script in a sandbox owner so everything rolls back on exit:

```elixir
:ok = Ecto.Adapters.SQL.Sandbox.mode(MyApp.Repo, :manual)
owner = Ecto.Adapters.SQL.Sandbox.start_owner!(MyApp.Repo, shared: false)
# ... assertions (raise on failure) ...
Ecto.Adapters.SQL.Sandbox.stop_owner(owner)
```

Works under `MIX_ENV=test mix run script.exs` — no manual cleanup, test DB untouched.

## 9. Hot-query composite indexes: match the WHERE/GROUP BY/ORDER BY shape

Separate single-column indexes do NOT serve multi-column predicates. When profiling shows a query pattern is hot (page lists, graph counts, version lookups, activity logs), write a migration that adds composite indexes shaped exactly like the query, then **verify with EXPLAIN that the planner actually uses them** — don't assume.

Verified on MyApp (migration `20260808000000_add_query_optimization_indexes`):

| Query pattern | Composite index that serves it |
|---|---|
| WHERE context_id=X AND page_type=Y AND archived=false ORDER BY updated_at DESC | pages (context_id, page_type, archived) |
| GROUP BY page_type WHERE context_id=X (counts) | pages (context_id, page_type) — gives an Index Only Scan |
| WHERE page_id=X AND version=Y (exact version lookup) | page_versions (page_id, version) UNIQUE — the two separate single-column indexes can't serve the composite predicate |
| WHERE context_id=X ORDER BY inserted_at DESC LIMIT N (activity log) | brain_log (context_id, inserted_at) — backward index scan |

Lessons:

- **EXPLAIN before/after is the verification.** Use a `mix run` script with a real (dummy) UUID: `Repo.query!("EXPLAIN SELECT ...", [])`. Confirm the plan says Index Scan using the new index / Index Only Scan / Index Scan Backward. If the planner still picks an old index, either the new one is redundant or the table is too small for it to matter — check with realistic row counts.
- **A UNIQUE composite beats two singles** for exact two-column lookups. `page_versions (page_id, version)` UNIQUE both enforces data integrity AND serves the lookup in one index.
- **Index Only Scans are the jackpot** — when the SELECT columns are all in the index, Postgres never touches the heap. GROUP BY page_type WHERE context_id=X becomes index-only with (context_id, page_type).
- **Ecto migration syntax:** `create index(:pages, [:context_id, :page_type, :archived], name: :pages_ctx_type_archived_idx)` / `create unique_index(:page_versions, [:page_id, :version], name: :page_versions_page_version_uidx)`. Always name indexes explicitly so `down` can drop by name and so prod/CI can check them.
- **GIN indexes for arrays/JSONB** (tags, meta) are separate — a composite B-tree won't cover array/JSONB containment; those need their own GIN.
- Apply to BOTH envs: `mix ecto.migrate` and `MIX_ENV=test mix ecto.migrate` before the suite.

Migration template (verified applied clean, up/down symmetric):

```elixir
def up do
  create index(:pages, [:context_id, :page_type, :archived], name: :pages_ctx_type_archived_idx)
  create index(:pages, [:context_id, :page_type], name: :pages_ctx_type_idx)
  create unique_index(:page_versions, [:page_id, :version], name: :page_versions_page_version_uidx)
  create index(:brain_log, [:context_id, :inserted_at], name: :brain_log_ctx_inserted_at_idx)
end
```

## 10. Partial expression indexes for hot JSONB `->>` filters

When a query filters on `fragment("?->>'kanban_status' = ?", p.meta, ^status)` or
similar `meta->>'key' = value` patterns, the GIN index on `meta` does NOT serve
this — GIN covers `@>`/`?` containment and key existence, not `->>` text equality
on a specific key. Every such filter is a **seq scan** over the table.

The fix is a **partial expression index** — an index on the expression
`(meta->>'kanban_status')`, filtered to only rows where the key is present:

```elixir
# migration
create index(
  :pages,
  ["((meta ->> 'kanban_status'))"],
  name: :pages_meta_kanban_status_idx,
  where: "meta ->> 'kanban_status' IS NOT NULL",
  concurrently: true
)
```

Key points:
- **Expression, not column**: `((meta ->> 'kanban_status'))` is a computed
  expression, wrapped in double parens so Postgres treats it as an indexable
  expression, not a column name.
- **Partial (`WHERE`)**: only index rows where the key exists — keeps the index
  tiny on tables where most rows don't have that meta key (e.g. notes don't
  have `kanban_status`).
- **`concurrently: true`**: doesn't lock the table on a populated prod DB.
  Requires `@disable_ddl_transaction true` + `@disable_migration_lock true` at
  the migration module level.
- **One per hot key**: if you filter by `kanban_status`, `assignee`,
  `plan_slug`, `goal_slug`, `project_slug` — each gets its own expression
  index. Don't try to combine them.

Verified on MyApp (migration `20260808061633`) — 5 expression indexes for the
kanban/todos views. The Ecto `where` fragments like
`fragment("?->>'kanban_status' = ?", p.meta, ^status)` now use these indexes
instead of seq-scanning `pages`.

Ecto migration syntax (loop over multiple keys):

```elixir
@keys ~w(kanban_status assignee plan_slug goal_slug project_slug)

def up do
  for key <- @keys do
    create index(
      :pages,
      ["((meta ->> '#{key}'))"],
      name: :"pages_meta_#{key}_idx",
      where: "meta ->> '#{key}' IS NOT NULL",
      concurrently: true
    )
  end
end

def down do
  for key <- @keys do
    drop_if_exists index(:pages, name: :"pages_meta_#{key}_idx", concurrently: true)
  end
end
```

**When to use**: any `meta->>'key' = ?` or `meta->>'key' IS NOT NULL` that appears
in a hot query path (kanban board, filtered list views, API list endpoints).
If the table is small (< 1000 rows), the seq scan is fine — don't over-index.
