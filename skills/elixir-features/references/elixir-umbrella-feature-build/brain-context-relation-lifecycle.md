# Brain Context — Relation & Embed Lifecycle Patterns

Patterns for managing derived/auto-created relations in my_app's `my_app.Brain`
context. These are the conventions established in the 2026-07-17 session that
implemented auto-resolving `![[embeds]]` on page create/update.

## Embeds auto-resolution on `create_page` / `update_page`

### The lifecycle

Pages can embed other pages via the `![[slug]]` markdown syntax (e.g.
`See ![[file-a]]` in a note body). These embeds should produce `embeds`-type
`Relation` rows automatically — the user never creates them by hand.

- **On `create_page/1`:** after the insert succeeds, call `resolve_embeds(page)`.
  This scans the body for `![[slug]]` tokens and creates an `embeds` relation
  for each one whose target page exists in the same context.

- **On `update_page/2`:** call `reresolve_embeds(updated_page)`. This is a
  two-phase operation: (1) delete any `embeds` relations whose target slug is no
  longer present in the updated body, then (2) call `resolve_embeds` to create
  relations for any newly-referenced slugs. Both phases are needed — `resolve`
  alone only adds, never removes.

### Where to hook it

Both calls go **after the log_action, before the broadcast**:

```elixir
# create_page/1 — inside {:ok, page} branch
log_action(page.context_id, "page.create", ...)
resolve_embeds(page)
broadcast_page_change(page.context_id, :created, page)
my_app.Embeddings.schedule(page)
my_app.Brain.PageAugmenter.schedule(page)

# update_page/2 — inside {:ok, updated_page} branch
log_action(updated_page.context_id, "page.update", ...)
reresolve_embeds(updated_page)
broadcast_page_change(updated_page.context_id, :updated, updated_page)
my_app.Embeddings.schedule(updated_page)
my_app.Brain.PageAugmenter.schedule(updated_page)
```

Placing the call before the broadcast ensures any LiveView that reacts to
`:updated`/`:created` sees a relation graph that is already consistent.

### `reresolve_embeds/1` implementation

```elixir
def reresolve_embeds(%Page{} = page) do
  current_slugs =
    page.body
    |> extract_embeds()
    |> Enum.map(& &1.slug)
    |> MapSet.new()

  page.id
  |> list_relations_for_page()
  |> Map.get(:outbound, [])
  |> Enum.filter(&(&1.relation_type == "embeds"))
  |> Enum.each(fn rel ->
    target_slug = rel.target && rel.target.slug

    unless target_slug && MapSet.member?(current_slugs, target_slug) do
      Repo.delete(rel)
    end
  end)

  resolve_embeds(page)
end
```

Key points:
- `extract_embeds/1` returns `[%{slug: slug, display: display}]` — already
  exists in `brain.ex`; verify before re-implementing.
- `list_relations_for_page/1` already does `preload: [:target]`, so
  `rel.target.slug` works without an extra query. A defensive
  `rel.target && rel.target.slug` guard handles the edge case of a relation
  whose target was deleted.
- The `MapSet` membership check is what makes stale-cleanup idempotent:
  relations whose target slug is still in the body are preserved, only the
  orphaned ones are deleted.

### Idempotency — `on_conflict: :nothing`, NOT the changeset constraint

`Brain.create_relation/1` inserts with `on_conflict: :nothing`. That is what
makes `resolve_embeds/1` idempotent: re-inserting an existing
`(source_id, target_id, relation_type)` tuple is silently ignored at the SQL
level and succeeds without raising.

**Do NOT rely on the `unique_constraint` in `Relation.changeset` for this.**
A changeset constraint converts the violation into `{:error, changeset}` — but
only AFTER Postgres has raised the error, and a raised SQL error **poisons the
whole surrounding transaction**: every later query in the same
`Repo.transaction` fails with `current transaction is aborted`, and the
transaction returns `{:error, :rollback}` even though your code matched
`{:error, _}` and kept going. This exact bug broke `Brain.rename_slug/2`
(2026-07-17) when it called `update_page` (which re-resolves embeds) inside a
single transaction.

Rule: any insert that can run (a) inside `Repo.transaction`, or (b) in an
idempotent lifecycle hook like `resolve_embeds`, must use
`on_conflict: :nothing`. Keep the changeset `unique_constraint` too — it is
the safety net for non-transactional callers — but `on_conflict` is what
prevents the SQL error from ever being raised.

So `reresolve_embeds` can safely call `resolve_embeds(page)` at the end without
checking which relations already exist: the stale ones were just deleted, and
the surviving ones no-op on re-insert — with zero SQL errors, even inside a
transaction.

### Test pattern (TDD)

The canonical test pair for this lifecycle:

