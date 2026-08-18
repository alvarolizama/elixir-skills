# Persisting computed graph signals into my_app `Page.meta` + curation_agent pair enrichment

Recurring class of work: writing derived/computed data (graph signals like
pagerank, community_id; future centrality, embeddings stats) into my_app's
`Page.meta` JSONB column, and surfacing those signals to the LLM-driven
agents (CurationAgent, LinkGardenerAgent) as enrichment on existing tool results
without leaking raw internals.

This reference captures the two patterns that recur every time:

1. **JSONB-merge persistence** — the `Repo.update_all` + `COALESCE(meta,
   '{}'::jsonb) || ?::jsonb` pattern that bypasses `Brain.update_page/2`
   to avoid triggering the augmenter/embeddings/broadcasts side effects.
2. **CurationAgent pair enrichment** — select `meta` in the `find_duplicates`
   query, derive a boolean from both pages' meta, then strip `meta` from
   the returned payload before the LLM sees it.

## Why NOT `Brain.update_page/2` for computed signals

`Brain.update_page/2` (`lib/my_app/brain.ex:472`) is the full update path:
it writes the page, then triggers the PageAugmenter (embeddings, summary,
tags, semantic relations) and LiveView broadcasts. This is correct for
user-driven edits but catastrophic for bulk computed-signal writes:

- Re-running embeddings on every page after a nightly pagerank refresh
  burns inference API budget and overwrites user-authored summaries.
- Broadcasts fan out to all connected LiveView sockets for no reason.
- The augmenter re-creates `semantic` relations, churning the graph you
  just computed signals over.

**Always use the direct `Repo.update_all` + jsonb-merge pattern below
for graph-signal writes.** Never `Brain.update_page/2`.

## The JSONB-merge persistence pattern

```elixir
def refresh_pagerank(context_id) do
  ranks = pagerank(context_id)

  Enum.each(ranks, fn {page_id, score} ->
    new_meta = %{"pagerank" => Float.round(score, 6)}

    query =
      from(p in my_app.Brain.Page,
        where: p.id == ^page_id,
        update: [set: [meta: fragment("COALESCE(meta, '{}'::jsonb) || ?::jsonb", ^new_meta)]]
      )

    Repo.update_all(query, [])
  end)

  :ok
end
```

Key points:

- **`COALESCE(meta, '{}'::jsonb)`** guards against `meta IS NULL` (some
  legacy pages may have null meta). Without it, `NULL || ?::jsonb` returns
  NULL and wipes the column.
- **`|| ?::jsonb`** is the PostgreSQL jsonb merge operator: shallow merge,
  right wins. Existing keys are preserved; only the keys in `new_meta` are
  overwritten.
- **`Float.round(score, 6)`** for pagerank — keeps meta clean. For
  `community_id`, store as a plain integer (no rounding).
- **Returns `:ok`** — matches the convention for refresh functions so the
  Quantum job entrypoint and tests can assert cleanly.
- **`Repo.update_all(query, [])`** — the second arg is the empty options
  list; the `update` clause in the query carries the set operation. This
  is a common Ecto gotcha: `update_all/2` with an `update` keyword in
  the query vs `update_all/3` with a separate `set:` keyword.

## The nightly-job entrypoint shape

```elixir
def refresh_all_scheduled do
  slug = my_app.Auth.default_context_slug()

  case my_app.Brain.get_context_by_slug(slug) do
    nil -> {:error, :context_not_found}
    ctx ->
      :ok = refresh_pagerank(ctx.id)
      :ok = refresh_communities(ctx.id)
      :ok
  end
end
```

Same pattern as `my_app.Agent.CurationAgent.run_scheduled/0`. When adding a new
signal refresh, chain it here after the existing ones. The refreshes are
independent (each loads its own edges), so order doesn't matter for
correctness — but pagerank-first is conventional so community detection
could later reuse pagerank as a node-weight without a second pass.

The Quantum job wiring lives in `config/config.exs` (~line 77) and is
guarded by `if config_env() != :test`; `config/test.exs` keeps `jobs: []`.
Do NOT add test config for the job — the `refresh_all_scheduled/0`
function is tested directly.

## Reading signals back: `community_pages/2` query

