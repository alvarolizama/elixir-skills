# LiveView Consolidation — N Near-Identical Views Into One

**Trigger:** N near-identical LiveViews (one per page type / entity)
drift and duplicate; the durable fix is ONE generic LiveView
parameterized by the URL, with routes restructured so a wildcard doesn't
swallow first-class routes. Also fires any time
`~p"/#{@workspace_slug}/..."` starts raising
`cannot convert nil to param`.

## Verify consolidation is correct BEFORE starting

- `diff` two of the near-identical LiveViews with the type name
  substituted — if they are ~95% identical (same render shell, same
  events, only the type, back path, and nav highlight differ),
  consolidation is right.
- Confirm the shared heavy lifting already lives in a helper that takes
  the type as a param (e.g. `PageDetail.load_page_detail/4` with `type`,
  `active_nav`, `redirect_to`). The generic wrapper should be THIN — no
  new logic.
- Grep the whole `lib/` AND `test/` for old route refs before deleting
  anything. Orphan tests are a silent regression source.

## The pattern

1. Resolve the type from `params` in `mount`/`handle_params`
   (e.g. `PageTypes.type_from_path(params["type"])`).
2. Guard mount: invalid type → `push_navigate` home instead of
   rendering.
3. Build back/page paths from `workspace_slug + type + slug` in ONE
   helper, not inline.
4. Delete the per-type LiveViews AND their test files (`rm` them — don't
   leave stubs).
5. Verify: `mix compile --warnings` zero warnings, then `mix test` and
   compare the failure set against the pre-refactor baseline
   (`git stash` + run + `git stash pop`) to prove zero regressions.

## Pitfall: route ordering — first-class routes BEFORE the generic wildcard

Phoenix matches routes in **definition order**. A generic
`live "/:workspace_slug/:type", PagesLive, :index` defined BEFORE
`live "/:workspace_slug/activity", ActivityLive, :index` swallows it —
`:type` captures `"activity"`. Same static-before-wildcard rule that
governs the root scope.

```elixir
# Correct order — first-class entities/views first, generic LAST
live "/:workspace_slug/goals", GoalLive, :index
live "/:workspace_slug/activity", ActivityLive, :index
live "/:workspace_slug/search", SearchLive, :index
# ... generic catch-all last:
live "/:workspace_slug/:type", PagesLive, :index
```

## Pitfall: `~p` with nil interpolation crashes at runtime

`~p"/#{@workspace_slug}/..."` raises
`ArgumentError: cannot convert nil to param` (via
`Phoenix.Param.Atom.to_param/1`) when the assign is nil — e.g. an
instance-level page rendered without a selected workspace. **Both**
fixes are needed:

1. **In `mount`, never let the slug be nil** — fall back to a default
   workspace slug even if the workspace ROW doesn't exist, so the
   template never sees nil:

   ```elixir
   {context, workspace_slug} =
     case context do
       nil -> {MyApp.Knowledge.get_workspace_by_slug(slug), slug}  # slug string survives
       ctx -> {ctx, ctx.slug}
     end
   ```

2. **In the layout/sidebar, guard workspace-scoped links** with
   `:if={@workspace_slug}` and render only global items (dashboard,
   settings, docs) when nil. Otherwise the `~p` interpolation in the
   sidebar nav crashes before the template even renders.

## Pitfall: Phoenix.Component helpers must be arity 1

In a module using `use Phoenix.Component`, a zero-arity
`defp foo()` is rejected:
`cannot declare attributes for function foo/0. Components must be
functions with arity 1`. Inline the map literal or make the helper take
an argument. Do NOT try to define private arity-0 helpers for nav-item
maps.

## Pitfall: type-inference warning on `is_nil(slug)`

After `case assigns[:workspace_slug] && ...` the compiler narrows the
type to `dynamic(not nil)` and warns
`comparison between distinct types found: workspace_slug == nil`.
Benign but noisy. Test `is_nil(assigns[:workspace_slug])` (direct map
access) rather than a previously-bound local var to dodge the
narrowing.

## Pitfall: test sessions behind role pipelines

When routes move behind an admin/editor pipeline, tests that seed the
slug but not the role flag fail with a **silent redirect to `/`** — no
assertion message, just a `MatchError` on
`{:error, {:live_redirect, %{to: "/"}}}`. Add
`|> Plug.Conn.put_session(:is_owner, true)` to every test setup that
hits a role-gated route.

## Pitfall: large `patch` on one function can duplicate content

Repeated large replace-patches on the same function (a 160-line
`if/else` block) silently duplicated the body (file grew ~150 lines,
orphaned `end`s, `unexpected reserved word: end`). After **2 failed
patches on the same region, rewrite the whole function/file with
`write_file`** instead of attempting a third patch. Verify with
`mix compile` after each file.

## Verification checklist

- [ ] `mix compile --warnings` → zero warnings
- [ ] `mix test` failure set == baseline (via `git stash` + `git stash pop`)
- [ ] First-class routes defined before the generic wildcard
- [ ] No `~p"/#{@workspace_slug}` interpolation can see nil (mount
      fallback + `:if` guard)
- [ ] Deleted per-type LiveViews AND their test files
- [ ] All `~p` refs updated in lib AND tests
      (grep `~p"/old/route` to confirm zero)
- [ ] Test setups behind role pipelines have `put_session(:is_owner, true)`