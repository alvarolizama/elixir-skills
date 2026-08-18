# Ecto migration: rename/2 does NOT rename columns (Ecto ≥3.14)

`rename :old_col, to: :new_col` inside `alter table` → `FunctionClauseError` in
`Ecto.Migration.rename/2`. In Ecto ≥3.14, `rename/2` only matches `%Table{}` and
`%Index{}` (renaming tables/indexes), NOT atoms for columns.

The signature changed: column renames used to be expressible as
`rename :col, to: :new` inside `alter table`, but `rename/2` in 3.14 resolves to
the table/index arity and blows up. Fix: raw SQL, reversible inside `change/0`:

```elixir
def change do
  execute(
    "ALTER TABLE providers RENAME COLUMN rerank_dialect TO rerank_format",
    "ALTER TABLE providers RENAME COLUMN rerank_format TO rerank_dialect"
  )
  alter table(:providers) do
    add :embedding_base_url, :string, null: true
  end
end
```

`execute(up, down)` keeps `change/0` reversible (no need to split into `up`/`down`).
Verified on my_app_gateway (migration `20260816000000`).
