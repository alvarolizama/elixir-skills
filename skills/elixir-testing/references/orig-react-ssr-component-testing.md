---
name: react-ssr-component-testing
description: "Test pure React components (SVG charts, HTML tables, data widgets) via renderToStaticMarkup from react-dom/server in a node/vitest environment. Zero deps, no jsdom, no browser. Covers assertion strategies for SVG geometry, inline-style colors, element counts, and the vitest globals type workaround."
version: 1.0.0
author: Álvaro Lizama
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [testing, react, svg, ssr, vitest, zero-deps, charts, data-viz]
    related_skills: [test-driven-development, riel-delegate]
---

# React SSR Component Testing

## Overview

When building **pure React components** — SVG charts, styled HTML tables, data
visualization widgets — that use only inline styles and no DOM APIs (no
`useState` that needs interaction, no `useRef` that needs a real DOM, no
`useEffect`), you can test them with `renderToStaticMarkup` from
`react-dom/server` and assert on the resulting HTML string.

This approach needs **zero new dependencies**: no `@testing-library/react`, no
`jsdom`, no `happy-dom`. It works in vitest's `node` environment out of the
box. The trade-off: you can't test interactivity (clicks, state changes) — only
what the component renders given a set of props.

## When to Use

- Testing SVG charts (bar charts, donut charts, line graphs) rendered as pure SVG.
- Testing styled HTML components (tables, cards, callouts) with inline styles.
- Projects where vitest runs in `node` environment (not `jsdom`).
- Components that take props and render static markup — no event handlers under test.
- Zero-dependency widget libraries where adding `@testing-library/react` + `jsdom`
  is overkill for what is essentially "does the SVG have the right elements?"
- **Creating e2e fixture/showcase files** that exercise every widget and variant
  in a component library — the same API-discovery and typechecking techniques
  apply whether the goal is test assertions or visual showcase pages. See
  `references/slide-fixture-creation.md` and `references/ebook-fixture-creation.md`
  for format-specific patterns.

**Don't use for:**
- Components with interactivity (clicks, form submissions) — use `@testing-library/react` + jsdom.
- Components using `useEffect`, `useLayoutEffect`, or refs that need a real DOM.
- Snapshot testing of large page trees — use vitest's `toMatchSnapshot` instead.

## The Core Pattern

```tsx
import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { MyChart } from './my-chart';

describe('MyChart', () => {
  it('renders the correct number of bars', () => {
    const html = renderToStaticMarkup(
      <MyChart data={[{ label: 'A', value: 10 }, { label: 'B', value: 20 }]} />
    );
    const barCount = (html.match(/<rect/g) || []).length;
    expect(barCount).toBe(2);
  });
});
```

Three steps:
1. **Render** the component to an HTML string via `renderToStaticMarkup`.
2. **Extract** the relevant data from the string — element counts via regex,
   attribute values via capture groups, substring presence via `toContain`.
3. **Assert** with standard vitest matchers.

## Assertion Strategies

### 1. Element counting

Count SVG/HTML elements by tag name. Each bar is a `<rect>`, each arc segment
is a `<circle>` with `stroke-dasharray`, each table row is a `<tr>`.

```tsx
const barCount = (html.match(/<rect/g) || []).length;
expect(barCount).toBe(data.length);

// Count only arc segments (exclude background track circle):
const segments = (html.match(/<circle[^>]*stroke-dasharray=/g) || []).length;
```

### 2. Attribute extraction

Use regex capture groups to pull attribute values and assert on them:

```tsx
// Verify all horizontal bars start at the same x
const xMatches = [...html.matchAll(/<rect[^>]*x="([^"]+)"/g)];
const xs = xMatches.map(m => m[1]);
expect(xs.every(x => x === xs[0])).toBe(true);

// Verify stroke-dasharray dash length equals full circumference
const dashMatch = html.match(/stroke-dasharray="([^"]+)"/);
const [dashStr] = dashMatch![1].split(' ');
const dash = Number(dashStr);
expect(dash).toBeCloseTo(2 * Math.PI * 120, 1);
```

### 3. Content presence/absence

```tsx
// Value labels visible by default
for (const d of sample) {
  expect(html).toContain(`>${d.value}<`);
}

// Hidden when showValues=false
expect(html).not.toContain('>10<');
```

### 4. Inline-style color assertions

