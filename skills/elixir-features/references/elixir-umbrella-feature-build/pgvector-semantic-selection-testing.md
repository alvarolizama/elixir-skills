# Testing pgvector-based semantic selection with synthetic embeddings

Pattern from the my_app `Summaries.candidate_pages/1` TDD session (Task 2.4),
reusable for any feature that selects records by embedding distance.

## The problem

You have a function that should return the *semantically closest* N records
(e.g. candidate pages for inline links, nearest neighbors for auto-relations).
The naive implementation sorts by `updated_at` desc. You need a test that
proves the selection is semantic, not temporal — and that relevant records
are included even when they're the oldest in the table.

## Technique: synthetic vectors + controlled timestamps

Construct 1024-dim vectors where the target is close to "relevant" pages and
far from "noise" pages. Give the noise pages **recent** `updated_at` and the
relevant pages **old** `updated_at`. If the function returns the relevant
pages, it's selecting by distance, not recency.

```elixir
test "returns semantically closest pages, not just most recent" do
  context = my_app.Brain.get_context_by_slug("personal")

  # Target = [1.0, 0.0, ...], relevant = [0.9, 0.0, ...] (small L2/cosine distance)
  # Noise = [0.0, 1.0, 0.0, ...] (max distance)
  target_vec  = [1.0 | List.duplicate(0.0, 1023)]
  relevant_vec = [0.9 | List.duplicate(0.0, 1023)]
  noise_vec   = [0.0, 1.0 | List.duplicate(0.0, 1022)]

  old_ts = ~U[2020-01-01 00:00:00Z]
  new_ts = ~U[2026-01-01 00:00:00Z]

  # 51 noise pages — recent, far away. A recency-based list_pages(limit: 50)
  # would return 50 of these and exclude all relevant pages.
  for i <- 1..51 do
    %Page{
      context_id: context.id,
      title: "Noise #{i}",
      slug: "noise-#{i}",
      body: "noise body",
      page_type: "note",
      embedding_hash: "noise-#{i}",
      embedding: Pgvector.new(noise_vec),
      updated_at: new_ts,
      inserted_at: new_ts
    }
    |> my_app.Repo.insert!()
  end

  # 3 relevant pages — old, close to target.
  relevant_slugs =
    for i <- 1..3 do
      %Page{
        context_id: context.id,
        title: "Relevant #{i}",
        slug: "relevant-#{i}",
        body: "relevant body",
        page_type: "note",
        embedding_hash: "relevant-#{i}",
        embedding: Pgvector.new(relevant_vec),
        updated_at: old_ts,
        inserted_at: old_ts
      }
      |> my_app.Repo.insert!()
      |> Map.fetch!(:slug)
    end

  target =
    %Page{
      context_id: context.id,
      title: "Target",
      slug: "target",
      body: "target body",
      page_type: "note",
      embedding_hash: "target",
      embedding: Pgvector.new(target_vec)
    }
    |> my_app.Repo.insert!()

  candidates = Summaries.candidate_pages(target)
  candidate_slugs = Enum.map(candidates, & &1.slug)

  for slug <- relevant_slugs do
    assert slug in candidate_slugs,
           "expected semantically close page #{slug} in candidates, got: #{inspect(candidate_slugs)}"
  end
end
```

### Why 51 noise pages (not just 2)?

The function has `limit: 50`. If there are ≤50 noise pages, a recency sort
might still include relevant pages by accident (the limit hasn't been
exhausted by noise). **51 noise pages** guarantees that a `limit: 50`
recency sort returns 50 noise pages and excludes all 3 relevant ones —
making the test a true discriminator between the old and new behavior.

### Vector design

| Vector | Purpose | Distance to target |
|--------|---------|-------------------|
| `[1.0, 0.0, ...]` | target | 0 (self) |
| `[0.9, 0.0, ...]` | relevant | small (~0.1 L2, ~0.005 cosine) |
| `[0.0, 1.0, 0.0, ...]` | noise | max (~1.41 L2, ~1.0 cosine) |

Keep vectors sparse (mostly zeros) — they're easy to construct with
`List.duplicate/2` and make the distance math predictable.

## Testing the fallback branch (no embedding)

When the function has a fallback for records without embeddings (e.g.
recency-sorted `list_pages`), test it separately with `embedding: nil`:

```elixir
test "falls back to list_pages when page has no embedding" do
  # ... create pages with embedding: nil ...
  candidates = Summaries.candidate_pages(target)
  # assert the fallback returns siblings, NOT the target itself
  refute target.slug in Enum.map(candidates, & &1.slug)
end
```

## Design decision: public function for testability

The plan suggested `candidate_pages/1` as a private function. We made it
**public** to test the selection logic directly without going through the
full LLM prompt construction (`augment_prompt/1`). This is preferable when:

