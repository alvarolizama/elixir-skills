# Slide Fixture Creation: All-Widgets Pattern (1920×1080)

Concrete patterns for creating e2e fixture content files that showcase
**every widget and variant** on the native 1920×1080 slide canvas. Extracted
from building `packages/core/e2e/fixture/content/all-widgets-slide/index.tsx`
in the open-delta monorepo.

This is the slide-format counterpart to `references/ebook-fixture-creation.md`
(which covers A4 ebook format). The key difference: slides render at the
widgets' native canvas size, so the challenge is fitting multiple layout
widgets per gallery page rather than scaling them down to fit a smaller format.

## Fixture file structure

Same contract as all open-delta fixtures:

```tsx
import type { DocMeta, Page } from '@open-delta/core';
import { BarChart, CoverLayout, /* ... */ type Series } from '@open-delta/core';

export const meta: DocMeta = {
  title: 'Fixture Title',
  createdAt: '2026-07-23T06:26:42.890Z',  // ISO 8601 UTC
};

const CoverPage: Page = () => ( /* ... */ );

export default [CoverPage, /* ... */] satisfies Page[];
```

## The full-canvas layout preview technique (KEY)

**Problem:** Layout widgets (`HeroLayout`, `SplitLayout`, `BentoGrid`,
`SectionLayout`, `QuoteLayout`, `StatLayout`, `CoverLayout`, `AgendaLayout`)
hardcode `width: 1920, height: 1080` in their root element. You want to show
3-4 variants of each on a single gallery page, but each takes the full canvas.

**Solution:** A reusable `LayoutPreview` component that wraps the full-canvas
widget in a scaled-down box using CSS `transform: scale()`:

```tsx
function LayoutPreview({ children, label, scale = 0.3 }: {
  children: React.ReactNode;
  label: string;
  scale?: number;
}) {
  const w = Math.round(1920 * scale);
  const h = Math.round(1080 * scale);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
      <div style={{
        width: w, height: h,
        overflow: 'hidden', borderRadius: 8,
        border: '1px solid rgba(255,255,255,0.1)',
        position: 'relative',
      }}>
        <div style={{
          transform: `scale(${scale})`,
          transformOrigin: 'top left',
          width: 1920, height: 1080,
        }}>
          {children}
        </div>
      </div>
      <span style={{ fontFamily: 'var(--od-font-body)', fontSize: 16, marginTop: 10, opacity: 0.6 }}>
        {label}
      </span>
    </div>
  );
}
```

At `scale=0.3`, each preview is 576×324px — three or four fit comfortably in
a row on the 1920×1080 canvas with room for labels and spacing.

**Why `transform: scale()` is better than `overflow: hidden` clipping:**
- Clipping (used in the ebook fixture) only shows the top-left portion of the
  widget — the rest is invisible. Good enough for ebook where space is tight.
- Scaling shows the *entire* widget at reduced size — the viewer sees the full
  layout, all content, and all design elements. This is the right approach for
  a 1920×1080 showcase where the goal is "see every variant at a glance."

## Gallery page structure

A reusable `GalleryPage` wrapper provides the page frame with a heading and
flexible content area:

```tsx
const FILL = {
  width: 1920, height: 1080,
  background: 'var(--od-bg)', color: 'var(--od-text)',
  boxSizing: 'border-box' as const,
};

function GalleryPage({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ ...FILL, padding: 80, display: 'flex', flexDirection: 'column' }}>
      <h2 style={{ fontFamily: 'var(--od-font-display)', fontSize: 56, fontWeight: 700, margin: '0 0 40px' }}>
        {title}
      </h2>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 32 }}>
        {children}
      </div>
    </div>
  );
}
```

Helper components for consistent layout within gallery pages:

```tsx
// Horizontal row of widgets (wraps automatically)
function Row({ children, gap = 48, align = 'flex-start' }: {
  children: React.ReactNode; gap?: number; align?: string;
}) {
  return <div style={{ display: 'flex', gap, alignItems: align as 'flex-start' | 'center', flexWrap: 'wrap' }}>{children}</div>;
}

// Small caption label above each widget variant
function VariantLabel({ children }: { children: React.ReactNode }) {
  return <span style={{ fontFamily: 'var(--od-font-body)', fontSize: 18, opacity: 0.5, marginBottom: 8, display: 'block' }}>{children}</span>;
}
```

## Category-based page organization

Group widgets by category, one or more categories per page:

| Page | Category | Widgets |
|------|----------|---------|
| Cover | — | GradientBackground + custom hero |
| Layouts (6-8 pages) | Layout widgets | HeroLayout, SplitLayout, BentoGrid, SectionLayout, QuoteLayout, StatLayout, CoverLayout, AgendaLayout |
| Charts & Data (5 pages) | Data visualization | BarChart, DonutChart, DataTable, Funnel, ProgressBar, GaugeChart, HeatMap, RadarChart, MetricRing, VersusComparison, ComparisonMatrix |
| Flow & Structure (3 pages) | Sequential/structural | Pyramid, Timeline, ProcessFlow, StepIndicator, Divider, NumberedList, StatGrid |
| Visual Elements (5 pages) | Decorative/interactive | GradientBackground, GradientText, Callout, StatCard, Badge, FeatureGrid, PricingCard, GlowCard, Avatar, IconCircle, StickyNote, Checklist |

