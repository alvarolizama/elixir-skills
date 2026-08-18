# Assertion Patterns: Structural & Flow Widgets

Concrete patterns extracted from building Pyramid, Timeline, ProcessFlow,
StepIndicator, Divider, CoverLayout, AgendaLayout, and NumberedList widgets
in the open-delta monorepo (`packages/core/src/widgets/`).

These widgets extend beyond the data-viz charts (BarChart, DonutChart) into
structural/flow components — layout containers, step progressors, dividers,
and full-canvas slide layouts.

## Project context (same as data-viz widgets)

- Monorepo: pnpm workspace, `packages/core`
- Test runner: vitest, `environment: 'node'`
- React jsx runtime: `react-jsx` (automatic)
- Design tokens: `--od-bg`, `--od-text`, `--od-accent`, `--od-radius`,
  `--od-font-display`, `--od-font-body`, `--od-size-hero`, `--od-size-body`
- Canvas: 1920×1080 for full-slide layouts

## Common prop patterns across structural widgets

All structural widgets follow the same prop conventions:

```tsx
export type WidgetProps = {
  // ... widget-specific props
  color?: string;           // default: 'var(--od-accent)'
  style?: CSSProperties;    // extra styles merged into root
};
```

- **Named exports** for both the component and its Props type
- **`style` prop** merged last (spread `...style` at end of root style object)
- **`data-od-widget`** attribute on root element for testability
- **`data-variant`/`data-direction`/`data-orientation`** attributes for
  variant/orientation assertions (preferred over style parsing)

## Pyramid assertions

### Count layers (polygon elements)

Each pyramid layer is a `<polygon>`. Count them directly:

```tsx
const html = renderToStaticMarkup(<Pyramid layers={layers} />);
const polyCount = (html.match(/<polygon/g) || []).length;
expect(polyCount).toBe(layers.length);
```

### Layer color override

```tsx
const html = renderToStaticMarkup(<Pyramid layers={layers} />);
expect(html).toContain('#abcdef'); // from layer.color
```

### Value display toggle

```tsx
// showValues=true (default): values appear in parentheses
expect(html).toContain('(10)');
// showValues=false: only labels, no parentheses
expect(html).not.toContain('(10)');
```

### Single-layer edge case

A single layer renders as a full-width trapezoid (still a polygon):

```tsx
const html = renderToStaticMarkup(<Pyramid layers={[{ label: 'Only' }]} />);
expect(html).toContain('Only');
expect((html.match(/<polygon/g) || []).length).toBe(1);
```

## Timeline assertions

### Count milestone nodes (circle elements)

Each milestone is a `<circle>` on the baseline. The baseline itself is a
`<line>`, so counting `<circle>` gives the node count directly:

```tsx
const html = renderToStaticMarkup(<Timeline milestones={milestones} />);
const circleCount = (html.match(/<circle/g) || []).length;
expect(circleCount).toBe(milestones.length);
```

### Label and date presence

```tsx
expect(html).toContain('Kickoff');
expect(html).toContain('Jan 2025');
```

### Date absence when not provided

When a milestone has no date, no date `<text>` element is rendered. Count
total `<text>` elements to verify:

```tsx
const html = renderToStaticMarkup(<Timeline milestones={[{ label: 'NoDate' }]} />);
expect(html).toContain('NoDate');
const textCount = (html.match(/<text/g) || []).length;
expect(textCount).toBe(1); // only the label, no date
```

### Icon inside node

```tsx
const html = renderToStaticMarkup(
  <Timeline milestones={[{ label: 'Start', icon: '★' }]} />,
);
expect(html).toContain('★');
```

### Custom dimensions

```tsx
const html = renderToStaticMarkup(
  <Timeline milestones={milestones} width={1600} height={300} nodeSize={40} />,
);
expect(html).toContain('width="1600"');
expect(html).toContain('height="300"');
expect(html).toContain('r="20"'); // nodeSize / 2
```