React inline styles serialize to `property:value` (no quotes, no spaces) in
`renderToStaticMarkup` output:

```tsx
// var(--od-accent) in inline style → "background:var(--od-accent)"
const accentCount = (html.match(/background:var\\(--od-accent\\)/g) || []).length;
expect(accentCount).toBe(columns.length);

// Hex colors in fill attribute
expect(html).toContain('#abcdef');
expect(html).not.toContain('#999999');
```

**Key:** `style={{ background: 'var(--od-accent)' }}` serializes as
`background:var(--od-accent)` (no spaces, no quotes) — not
`background: var(--od-accent)` like CSS. Match accordingly.

### 5. `data-*` attribute assertions (preferred for variant/size testing)

Instead of parsing inline styles to determine which variant a component
rendered, add `data-variant` / `data-size` / `data-od-widget` attributes to
the component's root element. This makes tests trivially readable and
decouples assertions from style implementation:

```tsx
// Component:
<div data-od-widget="callout" data-variant={variant}>...</div>

// Test:
expect(html).toContain('data-variant="warning"');
expect(html).toContain('data-od-widget="callout"');
```

This is strictly better than regexing the accent color out of inline styles
when you only need to verify "which variant was selected." Use style
assertions when you need to verify *what the variant produced* (e.g., the
correct accent color appeared), and `data-*` assertions when you need to
verify *which variant was chosen.*

### 5. Geometric verification

For SVG charts, verify the math is correct:

```tsx
// Single-value donut: dash should equal full circumference
const radius = (size - thickness) / 2;
const circumference = 2 * Math.PI * radius;
expect(dash).toBeCloseTo(circumference, 1);
```

## The vitest globals type workaround

**Problem:** Many repos configure vitest with `environment: 'node'` and don't add
`vitest/globals` to tsconfig `types`. Test files that use `describe`/`it`/`expect`
without importing them get TS2593 errors ("Cannot find name 'describe'").

**Fix:** Always explicitly import from `'vitest'`:

```tsx
// ✅ Correct — no TS errors
import { describe, expect, it } from 'vitest';

// ❌ Fails in repos without vitest/globals in tsconfig types
describe('MyChart', () => { ... });
```

This is strictly better than relying on globals — it's explicit, works in any
tsconfig, and doesn't require modifying project config. Some pre-existing test
files in the same repo may use the globals style (and have TS errors); don't copy
that pattern. Copy the explicit-import pattern instead.

## Verifying no new typecheck errors

After writing component + test files, verify you introduced zero new errors:

```bash
npx tsc --noEmit 2>&1 | grep -E "widgets/(my-component)\."
# Should output nothing — 0 new errors from your files
```

Compare against the pre-existing error count to confirm you didn't add to it:

```bash
npx tsc --noEmit 2>&1 | grep -c "my-new-files"
# vs
npx tsc --noEmit 2>&1 | grep -c "pre-existing-files"
```

## Design-token integration

Pure React widgets for design-system-driven projects should use CSS custom
properties (`var(--od-accent)`, `var(--od-font-body)`) rather than hardcoded
colors/fonts. This keeps widgets consistent with the design system and allows
theme switching. In tests, assert on the token name, not a resolved color:

```tsx
// ✅ Asserts on the token — works regardless of theme
expect(html).toContain('var(--od-accent)');

// ❌ Brittle — breaks if theme changes
expect(html).toContain('#6d4cff');
```

## Common Pitfalls

1. **Assuming inline styles serialize like CSS.** `style={{ background: 'red' }}`
   becomes `background:red` in `renderToStaticMarkup` output — no spaces, no
   quotes. Regex patterns must match this format: `/background:red/g`, not
   `/background: red/g`.

2. **Counting all `<circle>` elements when you only want arc segments.** A donut
   chart has a background track circle (no `stroke-dasharray`) plus segment
   circles (with `stroke-dasharray`). Filter by the distinguishing attribute:
   `html.match(/<circle[^>]*stroke-dasharray=/g)`.

3. **Using globals without importing.** In repos without `vitest/globals` in
   tsconfig types, `describe`/`it`/`expect` cause TS2593. Always import them
   explicitly from `'vitest'`.

4. **Asserting on resolved CSS variable values.** `renderToStaticMarkup` does not
   resolve `var(--od-accent)` to a hex color. The output contains the literal
   `var(--od-accent)` string. Assert on the token name.

