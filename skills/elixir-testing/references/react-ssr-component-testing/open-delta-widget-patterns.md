# Assertion Patterns from open-delta Widget Session

Concrete patterns extracted from building BarChart, DonutChart, and DataTable
widgets in the open-delta monorepo (`packages/core/src/widgets/`). Each
component is pure React + SVG/inline styles, tested via `renderToStaticMarkup`.

## Project context

- **Monorepo:** pnpm workspace, `packages/core` is the main package
- **Test runner:** vitest, `environment: 'node'` (not jsdom)
- **React:** available at `packages/core/node_modules/react`, `react-dom/server`
  resolves at `packages/core/node_modules/react-dom/server`
- **tsconfig:** `jsx: react-jsx`, `strict: true`, path alias `@/*` → `./src/app/*`
- **Design tokens:** `--od-bg`, `--od-text`, `--od-accent`, `--od-radius`,
  `--od-font-display`, `--od-font-body`, `--od-size-hero`, `--od-size-body`
- **Canvas:** 1920×1080 (presentation slides)

## BarChart assertions

### Count bars (vertical orientation)

Each bar is a `<rect>`. The baseline axis is a `<line>`. Counting `<rect>`
gives the bar count directly:

```tsx
const html = renderToStaticMarkup(<BarChart data={sample} />);
const barCount = (html.match(/<rect/g) || []).length;
expect(barCount).toBe(sample.length);
```

### Verify horizontal orientation

In horizontal mode, all bars start at the same x coordinate (label width +
padding). Extract x attributes and assert they're all equal:

```tsx
const xMatches = [...html.matchAll(/<rect[^>]*x="([^"]+)"/g)];
const xs = xMatches.map(m => m[1]);
expect(xs.every(x => x === xs[0])).toBe(true);
```

### Series.color precedence

```tsx
// Series.color takes priority
const html = renderToStaticMarkup(
  <BarChart data={[{ label: 'x', value: 5, color: '#abcdef' }]} color="#999999" />
);
expect(html).toContain('#abcdef');
expect(html).not.toContain('#999999');
```

## DonutChart assertions

### Count arc segments (not background track)

The donut has a background track circle (no `stroke-dasharray`) plus N segment
circles (each with `stroke-dasharray`). Filter by the distinguishing attribute:

```tsx
const segmentCircles = (html.match(/<circle[^>]*stroke-dasharray=/g) || []).length;
expect(segmentCircles).toBe(sample.length);
```

### Single-value full circle

When data has one entry, the single segment should occupy 100% of the ring.
The dash length should equal the full circumference:

```tsx
const radius = (size - thickness) / 2; // e.g. (280 - 40) / 2 = 120
const circumference = 2 * Math.PI * radius; // ≈ 753.98

const dashMatch = html.match(/stroke-dasharray="([^"]+)"/);
const [dashStr] = dashMatch![1].split(' ');
const dash = Number(dashStr);
expect(dash).toBeCloseTo(circumference, 1);
```

### Center label presence

```tsx
const html = renderToStaticMarkup(
  <DonutChart data={sample} centerLabel="Users" centerValue="100" />
);
expect(html).toContain('>Users<');
expect(html).toContain('>100<');
```

## DataTable assertions

### Row and column counts

**Use `[ >]` after tag name to avoid matching prefixes like `<thead>`:**

```tsx
const bodyRows = (html.match(/<tr[ >]/g) || []).length;
expect(bodyRows).toBe(rows.length + 1); // +1 for header row

const headerCells = (html.match(/<th[ >]/g) || []).length;
expect(headerCells).toBe(columns.length);

const bodyCells = (html.match(/<td[ >]/g) || []).length;
expect(bodyCells).toBe(rows.length * columns.length);
```

Without `[ >]`, `/<th/g` also matches `<thead>`, inflating counts by 1.

### Zebra striping

React inline styles serialize as `background:rgba(0,0,0,0.03)` (no spaces).
Count occurrences — each zebra row has one per cell:

```tsx
const rgbaMatches = (html.match(/rgba\(0,0,0,0.03\)/g) || []).length;
// Row index 1 (0-based) with 3 columns → 3 cells with zebra bg
expect(rgbaMatches).toBe(3);
```

### Highlighted row

Accent background in inline style serializes as `background:var(--od-accent)`:

```tsx
const accentCount = (html.match(/background:var\(--od-accent\)/g) || []).length;
expect(accentCount).toBeGreaterThanOrEqual(columns.length);
```

## Inline-style serialization reference

| React style object | Serialized output |
|---|---|
| `{ background: 'red' }` | `background:red` |
| `{ background: 'var(--od-accent)' }` | `background:var(--od-accent)` |
| `{ background: 'rgba(0,0,0,0.03)' }` | `background:rgba(0,0,0,0.03)` |
| `{ fill: '#6d4cff' }` | `fill="#6d4cff"` (SVG attribute, not style) |
| `{ fontSize: 14 }` | `font-size:14px` |

