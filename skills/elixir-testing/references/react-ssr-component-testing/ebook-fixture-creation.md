# Ebook Fixture Creation: All-Widgets Pattern

Concrete patterns for creating e2e fixture content files that showcase
widgets in ebook A4 format (794×1123). Extracted from building
`packages/core/e2e/fixture/content/all-widgets-ebook/index.tsx` in the
open-delta monorepo.

## Fixture file structure

Every fixture under `packages/core/e2e/fixture/content/<name>/index.tsx`
follows this contract:

```tsx
import type { DocMeta, Page } from '@open-delta/core';
import { BookCover, BookPage, /* ... */ } from '@open-delta/core';

export const meta: DocMeta = {
  title: 'Fixture Title',
  createdAt: '2026-07-23T06:27:23Z',  // ISO 8601 UTC
};

// Each page is a Page component (function returning JSX)
const Cover: Page = () => ( /* ... */ );

export default [Cover, /* ... */] satisfies Page[];
```

Key points:
- `meta` is a named export with `title` and `createdAt` (ISO timestamp).
- Default export is a `Page[]` array — the ordered pages of the document.
- Use `satisfies Page[]` (not `as Page[]`) for type safety without erasure.
- Widgets are imported from `@open-delta/core` (the monorepo package alias).

## Ebook page flow

A complete ebook fixture follows this page sequence:

1. **BookCover** — title, subtitle, author, optional gradient background
2. **TableOfContents** — entries with `{ label, page }` pointing to later pages
3. **ChapterDivider** — chapter number, title, description (one per chapter)
4. **BookPage** — content page with `chapter` header, `pageNumber`/`totalPages`
5. **BookBackCover** — title, author, description, ISBN

Repeat steps 3-4 for each chapter. Each BookPage can contain multiple
widgets arranged in a vertical flex column.

## The slide-to-ebook scaling technique (KEY)

**Problem:** Layout widgets (`HeroLayout`, `SplitLayout`, `BentoGrid`,
`SectionLayout`, `QuoteLayout`, `StatLayout`) hardcode `width: 1920,
height: 1080` in their root element. They do NOT accept a `format` prop
like ebook widgets do. When embedded inside a `BookPage` (794×1123),
they overflow massively.

**Solution:** Wrap each layout widget in a container with
`overflow: hidden`, a fixed height, and `borderRadius`. The layout
renders at full 1920×1080 internally but is visually clipped to fit
the BookPage content area:

```tsx
<div style={{ overflow: 'hidden', borderRadius: 'var(--od-radius)', height: 120 }}>
  <HeroLayout title="Lorem Ipsum" subtitle="Dolor sit amet" variant="centered" />
</div>
```

This is the standard pattern for including any 1920×1080 widget inside
an A4 BookPage. The `height` value controls how much of the widget is
visible. Common values: 80-120px for a scaled-down preview.

**Important:** The layout widgets are NOT actually scaled — they are
clipped. The content renders at full size but only the top portion
is visible. This is acceptable for fixture/showcase purposes where
the goal is visual presence, not pixel-perfect scaling.

For widgets that DO accept explicit width/height props (charts, funnels,
pyramids, timelines, process flows), pass reduced dimensions directly:

```tsx
// Charts: scale down from slide dimensions
<BarChart data={data} width={320} height={160} />      // slide: 600×300
<DonutChart data={data} size={160} thickness={24} />    // slide: 240
<Funnel stages={stages} width={320} height={140} />    // slide: 500×300
<GaugeChart value={72} size={150} />                    // slide: 260
<Pyramid layers={layers} width={400} height={180} />    // slide: 500×280
<Timeline milestones={ms} width={680} height={80} />    // slide: full width
```

## Type scale for ebook format

Ebook pages are ~40% the width of slides (794 vs 1920). Scale all
typography proportionally:

| Element        | Slide size | Ebook size |
|----------------|------------|------------|
| Page heading   | 64px       | 28px       |
| Subheading     | 24px       | 14px       |
| Body text      | 20px       | 14px       |
| Section label  | 18px       | 12px       |
| Chart labels   | default    | 12-14px    |

Shared style objects:

```tsx
const heading: React.CSSProperties = {
  fontFamily: 'var(--od-font-display)',
  fontSize: 28, fontWeight: 800, margin: 0, marginBottom: 8,
};
const subheading: React.CSSProperties = {
  fontFamily: 'var(--od-font-body)',
  fontSize: 14, opacity: 0.6, margin: 0, marginBottom: 16,
};
const sectionLabel: React.CSSProperties = {
  fontFamily: 'var(--od-font-body)',
  fontSize: 12, fontWeight: 700, textTransform: 'uppercase',
  letterSpacing: '0.1em', opacity: 0.5, margin: 0, marginBottom: 6,
};
```

## BookPage layout pattern

BookPage accepts `children`, `chapter`, `pageNumber`, `totalPages`,
`padding`, and `format`. The content area is `flex: 1` with
`overflow: hidden`. Structure content as a vertical flex column:

```tsx
<BookPage chapter="Chapter 1 — Layouts" pageNumber={4} totalPages={11} padding={48}>
  <div style={{ display: 'flex', flexDirection: 'column', gap: 20, height: '100%' }}>
    {/* Section label + widget pair */}
    <div>
      <p style={sectionLabel}>WidgetName · variant</p>
      <SomeWidget {...props} />
    </div>
    {/* More sections... */}
  </div>
</BookPage>
```

Use `padding={48}` (reduced from default 64) to maximize content area.
Group related widgets in rows with `display: flex, gap: 16, alignItems: center`.

## Complete widget import list

All widgets available from `@open-delta/core` (as of 2026-07):

```tsx
import {
  // Ebook layout widgets (accept format prop)
  BookCover, BookBackCover, BookPage, TableOfContents, ChapterDivider,
  // Slide layout widgets (hardcode 1920×1080 — needs overflow:hidden wrapper)
  HeroLayout, SplitLayout, BentoGrid, SectionLayout, QuoteLayout, StatLayout,
  CoverLayout, AgendaLayout,
  // Charts (accept width/height or size props)
  BarChart, DonutChart, RadarChart, GaugeChart, HeatMap,
  // Data widgets
  DataTable, Funnel, ProgressBar, MetricRing, Pyramid, Timeline,
  ProcessFlow, StepIndicator, ComparisonMatrix, VersusComparison,
  // Visual elements
  Badge, Callout, Divider, GradientText, GradientBackground,
  StatCard, StatGrid, FeatureGrid, GlowCard, Avatar, IconCircle,
  StickyNote, NumberedList, Checklist, PricingCard,
  // Types
  type Series, type ComparisonRow,
  // Utilities
  ImagePlaceholder, MorphElement,
  CanvasDimensionsProvider, useCanvasDimensions,
  cssVarsToString, defaultDesign, designToCssVars,
  useDocPageNumber, useIsActivePage,
  Step, Steps,
  FORMAT_PRESETS, getCanvasDimensions,
} from '@open-delta/core';
```

## TypeScript verification

The open-delta repo's `packages/core/tsconfig.json` uses a deprecated
`baseUrl` option. Running `tsc --noEmit` produces a TS5101 deprecation
error. Pass `--ignoreDeprecations 6.0` to silence it:

```bash
npx tsc --noEmit --project packages/core/tsconfig.json --ignoreDeprecations 6.0
```

Exit code 0 with no output = clean compile. This does NOT run the
test suite — use `pnpm vitest` or `pnpm test` for that.

## Common pitfalls

1. **Forgetting `satisfies Page[]`** — using `as Page[]` erases type
   checking. `satisfies` validates the array without widening.

2. **Using slide-sized chart dimensions** — BarChart 600×300 overflows
   a 794px-wide BookPage (794 - 2×48 padding = 698px content width).
   Scale to ~320×160 or similar.

3. **Not wrapping layout widgets in overflow:hidden** — HeroLayout at
   1920×1080 will blow out the BookPage. Always wrap.

4. **Missing `createdAt` in meta** — it's required on `DocMeta`. Use
   `date -u +"%Y-%m-%dT%H:%M:%SZ"` to generate the timestamp.

5. **Importing from relative paths** — fixture files should import from
   `@open-delta/core`, not `../../../src`. The monorepo's tsconfig
   resolves the package alias for e2e fixtures.