5. **Forgetting `role="img"` and `aria-label`.** SVG charts should have
   `role="img"` and an `aria-label` for accessibility. Include them in the
   component and they'll appear in the rendered output.

6. **Not guarding against division by zero.** Chart components that compute
   `value / total` must handle `total === 0`. Use `total || 1` to avoid `NaN`
   in stroke-dasharray / height calculations.

7. **Numeric values retain their full form — do NOT assume leading-zero
   dropping.** React serializes `opacity: 0.5` as `opacity:0.5` (NOT
   `opacity:.5`). Always run the test once and read the ACTUAL serialized
   output from the failure message before writing assertions on numeric values.
   Do not assume shorter forms — React preserves the value as-written in the
   style object. If the component code has `opacity: 0.5`, the output is
   `opacity:0.5`.

8. **CSS Grid properties serialize to kebab-case, but comma-separated values
   KEEP their spaces.** `gridTemplateColumns: 'repeat(3, 1fr)'` serializes as
   `grid-template-columns:repeat(3, 1fr)` (WITH space after comma). The kebab-case
   conversion applies to property names, NOT to value content. `gap` becomes
   `gap:16px`. Always run once and verify — don't assume spaces are stripped.

9. **`rgba()` values keep spaces between components.** `rgba(0, 0, 255, 0.15)`
   serializes as `rgba(0, 0, 255, 0.15)` (NOT `rgba(0,0,255,0.15)`). If the
   component code builds the string with template literals like
   `\`rgba(${rgb}, 0.15)\`` where `rgb` is `"0, 0, 255"`, the spaces are
   preserved in output. Always verify against actual output.

10. **Element-counting regex must distinguish tag from prefix matches.**
    `/<th/g` matches BOTH `<th>` AND `<thead>`, inflating counts by 1 per
    `<thead>`. Use `/<th[ >]/g` (tag followed by space or `>`) to count only
    `<th>` elements. Same for `<tr[ >]`, `<td[ >]`, `<circle[ >]`, etc. This
    is the #1 cause of "expected 4 to be 3" assertion failures in table tests.

9. **`import * as React` is only needed when you reference the `React.` namespace.**
   With `jsx: "react-jsx"` (the automatic runtime), JSX compiles without a
   `React` import. Test files and components that only use JSX (no
   `React.CSSProperties`, `React.ReactNode`, etc.) trigger `noUnusedLocals`
   errors if they include `import * as React`. Keep the import only in files
   that reference the `React.` namespace for types. If you see
   `'React' is declared but its value is never read`, just remove the import.

11. **`import type * as React` fails when you use `React.` as a value (e.g.
    `React.Fragment`).** This is the mirror of pitfall #9. If you only need
    types (`React.CSSProperties`, `React.ReactNode`), `import type * as React`
    is correct. But if you also reference `React.Fragment` as a JSX wrapper
    or any other `React.` value at runtime, TypeScript errors with `'React'
    cannot be used as a value because it was imported using 'import type'`
    (TS1361). Fix: change `import type * as React` to `import * as React`
    (drop the `type` keyword). The `import type` form erases the import at
    emit time, so any runtime usage breaks. When in doubt, use the non-type
    import — it works for both type annotations and runtime values.

12. **SVG presentation attributes serialize as `attr="value"` (quoted with
    `=`), NOT as CSS-style `property:value`.** Inline CSS styles on HTML
    elements serialize as `opacity:0.3` (no quotes, no space after colon).
    But SVG presentation attributes like `fill-opacity`, `stroke-width`,
    `stroke-dasharray`, `stroke-linecap` are emitted as XML attributes:
    `fill-opacity="0.3"`, `stroke-width="3"`, `stroke-dasharray="24 12.8"`.
    Tests that assert on SVG attributes MUST use the quoted `attr="value"`
    format, NOT the CSS `property:value` format:

    ```tsx
    // ✅ Correct — SVG attribute format (quoted, with =)
    expect(markup).toContain('fill-opacity="0.3"');
    expect(markup).toContain('stroke-width="3"');

    // ❌ Wrong — CSS inline-style format (will never match SVG attributes)
    expect(markup).toContain('fill-opacity:0.3');
    expect(markup).toContain('stroke-width:3');
    ```

    **Rule of thumb:** if the property is set via a JSX attribute
    (`<circle fillOpacity={0.3} />`), it serializes as `fill-opacity="0.3"`.
    If it's set via `style={{ opacity: 0.3 }}`, it serializes as
    `opacity:0.3`. The same numeric value takes different forms depending
    on whether it's an SVG attribute or a CSS inline style. This is a very
    common test-writing mistake — the assertion looks plausible but never
    matches.

