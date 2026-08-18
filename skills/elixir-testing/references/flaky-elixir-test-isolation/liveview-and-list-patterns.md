# LiveView & Global-List Test Patterns (2026-07-31, MyApp)

Three flaky-test families that go beyond plain "global aggregate count" — with the
exact fix that made each deterministic. All test-only changes, `async: true` kept.

## 1. LiveView `html =~` false positive: assertion string collides with a `<select>` option

**Symptom:** `refute html =~ log.model_requested` fails even though the row is gone.
The model name (`"model-7747"`) appears in the filter form's dropdown as
`<option value="model-7747">Model 7747</option>` — the raw HTML always contains the
string, so the refute can never pass.

**Fix:** anchor on a string that appears ONLY in the data row, never in form chrome.
Good anchors: the owner's email, a unique per-test api_key_prefix, an id-scoped
element via `has_element?/3`. Bad anchors: model names, team names, statuses —
anything the filter `<select>`/`<option>` also renders.

```elixir
# BAD — model_requested is also the <option value> of the model filter
refute html =~ log.model_requested

# GOOD — owner email only shows in the log row
%{owner: owner} = member_with_log(...)
anchor = owner.email
assert html =~ anchor          # row present
# ... apply filter ...
refute html =~ anchor          # row gone, option can't collide
```

Rule: before asserting on `html =~ <value>`, grep the template for everywhere that
value renders (rows AND form controls). If it's in a control, pick another anchor.

## 2. LiveView org-wide empty-state tests (admin list pages)

**Symptom:** `has_element?(view, "#teams-empty")` fails whenever another async test
created a team/provider — the page lists ALL org-wide rows, so "empty" is
seed-dependent.

Two deterministic strategies, in preference order:

### (a) Drive the page's own search/filter to a no-match term — PRESERVES the empty state

If the LiveView has a search input with `phx-change`, type a guaranteed-unique
no-match term; the list filters to zero and the empty state genuinely renders:

```elixir
test "teams page shows empty state when search matches nothing", %{conn: conn} do
  {:ok, view, _} = live(conn, ~p"/dashboard/teams")
  term = "zzz-no-match-#{System.unique_integer([:positive])}"

  view
  |> form("#teams-search-form", team_search: term)   # adjust form/field names
  |> render_change()

  assert has_element?(view, "#teams-empty")
end
```

This is the best fix: the empty-state code path is still exercised, just scoped to
a controlled query instead of global emptiness.

### (b) No filter exists → invert to a positive assertion on the fixture's own item

When the page has no search, "empty state" cannot be deterministic. Create a
uniquely-named fixture and assert the page renders ITS card (and that the empty
element is absent). Deterministic regardless of concurrent inserts:

```elixir
test "admin sees their created provider in the list", %{conn: conn} do
  {:ok, provider} = create_provider(%{name: "Prov #{unique()}"})
  {:ok, view, _} = live(conn, ~p"/dashboard/providers")

  assert has_element?(view, "#providers-#{provider.id}")
  refute has_element?(view, "#providers-empty")
end
```

Trade-off: you lose direct empty-state coverage. Accept it — an empty-state test
that flakes is worse than none. If the empty state matters, add a filter to the
page (production change) and use strategy (a).

## 3. Global list / delete / ordering assertions

**Symptom:** `assert Providers.list_providers() == [p1, p2]`, `assert length(list) == 2`,
`assert Logs.list_logs() == [l1, l2]` (ordering) — all break when concurrent tests
insert.

Fixes:

- **list**: assert membership, not equality —
  `assert Enum.any?(list, &(&1.id == p1.id))` and `length(list) >= 2`.
- **delete**: assert the specific id is gone, not that the list is empty —
  `refute Enum.any?(Providers.list_providers(), &(&1.id == provider.id))`.
  Same for cascade children (assert each child id absent).
- **ordering**: scope the query to the fixture so concurrent rows never enter the
  result set, then assert exact order — `Logs.list_logs(%{team_member_id: member.id})`
  returns only the fixture's logs, so `assert [first, second] = ...; first.inserted_at > second.inserted_at` is stable.

## Verification

Same as the parent skill: run the touched files 3× with `--seed 1 / 12345 / 99999`,
plus one CONTENTION run pairing the LiveView tests with a heavy async context file
(`mix test live_a_test.exs live_b_test.exs providers_test.exs --seed 7`) to force
concurrent inserts while the assertions run.