## ProcessFlow assertions

### Box and arrow counting

Each step is a bordered `<div>`; arrows between steps are SVG `<polygon>`
triangles. Count polygons to verify arrow count = steps - 1:

```tsx
const html = renderToStaticMarkup(<ProcessFlow steps={steps} />);
expect(html).toContain('Discover');
const arrowCount = (html.match(/<polygon/g) || []).length;
expect(arrowCount).toBe(steps.length - 1); // no arrow after last step
```

### Direction via data-attribute

```tsx
// horizontal (default)
expect(html).toContain('data-direction="horizontal"');
expect(html).toContain('flex-direction:row');

// vertical
const vHtml = renderToStaticMarkup(<ProcessFlow steps={steps} direction="vertical" />);
expect(vHtml).toContain('data-direction="vertical"');
expect(vHtml).toContain('flex-direction:column');
```

### Custom box dimensions

```tsx
const html = renderToStaticMarkup(
  <ProcessFlow steps={steps} boxWidth={300} boxHeight={120} />,
);
expect(html).toContain('width:300px');
expect(html).toContain('height:120px');
```

## StepIndicator assertions

### Completed step filling

Completed steps (index < current) have `background:{color}`. Count
occurrences to verify:

```tsx
const html = renderToStaticMarkup(
  <StepIndicator steps={steps} current={2} color="#ff0000" />,
);
const bgMatches = (html.match(/background:#ff0000/g) || []).length;
expect(bgMatches).toBe(2); // steps 0 and 1 are completed
```

### Current step ring border