14. **`<linearGradient` substring-matches `<line` — substring tests on SVG
    with gradient defs produce false negatives.** When you add `<defs><linearGradient>`
    to an SVG chart (e.g., for gradient bar fills, arc fills, gauge gradients)
    and then test for the *absence* of a needle `<line>` element with
    `expect(markup).not.toContain('<line')`, the test **fails** because
    `<linearGradient` contains the substring `<line`. This is especially
    common when testing gauge/arc variants that should have no needle.

    **Fix:** Use a word-boundary regex instead of substring matching:

    ```tsx
    // ❌ Fails — matches <linearGradient in <defs>
    expect(markup).not.toContain('<line');

    // ✅ Correct — word boundary after 'line' excludes 'linearGradient'
    const needleLine = markup.match(/<line\b/g);
    expect(needleLine).toBeNull();
    ```

    This pitfall only appears *after* you add gradient `<defs>` to a chart
    that previously had flat fills. The test passed before the restyle and
    breaks after — making it easy to misdiagnose as a component bug rather
    than a test bug.

15. **SVG gradient `offset="100%"` contains `%` — substring tests for
    percentage labels produce false negatives.** When a chart has gradient
    `<defs>`, the `<stop offset="0%">` and `<stop offset="100%">` elements
    contain `%`. Testing `expect(markup).not.toContain('%')` to verify that
    percentage value labels are hidden (e.g., `showPercentage={false}` on a
    Funnel) will **fail** because the gradient offsets match.

    **Fix:** Assert on text-node percentages specifically — rendered
    `<text>` content is wrapped in `>...<`:

    ```tsx
    // ❌ Fails — matches offset="100%" in gradient defs
    expect(markup).not.toContain('%');

    // ✅ Correct — only matches percentage values inside <text> elements
    expect(markup).not.toContain('>100%<');
    expect(markup).not.toContain('>50%<');
    ```

    This pitfall only appears *after* you add gradient `<defs>` to a chart
    component that previously used flat color fills.

16. **Container-level vs cell-level `border-radius` — broad negation tests
    produce false failures.** When a variant removes `border-radius` from
    *cells* but the wrapping container surface still has
    `border-radius:var(--od-radius)` (e.g., a ComparisonMatrix with an
    elevated surface container), a broad
    `expect(markup).not.toContain('border-radius:var(--od-radius)')` will
    **fail** because the container's border-radius matches the pattern.

    **Fix:** Use a regex that checks specifically for cell-level
    border-radius (width-qualified), not any occurrence:

    ```tsx
    // ❌ Fails — matches the container surface's border-radius
    expect(markup).not.toContain('border-radius:var(--od-radius)');

    // ✅ Correct — only matches cells that have both width and border-radius
    const cellMatches = markup.match(/width:200px[^"]*border-radius:var\(--od-radius\)/g);
    expect(cellMatches).toBeNull();
    ```

    This pitfall appears when you add an elevated surface wrapper
    (with its own border-radius) *around* a grid whose cells used to be
    the outermost element. The cell-level border-radius is correctly
    removed, but the container-level one triggers the false positive.

17. **`textTransform` on SVG `<text>` elements causes TS2322.** SVG `<text>`
    elements in JSX don't accept `textTransform`, `letterSpacing`, or
    `fontWeight` as direct attributes — TypeScript rejects them with
    `Type '...' is not assignable to type 'SVGTextElementAttributes'`.
    This happens when you add micro-labels (uppercase, letter-spacing) to
    SVG chart text elements as part of a design-system restyle.

    **Fix:** Pass these properties via the `style` prop instead:

    ```tsx
    // ❌ TS2322 — not valid SVG presentation attributes
    <text
      textTransform="uppercase"
      letterSpacing="0.08em"
      fontWeight={600}
    >
      {label}
    </text>

    // ✅ Correct — style prop accepts these CSS properties
    <text
      style={{ textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 600 }}
    >
      {label}
    </text>
    ```

    Note: `fontSize`, `fill`, `fontFamily`, `textAnchor`, and
    `dominantBaseline` ARE valid SVG presentation attributes and can be
    passed as JSX props directly. The issue is specifically with
    `textTransform`, `letterSpacing` (as a string), and `fontWeight` —
    these need the `style` prop.