When a consumer needs to query pages by a stored signal, use a fragment
on the text representation of the JSONB value cast to the right type:

```elixir
def community_pages(context_id, community_id) do
  Repo.all(
    from p in Page,
      where: p.context_id == ^context_id,
      where: fragment("(meta->>'community_id')::int = ?", ^community_id),
      select: %{id: p.id, slug: p.slug, title: p.title, page_type: p.page_type}
  )
end
```

- **`meta->>'community_id'`** returns the value as text (or NULL if absent).
- **`::int`** casts to integer so the `= ?` comparison is integer-to-integer.
  If you skip the cast, `"7" = 7` is false in Postgres.
- Pages without the key produce `NULL::int`, which fails the `=` predicate
  (NULL = anything is NULL/false), so they're correctly excluded.
- Always scope by `context_id` in addition to the meta filter — community
  ids are per-context (a page in context A with `community_id: 3` is
  unrelated to a page in context B with `community_id: 3`).

## CurationAgent pair enrichment pattern

When enriching an existing tool result (e.g. `find_duplicates`) with a
derived signal from both pages' meta:

```elixir
def execute_tool("find_duplicates", _args, %State{} = state) do
  context_id = state.session.context_id

  pairs =
    Repo.all(
      from p1 in Page,
        join: p2 in Page, on: ...,
        where: fragment("? <=> ?", p1.embedding, p2.embedding) < ^@duplicate_threshold,
        select: %{
          a: %{id: p1.id, slug: p1.slug, title: p1.title, meta: p1.meta},
          b: %{id: p2.id, slug: p2.slug, title: p2.title, meta: p2.meta},
          distance: fragment("? <=> ?", p1.embedding, p2.embedding)
        }
    )
    |> Enum.map(fn pair ->
      cid1 = get_in(pair.a, [:meta, "community_id"])
      cid2 = get_in(pair.b, [:meta, "community_id"])
      same_community = cid1 != nil and cid1 == cid2

      pair
      |> put_in([:a], Map.delete(pair.a, :meta))   # strip meta before LLM sees it
      |> put_in([:b], Map.delete(pair.b, :meta))
      |> Map.put(:same_community, same_community)
    end)

  {{:ok, pairs}, %{state | duplicate_pairs: pairs}}
end
```

Key points:

- **Select `meta` for both pages in the query** — single round trip, no
  N+1.
- **Derive the boolean in Elixir, not SQL** — keeps the query portable
  and makes the nil-handling explicit (`cid1 != nil and cid1 == cid2`).
- **Strip `meta` from the returned maps** — the LLM should see the
  derived flag (`same_community: true`), not the raw meta blob (which
  may contain internal keys, floats, etc. that confuse the prompt).
- **Document the new field in the system prompt** — tell the LLM what
  `same_community` means and how to weigh it. Without the prompt update,
  the field is ignored.

## System-prompt update for new signal fields

When you add a derived field to a tool result, update the agent's
`system_prompt/1` to explain it. Concrete example for `same_community`:

```
1. Call `find_duplicates` to get pairs of pages with very similar embeddings.
   Each pair includes a `same_community` boolean: when true, the graph
   community-detection algorithm also placed both pages in the same
   community (dense shared neighborhood). This is additional evidence
   that the pages are about the same topic — weigh it alongside the
   embedding distance, but do not treat it as conclusive on its own.
   When `same_community` is false, the pages are embedding-close but
   structurally in different communities (weaker duplicate signal).
```

Place the explanation at the workflow step where the tool is called, not
in a separate "rules" section — the LLM reads it in context that way.

## Testing the persistence + enrichment

Three test shapes cover this pattern:

### A — refresh writes the signal as the right type

```elixir
test "persists community_id into Page.meta as an integer" do
  ctx = fresh_context("rc")
  a = create_page(ctx, "g-rc-a")
  b = create_page(ctx, "g-rc-b")
  relate(a, b, "part_of")

  assert :ok = Graph.refresh_communities(ctx.id)

  a_reloaded = Brain.get_page!(a.id)
  assert is_integer(a_reloaded.meta["community_id"])
end
```

### B — existing meta keys survive the jsonb merge