Key rules:
- CSS properties use kebab-case in output (`font-size`, not `fontSize`)
- No spaces after colons in inline styles
- SVG `fill`/`stroke` are attributes, not styles — they appear as `fill="#..."`
- Numbers get units appended (`14` → `14px` for font-size)

## Vitest config (open-delta)

```ts
// vitest.config.ts
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['packages/**/*.test.ts', 'packages/**/*.test.tsx'],
    environment: 'node',
  },
});
```

Test files live next to their source: `bar-chart.tsx` → `bar-chart.test.tsx`.

## GradientBackground assertions

### Linear-gradient background string

The gradient is rendered as a CSS `background` inline style. The entire
`linear-gradient(...)` string appears in the output:

```tsx
const html = renderToStaticMarkup(<GradientBackground />);
expect(html).toContain('linear-gradient(');
expect(html).toContain('135deg'); // default direction
expect(html).toContain('var(--od-accent)'); // default from
expect(html).toContain('var(--od-bg)'); // default to
```

### Absolute positioning covering parent

```tsx
expect(html).toContain('position:absolute');
expect(html).toContain('inset:0');
```

### Opacity serialization — leading zero RETAINED

React serializes `opacity: 0.5` as `opacity:0.5`, NOT `opacity:.5`:

```tsx
const html = renderToStaticMarkup(
  <GradientBackground from="#ff0000" to="#0000ff" opacity={0.5} />
);
expect(html).toContain('opacity:0.5'); // NOT 'opacity:.5'
```

### Children rendered in a content layer above

When children are provided, they render inside a `<div>` with
`position:relative;z-index:1`:

```tsx
const html = renderToStaticMarkup(
  <GradientBackground>
    <span>hello</span>
  </GradientBackground>
);
expect(html).toContain('hello');
expect(html).toContain('z-index:1');
```

## Callout assertions

### Variant via data-attribute (preferred)

Callout renders `data-variant="info|warning|success|danger"` on the root
element. This is cleaner than parsing the accent color from inline styles:

```tsx
const html = renderToStaticMarkup(<Callout variant="warning">Be careful</Callout>);
expect(html).toContain('data-variant="warning"');
```

### Accent color per variant

When you need to verify the actual color produced:

```tsx
expect(html).toContain('#f59e0b'); // warning
expect(html).toContain('#22c55e'); // success
expect(html).toContain('#ef4444'); // danger
expect(html).toContain('var(--od-accent)'); // info (default)
```

### Title and body content

```tsx
const html = renderToStaticMarkup(
  <Callout title="Important">Body text</Callout>
);
expect(html).toContain('Important');
expect(html).toContain('Body text');
```

### Optional icon

```tsx
const html = renderToStaticMarkup(
  <Callout icon={<span>⚠</span>}>With icon</Callout>
);
expect(html).toContain('⚠');
```

## StatCard assertions

### Value and label

```tsx
const html = renderToStaticMarkup(
  <StatCard value="42%" label="Conversion" />
);
expect(html).toContain('42%');
expect(html).toContain('Conversion');
```

### Trend indicator (up/down)

```tsx
// Up trend: ▲ arrow, green color, trend value
const up = renderToStaticMarkup(
  <StatCard value="1,204" label="Users" trend="up" trendValue="+12%" />
);
expect(up).toContain('▲');
expect(up).toContain('+12%');
expect(up).toContain('#22c55e');

// Down trend: ▼ arrow, red color
const down = renderToStaticMarkup(
  <StatCard value="3.2%" label="Churn" trend="down" />
);
expect(down).toContain('▼');
expect(down).toContain('#ef4444');
```

### Trend row absent when no trend prop

```tsx
const html = renderToStaticMarkup(<StatCard value="50" label="Items" />);
expect(html).not.toContain('▲');
expect(html).not.toContain('▼');
```

## StatGrid assertions

### Grid template columns

`gridTemplateColumns` serializes as `grid-template-columns:repeat(N, 1fr)`
(space after comma is PRESERVED from the source value):

```tsx
const html = renderToStaticMarkup(<StatGrid cards={cards} columns={2} />);
expect(html).toContain('grid-template-columns:repeat(2, 1fr)');
```

### Default columns and gap

```tsx
const html = renderToStaticMarkup(<StatGrid cards={cards} />);
expect(html).toContain('grid-template-columns:repeat(3, 1fr)'); // default 3
expect(html).toContain('gap:16px'); // default 16
```

### All cards rendered

```tsx
const html = renderToStaticMarkup(<StatGrid cards={cards} />);
for (const card of cards) {
  expect(html).toContain(card.label);
}
```

## Badge assertions

### Variant via data-attribute