The current step has `border:3px solid {color}` (thicker than completed
steps' `2px`):

```tsx
expect(html).toContain('border:3px solid #00ff00');
```

### Orientation via data-attribute

```tsx
expect(html).toContain('data-orientation="horizontal"');
expect(html).toContain('flex-direction:row');
```

### Step numbers

```tsx
expect(html).toContain('>1<');
expect(html).toContain('>2<');
```

## Divider assertions

### Variant via data-attribute

```tsx
expect(html).toContain('data-variant="line"');
expect(html).toContain('data-variant="dots"');
```

### Line variant — solid bar

```tsx
expect(html).toContain('background:#ff0000');
```

### Dots variant — count circles

Three dots, each with `border-radius:50%`:

```tsx
const dotCount = (html.match(/border-radius:50%/g) || []).length;
expect(dotCount).toBe(3);
```

### Gradient variant — linear-gradient string

```tsx
expect(html).toContain('linear-gradient');
expect(html).toContain('#0000ff');
```

### Wave variant — SVG path

```tsx
expect(html).toContain('<svg');
expect(html).toContain('<path');
```

### Label overlay positioning

When a label is provided, it renders as a `<span>` with
`position:absolute` on top of the divider:

```tsx
expect(html).toContain('Section Break');
expect(html).toContain('position:absolute');
```

### No label span when absent

```tsx
expect(html).not.toContain('<span');
```

## CoverLayout assertions

### Full-canvas dimensions

CoverLayout (like all slide layouts) renders at 1920×1080:

```tsx
expect(html).toContain('width:1920px');
expect(html).toContain('height:1080px');
```

### Accent bar presence/absence

```tsx
// default: accent bar shown
expect(html).toContain('var(--od-accent)');
expect(html).toContain('width:120px');

// accent=false: no accent bar
const html2 = renderToStaticMarkup(<CoverLayout title="T" accent={false} />);
expect(html2).not.toContain('var(--od-accent)');
```

### Author/date row

The metadata row is positioned at `bottom:80px`. When neither author nor
date is provided, the entire row is omitted:

```tsx
// with author + date
expect(html).toContain('Jane Doe');
expect(html).toContain('2025-01-01');
expect(html).toContain('bottom:80px');

// without metadata
const html2 = renderToStaticMarkup(<CoverLayout title="T" />);
expect(html2).not.toContain('bottom:80px');
```

### Background layer

```tsx
const html = renderToStaticMarkup(
  <CoverLayout title="T" background={<img src="/bg.png" alt="" />} />,
);
expect(html).toContain('/bg.png');
```

### Alignment

```tsx
const html = renderToStaticMarkup(<CoverLayout title="T" align="center" />);
expect(html).toContain('data-align="center"');
expect(html).toContain('text-align:center');
```

## AgendaLayout assertions

### Numbered circles

Each agenda item gets a numbered circle. Verify numbers 1..N appear:

```tsx
expect(html).toContain('>1<');
expect(html).toContain('>2<');
expect(html).toContain('>3<');
expect(html).toContain('>4<');
```

### Multi-column grid

```tsx
expect(html).toContain('grid-template-columns:repeat(2, 1fr)');
```

### Default single column

```tsx
expect(html).toContain('grid-template-columns:repeat(1, 1fr)');
```

### Accent bar toggle

Same pattern as CoverLayout — `var(--od-accent)` present by default,
absent when `accent={false}`.

## NumberedList assertions

### Numbers and items

```tsx
expect(html).toContain('>1<');
expect(html).toContain('First point');
```

### Orientation

```tsx
expect(html).toContain('data-orientation="horizontal"');
expect(html).toContain('flex-direction:row');

const vHtml = renderToStaticMarkup(<NumberedList items={items} vertical />);
expect(vHtml).toContain('data-orientation="vertical"');
expect(vHtml).toContain('flex-direction:column');
```

### Custom circle and font sizes

```tsx
const html = renderToStaticMarkup(
  <NumberedList items={items} circleSize={64} fontSize={36} />,
);
expect(html).toContain('width:64px');
expect(html).toContain('height:64px');
expect(html).toContain('font-size:36px');
```

### White text on colored circle

```tsx
expect(html).toContain('color:#fff');
```

## Structural widget patterns summary

| Widget type | Root element | Key SVG elements | Key data-* attributes |
|---|---|---|---|
| Pyramid | `<svg>` | `<polygon>` per layer | — |
| Timeline | `<svg>` | `<circle>` per node, `<line>` baseline | — |
| ProcessFlow | `<div>` | `<polygon>` per arrow (inline SVG) | `data-direction` |
| StepIndicator | `<div>` | — (pure div/flex) | `data-orientation` |
| Divider | `<div>` | `<path>` for wave variant | `data-variant` |
| CoverLayout | `<div>` | — (pure div/flex) | `data-align` |
| AgendaLayout | `<div>` | — (pure div/flex/grid) | — |
| NumberedList | `<div>` | — (pure div/flex) | `data-orientation` |

### Hybrid SVG + HTML widgets

ProcessFlow and Divider are hybrid: the root container is an HTML `<div>`,
but arrows/waves are inline `<svg>` elements. This means:

- Box/label assertions use `toContain` on text content
- Arrow/wave assertions count `<polygon>` or `<path>` elements
- Both types of assertions work in the same test without conflict

### Full-canvas layout widgets

CoverLayout and AgendaLayout render at a fixed 1920×1080 canvas size (same
as HeroLayout, SplitLayout, etc. from the existing `layouts.tsx`). They share
these patterns:

- `width:1920px`, `height:1080px` on root
- `background:var(--od-bg)`, `color:var(--od-text)` on root
- Optional accent bar: a `<div>` with `background:var(--od-accent)` and
  `width:96px` or `width:120px`, toggled by `accent` boolean prop
- Assertions for accent bar presence/absence are identical across all
  layout widgets

### Numbered-circle pattern (shared)

AgendaLayout, StepIndicator, and NumberedList all use numbered circles. The
circle is a `<div>` (not SVG) with:
- `border-radius:50%`
- `background:{color}` (AgendaLayout, NumberedList) or conditional
  fill/ring (StepIndicator)
- White text (`color:#fff`)
- Number text as children (`{i + 1}`)

Tests verify the number appears as `>{n}<` in the rendered output.
