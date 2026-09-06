# SSR component testing for pure React widgets (renderToStaticMarkup)

Symptom: a pure-React widget (no server, no data fetching — props in, markup
out) regresses its rendered HTML without any test noticing, because the suite
only exercises the interactive path inside a browser. This pattern pins the
markup with `renderToStaticMarkup` for speed and determinism.

## Scope: widgets, not applications

This works for **pure presentational widgets**: components that render markup
from props and have no client-side state/hydration requirements. Do NOT use
`renderToStaticMarkup` to test interactivity (event handlers, effects,
lifecycle) — that needs a DOM/jsdom or browser runner. Pure widgets are common
in design systems and content packages; their contract is "given these props,
this HTML must come out."

## Fixture creation contract

A widget test couples a fixture to the component's prop types. Keep fixtures
as plain JSON/JS data modules, one per widget, named after the widget:

```ts
// fixtures/cover-card.fixtures.ts
export const coverCardFixtures = {
  minimal: { title: "Minimal", body: "Just text." },
  full: {
    title: "A Longer Title",
    subtitle: "String or null",
    flag: "featured",
    cover: { kind: "image", src: "/asset/cover.jpg" },
  },
  edge: { title: "", body: null },
} as const;
```

Rules:
- Every fixture is **valid against the component's props type** — a fixture
  that violates the type tests nothing (TS/type-check in the fixture file).
- Include at least: minimal, full, and edge (empty string, null).
- Fixtures are shared between the SSR test and any snapshot/story tooling, so
  the render under test always matches the design-time fixture.
- Never fabricate data in the test body; import from the fixture module.

## Variant props: one component, one matrix

Instead of one test per prop, drive a **variant matrix** — a table of prop
shapes and expected structural outcomes:

```ts
describe.each([
  ["minimal", coverCardFixtures.minimal, 'aria-label="card"', null],
  ["full", coverCardFixtures.full, 'data-flag="featured"', null],
  ["edge", coverCardFixtures.edge, 'aria-label="card"', null],
])("%s", (_name, props, expectedAttr, _note) => {
  test("renders the expected structure", () => {
    const html = renderToStaticMarkup(
      createElement(MyOrgCard, props),
    );
    expect(html).toContain(expectedAttr);
  });
});
```

A variant that changes the rendered TREE (conditional block, different tag,
new data-attribute) earns a row; a variant that only changes text content
earns an assertion on the text, not a new tree expectation. Assert the
presence of variant-marker attributes (`data-flag`, `data-kind`) and absence
of the opposite variant's markers:

```ts
expect(html).toContain('data-kind="grid"');
expect(html).not.toContain('data-kind="stack"');
```

## Structural widget patterns

Compose assertions from the OUTSIDE in — pin structure first, then text:

1. **Root element**: single root `<div ...>` (or component root tag).
2. **Data attributes**: variant markers and id hooks render exactly once.
3. **Required roles/semantics**: `aria-*`, headings, `<img alt>` present.
4. **Text content**: title/body render raw (escape concerns are React's; test
   the values you control).
5. **Composition**: nested widgets render their own structure — assert the
   inner widget's marker appears inside the outer widget's root:
   `expect(html).toContain('<article data-widget="meta">')`.

Rules:
- Assert on stable markers, not on full snapshot strings — snapshots break on
  any formatting change; markers only move when behavior changes.
- One widget, one test file, one fixture module. Nested widgets are tested
  both standalone and as a child of their parent (composition test).

## Render parity: static vs. interactive

Where a widget is ALSO exercised in a browser test, keep the SSR markup test
as the source of truth for structure and add ONE parity test in the browser
runner asserting the interactive render contains the same markers. This
catches the classic drift: interactive path gains a wrapper the SSR test
doesn't know about.

## Plan-driven pnpm waves

When many widgets change together, run their tests in **waves** ordered by
dependency: leaf widgets first (their fixtures can't depend on parents),
then composite widgets, then pages/stories. With pnpm workspaces, wave =
`pnpm --filter @my-org/widget-a --filter @my-org/widget-b test` from the
root; each wave's exit code gates the next. This is plan-driven: the wave
order is derived from the import graph, not from file modification time.

```bash
# wave 1 — leaves
pnpm --filter @my-org/widget-a --filter @my-org/widget-b test
# wave 2 — composites
pnpm --filter @my-org/composite-card test
# wave 3 — integration / stories
pnpm --filter @my-org/storybook test
```

Why: a failing leaf poisons every composite's failure output with the same
root cause; fixing leaves first keeps each wave's failure list small and
attributable.

## Verification

```bash
pnpm vitest run src/widgets            # unit markup tests (fast, no DOM)
pnpm --filter @my-org/<widget> test    # wave 1 leaf gate
pnpm typecheck                         # fixtures satisfy component props
```

Expected output shape: each widget file reports its variant rows as passing;
`typecheck` exits 0 with no errors. If a markup assertion fails, the diff
shows the rendered HTML around the marker — read the marker, not the
whitespace.

Anti-patterns: snapshotting full HTML (churn without signal); testing
interactivity with `renderToStaticMarkup` (event handlers are silently
dropped — the test passes while the app is broken); fabricating fixture data
inline per test (duplicates drift); asserting on class lists (formatting
churn) instead of data-attributes.