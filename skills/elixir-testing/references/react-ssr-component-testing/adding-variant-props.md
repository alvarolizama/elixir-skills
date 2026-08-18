# Adding Visual Style Variants to Existing Widgets

Recipe extracted from adding a `variant` prop to 11 widgets in the open-delta
monorepo (`packages/core/src/widgets/`). Each widget received 3+ style options
with full backward compatibility — existing consumers see no change because
the default variant matches the original rendering.

## Prop naming convention

- **Prop name:** `variant` (for most widgets) or `styleVariant` when the
  widget already has a `variant` prop for semantic meaning (e.g. Callout
  already had `variant: 'info' | 'warning' | 'success' | 'danger'`).
- **Type:** exported as `WidgetNameVariant` (e.g. `GaugeVariant`,
  `HeatMapVariant`, `ComparisonVariant`).
- **Default:** always the original behavior — named `'default'` (or
  `'outlined'` for Callout, `'grid'` for HeatMap — match the original look).
- **Root attribute:** `data-variant={variant}` on the root element for
  trivial testability.

## Backward compatibility pattern

The key principle: **the default variant must produce identical output to
the original component.** This means:

1. Add `variant = 'default'` to the destructured props with a default value.
2. Branch on `variant` only for non-default cases.
3. Keep the original code path for `'default'`.