```elixir
# create resolves embeds
test "create_page resolves ![[embed]] into embeds relation", %{context: ctx} do
  {:ok, artifact} = Brain.create_page(%{context_id: ctx.id, title: "File", slug: "file-a", page_type: "artifact"})
  {:ok, note} = Brain.create_page(%{context_id: ctx.id, title: "Note", slug: "note-a", page_type: "note", body: "See ![[file-a]]"})
  rels = Brain.list_relations_for_page(note.id).outbound
  assert Enum.any?(rels, &(&1.relation_type == "embeds" and &1.target_id == artifact.id))
end

# update removes stale embeds
test "update_page removes stale embeds relations", %{context: ctx} do
  {:ok, a} = Brain.create_page(%{context_id: ctx.id, title: "A", slug: "a", page_type: "artifact"})
  {:ok, b} = Brain.create_page(%{context_id: ctx.id, title: "B", slug: "b", page_type: "artifact"})
  {:ok, note} = Brain.create_page(%{context_id: ctx.id, title: "N", slug: "n", page_type: "note", body: "![[a]] ![[b]]"})
  {:ok, note} = Brain.update_page(note, %{"body" => "only ![[a]] now"})
  targets = Brain.list_relations_for_page(note.id).outbound |> Enum.filter(&(&1.relation_type == "embeds")) |> Enum.map(& &1.target_id)
  assert a.id in targets
  refute b.id in targets
end
```

### When to extend this pattern

If another relation type becomes body-derived (e.g. `[[wikilink]]` →
`related` relations), reuse this exact structure:
1. Add the extraction function (`extract_wikilinks/1`).
2. Add `resolve_wikilinks/1` mirroring `resolve_embeds/1`.
3. Add `reresolve_wikilinks/1` mirroring `reresolve_embeds/1` (delete stale,
   then resolve).
4. Call both from `create_page` and `update_page` in the same location.

The two-phase (delete-stale + resolve-new) structure is the durable part;
the specific regex and relation type are the variable part.

## Meta-derived relations: `sync_planning_relations/2` (2026-07-17)

The embeds lifecycle above derives relations from the page **body**. The
planning-hierarchy feature derives `part_of` relations from the page
**`meta` JSONB map** (`goal_slug` / `plan_slug`). The stale-cleanup
strategy differs because of this — see the contrast below.

### What it does

- **plan** with `meta.goal_slug` → ensures `part_of` plan→goal.
- **todo** with `meta.plan_slug` → ensures `part_of` todo→plan.
- **todo** with `meta.goal_slug` and NO `plan_slug` → ensures `part_of`
  todo→goal. When a `plan_slug` IS set, the direct todo→goal link is
  dropped (plan takes precedence).
- On slug change/removal, the old `part_of` to the *prior* target is
  deleted. Manual `part_of` relations to unrelated targets are NEVER
  touched — cleanup is keyed on the exact prior slug.

### Hook placement (same slot as embeds)

```elixir
# create_page/1 — inside {:ok, page} branch
log_action(...)
resolve_embeds(page)
sync_planning_relations(page)          # NEW — no prior_page on create

# update_page/2 — inside {:ok, updated_page} branch
log_action(...)
reresolve_embeds(updated_page)
sync_planning_relations(updated_page, page)   # NEW — page is the pre-update struct
```

### Stale cleanup via PRIOR state (contrast with embeds)

`reresolve_embeds` re-reads existing relations from the DB and diffs them
against the current body to find stale ones. That works because the body
is the single source of truth — any `embeds` relation whose target slug
isn't in the current body is stale by definition.

`sync_planning_relations` CANNOT use that approach, because manual
`part_of` relations to other targets are legitimate and must survive.
Instead it needs the **prior** `meta` to know which single old slug to
clean up:

```elixir
def sync_planning_relations(page, prior_page \\ nil)

def sync_planning_relations(%Page{page_type: type} = page, prior_page)
    when type in ~w(plan todo) do
  new_goal = meta_string(page.meta, "goal_slug")
  prior_goal = if prior_page, do: meta_string(prior_page.meta, "goal_slug"), else: nil
  # ...
  maybe_drop_planning_part_of(page.slug, prior_goal, new_goal, context_id)
  ensure_part_of(page.slug, new_goal, context_id)
end
```

The `maybe_drop_planning_part_of(source, prior_slug, new_slug, ctx)` guard
only deletes when `prior_slug != new_slug` — i.e. the slug actually changed
or was removed. This is what preserves manual relations: a manually-created
`part_of` to some unrelated slug is never `prior_slug`, so it's never
touched.

**Rule:** when the "current valid set" comes from a field the user can
also set manually elsewhere (meta, tags, etc.), use prior-state diffing,
not DB-diffing. DB-diffing would delete relations the user intentionally
created.

### Reading jsonb meta: `meta_string/2`

`meta` is a `:map` field backed by jsonb. Postgres returns it as a
**string-keyed** map (`%{"goal_slug" => "x"}`), not atom keys. Read it
with a defensive helper:

```elixir
defp meta_string(nil, _key), do: nil
defp meta_string(meta, key) when is_map(meta) do
  case Map.get(meta, key) do
    val when is_binary(val) -> val
    _ -> nil
  end
end
```