```tsx
const html = renderToStaticMarkup(<Badge variant="solid">New</Badge>);
expect(html).toContain('data-variant="solid"');
expect(html).toContain('data-size="md"'); // default size
```

### Solid variant — filled background

```tsx
const html = renderToStaticMarkup(
  <Badge variant="solid" color="#ff0000">New</Badge>
);
expect(html).toContain('background:#ff0000');
```

### Outline variant — border only

```tsx
const html = renderToStaticMarkup(
  <Badge variant="outline" color="#00ff00">Beta</Badge>
);
expect(html).toContain('border:1px solid #00ff00');
expect(html).toContain('background:transparent');
```

### Subtle variant — rgba tint

When the color is a hex string, the subtle variant converts it to
`rgba(r, g, b, 0.15)` with spaces (the `hexToRgb` helper returns
`"r, g, b"` with spaces, which are preserved in the template literal):

```tsx
const html = renderToStaticMarkup(
  <Badge variant="subtle" color="#0000ff">Info</Badge>
);
expect(html).toContain('rgba(0, 0, 255, 0.15)'); // WITH spaces
```

### Size presets

```tsx
// small
expect(renderToStaticMarkup(<Badge size="sm">S</Badge>)).toContain('font-size:12px');
expect(renderToStaticMarkup(<Badge size="sm">S</Badge>)).toContain('padding:2px 10px');

// large
expect(renderToStaticMarkup(<Badge size="lg">L</Badge>)).toContain('font-size:16px');
expect(renderToStaticMarkup(<Badge size="lg">L</Badge>)).toContain('padding:6px 18px');
```

## Updated inline-style serialization reference

**IMPORTANT:** These values were verified against actual `renderToStaticMarkup`
output in React 18.3. Do NOT assume shorter/normalized forms — React preserves
the value as-written in the style object. Always run the test once and read the
failure message's "Received:" output to confirm the exact serialization before
finalizing assertions.

| React style object | Serialized output | Notes |
|---|---|---|
| `{ background: 'red' }` | `background:red` | No space after colon |
| `{ background: 'var(--od-accent)' }` | `background:var(--od-accent)` | |
| `{ background: 'rgba(0,0,0,0.03)' }` | `background:rgba(0,0,0,0.03)` | Value preserved as-written |
| `{ background: \`rgba(${rgb}, 0.15)\` }` (rgb=`"0, 0, 255"`) | `background:rgba(0, 0, 255, 0.15)` | Spaces in the template literal ARE preserved |
| `{ opacity: 0.5 }` | `opacity:0.5` | Leading zero RETAINED — NOT `.5` |
| `{ gridTemplateColumns: 'repeat(3, 1fr)' }` | `grid-template-columns:repeat(3, 1fr)` | Space after comma RETAINED |
| `{ gridTemplateColumns: 'repeat(3,1fr)' }` | `grid-template-columns:repeat(3,1fr)` | No space if source has none |
| `{ gap: 16 }` | `gap:16px` | |
| `{ fontSize: 14 }` | `font-size:14px` | |
| `{ fill: '#6d4cff' }` | `fill="#6d4cff"` | SVG attribute, not inline style |
| `{ border: '1px solid #00ff00' }` | `border:1px solid #00ff00` | |
| `{ padding: '2px 10px' }` | `padding:2px 10px` | |
| `{ borderRadius: 9999 }` | `border-radius:9999px` | |

**Key rules (verified):**
- Property names convert to kebab-case (`fontSize` → `font-size`)
- No space after the colon separating property from value
- Value content is preserved EXACTLY as written in the style object — spaces,
  commas, leading zeros all survive serialization unchanged
- SVG `fill`/`stroke` are attributes (appear as `fill="..."`), not inline styles
- Numbers get units appended (`14` → `14px` for font-size, `16` → `16px` for gap)

## Element-counting regex — the #1 table-test pitfall

`/<th/g` matches BOTH `<th>` AND `<thead>`, inflating the count by 1 per
`<thead>`. This causes "expected 4 to be 3" failures.

**Always use `[ >]` after the tag name** to match only the element, not prefixes:

```tsx
// ✅ Correct — counts only <th> elements, not <thead>
const headerCells = (html.match(/<th[ >]/g) || []).length;

// ✅ Correct — counts only <td> elements
const bodyCells = (html.match(/<td[ >]/g) || []).length;

// ✅ Correct — counts only <tr> elements
const bodyRows = (html.match(/<tr[ >]/g) || []).length;

// ❌ WRONG — also matches <thead>
const headerCells = (html.match(/<th/g) || []).length;  // +1 for <thead>
```

This applies to ALL HTML element counting in `renderToStaticMarkup` output.
The `[ >]` pattern ensures you match `<tag>`, `<tag ` (with attributes), but
not `<tagprefix>`.