18. **`color-mix()` in inline styles serializes with the exact formatting
    from the source string.** The new design language uses
    `color-mix(in srgb, var(--od-text) X%, transparent)` extensively for
    muted text and hairline borders. This serializes exactly as written:

    ```tsx
    // Component: color: 'color-mix(in srgb, var(--od-text) 60%, transparent)'
    // Serialized: color:color-mix(in srgb, var(--od-text) 60%, transparent)
    ```

    Tests must match the exact spacing — `color-mix(in srgb, var(--od-text) 60%, transparent)`,
    not `color-mix(in srgb,var(--od-text) 60%,transparent)`. Always run once
    and verify against actual output, as with all inline-style assertions.

13. **React `key` props are NOT emitted in `renderToStaticMarkup` output.**
    The `key` prop is a React-internal reconciliation mechanism — it is
    stripped from the rendered HTML entirely. Tests cannot assert on key
    values:

    ```tsx
    // Component: <div key={`segment-${i}`} />

    // ❌ This will ALWAYS return 0 matches — keys are stripped
    const segmentCount = (markup.match(/segment-\d/g) || []).length;
    expect(segmentCount).toBe(10);  // FAILS: got 0

    // ✅ Assert on observable output instead — count dividers,
    // fill colors, or other rendered attributes
    const dividerCount = (markup.match(/border-right:2px solid/g) || []).length;
    expect(dividerCount).toBe(9);  // 10 segments → 9 dividers
    ```

    When testing `.map()` output where elements only differ by index, find
    an observable side effect (rendered attributes, sibling counts, border
    dividers, filled vs unfilled segments) rather than relying on the
    React key.

## Verification Checklist

- [ ] Component renders without errors via `renderToStaticMarkup`
- [ ] Tests explicitly import `{ describe, expect, it }` from `'vitest'`
- [ ] Element counts match data length
- [ ] Element-counting regex uses `[ >]` after tag name (e.g. `/<th[ >]/g`)
- [ ] Numeric/style assertions verified against ACTUAL output (run test, read failure)
- [ ] Color assertions use token names (`var(--od-accent)`) not resolved hex
- [ ] **For fixture files:** typecheck the file explicitly with inline flags —
      `tsc -p tsconfig.json` silently passes if the fixture dir isn't in `include`.
      See `references/slide-fixture-creation.md` for the exact command.
- [ ] `npx tsc --noEmit` shows 0 new errors from your files
- [ ] No `import * as React` in files that only use JSX (not `React.` namespace)
- [ ] No `import type * as React` in files that use `React.` as a value (e.g. `React.Fragment`) — use `import * as React` instead
- [ ] SVG attribute assertions use `attr="value"` format (e.g. `fill-opacity="0.3"`), NOT CSS-style `attr:value`
- [ ] No assertions on React `key` prop values — keys are stripped from `renderToStaticMarkup` output; assert on observable side effects instead
- [ ] Edge cases covered (empty data, single value, zero total)
- [ ] SVG has `role="img"` and `aria-label` for accessibility
- [ ] Variant/size assertions use `data-*` attributes, not style parsing
- [ ] After a rename wave: check that physical asset files (`.png`, `.webp`) were renamed to match code references — subagents rename references in code but forget to `mv` the actual files
- [ ] If SVG charts have gradient `<defs>`: absence-of-element tests use `/<line\b/g` (word boundary), NOT `.toContain('<line')` — `<linearGradient` contains `<line`
- [ ] If SVG charts have gradient `<defs>`: absence-of-`%` tests assert `>N%<` (text-node content), NOT just `%` — `offset="100%"` in gradient stops contains `%`
- [ ] If a surface container wraps a grid: cell-level negation tests use width-qualified regex (e.g., `/width:200px[^"]*border-radius:/`), NOT broad `.not.toContain()` — container-level border-radius will match

## Subagent-created test files: predictable failure patterns

When dispatching subagents to create React component + test files (e.g. widget
libraries), the parent must budget time to fix these recurring issues:

