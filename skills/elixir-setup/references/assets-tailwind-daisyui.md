# daisyUI theme customization & Tailwind v4 CSS design system

Customize daisyUI themes and add a design-system layer purely in
`assets/css/app.css` — no `.ex`, `.heex`, `.js`, or config-file changes
required (Tailwind v4).

## daisyUI theme block structure

Themes live in `@plugin "../vendor/daisyui-theme" { ... }` blocks. Each block
is a complete theme: name, color-scheme, and CSS custom properties for every
daisyUI color token. Two blocks ship by default: `dark` and `light`.

```css
@plugin "../vendor/daisyui-theme" {
  name: "dark";
  default: false;
  prefersdark: true;
  color-scheme: "dark";
  --color-base-100: oklch(17.5% 0.008 255);
  --color-base-200: oklch(21% 0.008 255);
  --color-base-300: oklch(26.5% 0.008 255);
  --color-base-content: oklch(95% 0.004 255);
  --color-primary: oklch(72% 0.13 175);
  --color-primary-content: oklch(98% 0.01 175);
  /* ... secondary, accent, neutral, info, success, warning, error ... */
  --radius-selector: 0.375rem;
  --radius-field: 0.375rem;
  --radius-box: 0.625rem;
  --border: 1px;
  --depth: 1;
  --noise: 0;
}
```

### Key rules

- **Theme names must match exactly.** `"dark"` and `"light"` are referenced by
  `@custom-variant dark (&:where([data-theme=dark], [data-theme=dark] *))` and
  the toggle in `app.js`. Do not rename them.
- **All color values use oklch** — `oklch(L% C H)`: L lightness (0–100), C
  chroma (0–0.4+), H hue angle (0–360).
- **`--color-*-content` is the foreground** paired with each background.
  Ensure WCAG AA contrast (4.5:1).
- **`--border: 1px`** (not 1.5px) for a refined look;
  `--radius-box: 0.625rem`, `--radius-field: 0.375rem` for softer corners.

## A proven cool-toned palette (oklch values)

Design principles:
- **Hue consistency**: all base colors at hue ~255 (blue-gray), very low
  chroma (~0.008) → neutral cool background.
- **Primary teal**: hue ~175–180. L=72% in dark, L=55% in light for contrast;
  chroma ~0.12–0.13 — distinctive, not neon.
- **Semantic colors**: chroma ~0.09–0.13 (not default 0.15–0.25) →
  info/success/warning/error harmonize instead of jaring.
- **Accent**: same hue family as warning (amber ~75) but lower chroma. Total:
  two color families — cool blue-gray + teal, with warm amber as accent.

| Token | Dark | Light |
|-------|------|-------|
| base-100 | `oklch(17.5% 0.008 255)` | `oklch(99% 0.003 255)` |
| base-200 | `oklch(21% 0.008 255)` | `oklch(96.5% 0.004 255)` |
| base-300 | `oklch(26.5% 0.008 255)` | `oklch(92% 0.005 255)` |
| base-content | `oklch(95% 0.004 255)` | `oklch(24% 0.006 255)` |
| primary | `oklch(72% 0.13 175)` | `oklch(55% 0.12 180)` |
| primary-content | `oklch(98% 0.01 175)` | `oklch(98% 0.01 180)` |
| secondary | `oklch(55% 0.006 255)` | `oklch(50% 0.006 255)` |
| accent | `oklch(75% 0.09 75)` | `oklch(68% 0.09 75)` |
| info | `oklch(62% 0.09 240)` | — |
| success | `oklch(62% 0.10 160)` | — |
| warning | `oklch(70% 0.10 75)` | — |
| error | `oklch(60% 0.13 25)` | — |

## Design-system layer (plain CSS, no @apply)

Plain CSS rules after the component styles — Tailwind v4 processes them fine.

### Typography scale

