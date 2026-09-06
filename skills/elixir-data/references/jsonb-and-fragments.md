# JSONB & Fragments — filtering, defaults, expression indexes

Everything about `meta`-style JSONB columns: what silently fails, what works,
and how to index it. All verified.

## The `@>` containment trap

Symptom: `fragment("? @> ?::jsonb", p.meta, ^json)` returns `false` through
Postgrex even when the stored row exactly contains the object; the same query
with a literal (`'{"role":"sales"}'::jsonb`) returns `true`.

Mechanism (verified): Postgrex encodes the JSON string param as `text`;
containment over the casted parameter doesn't match the stored jsonb.
`@>` with a parameter is a dead end — do not fight it.

## Per-key `->>` filter (the working pattern)

One `where` per key/value pair → AND semantics, correct pagination, indexable:

```elixir
defp maybe_filter_props(query, props) when is_map(props) and map_size(props) > 0 do
  Enum.reduce(props, query, fn {key, value}, q ->
    text_value = if is_binary(value), do: value, else: Jason.encode!(value)
    where(q, [p], fragment("?->? = ?", p.meta, ^to_string(key), ^text_value))
  end)
end
defp maybe_filter_props(query, _props), do: query
```

Notes:

- The KEY as a parameter (`->>?`) works; only the `@>` jsonb VALUE param is broken.
- Non-string values (numbers, nested maps) must be `Jason.encode!/1`'d so the
  comparison matches how the store serialized them.
- For deeply nested filters (`meta.props.role`), address the path directly:
  `fragment("?->'props'->>? = ?", p.meta, ^key, ^text_value)` — the string key
  inside the fragment must be passed as a PARAMETER, or quotes get stripped and
  you get `ERROR 42703 (undefined_column) column "props" does not exist`.

## Inbox / null-checks

Filters for "no link set" use SQL NULL semantics on the `->>` result:

```elixir
from q in query,
  where: fragment("meta->>'project_slug' IS NULL") and
         fragment("meta->>'goal_slug' IS NULL")
```

## Post-query Elixir filter: fallback only

`Repo.all` + `Enum.filter` over `get_in(page.meta, ["props"])` is correct for
small non-paginated datasets — but it filters AFTER `limit`/`offset`, so
pagination silently shrinks pages. Reserve it for the small-data case.

## Nullable columns

Any fragment over a nullable JSONB column crashes on NULL rows. Guard:
`not is_nil(p.meta) and fragment(...)`.

## Expression indexes for `->>` filters

GIN covers `@>` and `?`, NOT `meta->>'key' = ?`. A per-key partial expression
index is what serves the `->>` filter:

```sql
CREATE INDEX pages_meta_kanban_status_idx
  ON pages ((meta ->> 'kanban_status'))
  WHERE meta ->> 'kanban_status' IS NOT NULL;
```

Ecto migration form (loop over the hot keys; `concurrently: true` requires
`@disable_ddl_transaction true` + `@disable_migration_lock true`):

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

Verify afterwards in `pg_indexes`.

## JSONB map key round-trip

`Repo.insert` returns map fields as-given (atom keys); the next DB read
returns string keys; `{:array, :map}` returns string keys too. Normalize after
every DB read — template dot access crashes on atom-keyed maps:

```elixir
%{summary | top_pages: Enum.map(summary.top_pages || [], fn p ->
  %{slug: Map.get(p, "slug") || Map.get(p, :slug),
    title: Map.get(p, "title") || Map.get(p, :title)}
end)}
```

## JSONB defaults in migrations

`add :col, :jsonb, default: %{}` in an `alter` is rejected by Ecto. Use
`default: fragment("'{}'::jsonb")`.

## The hierarchy-vs-links model (when the JSONB exists at all)

A rigid `project > goal > plan` hierarchy with precedence rules creates opaque
precedence (one slug silently wins), impossible multi-parents, and JOIN-heavy
queries. Prefer INDEPENDENT links — each slug materializes its own relation:

```
Todo
  ├── meta.project_slug  →  part_of project
  ├── meta.goal_slug     →  part_of goal
  └── meta.plan_slug     →  part_of plan
```

Each link syncs independently (`sync_one_link` per slug), queries filter
directly by `meta->>'field' = ?`, and new link types are trivial to add.
Use a true hierarchy only when the domain is a real single-parent tree
(filesystems, org charts, taxonomies).

## Kanban-on-JSONB patterns

- One global kanban with filter dropdowns beats per-container boards
  (per-container boards duplicate 600+ lines; cards show at most 2 linked
  containers as badges, rest in tooltip; clicking a badge filters by that link).
- Filters combinable: `project:X AND goal:Y`, `project:X AND inbox`,
  `inbox` (no links at all).
- Don't JOIN for filters — `meta->>'field' = ?` with expression indexes is
  simpler and faster.
- Don't auto-hide done; provide a "Show done" toggle.

## Probe recipe

Before baking a new fragment, probe with a disposable script that inserts a
real fixture row and asserts the query — and use a sandbox owner for zero
residue:

```elixir
:ok = Ecto.Adapters.SQL.Sandbox.mode(Repo, :manual)
owner = Ecto.Adapters.SQL.Sandbox.start_owner!(Repo, shared: false)
# ... assertions ...
Ecto.Adapters.SQL.Sandbox.stop_owner(owner)
```

Raw probe gotchas: UUID params need `Ecto.UUID.dump!/1` (binary form), and
`timestamp` decodes as `NaiveDateTime` (cast `::date` when you want `Date`).

## Verification

- `Repo.to_sql(:all, query)` must show the `meta` WHERE clause before you trust
  a fragment filter.
- After index migrations: `SELECT indexname FROM pg_indexes WHERE tablename = 'pages'`
  shows the expression indexes; `EXPLAIN` with `SET enable_seqscan = off` shows
  them being used.