The `is_binary/1` guard rejects `nil`, `""`, atoms, and numbers — all of
which should be treated as "no value." Don't assume the key exists or holds
a string.

### `create_relation_by_slugs` already handles missing targets

`sync_planning_relations` calls `create_relation_by_slugs/4`, which returns
`{:error, :target_not_found}` when the goal/plan page doesn't exist yet.
That's fine — `ensure_part_of/3` ignores the return value. The lint report
(see below) flags the broken ref; the page creation itself never fails.
This respects the "captura rápida tiene prioridad" principle: slugs may
point forward to pages not yet created.

### Lint extensions for planning refs

The `lint/1` report was extended with three read-only checks, each a
separate public function feeding into the report map:

- `broken_plan_refs/1` — todos whose `plan_slug` doesn't resolve to a plan.
- `broken_goal_refs/1` — plans+todos whose `goal_slug` doesn't resolve to a goal.
- `unplanned_todos/1` — todos with no plan AND no goal (informational, not error).

Each uses a `not in subquery(...)` pattern on the jsonb fragment:

```elixir
known_plan_slugs = from(p in Page, where: p.context_id == ^cid and p.page_type == "plan", select: p.slug)

from p in Page,
  where: p.context_id == ^cid and p.page_type == "todo" and
    fragment("?->>'plan_slug'", p.meta) != "" and
    fragment("?->>'plan_slug'", p.meta) not in subquery(known_plan_slugs)
```

**Rule:** extend the existing `lint/1` map — never replace it. Add new
keys alongside `:orphans`, `:stale`, `:contested`. Callers (e.g.
`mcp.ex` lint formatter) read specific keys and ignore unknown ones, so
additive changes are safe.

## Jsonb hierarchy filters with derived join + `"none"` semantics (2026-07-17)

When a child row links to a parent via a jsonb meta slug AND that parent links
to a grandparent the same way, filtering the child by grandparent needs a
**self-join on the same table through the jsonb fragment**. The goal of the
child is **derived** (single source of truth = the parent), never denormalized
onto the child.

```elixir
# todo --meta.plan_slug--> plan --meta.goal_slug--> goal
# "todos of goal X" = todos with meta.goal_slug == X  OR  todos whose plan has meta.goal_slug == X

defp maybe_filter_goal_slug(query, nil), do: query

defp maybe_filter_goal_slug(query, goal_slug) do
  from p in query,
    left_join: plan in Page,
    on:
      plan.slug == fragment("?->>'plan_slug'", p.meta) and
        plan.context_id == p.context_id and
        plan.page_type == "plan",
    where:
      fragment("?->>'goal_slug'", p.meta) == ^goal_slug or
        fragment("?->>'goal_slug'", plan.meta) == ^goal_slug
end
```

Key points:

- **Join condition uses the jsonb fragment** `fragment("?->>'plan_slug'", p.meta)`
  matched against the sibling's `slug` column — always qualify with
  `context_id` and `page_type` so slugs don't collide across contexts or with
  a non-plan page that happens to share the slug.
- **`distinct(query, true)` (full-row), NOT `distinct(query, [p], p.id)`** —
  a todo matching via both its own `goal_slug` and its plan's produces a
  duplicate row from the OR + join. `DISTINCT ON (p.id)` requires `p.id` to
  lead the `ORDER BY`, which conflicts with `order_by(desc: p.updated_at)`.
  Full-row `DISTINCT` has no such coupling and join duplicates are
  byte-identical, so it's safe. (Already a pitfall in the umbrella SKILL.md.)
- **Literal `"none"` = "has no X"** — reserve a sentinel string for the orphan
  query rather than overloading `nil` (which means "no filter"):

  ```elixir
  defp maybe_filter_goal_slug(query, "none") do
    from p in query,
      left_join: plan in Page, on: /* same as above */,
      where:
        (is_nil(fragment("?->>'goal_slug'", p.meta)) or
           fragment("?->>'goal_slug'", p.meta) == "") and
          (is_nil(fragment("?->>'goal_slug'", plan.meta)) or
             fragment("?->>'goal_slug'", plan.meta) == "")
  end
  ```

  For `"none"` BOTH the direct value and the derived value must be absent —
  an orphan is "no direct goal AND no plan that has a goal."
- **Empty string is also "absent"** — jsonb meta can hold `""` from form
  inputs; always treat `""` the same as NULL in absence checks.
- **Derived, not denormalized** — the child's `goal_slug` is NOT written when
  a `plan_slug` is set. This keeps one source of truth (the plan), so moving
  the plan to another goal never desyncs the children. The cost is one
  indexed LEFT JOIN, trivial in Postgres. Only denormalize when the read
  pattern is hot enough to justify the sync-on-write complexity.
- **Doc the scope** — these filters only make sense for certain `page_type`s
  (goal_slug for plan/todo, plan_slug for todo). Note it in the `@doc`, not
  in validation — the filter on a non-planning type just returns everything.