```css
.text-display { font-size: 2.25rem; font-weight: 800; letter-spacing: -0.02em; line-height: 1.15; }
.text-title   { font-size: 1.5rem; font-weight: 700; letter-spacing: -0.01em; line-height: 1.25; }
.text-heading { font-size: 1.125rem; font-weight: 600; line-height: 1.4; }
.text-body    { font-size: 0.875rem; font-weight: 400; line-height: 1.5; }
.text-caption { font-size: 0.75rem; font-weight: 500; line-height: 1.4;
                color: color-mix(in oklch, var(--color-base-content) 55%, transparent); }
```

### Elevation system (theme-adaptive shadows)

```css
:root {
  --shadow-surface-2: 0 1px 2px oklch(0% 0 0 / 0.08);
  --shadow-surface-3: 0 4px 12px oklch(0% 0 0 / 0.12);
}
:root:where([data-theme="dark"]) {
  --shadow-surface-2: 0 1px 3px oklch(0% 0 0 / 0.30);
  --shadow-surface-3: 0 4px 16px oklch(0% 0 0 / 0.40);
}
:root:where([data-theme="light"]) {
  --shadow-surface-2: 0 1px 2px oklch(20% 0.005 255 / 0.08);
  --shadow-surface-3: 0 4px 12px oklch(20% 0.005 255 / 0.12);
}
```

- surface-1: `bg-base-200` + subtle border (no shadow)
- surface-2: `bg-base-100` + border + small shadow
- surface-3: `bg-base-100` + border + deeper shadow

Borders derived from the text color work in both themes:
`border: 1px solid oklch(from var(--color-base-content) l c h / 8%)`.

### Skeleton shimmer + micro-interactions

```css
.skeleton {
  background: linear-gradient(90deg, var(--color-base-300) 0%,
    var(--color-base-200) 50%, var(--color-base-300) 100%);
  background-size: 200% 100%;
  border-radius: var(--radius-field);
  animation: shimmer 1.5s infinite linear;
}
@keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
@media (prefers-reduced-motion: reduce) { .skeleton { animation: none; background-size: 100%; } }

.lift { transition: all 150ms ease; }
.lift:hover { transform: translateY(-0.5px); box-shadow: var(--shadow-surface-3); }
:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
```

## What NOT to break

- `@custom-variant` declarations (`phx-click-loading`, `phx-submit-loading`,
  `phx-change-loading`, `dark`) must stay exactly as shipped.
- `@plugin` imports (`tailwindcss`, `phoenix-colocated`, `heroicons`,
  `daisyui`, `daisyui-theme`) must stay.
- `@source` directives — they tell Tailwind where to scan for class usage.
- The `[data-phx-session]` display rule keeps LiveView wrappers transparent.

## Tailwind v4 config model (if CSS is missing entirely)

Tailwind v4 does NOT use `tailwind.config.js`. Config lives in the CSS via
`@theme {}`:

```css
@import "tailwindcss";
@theme {
  --font-sans: 'Inter', system-ui, sans-serif;
  --color-brand-500: #0ea5e9;
}
```

`@theme` names MUST follow `--{category}-{name}`: `--color-brand-500` →
`bg-brand-500`/`text-brand-500`; `--brand-500` (no `color-`) generates
nothing. Also required: a `config :tailwind` profile in `config/config.exs`,
watchers in `config/dev.exs`, and one initial `mix tailwind default` run to
produce `priv/static/assets/app.css`.

## Verification

`mix assets.build` may fail on unrelated Elixir errors (e.g. Gettext dynamic
msgid) — verify CSS independently:

```bash
mix tailwind default        # runs only the Tailwind compile step → "Done in Xms"
grep -E '(text-display|surface-1|skeleton|shimmer|\.lift|focus-ring)' \
  priv/static/assets/css/app.css
```

For a full asset check (Tailwind v3→v4 migration complete):
`ls apps/MyApp/priv/static/assets/app.css` (non-zero bytes), layout uses
`type="module"` for ESM imports, `Plug.Static` lists the `assets` dir.