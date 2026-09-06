# LiveViewTest pitfalls: form/3 selects, html =~, flash, empty states

Symptom: LiveView tests that pass solo and under load but still bite — or fail
in ways that look like the view is broken when the test is. Each family below
has a concrete mechanism and a deterministic fix. All changes are test-only;
`async: true` is kept.

## `form/3` validates select values against CURRENTLY rendered options

**Symptom:** submitting a value the select doesn't offer raises:

```
** (ArgumentError) value for select "..." must be one of [...]
```

**Mechanism:** `LiveViewTest.form/3` inspects the CURRENTLY rendered HTML.
A select whose options are populated dynamically (after a `phx-change`
re-render) — or from fixtures created after the view mounted — can't accept
the value you submit, even though the underlying domain supports it.

**Fix — order of operations in the test:**

1. Create the fixtures that feed the select's options BEFORE `live/2` mounts
   the view — a subject created after mount is invisible to the select.
2. If options depend on prior interaction, `render_change/2` the controlling
   select first so the target options exist, then submit the dependent form.

```elixir
# Option-feeders first:
{:ok, parent} = create_parent_fixture()
{:ok, view, _html} = live(conn, ~p"/parents/#{parent}/children/new")

# dynamic options: drive the type-select, THEN fill the dependent form
view |> form("#child-form", %{type: "advanced"}) |> render_change()
view |> form("#child-form", %{type: "advanced", user_id: user.id}) |> render_submit()
```

## UUID-typed refute targets must be castable

**Symptom:** `refute MyApp.query_using_binary_id("other-team")` dies with
`Ecto.Query.CastError`, even though zero rows match.

**Mechanism:** the `where` clause casts the value BEFORE it finds zero rows. A
non-UUID string cannot be dumped to a `:binary_id` parameter type.

**Fix:** use a real, castable id for the negative case:

```elixir
refute MyApp.list_team_materials(Ecto.UUID.generate()) == [fixture_material]
```

## `html =~ value` collides with form chrome

**Symptom:** `refute html =~ log.status` never passes even though the row
is gone — the value also renders as `<option value="...">` in a
filter select, so the raw HTML always contains the string.

**Mechanism:** `html =~` is a raw substring check over the whole serialized
page, including every form control.

**Fix:** anchor on a string that appears ONLY in the data row, never in form
chrome. Good anchors: owner email, unique per-test `api_key_prefix`,
id-scoped element via `has_element?`. Bad anchors: model names, team names,
statuses — anything the filter `<select>`/`<option>` also renders.

```elixir
# BAD — the deleted value is also the <option value> of a filter select
refute html =~ log.status

# GOOD — owner email only shows in the log row
anchor = owner.email
assert html =~ anchor
# ... apply filter ...
refute html =~ anchor
```

Rule: before asserting on `html =~ <value>`, grep the template for everywhere
that value renders (rows AND form controls). If it's in a control, pick
another anchor.

## `has_element?` not `html =~ selector`

**Symptom:** `assert html =~ "input[name=\"q\"]"` always fails.

**Mechanism:** a CSS selector string never appears literally in serialized
HTML — it's a query language, not markup.

**Fix:** use the LiveViewTest element API:

```elixir
assert has_element?(view, ~s(input[name="q"]))
assert has_element?(view, "#providers-#{provider.id}")
refute has_element?(view, "#providers-empty")
```

## Flash text is case- and plural-sensitive

**Symptom:** `assert html =~ "Profile updated"` fails while the page displays
`"1 profiles updated."`.

**Mechanism:** flash messages carry exact runtime strings; case and plural
are baked in.

**Fix:** copy the exact runtime string produced by the flash, e.g. assert on
`"#{count} profiles updated."` with the same count the test created.

## Org-wide empty states can't be deterministic while async tests insert

**Symptom:** `has_element?(view, "#teams-empty")` fails whenever another async
test created a team — the page lists ALL org-wide rows, so "empty" is
seed-dependent.

Two deterministic strategies, in preference order:

**(a) Drive the page's own search/filter to a no-match term — preserves the
empty state.** If the LiveView has a search input with `phx-change`, type a
guaranteed-unique no-match term; the list filters to zero and the empty state
genuinely renders:

```elixir
{:ok, view, _} = live(conn, ~p"/dashboard/teams")
term = "zzz-no-match-#{System.unique_integer([:positive])}"

view
|> form("#teams-search-form", team_search: term)
|> render_change()

assert has_element?(view, "#teams-empty")
```

**(b) No filter exists → invert to a positive assertion on the fixture's own
item.** Create a uniquely-named fixture and assert the page renders ITS card
(and that the empty element is absent):

```elixir
{:ok, provider} = create_provider(%{name: "Prov #{System.unique_integer([:positive])}"})
{:ok, view, _} = live(conn, ~p"/dashboard/providers")

assert has_element?(view, "#providers-#{provider.id}")
refute has_element?(view, "#providers-empty")
```

Trade-off: you lose direct empty-state coverage. Accept it — an empty-state
test that flakes is worse than none; if the empty state matters, add a filter
to the page (a production change) and use strategy (a).

## Global list / delete / ordering assertions

**Symptom:** `assert MyApp.Catalog.list() == [p1, p2]`,
`assert length(list) == 2`, `assert Logs.list() == [l1, l2]` — all break when
concurrent tests insert.

**Fixes:**

- **list:** assert membership, not equality —
  `assert Enum.any?(list, &(&1.id == p1.id))` and `length(list) >= 2`.
- **delete:** assert the specific id is gone, not that the list is empty —
  `refute Enum.any?(MyApp.Catalog.list(), &(&1.id == provider.id))`. Same for
  cascade children (assert each child id absent).
- **ordering:** scope the query to the fixture so concurrent rows never enter
  the result set, then assert exact order —
  `MyApp.Audit.list_logs(%{owner_id: owner.id})` returns only the
  fixture's logs, so `assert [first, second] = ...` with
  `first.inserted_at >= second.inserted_at` is stable.

## Verification

Same as the parent skill: run the touched files 3× with
`--seed 1 / 12345 / 99999`, plus one CONTENTION run pairing the LiveView tests
with a heavy async context file to force concurrent inserts while the
assertions run:

```bash
mix test test/a_live_test.exs test/b_live_test.exs test/heavy_async_test.exs --seed 7
```