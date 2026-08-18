# Visual-Language Restyle Patterns for open-delta Widgets

Concrete patterns from restyling 18 widgets (bar-chart, donut-chart,
gauge-chart, heat-map, radar-chart, metric-ring, progress-bar, data-table,
stat-card, stat-grid, funnel, pyramid, timeline, process-flow,
comparison-matrix, versus-comparison, step-indicator, feature-grid) to a
shared professional visual language.

## The shared visual language

Every restyled widget follows the same five-layer treatment:

### 1. Elevated surfaces

HTML container widgets (stat-card, process-flow, heat-map, data-table,
comparison-matrix, versus-comparison, feature-grid) get elevation:

```tsx
boxShadow: '0 1px 2px rgba(0,0,0,0.05), 0 12px 32px -8px rgba(0,0,0,0.12)',
border: '1px solid color-mix(in srgb, var(--od-text) 10%, transparent)',
borderRadius: 'var(--od-radius)',
```

The two-layer shadow (tight 1px + diffuse 12px) gives a subtle "floating"
feel without heavy drop-shadow. The border uses `color-mix` at 10% to
adapt to theme automatically — no hardcoded rgba.

### 2. Top accent gradient bars

Most surfaces get a 3px gradient bar at the top:

```tsx
<div style={{
  position: 'absolute',
  top: 0,
  left: 0,
  right: 0,
  height: 3,
  background: `linear-gradient(90deg, ${color}, color-mix(in srgb, ${color} 40%, transparent))`,
}} />
```

Requires `position: 'relative'` and `overflow: 'hidden'` on the parent.
Skip for `minimal` variant (which has no border/bg at all).

### 3. Typography hierarchy

- **Micro-labels:** uppercase, `0.08em` letter-spacing, 600 weight,
  `color-mix(in srgb, var(--od-text) 60%, transparent)` (muted).
  Used for column headers, axis labels, progress labels, timeline dates.
- **Big values:** 800 weight, `-0.02em` letter-spacing,
  `var(--od-font-display)`. Used for stat values, gauge numbers, table
  headers.
- **Body text:** `color-mix(in srgb, var(--od-text) 65%, transparent)`
  for descriptions and muted content.

```tsx
// Micro-label (SVG text — MUST use style prop, not attributes, for
// textTransform/letterSpacing/fontWeight — see pitfall #17)
<text
  style={{ textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 600 }}
  fill="color-mix(in srgb, var(--od-text) 60%, transparent)"
  fontSize={12}
>
  {label}
</text>

// Big value
<div style={{
  fontFamily: 'var(--od-font-display)',
  fontWeight: 800,
  letterSpacing: '-0.02em',
  fontSize: 72,
}}>
  {value}
</div>
```

### 4. SVG chart gradients

Every SVG chart gets `<defs><linearGradient>` for its primary visual
elements:

```tsx
<defs>
  <linearGradient id={`bar-grad-${i}`} x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stopColor={color} stopOpacity={1} />
    <stop offset="100%" stopColor={color} stopOpacity={0.4} />
  </linearGradient>
</defs>

// Then reference in the fill:
<rect fill={`url(#bar-grad-${i})`} />
```

Pattern per chart type:
- **BarChart (vertical):** gradient per bar, `y1=0 y2=1` (top→bottom)
- **BarChart (horizontal):** gradient per bar, `x1=0 x2=1` (left→right)
- **DonutChart:** gradient per segment, `x1=0 y1=0 x2=1 y2=1` (diagonal)
- **GaugeChart:** single gradient, `x1=0 y1=0 x2=1 y2=0` (horizontal)
- **RadarChart:** gradient per series, `x1=0 y1=0 x2=1 y2=1`
- **MetricRing:** always has gradient def (even in default variant, for
  potential variant switching)
- **Funnel:** default variant gets its own gradient defs (`funnel-def-grad-N`)
  in addition to the `gradient` variant's `funnel-grad-N`
- **Pyramid:** default variant gets `pyr-def-grad-N`; `gradient` variant
  keeps its existing `pyramid-grad-N` with white-fade

### 5. Hairline gridlines

SVG charts get subtle gridlines:

```tsx
const GRIDLINE_COLOR = 'color-mix(in srgb, var(--od-text) 10%, transparent)';

// In BarChart vertical:
{[0.25, 0.5, 0.75].map((ratio) => (
  <line
    x1={PADDING_HORIZONTAL}
    y1={height - AXIS_THICKNESS - chartH * ratio}
    x2={width - PADDING_HORIZONTAL}
    y2={height - AXIS_THICKNESS - chartH * ratio}
    stroke={GRIDLINE_COLOR}
    strokeWidth={1}
  />
))}
```

The baseline axis also uses `GRIDLINE_COLOR` instead of `var(--od-text)`.

## Backward compatibility rules

- **Props API:** No removals or renames. Additive-only changes.
- **`data-od-widget` / `data-variant`:** Must be preserved on root elements.
- **Absolute pixel sizing:** Keep all `width`, `height`, `size` props in
  pixels — don't switch to rem/percentages.
- **`var(--od-*)` tokens:** Keep using design tokens; don't hardcode colors.
  The `color-mix()` expressions wrap these tokens for muted variants.

## Test assertion updates

After restyling, update tests to assert the NEW structure. Do NOT weaken
assertions — assert the new visual elements:

```tsx
// Gradient defs present
expect(html).toContain('linearGradient');
expect(html).toContain('bar-grad-0');

// Hairline gridlines present
expect(html).toContain('color-mix(in srgb, var(--od-text) 10%, transparent)');

// Elevation shadow present
expect(markup).toContain('0 12px 32px -8px');

// Top accent bar present
expect(markup).toContain('linear-gradient(90deg');

// Muted text using color-mix
expect(html).toContain('color-mix(in srgb, var(--od-text) 60%, transparent)');
```

### Common test failures after restyle (and fixes)

See SKILL.md pitfalls #14-#18 for the three false-failure patterns:
1. `<linearGradient` matching `<line` → use `/<line\b/g`
2. `offset="100%"` matching `%` → assert `>N%<` not just `%`
3. Container `border-radius` matching cell-level → width-qualified regex

## color-mix() serialization reference

| React style object | Serialized output |
|---|---|
| `color: 'color-mix(in srgb, var(--od-text) 60%, transparent)'` | `color:color-mix(in srgb, var(--od-text) 60%, transparent)` |
| `border: '1px solid color-mix(in srgb, var(--od-text) 10%, transparent)'` | `border:1px solid color-mix(in srgb, var(--od-text) 10%, transparent)` |
| `background: 'color-mix(in srgb, var(--od-accent) 8%, transparent)'` | `background:color-mix(in srgb, var(--od-accent) 8%, transparent)` |
| ``background: `linear-gradient(90deg, ${color}, color-mix(in srgb, ${color} 40%, transparent))` `` | `background:linear-gradient(90deg, var(--od-accent), color-mix(in srgb, var(--od-accent) 40%, transparent))` |

Key: `color-mix()` expressions are preserved exactly as written — all
spaces, commas, and percentages survive serialization unchanged.