1. **Missing vitest imports.** Subagents write `describe`/`it`/`expect` as
   globals. In repos without `vitest/globals` in tsconfig types, this causes
   TS2593. Fix: add `import { describe, expect, it } from 'vitest';` to every
   test file. Detect with `tsc --noEmit | grep "Cannot find name 'describe'"`.

2. **Wrong CSS serialization assumptions in assertions.** Subagents write
   assertions from theory, not verified output. Common wrong assumptions:
   - `repeat(3,1fr)` (no space) vs actual `repeat(3, 1fr)` (with space)
   - `rgba(0,0,255,0.15)` (no spaces) vs actual `rgba(0, 0, 255, 0.15)` (with spaces)
   - `opacity:.5` (dropped zero) vs actual `opacity:0.5` (retained)
   Fix: run tests, read failure message "Received:" output, update assertions.

3. **Naive element-counting regex.** `/<th/g` matches `<thead>`, inflating
   counts. Fix: `/<th[ >]/g` (see Pitfall #10 above).

4. **Biome lint: `noArrayIndexKey`.** Subagents use `key={i}` in `.map()`.
   Fix: use a stable data-derived key (`key={col}` for unique column headers,
   `key={row.join('|')}` for table rows, `key={card.label}` for stat cards)
   or `key={\`row-${i}\`}` as a last resort.
   **WARNING: `// biome-ignore` comments placed inside `.map()` callbacks
   before the JSX element are treated as JS comments in expression position,
   NOT as biome suppression directives — biome still flags the rule.** This
   approach does not work in JSX `.map((item, i) => ( // biome-ignore... <div /> ))`.
   The only reliable fixes are: (a) use a non-index key, or (b) add the widget
   directory to `biome.json` overrides with `"suspicious": { "noArrayIndexKey": "off" }`.

5. **Biome lint: `useValidAriaRole` on props named `role`.** A component with
   a prop called `role` (e.g. `QuoteLayout role="CEO"`) triggers the ARIA
   validator. Fix: `// biome-ignore lint/a11y/useValidAriaRole: role is a
   component prop, not an ARIA attribute`. Note: this biome-ignore works because
   it's placed on the test file line, not inside a JSX `.map()` callback (see
   pitfall #4 for why map-callback biome-ignore comments don't work).

6. **Biome lint: `noNonNullAssertion`.** Subagents write `match![1]` after a
   regex match. Fix: guard with a ternary: `match ? match[1] : ''`, or use
   optional chaining if available. This is a style rule, not a correctness
   issue — but biome blocks commits on it.

7. **Duplicate shared file creation.** Two subagents with disjoint scopes may
   both create `types.ts`. Check after the wave and merge if both had
   different but needed content.

8. **HTML entity double-encoding in test assertions.** When a component
   renders text containing `&` (e.g. `Q&A`), React's `renderToStaticMarkup`
   encodes it to `Q&amp;A`. If the test asserts `Q&amp;A`, and the component
   itself outputs the entity as a string literal (`Q&amp;A` in source),
   React encodes it AGAIN to `Q&amp;amp;A`. Fix: don't assert on text
   containing HTML entities — either remove the assertion and rely on other
   assertions for coverage, or use a test string without special characters.

9. **Physical asset files not renamed.** When a rename task changes
   `open-slide.png` → `open-delta.png` in code references, subagents forget
   to `mv` the actual file. The build breaks with "Module not found:
   Can't resolve '../../public/assets/open-delta-cover.webp'". Fix: after a
   rename wave, `grep` for renamed asset references and `mv` the physical
   files to match. Check `apps/*/public/` and `packages/*/src/app/` for
   assets referenced by renamed paths.

**Efficient fix flow:** dispatch → wait for all → `tsc --noEmit` → fix all
import/type errors in one batch → `vitest run` → fix all assertion errors in
one batch → `biome check --write` → fix remaining lint errors manually (see
pitfalls #4-#6 above for specific patterns) → commit.

**Biome lint fix priority for React widgets:** (1) prefer stable data-derived
keys to avoid `noArrayIndexKey` entirely; (2) if a prop name conflicts with
ARIA attributes, add `// biome-ignore` on the test file line (NOT inside JSX
map callbacks); (3) replace `!` non-null assertions with guarded ternaries;
(4) as a last resort, add the widget directory to `biome.json` overrides
with the specific rule turned off.

**The `biome.json` overrides approach (recommended for widget libraries):**
When building a widget library with many components, fighting per-file
biome-ignore comments is unsustainable. Instead, add the widget directory to
`biome.json` overrides:

```json
{
  "includes": ["**/slides/**", "apps/web/components/landing/**", "packages/core/src/widgets/**"],
  "linter": {
    "rules": {
      "a11y": { "noSvgWithoutTitle": "off" },
      "suspicious": { "noArrayIndexKey": "off" }
    }
  }
}
```

This is the pragmatic choice for a widget library where:
- SVGs are decorative data viz (no `title` needed — the data labels ARE the title)
- Index keys are stable in static data-display components (no reordering)
- The alternative is dozens of biome-ignore comments that don't work in JSX `.map()` callbacks anyway

## Related Skills

- `test-driven-development` — TDD methodology (when to write tests, not how to
  test React SVG components specifically).
- `riel-delegate` — when tests and impl are owned by different
  agents; the assertion patterns here apply to the test-authoring side.

## References

- `references/open-delta-widget-patterns.md` — concrete assertion recipes
  extracted from building BarChart, DonutChart, DataTable, GradientBackground,
  Callout, StatCard, StatGrid, and Badge in the open-delta monorepo. Includes
  a complete inline-style serialization reference table, data-attribute
  assertion patterns, and opacity/grid serialization quirks.
- `references/structural-widget-patterns.md` — assertion recipes for
  structural/flow widgets: Pyramid, Timeline, ProcessFlow, StepIndicator,
  Divider, CoverLayout, AgendaLayout, NumberedList. Covers hybrid SVG+HTML
  widget testing, full-canvas layout assertions, numbered-circle patterns,
  and the `data-variant`/`data-direction`/`data-orientation` attribute
  conventions used across non-chart widgets.
- `references/plan-driven-waves-pnpm.md` — playbook for executing large
  multi-phase markdown plans in pnpm/TypeScript monorepos with subagent waves.
  Covers pnpm lockfile regeneration traps, `@types/react` version hoisting
  conflicts, turbo cache masking, biome check flow, and the decision to use
  `execute_code` scripts for deterministic renames vs. subagents for judgment
  work.
- `references/adding-variant-props.md` — recipe for retroactively adding a
  `variant` prop to existing widgets with 3+ style options each, keeping
  backward compatibility. Covers the prop-naming convention, SVG gradient
  defs pattern, conditional element rendering, and test assertions for each
  variant type. Includes a catalog of 11 widget variants (Callout,
  DataTable, Funnel, GaugeChart, HeatMap, MetricRing, ProgressBar,
  RadarChart, Pyramid, VersusComparison, ComparisonMatrix).
- `references/ebook-layout-patterns.md` — assertion recipes for ebook layout
  widgets: BookCover, BookBackCover, BookPage, TableOfContents,
  ChapterDivider. Covers portrait canvas dimensions (A4/Letter), accent bar
  patterns shared with slide layouts, format prop assertions, and the
  multi-format canvas integration model.
- `references/visual-language-restyle.md` — the five-layer visual language
  recipe (elevation + hairline, top accent gradient bars, typography
  hierarchy with micro-labels, SVG gradient defs, hairline gridlines)
  applied when restyling the open-delta widget library. Includes
  `color-mix()` serialization reference, backward compatibility rules, and
  test assertion patterns for the restyled markup.
- `references/ebook-fixture-creation.md` — patterns for creating e2e fixture
  content files that showcase all widgets in ebook A4 format (794×1123).
  Covers the slide-to-ebook scaling technique (overflow:hidden wrappers for
  1920×1080 layout widgets), type scale reduction table, BookPage content
  layout pattern, complete widget import list, and the `--ignoreDeprecations
  6.0` tsc quirk for this repo's tsconfig.
- `references/slide-fixture-creation.md` — patterns for creating e2e fixture
  content files that showcase every widget and variant on the native
  1920×1080 slide canvas. Covers the `transform: scale()` layout-preview
  technique (better than overflow:hidden clipping because it shows the full
  widget at reduced size), gallery page structure, category-based page
  organization, the tsconfig-include pitfall (fixture dirs aren't in the
  tsconfig `include` array, so `tsc -p tsconfig.json` silently passes), and a
  coverage audit script to verify every widget/variant is present.
