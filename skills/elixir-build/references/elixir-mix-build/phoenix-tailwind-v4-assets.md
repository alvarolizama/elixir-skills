# Phoenix Tailwind v4 Asset Setup

When CSS doesn't load in a Phoenix app, the root cause is usually a Tailwind v3→v4 migration gap or missing asset pipeline. The `tailwind` hex package ≥0.3 ships Tailwind CLI v4, which has a fundamentally different config model.

## Symptom

Browser loads the page but CSS is unstyled. `/assets/app.css` returns 404 or empty. No `priv/static/assets/` directory exists.

## Root causes (check all)

### 1. Tailwind v4 config mismatch

Tailwind v4 does NOT use `tailwind.config.js`. Configuration lives in the CSS file itself via `@theme {}`.

**v3 (wrong for v4):**
```js
// tailwind.config.js — DELETE THIS when using tailwind hex ≥0.3
module.exports = {
  content: ["./js/**/*.js", "../lib/**/*.{ex,heex}"],
  theme: { extend: { colors: { brand: { 500: '#0ea5e9' } } } },
  plugins: [require('@tailwindcss/forms')]
}
```

**v4 (correct):**
```css
/* assets/css/app.css */
@import "tailwindcss";

@theme {
  --font-sans: 'Inter', system-ui, sans-serif;
  --color-brand-500: #0ea5e9;
  /* all custom colors, fonts, spacing go here as CSS custom properties */
}
```

### 2. No tailwind profiles in config/config.exs

```elixir
# config/config.exs — REQUIRED for mix tailwind to work
config :tailwind,
  version: "4.3.0",  # check with: ls _build/tailwind-*
  default: [
    args: ~w(--input=css/app.css --output=../priv/static/assets/app.css),
    cd: Path.expand("../apps/MyApp/assets", __DIR__)
  ]
```

### 3. No watchers in config/dev.exs

```elixir
# config/dev.exs — without watchers, CSS won't recompile on change
config :MyApp, MyAppWeb.Endpoint,
  # ...other config...
  watchers: [
    tailwind: {Tailwind, :install_and_run, [:default, ~w(--watch)]}
  ]
```

### 4. No initial CSS compilation

Even with profiles configured, `priv/static/assets/` must exist with compiled CSS. Run once:

```bash
mix tailwind default
```

This creates `priv/static/assets/app.css`. The watcher handles updates after that.

### 5. JS imports without npm/esbuild

When there's no `package.json` or esbuild, `app.js` can't resolve `import {Socket} from "phoenix"`. For dev without npm:

1. Copy pre-built JS from deps to priv/static/assets:
```bash
cp deps/phoenix/priv/static/phoenix.mjs apps/MyApp/priv/static/assets/phoenix.mjs
cp deps/phoenix_live_view/priv/static/phoenix_live_view.esm.js apps/MyApp/priv/static/assets/phoenix_live_view.esm.js
```

2. Use absolute path imports in app.js:
```js
import {Socket} from "/assets/phoenix.mjs"
import {LiveSocket} from "/assets/phoenix_live_view.esm.js"
```

3. Copy app.js to priv/static/assets:
```bash
cp apps/MyApp/assets/js/app.js apps/MyApp/priv/static/assets/app.js
```

4. Use `type="module"` in the layout (ESM imports require it):
```html
<!-- WRONG — ESM imports won't resolve -->
<script defer src="/assets/app.js"></script>

<!-- RIGHT -->
<script type="module" src="/assets/app.js"></script>
```

## Verification checklist

```bash
# 1. Tailwind binary is downloaded
ls _build/tailwind-macos-*

# 2. CSS compiles
mix tailwind default
ls -la apps/MyApp/priv/static/assets/app.css  # should be >0 bytes

# 3. JS files exist
ls apps/MyApp/priv/static/assets/{app.js,phoenix.mjs,phoenix_live_view.esm.js}

# 4. Plug.Static serves the assets directory
# endpoint.ex should have:
# plug Plug.Static, at: "/", from: :MyApp, only: ~w(assets fonts images favicon.ico robots.txt)

# 5. Layout uses type="module"
grep 'type="module"' apps/MyApp/lib/my_app_web/layouts/root.html.heex
```

## Pitfall: `@theme` custom properties naming

Tailwind v4 `@theme` uses CSS custom property names that map to utility classes:
- `--color-brand-500` → `bg-brand-500`, `text-brand-500`
- `--font-sans` → `font-sans`
- `--spacing-*` → spacing utilities

The naming MUST follow the `--{category}-{name}` pattern. `--brand-500` (without `color-`) won't generate `bg-brand-500`.