```tsx
// Before:
export function Widget({ color = 'var(--od-accent)', ... }) {
  return <div style={{ background: color }}>...</div>;
}

// After:
export function Widget({ color = 'var(--od-accent)', variant = 'default', ... }) {
  const fill = variant === 'gradient' ? `url(#widget-grad)` : color;
  return (
    <div data-variant={variant} style={{ background: fill }}>
      {variant === 'gradient' && (
        <defs>
          <linearGradient id="widget-grad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={1} />
            <stop offset="100%" stopColor={color} stopOpacity={0.4} />
          </linearGradient>
        </defs>
      )}
      ...
    </div>
  );
}
```

## Variant implementation strategies

### 1. Color/background swap (simplest)

Change background color or opacity based on variant. Used by:
- **Callout** `styleVariant`: `filled` (solid bg), `outlined` (border + transparent), `subtle` (low-opacity tint overlay)
- **DataTable** `variant`: `default`, `minimal` (no borders), `striped` (forces zebra), `bordered` (outer border)
- **ComparisonMatrix** `variant`: `default`, `minimal` (no border-radius), `zebra` (alternating row backgrounds)

### 2. Border radius change

Change cell shape via `borderRadius`. Used by:
- **HeatMap** `variant`: `grid` (default radius), `rounded` (12px), `circle` (50%)

### 3. SVG gradient defs

Inject `<defs><linearGradient>` and reference via `url(#id)`. Used by:
- **Funnel** `variant`: `gradient` — each stage gets its own gradient def
- **MetricRing** `variant`: `gradient` — progress arc stroke uses gradient
- **Pyramid** `variant`: `gradient` — each layer gets a gradient fading to white

```tsx
// Gradient def pattern for SVG widgets
const fill = variant === 'gradient' ? `url(#funnel-grad-${i})` : color;

// Inside the SVG, before the shapes:
{variant === 'gradient' && (
  <defs>
    <linearGradient id={`funnel-grad-${i}`} x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stopColor={color} stopOpacity={1} />
      <stop offset="100%" stopColor={color} stopOpacity={0.4} />
    </linearGradient>
  </defs>
)}
```

**Pitfall:** gradient IDs must be unique per element instance when rendering
multiple shapes with gradients. Use `funnel-grad-${i}` (index-based) or
`funnel-grad-${stage.label}` (label-based).

### 4. Conditional element rendering

Show/hide entire SVG elements based on variant. Used by:
- **GaugeChart** `variant`: `default` (arc + needle), `arc` (arc only, no needle), `needle` (needle only, no arc fill)
- **Funnel** `variant`: `minimal` (shapes only, no labels/percentages)
- **RadarChart** `variant`: `outline` (fill="none", thicker stroke), `filled` (higher fill-opacity 0.3)

```tsx
const showTrack = variant !== 'needle';
const showArc = variant !== 'needle';
const showNeedle = variant === 'needle' || variant === 'default';

// Conditionally render:
{showTrack && <path d={...} stroke={trackColor} />}
{showArc && <path d={...} stroke={color} strokeDasharray={...} />}
{showNeedle && (
  <g transform={`rotate(${needleAngle}, ${cx}, 0)`}>
    <line x1={cx} y1={0} x2={cx + radius - 10} y2={0} stroke={color} />
    <circle cx={cx} cy={0} r={6} fill={color} />
  </g>
)}
```

### 5. Geometric inversion

Change the shape geometry entirely. Used by:
- **Pyramid** `variant`: `inverted` (widest at top, narrowest at bottom)

### 6. CSS background-image patterns

Use `repeating-linear-gradient` or `linear-gradient` as background-image.
Used by:
- **ProgressBar** `variant`: `striped` (diagonal stripes), `gradient` (fade), `segments` (10 discrete segments)

### 7. Layout/overlay additions

Add overlay elements or change layout structure. Used by:
- **VersusComparison** `variant`: `split` (diagonal SVG divider line overlay), `card` (bordered cards on each side)

## Test patterns for variants

Each variant needs at minimum:
1. A `data-variant` assertion to verify the correct variant was selected.
2. A content/structure assertion to verify the variant produced the expected
   visual difference.

```tsx
it('defaults to default variant', () => {
  const markup = renderToStaticMarkup(<Widget value={50} />);
  expect(markup).toContain('data-variant="default"');
});

it('gradient variant renders linearGradient defs', () => {
  const markup = renderToStaticMarkup(<Widget value={50} variant="gradient" />);
  expect(markup).toContain('data-variant="gradient"');
  expect(markup).toContain('linearGradient');
  expect(markup).toContain('url(#widget-grad)');
});

it('minimal variant hides labels', () => {
  const markup = renderToStaticMarkup(<Widget data={data} variant="minimal" />);
  expect(markup).toContain('data-variant="minimal"');
  expect(markup).not.toContain('Label');
});
```

### Critical: SVG attribute vs CSS inline-style assertion format

When asserting on SVG presentation attributes (`fill-opacity`,
`stroke-width`, `stroke-dasharray`), use the quoted XML format:

```tsx
// ✅ SVG attributes are quoted with =
expect(markup).toContain('fill-opacity="0.3"');
expect(markup).toContain('stroke-width="3"');

// ❌ CSS inline-style format — will NEVER match SVG attributes
expect(markup).toContain('fill-opacity:0.3');
expect(markup).toContain('stroke-width:3');
```

See SKILL.md pitfall #12 for full details.

### Critical: React keys are stripped from SSR output

When testing `.map()` output where elements have `key` props, the keys are
not in the rendered HTML. Assert on observable side effects instead:

```tsx
// ❌ Keys are stripped — always returns 0
const count = (markup.match(/segment-\d/g) || []).length;

// ✅ Count rendered dividers between segments
const dividers = (markup.match(/border-right:2px solid/g) || []).length;
expect(dividers).toBe(9); // 10 segments → 9 dividers
```

See SKILL.md pitfall #13 for full details.

## Variant catalog (11 widgets)

| Widget | Prop name | Variants | Key technique |
|---|---|---|---|
| Callout | `styleVariant` | filled, outlined, subtle | Background swap + tint overlay |
| DataTable | `variant` | default, minimal, striped, bordered | Border toggling + forced zebra |
| Funnel | `variant` | default, gradient, minimal | SVG gradient defs + label hiding |
| GaugeChart | `variant` | default, arc, needle | Conditional SVG element rendering |
| HeatMap | `variant` | grid, rounded, circle | Border radius change |
| MetricRing | `variant` | default, gradient, dashed | SVG gradient + dasharray on track |
| ProgressBar | `variant` | default, striped, gradient, segments | CSS background-image patterns |
| RadarChart | `variant` | default, filled, outline | Fill opacity + stroke width |
| Pyramid | `variant` | default, inverted, gradient | Geometric inversion + SVG gradients |
| VersusComparison | `variant` | default, split, card | SVG overlay + bordered card layout |
| ComparisonMatrix | `variant` | default, minimal, zebra | Border radius removal + row backgrounds |

## Execution workflow

When adding variants to N widgets in one session:

1. **Read all component files** first (batch read_file calls).
2. **Read all test files** to understand existing assertion patterns.
3. **Write all components** (batch write_file — they're independent).
4. **Write all test files** (batch write_file — independent).
5. **Run all tests** in one `vitest run` call targeting the specific test files.
6. **Fix assertion failures** — the most common are:
   - SVG attribute format mismatch (pitfall #12)
   - React keys stripped from output (pitfall #13)
   - Inline-style serialization assumptions (pitfalls #7-#9)
7. **Re-run tests** to confirm all pass.

This batch approach is much faster than read→write→test per widget because
the files are independent and the test failures cluster (same assertion
mistakes repeated across files).
