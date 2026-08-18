# Assertion Patterns: Ebook Layout Widgets

Concrete patterns extracted from building BookCover, BookBackCover,
BookPage, TableOfContents, and ChapterDivider widgets in the open-delta
monorepo (`packages/core/src/widgets/`). These widgets target portrait
canvas dimensions (A4 794×1123, Letter 816×1056) instead of the standard
1920×1080 slide canvas.

## Project context

- Same monorepo, same test runner (vitest, node environment)
- Design tokens: `--od-bg`, `--od-text`, `--od-accent`, `--od-font-display`,
  `--od-font-body`, `--od-radius`
- Ebook format presets live in `packages/core/src/formats.ts`:
  - A4: 794×1123
  - Letter: 816×1056
- All ebook widgets accept a `format?: 'a4' | 'letter'` prop (default 'a4')

## BookCover assertions

### Title, subtitle, and author content

```tsx
const html = renderToStaticMarkup(
  <BookCover title="The Art of Data" subtitle="A visual guide" author="Jane Doe" />,
);
expect(html).toContain('The Art of Data');
expect(html).toContain('A visual guide');
expect(html).toContain('Jane Doe');
```

### Accent bar presence/absence

The accent bar is a thin `<div>` with `background:var(--od-accent)`:

```tsx
// default: accent bar shown
expect(html).toContain('var(--od-accent)');
expect(html).toContain('height:6px');

// accent=false: no accent bar
const html2 = renderToStaticMarkup(<BookCover title="T" accent={false} />);
expect(html2).not.toContain('height:6px');
```

### Format dimensions

```tsx
// A4 (default)
expect(html).toContain('width:794px');
expect(html).toContain('height:1123px');

// Letter
const letterHtml = renderToStaticMarkup(<BookCover title="T" format="letter" />);
expect(letterHtml).toContain('width:816px');
expect(letterHtml).toContain('height:1056px');
```

### Background layer

When `background` prop is provided, it renders inside an absolutely
positioned container:

```tsx
const html = renderToStaticMarkup(
  <BookCover title="T" background={<div data-testid="bg" />} />,
);
expect(html).toContain('position:absolute');
expect(html).toContain('inset:0');
```

## BookBackCover assertions

### Title, author, description, ISBN

```tsx
const html = renderToStaticMarkup(
  <BookBackCover
    title="The Art of Data"
    author="Jane Doe"
    description="A comprehensive guide."
    isbn="978-0-123456-78-9"
  />,
);
expect(html).toContain('The Art of Data');
expect(html).toContain('Jane Doe');
expect(html).toContain('A comprehensive guide.');
expect(html).toContain('978-0-123456-78-9');
```

### ISBN uses marginTop: auto

The ISBN row is pushed to the bottom with `marginTop:auto`:

```tsx
expect(html).toContain('margin-top:auto'); // React serializes marginTop as margin-top
```

Wait — actually React serializes `marginTop` as `margin-top` in inline
styles. But `marginTop: 'auto'` becomes `margin-top:auto`. Verify against
actual output.

## BookPage assertions

### Children content rendering

```tsx
const html = renderToStaticMarkup(
  <BookPage>
    <p>Chapter content here</p>
  </BookPage>,
);
expect(html).toContain('Chapter content here');
```

### Chapter header

The chapter header is a `<div>` with uppercase text and a bottom border:

```tsx
const html = renderToStaticMarkup(
  <BookPage chapter="Chapter 2: Getting Started">
    <p>Content</p>
  </BookPage>,
);
expect(html).toContain('Chapter 2: Getting Started');
expect(html).toContain('text-transform:uppercase');
```

### Page number with total

```tsx
const html = renderToStaticMarkup(
  <BookPage pageNumber={5} totalPages={20}>
    <p>x</p>
  </BookPage>,
);
expect(html).toContain('5');
expect(html).toContain('20');
```

### Page number absent when omitted

```tsx
const html = renderToStaticMarkup(<BookPage><p>x</p></BookPage>);
expect(html).not.toContain('tabular-nums');
```

