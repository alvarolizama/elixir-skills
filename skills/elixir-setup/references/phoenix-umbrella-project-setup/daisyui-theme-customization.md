# daisyUI Theme Customization & CSS Design System (Tailwind v4)

How to customize daisyUI themes and add a design system layer to a Phoenix
project's `assets/css/app.css` — without touching `.ex`, `.heex`, `.js`, or
config files.

## daisyUI theme block structure

daisyUI themes are defined in `@plugin "../vendor/daisyui-theme" { ... }` blocks.
Each block is a complete theme: name, color-scheme, and CSS custom properties
for every daisyUI color token. Two blocks ship by default: `dark` and `light`.

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

- **Theme names must match exactly** — `"dark"` and `"light"` are referenced by
  `@custom-variant dark (&:where([data-theme=dark], [data-theme=dark] *))` and
  by the theme toggle in `app.js`. Do not rename them.
- **All color values use oklch** — `oklch(L% C H)` where L is lightness (0-100),
  C is chroma (0-0.4+), H is hue angle (0-360).
- **`--color-*-content` is the foreground color** paired with each background
  color. Ensure sufficient contrast (WCAG AA 4.5:1).
- **`--border: 1px`** (not `1.5px`) for a more refined, Linear/Notion-like look.
- **`--radius-box: 0.625rem`**, `--radius-field: 0.375rem`,
  `--radius-selector: 0.375rem` for slightly larger, softer corners.

## Linear/Notion-style palette (oklch values)

### Dark theme

| Token | Value | Description |
|-------|-------|-------------|
| base-100 | `oklch(17.5% 0.008 255)` | Gris-azulado muy oscuro |
| base-200 | `oklch(21% 0.008 255)` | Un escalón más claro |
| base-300 | `oklch(26.5% 0.008 255)` | Dos escalones más claro |
| base-content | `oklch(95% 0.004 255)` | Texto casi blanco con tinte frío |
| primary | `oklch(72% 0.13 175)` | Teal / verde-azulado sobrio |
| primary-content | `oklch(98% 0.01 175)` | Blanco con tinte teal |
| secondary | `oklch(55% 0.006 255)` | Gris neutro |
| accent | `oklch(75% 0.09 75)` | Ámbar discreto |
| info | `oklch(62% 0.09 240)` | Azul sobrio |
| success | `oklch(62% 0.10 160)` | Verde sobrio |
| warning | `oklch(70% 0.10 75)` | Ámbar |
| error | `oklch(60% 0.13 25)` | Rojo sobrio |

### Light theme

| Token | Value | Description |
|-------|-------|-------------|
| base-100 | `oklch(99% 0.003 255)` | Casi blanco con tinte frío |
| base-200 | `oklch(96.5% 0.004 255)` | Gris muy claro |
| base-300 | `oklch(92% 0.005 255)` | Gris claro |
| base-content | `oklch(24% 0.006 255)` | Texto oscuro con tinte frío |
| primary | `oklch(55% 0.12 180)` | Teal más oscuro para contraste |
| primary-content | `oklch(98% 0.01 180)` | Blanco con tinte teal |
| secondary | `oklch(50% 0.006 255)` | Gris neutro |
| accent | `oklch(68% 0.09 75)` | Ámbar discreto |

### Design principles

- **Hue consistency:** all base colors use hue ~255 (blue-gray) with very low
  chroma (~0.008). This creates a neutral, cool-toned background.
- **Primary teal:** hue ~175-180 (teal/cyan-green). Use L=72% in dark, L=55%
  in light for contrast. Chroma ~0.12-0.13 — saturated enough to be
  distinctive, not neon.
- **Semantic colors:** chroma ~0.09-0.13 (not the default 0.15-0.25). This
  makes info/success/warning/error feel harmonized rather than jarring.
- **Accent:** use the same hue family as warning (amber, hue ~75) but lower
  chroma. This keeps the palette to two color families: cool blue-gray + teal,
  with warm amber as a discrete accent.

## CSS utility classes (plain CSS, no @apply)

Add these after the existing component styles in `app.css`. Tailwind v4
processes them fine as plain CSS rules.

### Typography scale

```css
.text-display {
  font-size: 2.25rem;
  font-weight: 800;
  letter-spacing: -0.02em;
  line-height: 1.15;
}
.text-title {
  font-size: 1.5rem;
  font-weight: 700;
  letter-spacing: -0.01em;
  line-height: 1.25;
}
.text-heading {
  font-size: 1.125rem;
  font-weight: 600;
  line-height: 1.4;
}
.text-body {
  font-size: 0.875rem;
  font-weight: 400;
  line-height: 1.5;
}
.text-caption {
  font-size: 0.75rem;
  font-weight: 500;
  line-height: 1.4;
  color: color-mix(in oklch, var(--color-base-content) 55%, transparent);
}
```

### Elevation system

Use CSS variables for shadows so they adapt per theme:

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

- **surface-1:** `bg-base-200` + subtle border (no shadow)
- **surface-2:** `bg-base-100` + border + small shadow (1px blur)
- **surface-3:** `bg-base-100` + border + deeper shadow (4px+12px)

Border uses `oklch(from var(--color-base-content) l c h / 8%)` — derived
from the text color so it works in both themes automatically.

### Skeleton loading with shimmer

```css
.skeleton {
  background: linear-gradient(90deg,
    var(--color-base-300) 0%,
    var(--color-base-200) 50%,
    var(--color-base-300) 100%);
  background-size: 200% 100%;
  border-radius: var(--radius-field);
  animation: shimmer 1.5s infinite linear;
}
@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
@media (prefers-reduced-motion: reduce) {
  .skeleton { animation: none; background-size: 100%; }
}
```

### Micro-interactions

```css
.lift {
  transition: all 150ms ease;
}
.lift:hover {
  transform: translateY(-0.5px);
  box-shadow: var(--shadow-surface-3);
}
.focus-ring:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}
:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}
```

## What NOT to break

- **TipTap editor styles** (`.md-editor`, `.tiptap`, `.editor-toolbar`,
  `.tb-btn`, `.wikilink`, `.embed-placeholder`) — leave these untouched.
- **`@custom-variant` declarations** — `phx-click-loading`, `phx-submit-loading`,
  `phx-change-loading`, and `dark` must remain exactly as they are.
- **`@plugin` imports** — `tailwindcss`, `phoenix-colocated`, `heroicons`,
  `daisyui`, `daisyui-theme` plugin blocks must stay.
- **`@source` directives** — these tell Tailwind where to scan for class usage.
- **`[data-phx-session]` display rule** — keeps LiveView wrappers transparent.

## Verification

When `mix assets.build` fails due to unrelated `.ex` compilation errors (e.g.,
Gettext dynamic msgid), verify CSS independently:

```bash
mix tailwind default
```

This runs only the Tailwind compilation step. If it outputs "Done in Xms"
without errors, the CSS is valid. Check for the new classes in the output:

```bash
grep -E '(text-display|surface-1|skeleton|shimmer|\.lift|focus-ring)' \
  priv/static/assets/css/app.css
```
