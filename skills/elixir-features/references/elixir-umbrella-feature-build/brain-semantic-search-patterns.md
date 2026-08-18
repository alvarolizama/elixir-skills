# Brain / semantic-knowledge feature patterns

Condensed notes from building the `Harness.Brain` LLM-wiki feature inside the
Money Bot umbrella.

## Design

- Entries are plain `text/markdown` records with a `vector(1024)` embedding and a
  `type` enum: `concept`, `question`, `procedure`, `entity`, `reference`,
  `decision`.
- Relationships are semantic, not explicit. The graph is a nearest-neighbor
  query using pgvector cosine distance. No link table is required for the MVP.
- In the final model every entry belongs to a `Brain.Context`. Slugs are
  unique **per context**, not globally.

## Implementation shape

| Responsibility | Where |
|----------------|-------|
| Schema + migrations | `:core` (`Core.Brain.Entry`, `Core.Brain.Context`) |
| Context + DB queries | `:core` (`Core.Brain`) |
| Vector generation via inference endpoint | `:harness` (`Harness.Brain.Vectorizer`) |
| Trigger vectorization after save | `:admin` (web LiveView `handle_event`) |
| UI: contexts / entries / graph | `:admin` (`Admin.BrainLive.*`) |

## Code snippets

### Schema

```elixir
@primary_key {:id, :binary_id, autogenerate: true}
schema "brain_entries" do
  field :type, :string
  field :title, :string
  field :slug, :string
  field :body, :string
  field :embedding, Pgvector.Ecto.Vector

  belongs_to :context, Core.Brain.Context, type: :binary_id

  timestamps(type: :utc_datetime_usec)
end
```

### Distance query

```elixir
import Pgvector.Ecto.Query

Entry
|> where([e], not is_nil(e.embedding))
|> maybe_filter_by_context(context_id)
|> order_by([e], asc: cosine_distance(e.embedding, ^Pgvector.new(embedding)))
|> limit(^k)
```

### Migration

```elixir
create table(:brain_contexts, primary_key: false) do
  add :id, :binary_id, primary_key: true
  add :name, :string, null: false
  add :slug, :string, null: false
  add :description, :text
  timestamps(type: :utc_datetime_usec)
end

create unique_index(:brain_contexts, [:slug])

alter table(:brain_entries) do
  add :context_id, references(:brain_contexts, type: :binary_id, on_delete: :delete_all)
end

flush()

# Backfill only if there are existing entries
execute """
DO $$
DECLARE
  v_count int;
BEGIN
  SELECT COUNT(*) INTO v_count FROM brain_entries;
  IF v_count > 0 THEN
    INSERT INTO brain_contexts (id, name, slug, description, inserted_at, updated_at)
    VALUES (gen_random_uuid(), 'General', 'general', 'Default context.', now(), now());

    UPDATE brain_entries
    SET context_id = (SELECT id FROM brain_contexts WHERE slug = 'general' LIMIT 1);
  END IF;
END $$;
"""

alter table(:brain_entries) do
  modify :context_id, :binary_id, null: false
end

drop unique_index(:brain_entries, [:slug])
create unique_index(:brain_entries, [:context_id, :slug])
```

### LiveView graph hook data attributes

```html
<div
  id="brain-graph"
  phx-hook="BrainGraph"
  data-nodes={Jason.encode!(@graph_data.nodes)}
  data-edges={Jason.encode!(@graph_data.edges)}
>
  <canvas class="w-full h-full"></canvas>
</div>
```

## Lessons

1. Keep `:core` free of `:harness` calls. The data context should not know how
   embeddings are produced; it only stores them.
2. Trigger async vectorization from the web layer (or a job) after the DB
   record exists, not from inside the context's `create_entry`.
3. Order static routes before dynamic ones: `/brain/graph` before `/brain/:slug`.
4. Use `Pgvector.Ecto.Query.cosine_distance/2`; bare `<=>` is not valid Elixir
   syntax inside `order_by`.
5. When adding a required parent relationship to an existing table, make the
   column nullable, conditionally backfill, then set `null: false`. Replace global
   unique indexes with scoped ones.
6. Verify `<.form phx-submit="...">` actually intercepts submit. If the browser
   makes a normal HTTP GET/POST instead of a LiveView event, inspect the rendered
   form in DevTools for a missing/mismatched `phx-submit` or a `<button>` that is
   not `type="submit"`.