## TableOfContents assertions

### Title and entries

```tsx
const html = renderToStaticMarkup(
  <TableOfContents
    entries={[
      { label: 'Introduction', page: 1 },
      { label: 'Chapter 1', page: 5 },
    ]}
  />,
);
expect(html).toContain('Table of Contents');
expect(html).toContain('Introduction');
expect(html).toContain('Chapter 1');
```

### Custom title

```tsx
const html = renderToStaticMarkup(
  <TableOfContents title="Índice" entries={[]} />,
);
expect(html).toContain('Índice');
```

### Page numbers with accent color

Page numbers use `var(--od-accent)`:

```tsx
expect(html).toContain('var(--od-accent)');
```

### Dotted leaders

```tsx
expect(html).toContain('dotted');
```

## ChapterDivider assertions

### Title and description

```tsx
const html = renderToStaticMarkup(
  <ChapterDivider title="Getting Started" description="What you will learn" />,
);
expect(html).toContain('Getting Started');
expect(html).toContain('What you will learn');
```

### Chapter number with zero-padding

When `number` is provided, it renders as a two-digit string (01, 02, etc.)
with low opacity:

```tsx
const html = renderToStaticMarkup(
  <ChapterDivider number={3} title="Advanced Topics" />,
);
expect(html).toContain('03');
```

### Accent bar

```tsx
expect(html).toContain('var(--od-accent)');
```

## Common ebook widget patterns

| Widget | Root element | Format prop | Key assertions |
|---|---|---|---|
| BookCover | `<div>` | `format?: 'a4' \| 'letter'` | Title, accent bar, dimensions, background layer |
| BookBackCover | `<div>` | `format?: 'a4' \| 'letter'` | Title, author, description, ISBN, dimensions |
| BookPage | `<div>` | `format?: 'a4' \| 'letter'` | Children, chapter header, page number |
| TableOfContents | `<div>` | `format?: 'a4' \| 'letter'` | Title, entries, dotted leaders, page numbers |
| ChapterDivider | `<div>` | `format?: 'a4' \| 'letter'` | Number, title, description, accent bar |

### Dimension assertion patterns

All ebook widgets accept a `format` prop that controls the canvas dimensions.
The dimensions appear as `width:Npx;height:Npx` in the root element's inline
style:

```tsx
// A4 format (default)
expect(html).toContain('width:794px');
expect(html).toContain('height:1123px');

// Letter format
expect(html).toContain('width:816px');
expect(html).toContain('height:1056px');
```

### Accent bar pattern (shared with slide layouts)

BookCover, ChapterDivider, and several slide layout widgets share the same
accent bar pattern: a thin `<div>` with `background:var(--od-accent)` and a
small height (4-8px). The bar is toggled by an `accent` boolean prop (default
true). Assertions are identical across all widgets that use this pattern.

### Content layer with zIndex

BookCover renders its background layer at `zIndex:0` and content at
`zIndex:1`:

```tsx
expect(html).toContain('z-index:0'); // background
expect(html).toContain('z-index:1'); // content
```

## Integration with multi-format canvas

The ebook widgets use fixed dimensions from `FORMAT_PRESETS` in
`packages/core/src/formats.ts`. They do NOT read from `useCanvasDimensions()`
context — they accept a `format` prop directly. This makes them usable in
isolation (tests, standalone rendering) without mounting a context provider.

The `CanvasDimensionsProvider` in `packages/core/src/app/lib/canvas-context.tsx`
is for the runtime app (slide viewer, thumbnail rail, etc.) to know the
active format. Individual page components can use either the context hook
or the ebook layout widgets directly.

## Test file conventions

Ebook widget tests follow the same conventions as all other widget tests:
- `import { describe, expect, it } from 'vitest'`
- `import { renderToStaticMarkup } from 'react-dom/server'`
- Test file lives next to source: `book-cover.tsx` → `book-cover.test.tsx`
- Assertions on content via `toContain`
- Assertions on dimensions via `width:Npx` / `height:Npx` patterns
- No jsdom, no testing-library
