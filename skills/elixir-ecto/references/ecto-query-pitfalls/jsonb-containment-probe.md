# JSONB containment debugging transcript (my_app, 2026-03)

Context: adding a `props` filter (`meta.props` JSONB bag) to `Brain.list_pages/1`. Page schema has `field :meta, :map, default: %{}`. The session that produced the `ecto-query-pitfalls` skill.

## Attempt 1 — `meta->'props' @> jsonb`

```elixir
where(query, [p], fragment("?->'props' @> ?::jsonb", p.meta, ^props_json))
```

Runtime error:

```
** (Postgrex.Error) ERROR 42703 (undefined_column) column "props" does not exist
query: SELECT ... WHERE (p0."meta"->props @> $2::jsonb)
```

The single quotes around `'props'` were stripped during fragment macro expansion, turning the string key into a column reference.

## Attempt 2 — key as parameter

```elixir
fragment("?->? @> ?::jsonb", p.meta, "props", ^props_json)
```

No SQL error, but returned 0 rows for a matching fixture. Data verified present:

```
Raw meta in DB: "{\"props\": {\"role\": \"sales\"}}"
```

## Attempt 3 — whole-map containment

```elixir
filter_json = Jason.encode!(%{"props" => %{"role" => "sales"}})
where(query, [p], fragment("? @> ?::jsonb", p.meta, ^filter_json))
```

Probe result:

```
Raw meta in DB: "{\"props\": {\"role\": \"sales\"}}"
Containment test: false
```

`@>` returned `false` despite a visually exact match — most likely the custom `PostgresTypes` type module encoding the param differently than the stored jsonb. Not worth fighting.

## Attempt 4 — raw SQL probe (hit a second trap)

```elixir
Repo.query!("SELECT meta @> $1::jsonb FROM pages WHERE id = $2", [json, page.id])
```

```
** (DBConnection.EncodeError) Postgrex expected a binary of 16 bytes, got "845571d9-..."
```

Raw queries with UUID primary keys need `Ecto.UUID.dump!(page.id)`, not the string form.

## Initial approach — post-query Elixir filter

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

19/19 ad-hoc checks passed (AND logic, single/multi props, no-match, nil/empty props) plus full suite green. Shipped in commit `9ec52f7`.

**Lesson:** with `:map` fields and a custom types module, prefer Elixir-side filtering unless profiling proves you need the SQL operator — and then probe with raw SQL + `Ecto.UUID.dump!/1` first.

---

## UPDATE (my_app Fase 3, 2026-08): the SQL filter IS achievable — per-key `->>` comparison

A later session revisited this to push the `props` filter into SQL (the post-query `Enum.filter` broke `limit`/`offset` pagination). Probing confirmed WHY `@>` fails and what works instead:

**Root cause of the `@>` false:** the value is sent as a `text` param. Verified directly:

```
ENCODED: "{\"role\":\"sales\"}"
PARAM containment (meta->props @> $1::jsonb): [[false], [false], [false]]
RAW literal  (meta->props @> '{"role":"sales"}'::jsonb): [[true], [true], [true]]
```

Same value — literal `true`, param `false`. Postgrex sends the JSON string as `text` and `@>` over the casted param doesn't match. So `@>` with a param is a dead end, full stop.

**What works — per-key `->> ? = ?` text comparison** (the same pattern the codebase already uses for `kanban_status`, `assignee`, etc.). One `where` per key/value pair gives AND logic, keeps pagination correct, and hits the meta GIN/expression indexes:

```elixir
defp maybe_filter_props(query, props) when is_map(props) and map_size(props) > 0 do
  Enum.reduce(props, query, fn {key, value}, q ->
    text_value = if is_binary(value), do: value, else: Jason.encode!(value)
    where(q, [p], fragment("?->'props'->>? = ?", p.meta, ^to_string(key), ^text_value))
  end)
end
defp maybe_filter_props(query, _props), do: query
```

Confirmed green: single filter (2 rows), AND filter (1 row), SQL `to_sql` contains the `props` WHERE, full suite 582/582. The key as a parameter (`->>?`) DOES work here — only the `@>` jsonb value param is broken.

**Refined rule:** for flat JSONB key/value filters, prefer per-key `->> ? = ?` in SQL over post-query Elixir filtering whenever `limit`/`offset` pagination matters. Reserve the Elixir filter for small, non-paginated datasets.

---

## UPDATE (my_app Fase 3, 2026-08): expression indexes for `->>` filters

The per-key `->> ? = ?` approach works in SQL but without an index it's still a
seq scan. The GIN index on `meta` does NOT cover `meta->>'key' = ?` (GIN covers
`@>`/`?`, not `->>` text equality on a specific key).

**Fix:** partial expression indexes — one per hot key, built concurrently:

```sql
CREATE INDEX pages_meta_kanban_status_idx
  ON pages ((meta ->> 'kanban_status'))
  WHERE meta ->> 'kanban_status' IS NOT NULL;
```

Ecto version (loop over 5 keys, migration `20260808061633`):

```elixir
@keys ~w(kanban_status assignee plan_slug goal_slug project_slug)

def up do
  for key <- @keys do
    create index(:pages, ["((meta ->> '#{key}'))"],
      name: :"pages_meta_#{key}_idx",
      where: "meta ->> '#{key}' IS NOT NULL",
      concurrently: true)
  end
end
```

Requires `@disable_ddl_transaction true` + `@disable_migration_lock true` at the
module level for `concurrently: true`. Verified: all 5 indexes created clean,
tests 582/582, ad-hoc verification confirmed the indexes exist in `pg_indexes`.
