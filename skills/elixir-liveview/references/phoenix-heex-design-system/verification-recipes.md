# HEEx Design-System Refactor: Verification Recipes

## Standard verification sequence

```bash
# 1. Compile — must be zero warnings
mix compile --warnings-as-errors

# 2. Run web tests (adjust path to project)
mix test test/dran_web/

# 3. If a specific LiveView test exists:
mix test test/dran_web/live/dashboard_live_test.exs
```

## When no dedicated test exists

If there's no `dashboard_live_test.exs`, run the whole `test/dran_web/`
directory. Tests for other LiveViews (graph, search, etc.) exercise the
shared layout and will catch regressions in layout-level markup.

## Updating tests that assert on old markup

When you change class names or markup structure, tests that assert on text
content or old class names will fail. Update them using `has_element?/2`
with robust selectors.

### Before (fragile — asserts on text)

```elixir
assert html =~ "Pages by Type"
assert html =~ "card-title"
```

### After (robust — asserts on structure)

```elixir
# If the element has an ID, use it
assert has_element?(view, "#dashboard-header")

# If you changed classes, assert on the new class
assert has_element?(view, "h2.text-heading")

# For links, assert on the navigate destination
assert has_element?(view, "a[href='/todos']")
```

## Common assertion patterns after design-system refactor

```elixir
# Typography classes
assert has_element?(view, "h1.text-title")
assert has_element?(view, "h2.text-heading")

# Surface classes
assert has_element?(view, ".surface-2")

# Metric card structure
assert has_element?(view, ".surface-2.lift")

# Semantic badge colors
assert has_element?(view, "span.bg-info\\/15")  # escaped / in selector
# Or simpler: check the badge text is present
assert has_element?(view, "span", "This Week")

# "View all" links
assert has_element?(view, "a[href='/graph'].text-primary")
```

## Pre-existing warnings to ignore

When running `mix test test/dran_web/`, you may see warnings about:

- **Forms with `phx-change` but missing `id`** — these come from the shared
  layout (context selector, search bar, session form), not from your
  LiveView. They are pre-existing and not caused by design-system refactoring.

- **Unused variable `html`** in other test files — pre-existing, not your
  concern unless the file you're working on has it.

These do not indicate a problem with your changes.

## Distinguishing real regressions from flaky async test failures

When you change **only Tailwind classes** in a HEEx template (no Elixir logic,
no assigns, no events), a full `mix test` run may still show 1–3 failures.
These are almost always **flaky async backend tests** (DB connection pool
exhaustion, `Req.TransportError{:econnrefused}` to rerank/inference services,
`DBConnection.OwnershipError` in spawned Tasks) — not regressions from your
CSS change. The signal is definitive:

- **Different tests fail on each run** — run `mix test` twice; if the failing
  test names change between runs, the failures are non-deterministic and
  unrelated to your change. A real regression fails the same test every time.
- **Failing tests are in backend modules** (`my_app.SummariesTest`,
  `my_app.Agent.Ingest.UtilsTest`, `DranWeb.API.SearchControllerTest`) that
  depend on external services, not in `test/dran_web/live/*_test.exs`.
- **Isolating the failing test files makes them pass** —
  `mix test test/my_app/summaries_test.exs test/dran_web/api/search_controller_test.exs`
  goes green when run alone. This proves the failure is test-interference,
  not a bug in the code under test.

### Verification protocol for CSS-only changes

```bash
# 1. Compile — zero warnings is the hard gate
mix compile --warnings-as-errors

# 2. Run ONLY the LiveView tests for the web layer — these are the tests
#    that could actually be affected by a HEEx class change.
mix test test/dran_web/live/ test/dran_web/components/

# 3. If the user asked for the full suite, run it — but interpret failures
#    through the lens above. Re-run to confirm flakiness if needed.
PORT=4099 mix test 2>&1 | grep -E "^\s+\d+\) test"
```

**Do NOT chase a flaky backend test failure as if it were a regression.**
Report it honestly: "N flaky tests in backend modules that depend on external
services — unrelated to this CSS change; confirmed by isolation." Spending 20
minutes debugging `my_app.SummariesTest` when you only edited Tailwind classes
is a trap.

## daisyUI semantic color quick-reference

| Semantic token | Light theme | Dark theme | Badge class |
|---|---|---|---|
| `base` | near-white bg / dark text | dark bg / light text | `bg-base-300 text-base-content/70` |
| `primary` | teal | teal | `bg-primary/15 text-primary` |
| `secondary` | grey | grey | `bg-secondary/15 text-secondary` |
| `accent` | amber | amber | `bg-accent/15 text-accent` |
| `info` | blue | blue | `bg-info/15 text-info` |
| `success` | green | green | `bg-success/15 text-success` |
| `warning` | amber | amber | `bg-warning/15 text-warning` |
| `error` | red | red | `bg-error/15 text-error` |

The `/15` opacity creates a tinted background. Use `/10` for icon backgrounds
(inside metric card icon squares). Use `text-{semantic}` (no opacity) for
foreground text on badges.

## Custom design-system class quick-reference

| Class | CSS definition (typical) | Purpose |
|---|---|---|
| `.text-display` | 2.25rem / 800 / -0.02em | Hero title |
| `.text-title` | 1.5rem / 700 / -0.01em | Page h1 |
| `.text-heading` | 1.125rem / 600 | Section h2 |
| `.text-body` | 0.875rem / 400 | Body text |
| `.text-caption` | 0.75rem / 500 / 55% base-content | Metadata, labels |
| `.surface-1` | base-200 bg + thin border | Subtle bg |
| `.surface-2` | base-100 bg + thin border + shadow-2 | Card surface |
| `.surface-3` | base-100 bg + thin border + shadow-3 | Elevated card |
| `.lift` | transition + hover: translateY + shadow-3 | Hover micro-interaction |
| `.skeleton` | gradient + shimmer animation | Loading placeholder |
| `.focus-ring` | focus-visible: 2px primary outline | Accessibility focus |
