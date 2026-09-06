# SSR fixtures, variant props, pnpm waves

Symptom: a component needs behavior that varies by props, but the test suite
is a pile of near-identical files that drift the moment the design changes.
Replace them with one fixture module, a variant matrix, and dependency-ordered
test waves.

## Fixture file contract

One fixture module per component, co-located with the component, named after
it, exporting an object shaped exactly like the component's props:

```ts
// fixtures/cover-card.ts
import type { CoverCardProps } from "../cover-card";

export const coverCardFixtures = {
  minimal: { title: "Minimal", body: "Just text." },
  full: {
    title: "A Longer Title",
    subtitle: "String or null",
    flag: "featured",
    cover: { kind: "image", src: "/asset/cover.jpg" },
  },
  edge: { title: "", body: null },
} satisfies Record<string, CoverCardProps>;
```

Rules:

- `satisfies` makes the type-check the fixture's guard — a fixture that
  violates the props type fails `tsc`, which is exactly where you want it.
- Cover minimal / full / edge (empty string, null) at minimum.
- Never fabricate data inside a test body; import it. Inline fabrication
  duplicates drift.
- The same fixtures feed the SSR test and any showcase/story files, so
  design-time and test-time data never diverge.

## Variant prop matrix

When a component has a `variant` prop (or several boolean-ish props), test
every variant row as an expected structural outcome:

```ts
const cases: Array<[string, CoverCardProps, string, string | null]> = [
  ["minimal", coverCardFixtures.minimal, 'aria-label="card"', "data-kind=stack"],
  ["featured", coverCardFixtures.full, 'data-flag="featured"', "data-kind=grid"],
  ["edge", coverCardFixtures.edge, 'aria-label="card"', "data-kind=stack"],
];

describe.each(cases)("%s", (name, props, present, absent) => {
  it("renders the expected structure", () => {
    const html = renderToStaticMarkup(createElement(MyOrgCard, props));
    expect(html).toContain(present);
    if (absent) expect(html).not.toContain(absent);
  });
});
```

Rules:

- A variant that changes the TREE (conditional block, different tag, new
  `data-*` attr) earns a row with present + absent markers.
- A variant that only changes text earns a text assertion, not a fresh tree
  expectation.
- Assert variant markers (`data-kind`, `data-flag`) rather than visual
  classes — classes churn, data-attributes only move when behavior changes.

## Structural widget assertions

Assert from the outside in:

1. Root element — single root tag with the widget's id/data attribute.
2. Data attributes — variant markers, ids, `aria-*` render exactly once.
3. Semantics — headings, `img alt`, roles present.
4. Text — the values you control render verbatim.
5. Composition — a nested widget's marker appears INSIDE the parent's root:

```ts
expect(html).toContain('<article data-widget="meta">');
```

Compositional components get both tests: standalone (its own markup) and as a
child (its marker inside the parent).

## pnpm wave execution

Derive the wave order from the import graph — leaves first, composites second,
integrations/stories last:

```bash
# wave 1 — leaf widgets
pnpm --filter @my-org/button --filter @my-org/icon test
# wave 2 — composites that import leaves
pnpm --filter @my-org/card test
# wave 3 — showcases / integration
pnpm --filter @my-org/storybook test
```

Why: when a leaf breaks, every composite's failure output repeats the same
root cause. Fixing leaves first keeps each wave's failure list short and
attributable; each wave's exit code gates the next. Do not order by file
modification time — that is not a dependency order.

## Verification

```bash
pnpm typecheck                 # fixtures satisfy props; exit 0
pnpm vitest run src/components # variant matrix green
pnpm --filter @my-org/card test --run  # wave 2 gates only after wave 1 passed
```

Anti-patterns: full-HTML snapshots (formatting churn without signal);
`renderToStaticMarkup` for interactive behavior (event handlers are silently
dropped — test passes while the app is broken); class-list assertions;
fixture modules that bypass the props type.