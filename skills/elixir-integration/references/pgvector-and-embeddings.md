# pgvector & Embeddings in Ecto

Setting up pgvector in Ecto, testing with stubbed embeddings, and adapting
to Ecto 3.14 schema-introspection changes. Symptom → mechanism → fix →
verification.

## pgvector setup

**Symptom.** `Ecto.Query` with an embedding column fails to compile or
errors at runtime: "type vector can not be handled by the types module
`Postgrex.DefaultTypes`".

**Mechanism.** `Postgrex` does not know the `vector` type by default; the
types module that maps `vector` → `Ecto` must be registered in config, and
the schema must declare the field type.

**Fix.**

```elixir
# config/config.exs
config :my_app, MyApp.Repo,
  types: MyApp.PostgrexTypes

# lib/my_app/postgrex_types.ex
defmodule MyApp.PostgrexTypes do
  @behaviour Postgrex.Extension
  # implement encode/encode!/decode/decode!/format/name for "vector"
end

# schema
schema "documents" do
  field :embedding, MyApp.Pgvector.Ecto.Type   # vector(1536) etc.
end
```

**Verification.**

```bash
MIX_ENV=test mix ecto.migrate && mix test
```

The error above going away at migrate time is the proof the types module
is wired; if it appears, the `types:` config line is missing or the
extension is not loaded (`CREATE EXTENSION IF NOT EXISTS vector` in the
migration).

## Embedding dimension discipline

**Symptom.** Cosine searches return garbage similarity or Postgres rejects
the vector length.

**Mechanism.** Different providers emit different dimensions (e.g. 384 vs
1536); the column declared for one dimension rejects another.

**Fix.** Pin the provider/model in config, derive the column dimension
from it, and assert at runtime when indexing:

```elixir
@dimension Application.compile_env(:my_app, :embedding_dimension)

def insert_embedding(changeset, vector) when is_binary(vector) do
  Ecto.Changeset.validate_change(changeset, :embedding, fn _, v ->
    if byte_size(v) == @dimension, do: [], else: [embedding: "wrong dimension"]
  end)
end
```

**Verification.** Test inserts a wrong-length vector → changeset error;
route the dimension centrally so a provider swap cannot desync it.

## Testing with stubbed embeddings

**Symptom.** Tests call the embedding provider on every insert even though
search logic (not vector math) is what's under test.

**Mechanism.** `Req`/HTTP calls run in tests, hit real endpoints, and make
the suite slow and flaky.

**Fix.** Stub the embedding call with `Req.Test` (see `rest-api-patterns.md`)
and inject deterministic vectors:

```elixir
test "search finds nearest" do
  Req.Test.stub(MyApp.Embeddings, fn conn ->
    Plug.Conn.resp(conn, 200, ~s({"embedding":[0.1,0.2,0.3]}))
  end)
end
```

Deterministic fixtures (same input → same bytes) keep assertions exact.

**Verification.** `mix test` passes with `Req.Test` and no network; a test
that exercises a real provider call is marked `@tag :integration` and
excluded by default.

## Ecto 3.14 schema-introspection changes

**Symptom.** After upgrading Ecto, existing `field :embedding,
MyApp.Pgvector.Ecto.Type` schemas fail loading at compile time, or
`Ecto.embedded_load/2` behaves differently.

**Mechanism.** Ecto 3.14 changed schema introspection (types are resolved
lazily / via the schema's `__schema__` metadata differently than 3.12).
Code that introspects `MyApp.Schema.__schema__(:fields)` at compile time
and assumed old type shapes breaks.

**Fix.**

- Pin Ecto to the target version and run `mix ecto.migrate` + full suite
  on upgrade; read the changelog for introspection semantics.
- Avoid compile-time introspection of custom types — resolve them through
  the repo's types module at runtime, or cache the field list lazily.
- Re-run the pgvector wire-up (types config + extension) after upgrade:
  the two are separate and either can be silently reverted by a bad merge.

**Verification.** After upgrade: `mix compile --warnings-as-errors` and the
migrate + test pair above all green; a query assembling a vector search
(`ORDER BY embedding <#> ...` or `<=>`) returns expected nearest rows.

## Verification commands

```bash
MIX_ENV=test mix ecto.migrate && mix test
mix compile --warnings-as-errors

# vector type is wired in config
grep -rn "types:.*PostgrexTypes\|Postgrex.Extension" config/ lib/ | wc -l   # >= 1
```