- Testing the prompt output would require stubbing the inference API
  and parsing the prompt string (fragile, tests the wrong thing).
- The selection logic is the actual business value — it's what changed.
- The function has a clean contract: `Page.t() -> [map()]`.

Testing through the prompt tests integration; testing the function directly
tests the unit. Do both when feasible, but prioritize the unit test.

## Pitfall: branch consistency on self-exclusion

When a function has two branches (embedding path vs. fallback path), both
must agree on invariants. The embedding branch excluded the target page
via `where: p.id != ^page.id` in the SQL query. The fallback branch used
`Brain.list_pages/1` which does NOT exclude the target — so the target
appeared in its own candidate list. Fix: add `|> Enum.reject(&(&1.id == page.id))`
to the fallback to match the SQL branch's invariant.

**Rule:** when a function has `if has_embedding? do ... else ... end`,
audit both branches for shared invariants (self-exclusion, context scoping,
limit). They must agree.

## Constructing a vector at a target cosine distance

When testing functions that filter neighbors by a distance threshold (e.g.
`PageAugmenter.semantic_threshold/1`), you need a vector at a *specific*
cosine distance from the reference — not just "close" or "far."

**Technique:** given a reference unit vector `e1 = [1.0, 0.0, 0.0, ...]`,
construct the target as `[cos θ, sin θ, 0.0, ...]` where `cos θ = 1 - d`
and `d` is the desired cosine distance.

```elixir
# d = target cosine distance from e1.
# cosine_distance(e1, v) = 1 - dot(e1, v) / (|e1| * |v|) = 1 - cos θ = d
defp vector_at_distance(d) do
  cos = 1.0 - d
  sin = :math.sqrt(max(0.0, 1.0 - cos * cos))
  [cos, sin] ++ List.duplicate(0.0, 1022)
end

# The reference vector the embeddings stub returns for the source page.
defp reference_vector, do: [1.0, 0.0] ++ List.duplicate(0.0, 1022)
```

**Why this works:** pgvector's `<=>` operator computes cosine *distance*
(`1 - cosine_similarity`). For unit vectors, `distance = 1 - cos θ`. So
to get distance `d`, set `cos θ = 1 - d` and `sin θ = √(1 - cos²θ)`.

**Test pattern for threshold-based filtering:**

```elixir
test "short page does NOT create relation at distance 0.18 (threshold 0.15)" do
  # Short body (<500 chars) → threshold 0.15. Neighbor at 0.18 > 0.15 → no edge.
  enable_inference()
  stub_embeddings_chat()  # stub returns reference_vector/0 for /v1/embeddings

  context = Brain.get_context_by_slug("personal")

  {:ok, target} = Brain.create_page(%{context_id: context.id, title: "T", slug: "t", body: "x", page_type: "note"})
  set_embedding(target, vector_at_distance(0.18))  # 0.18 > 0.15 threshold

  {:ok, page} = Brain.create_page(%{context_id: context.id, title: "S", slug: "s",
    body: String.duplicate("x", 300), page_type: "note"})

  assert :ok = PageAugmenter.run(page)
  %{outbound: outbound} = Brain.list_relations_for_page(page.id)
  refute Enum.any?(outbound, &(&1.target_id == target.id))
end

test "long page creates relation at distance 0.25 (threshold 0.28)" do
  # Long body (>4000 chars) → threshold 0.28. Neighbor at 0.25 < 0.28 → edge.
  # ... same setup, body: String.duplicate("y", 4001), distance: 0.25
  # assert Enum.any?(outbound, &(&1.target_id == target.id))
end
```

**Key details:**
- The embeddings stub (`/v1/embeddings` endpoint) must return `reference_vector/0`
  for the source page. The target page's embedding is set directly via
  `Ecto.Changeset.change(embedding: Pgvector.new(vector_at_distance(d)))`.
- Use unique `embedding_hash` values per page to prevent `Embeddings.needs_embedding?`
  from re-generating (which would overwrite your carefully constructed vector).
- For multi-neighbor tests, construct vectors at different distances
  (`vector_at_distance(0.05 + i * 0.05)`) to control which neighbors pass
  the threshold and which don't.

## Running the TDD cycle

```bash
# RED — function doesn't exist, test fails with UndefinedFunctionError
mix test test/my_app/summaries_test.exs

# GREEN — implement candidate_pages/1, all tests pass
mix test test/my_app/summaries_test.exs

# Verify no warnings
mix compile --warnings-as-errors
```

The RED phase should fail with `function my_app.Summaries.candidate_pages/1 is undefined or private`
— a clean failure proving the test exercises the new code, not existing behavior.
