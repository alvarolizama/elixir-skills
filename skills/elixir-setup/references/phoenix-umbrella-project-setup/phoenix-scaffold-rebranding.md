# Phoenix Scaffold Rebranding Checklist

When a Phoenix project is generated with `mix phx.new`, it ships with
Phoenix Framework branding across **four** files. Every new project needs
all four updated before it can ship as a real product.

## Files to rebrand

### 1. `priv/static/images/logo.svg`

The default logo is the Phoenix bird (a complex multi-path SVG in
`#FD4F00` orange). Replace it entirely with a custom SVG logo for the
project.

Design tips:
- Keep `viewBox` small (e.g. `0 0 64 64`) for crisp scaling at navbar size
- Use `<defs><linearGradient>` for a modern gradient look
- Keep `fill="none"` on the root `<svg>` and apply colors per-element
- The logo is referenced in `layouts.ex` at width 32–36px — test at that size
- Set `aria-hidden="true"` if the brand name is visible as text next to it

### 2. `lib/<app>_web/controllers/page_html/home.html.heex`

The default home page is a Phoenix demo with:
- The Phoenix bird SVG inline
- "Phoenix Framework" heading + version badge
- "Peace of mind from prototype to production" headline
- Links to Phoenix docs, GitHub, changelog, Elixir Forum, Discord, Slack, Fly.io
- A large background SVG with Phoenix brand colors (#EE7868, #FF9F92, etc.)

Replace with a real product landing page. Structure that works well:

```
- Brand header (logo + product name)
- Hero section (headline, subheadline, CTAs)
- Feature cards (3-column grid with icons)
- Footer (version + theme toggle)
```

Use `<.link href={~p"/login"}>` for the primary CTA (not raw `<a href>`).
Use `<.icon name="hero-..." />` for feature card icons (never Heroicons modules).
Background gradient orbs (`bg-primary/10 blur-3xl`) look better than the
Phoenix SVG mess and are 2 lines of code.

### 3. `lib/<app>_web/components/layouts/root.html.heex`

The `<.live_title>` has `suffix=" · Phoenix Framework"`. Change to the
project's tagline, e.g. `suffix=" · LLM Gateway"`.

Also check: the default title is `MyApp` (lowercase t) — fix casing
to match the brand: `MyApp`.

### 4. `lib/<app>_web/components/layouts.ex` — `app/1` function

The `app/1` function component renders the navbar for non-dashboard pages.
The scaffold ships:

```heex
<a href="https://phoenixframework.org/" class="btn btn-ghost">Website</a>
<a href="https://github.com/phoenixframework/phoenix" class="btn btn-ghost">GitHub</a>
<a href="https://phoenix.hexdocs.pm/overview.html" class="btn btn-primary">Get Started</a>
```

Replace with app-specific links. Minimal clean navbar:

```heex
<header class="navbar px-4 sm:px-6 lg:px-8">
  <div class="flex-1">
    <a href="/" class="flex-1 flex w-fit items-center gap-2">
      <img src={~p"/images/logo.svg"} width="36" alt="ProductName" />
      <span class="text-lg font-bold">ProductName</span>
    </a>
  </div>
  <div class="flex-none">
    <ul class="flex flex-column px-1 space-x-4 items-center">
      <li><.theme_toggle /></li>
      <li>
        <.link href={~p"/login"} class="btn btn-primary gap-2">
          Iniciar sesión <span aria-hidden="true">&rarr;</span>
        </.link>
      </li>
    </ul>
  </div>
</header>
```

Key changes from scaffold:
- Logo `<img>` gets an `alt` attribute
- Version badge (`v{Application.spec(:phoenix, :vsn)}`) → product name
- Phoenix links → app-specific CTA (login)
- Use `<.link>` not raw `<a>` for internal routes

## Also check (dashboard layout)

If the project has a `dashboard/1` layout function (sidebar + topbar),
check its sidebar for the same logo reference. The sidebar typically
already has the product name in a `<span>` — just verify the logo path
points to the new SVG.

## README.md

The scaffold does not generate a README.md with real content (just a
placeholder). Create one with:

- Project name + one-line description
- Stack (Elixir, Phoenix, Postgres, Oban, etc.)
- Features list (grouped by domain)
- Quick start (`mix setup`, `mix phx.server`)
- Default credentials (from `seeds.exs`)
- API usage example (if applicable)
- Project structure tree
- Useful commands
- Deploy notes

## Verification

```bash
# Compile clean
mix compile --warnings-as-errors

# Visual check — load the home page and verify:
# 1. No "Phoenix Framework" text anywhere
# 2. No Phoenix bird logo
# 3. No links to phoenixframework.org / github.com/phoenixframework
# 4. Title bar shows product name, not "Phoenix Framework"
# 5. Logo renders at navbar size
```

## MyApp example (2026-07-26)

- Logo: portal/gate concept with gradient índigo→violeta, hexagonal token
- Home: hero + 3 feature cards (Proxy compatible, Presupuestos, Multi-proveedor)
- Title suffix: " · LLM Gateway"
- Navbar: logo + "MyApp" + theme toggle + "Iniciar sesión"
- README: full project docs with stack, features, proxy usage example