```elixir
test "preserves existing meta keys when writing community_id" do
  # ... set meta: %{"kind" => "thought", "author" => "tester"} first
  :ok = Graph.refresh_communities(ctx.id)
  b_reloaded = Brain.get_page!(b.id)
  assert b_reloaded.meta["author"] == "tester"
  assert is_integer(b_reloaded.meta["community_id"])
end
```

### C — enrichment flag is set correctly (true / false / missing)

```elixir
test "enriches pairs with same_community flag when both pages share a community_id" do
  # insert two pages with close embeddings AND meta: %{"community_id" => 7}
  {{:ok, pairs}, _} = CurationAgent.execute_tool("find_duplicates", %{}, state)
  assert hd(pairs).same_community == true
  refute Map.has_key?(hd(pairs).a, :meta)  # meta stripped from payload
end

test "sets same_community to false when community_id is missing" do
  # pages with close embeddings but no community_id in meta
  # must be false, not crash
end
```

The `insert_page!` helper in curation_agent tests needs `meta: attrs[:meta] || %{}`
added so tests can seed pages with pre-set community_id. Without it, meta
defaults to nil and the JSONB queries behave unexpectedly.

## Pure-Elixir Label Propagation — implementation notes

When implementing a new graph algorithm over `relations`, the shape is:

1. **Load edges** via `Graph.load_edges(context_id)` — returns
   `%{source, target, type, weight}` maps scoped by context.
2. **Filter** by the algorithm's edge policy (e.g. `community_edge?/1`
   excludes `semantic` and `contradicts`; pagerank uses all edges).
3. **Build the adjacency structure** in one `Enum.reduce` — for
   community detection, undirected weighted: accumulate weight in both
   directions using nested `Access.key`:
   ```elixir
   adj =
     Enum.reduce(edges, %{}, fn e, acc ->
       acc
       |> update_in([Access.key(e.source, %{}), Access.key(e.target, 0.0)], &(&1 + e.weight))
       |> update_in([Access.key(e.target, %{}), Access.key(e.source, 0.0)], &(&1 + e.weight))
     end)
   ```
   `Access.key(k, default)` creates the nested map on demand and returns
   the default for missing keys, so this works on an empty accumulator.
4. **Iterate with `Enum.reduce_while`** for early-stop. Use a min-iter
   threshold (e.g. `iter > 3`) before checking convergence — the first
   1-2 iterations of Label Propagation barely move labels, and stopping
   on "no change after iter 1" produces degenerate clusterings.
5. **Shuffle node update order** each iteration (`Enum.shuffle(nodes)`)
   — Label Propagation is order-dependent; shuffling prevents pathological
   label cascades. This makes the algorithm non-deterministic; community
   ids are unstable across runs. Consumers must treat `community_id` as
   an opaque grouping key.
6. **Compress labels to `1..k`** at the end: `unique |> Enum.sort() |>
   Enum.with_index(1) |> Map.new()`. Keeps ids small and stable in shape
   regardless of which raw label (page id) "won" each community.
7. **Test with a fixed `:seed`** opt that calls `:rand.seed(:exsss,
   seed)` before the loop — makes assertions on pair-equality properties
   deterministic. Production leaves it unset.

### Edge cases to test

- **Empty context** — returns `%{}` (no nodes).
- **Only filtered edges** (e.g. only `semantic`) — returns `%{}` because
  no community edges survive the filter. Nodes do NOT appear as
  singletons; they're simply absent from the result. Tests must assert
  `refute Map.has_key?(comms, page.id)`, not `comms[a.id] != comms[b.id]`.
- **Isolated nodes** (no edges at all) — also absent from the result,
  for the same reason. If you need singletons for isolated nodes, you
  must union the node set with all pages in the context before
  initializing labels.
- **Undirected behavior** — edge direction must not affect clustering.
  Test with a triangle using mixed directions (a→b, c→b, a→c).

## Cross-references

- `references/my_app-agent-add-tool.md` — adding a new tool to an agent
  module (this session did NOT add a tool; it enriched an existing one).
  The enrichment pattern here is the lighter-weight sibling: no new tool
  spec, no `summarize_result/1` clause, just a derived field on the
  existing result + a system-prompt sentence.
- `references/brain-context-relation-lifecycle.md` — how `relations` and
  `Brain.create_relation/1` behave, which `load_edges/1` reads from.