Each layout page typically shows 3-4 variant previews in a single row.
Each data/visual page shows 3-12 widget instances arranged in rows.

## Full-canvas cover page pattern

The cover page doesn't use `GalleryPage` — it's a full-canvas custom layout:

```tsx
const CoverPage: Page = () => (
  <div style={{ ...FILL, position: 'relative' }}>
    <GradientBackground opacity={0.35} />
    <div style={{ position: 'relative', zIndex: 1, width: '100%', height: '100%',
      display: 'flex', flexDirection: 'column', justifyContent: 'center',
      alignItems: 'center', textAlign: 'center' }}>
      <div style={{ width: 120, height: 10, background: 'var(--od-accent)',
        borderRadius: 'var(--od-radius)', marginBottom: 48 }} />
      <h1 style={{ fontFamily: 'var(--od-font-display)', fontSize: 120,
        fontWeight: 800, margin: 0, lineHeight: 1.05 }}>All Widgets</h1>
      <p style={{ fontFamily: 'var(--od-font-body)', fontSize: 36,
        margin: '32px 0 0', opacity: 0.8, maxWidth: 1000 }}>
        Every widget & variant — lorem ipsum showcase
      </p>
    </div>
  </div>
);
```

## TypeScript verification

The open-delta repo's `packages/core/tsconfig.json` has `"include": ["src", "tsdown.config.ts", "e2e/tests", "playwright.config.ts"]` — **e2e fixture content directories are NOT in the include list**. Running `tsc --noEmit -p tsconfig.json` will silently pass even if your fixture file has type errors, because tsc doesn't know about it.

**Correct verification:** pass the file explicitly with inline compiler flags:

```bash
cd packages/core && npx tsc --noEmit --pretty \
  --jsx react-jsx --module ESNext --moduleResolution bundler \
  --target ES2022 --lib ES2022,DOM,DOM.Iterable \
  --strict --skipLibCheck --allowImportingTsExtensions \
  --resolveJsonModule --isolatedModules --moduleDetection force \
  --noUnusedLocals --noUnusedParameters \
  e2e/fixture/content/all-widgets-slide/index.tsx
```

Exit code 0 with no output = clean compile. Any prop mismatches, unused
imports, or type errors will show here.

## Common pitfalls

1. **Trusting `tsc -p tsconfig.json` for fixture files.** The tsconfig
   `include` array doesn't cover `e2e/fixture/content/`. The build will
   "pass" silently while your fixture has type errors. Always typecheck
   the file explicitly with inline flags (see above).

2. **Unused lorem ipsum constants.** With `noUnusedLocals` enabled, any
   declared-but-unused constant (e.g. `LOREM_LONG` that you defined but
   didn't reference) will error. Only declare constants you actually use,
   or remove them before typechecking.

3. **Forgetting `type` prefix on type-only imports.** `Series` and
   `ComparisonRow` are types — import them as `type Series` in the import
   list, or use a separate `import type` line. Mixing them as value imports
   works with `isolatedModules` but is cleaner with the `type` prefix.

4. **Using `as Page[]` instead of `satisfies Page[]`.** `as` erases type
   checking; `satisfies` validates without widening. Always use `satisfies`.

5. **Layout widget variants that need `React.ReactNode` children.**
   `SplitLayout` requires `left` and `right` props as `ReactNode`. Inline
   JSX with `<div style={{ padding: 60 }}>` works, but remember the
   padding is relative to the full 1920×1080 canvas before scaling —
   use generous values (60-80px).

6. **`align` prop type in helper components.** When building a `Row` helper
   that accepts an `align` string, cast it properly:
   `align as 'flex-start' | 'center'` — otherwise TypeScript infers `string`
   which doesn't satisfy `React.CSSProperties['alignItems']`.

## Coverage audit script

After writing the fixture, verify every widget and variant is present:

```python
# Quick coverage check — run with execute_code
import re

with open("e2e/fixture/content/all-widgets-slide/index.tsx") as f:
    content = f.read()

expected = {
    "HeroLayout": ["default", "centered", "split", "fullscreen"],
    "SplitLayout": ["default", "diagonal", "asymmetric"],
    # ... etc for all widgets
}

missing = []
for widget, variants in expected.items():
    if widget not in content:
        missing.append(f"WIDGET MISSING: {widget}")
    for v in variants:
        patterns = [f'variant="{v}"', f'color="{v}"', f'checkmarkStyle="{v}"',
                    f'cardStyle="{v}"', f'orientation="{v}"']
        if not any(p in content for p in patterns):
            missing.append(f"{widget}: variant '{v}' not found")

print("✅ ALL PRESENT" if not missing else "\n".join(missing))
```

This catches missed variants before the e2e test suite runs.
