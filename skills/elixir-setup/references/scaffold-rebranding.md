# Scaffold rebranding (Phoenix default branding removal)

`mix phx.new` ships Phoenix Framework branding in FOUR files. Every new
project needs all four updated before it can ship as a real product.

## Files to rebrand

### 1. `priv/static/images/logo.svg`

The default is the Phoenix bird (multi-path SVG in `#FD4F00`). Replace with a
custom SVG logo. Tips: keep `viewBox` small (e.g. `0 0 64 64`) for crisp
scaling at navbar size; use `<defs><linearGradient>` for a modern look; keep
`fill="none"` on the root `<svg>` and color per element; the logo renders at
32–36px in `layouts.ex` — test at that size; set `aria-hidden="true"` when
the brand name is visible as text next to it.

### 2. `lib/<app>_web/controllers/page_html/home.html.heex`

The default home is a Phoenix demo (bird SVG, "Phoenix Framework" heading +
version badge, links to Phoenix docs/GitHub/Forum/Discord/Slack/Fly.io,
brand-colored background SVG). Replace with a real landing:
brand header (logo + name), hero (headline, subheadline, CTAs), feature cards
(3-column grid with icons), footer (version + theme toggle). Use
`<.link href={~p"/login"}>` for the primary CTA (not raw `<a>`), `<.icon
name="hero-..." />` for icons (never Heroicons modules), and gradient orbs
(`bg-primary/10 blur-3xl`) instead of the Phoenix background SVG.

### 3. `lib/<app>_web/components/layouts/root.html.heex`

`<.live_title>` ships `suffix=" · Phoenix Framework"` — change to the
product tagline. The scaffold default title is `MyApp` (lowercase `t`) —
fix casing to the brand (`MyApp`).

### 4. `lib/<app>_web/components/layouts.ex` — `app/1` function

The scaffold navbar ships three Phoenix links (Website / GitHub /
Get Started). Replace with app-specific links:

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
          Sign in <span aria-hidden="true">&rarr;</span>
        </.link>
      </li>
    </ul>
  </div>
</header>
```

Key changes vs scaffold: logo `<img>` gets an `alt`; the version badge
(`v{Application.spec(:phoenix, :vsn)}`) becomes the product name; Phoenix
links become an app CTA; use `<.link>` for internal routes.

Also check the `dashboard/1` layout (sidebar) for the same logo reference.

## README.md

The scaffold generates only a placeholder. Create one with: name +
one-line description, stack (Elixir, Phoenix, Postgres, Oban...), features
grouped by domain, quick start (`mix setup`, `mix phx.server`), default
credentials (from `seeds.exs`), API usage example, project structure tree,
useful commands, deploy notes.

## Favicon (macOS, no ImageMagick)

```bash
# 1. SVG source in priv/static (project convention)
cp path/to/logo.svg priv/static/favicon.svg

# 2. SVG → PNG at base size
sips -s format png priv/static/favicon.svg --out /tmp/favicon_64.png
file /tmp/favicon_64.png     # PNG image data, 64 x 64, ... RGBA

# 3. Resize to 16/32/48 and pack into a multi-resolution .ico with stdlib Python
python3 - <<'PY'
import subprocess, struct, os
base = "/tmp/favicon_64.png"
sizes = [16, 32, 48, 64]
images = []
for size in sizes:
    if size != 64:
        out = f"/tmp/favicon_{size}.png"
        subprocess.run(["sips", "-z", str(size), str(size), base, "--out", out], capture_output=True)
    else:
        out = base
    with open(out, "rb") as f:
        images.append((size, size, f.read()))
count = len(images)
header = struct.pack("<HHH", 0, 1, count)
entries, pixel_data, offset = [], b"", 6 + 16 * count
for w, h, png in images:
    w_byte, h_byte = (0 if w >= 256 else w), (0 if h >= 256 else h)
    entries.append(struct.pack("<BBBBHHII", w_byte, h_byte, 0, 0, 1, 32, len(png), offset))
    pixel_data += png
    offset += len(png)
with open("priv/static/favicon.ico", "wb") as f:
    f.write(header + b"".join(entries) + pixel_data)
PY

# 4. Register in static paths (lib/<app>_web.ex)
def static_paths, do: ~w(assets fonts images favicon.ico favicon.svg robots.txt)

# 5. Root layout links — browsers prefer SVG, .ico as fallback
<link rel="icon" type="image/svg+xml" href={~p"/favicon.svg"} />
<link rel="alternate icon" href={~p"/favicon.ico"} sizes="any" />
```

Why not ImageMagick/Pillow/cairosvg: `convert` needs a full brew install;
Pillow often has broken native extensions in hermetic Python environments;
cairosvg drags Cairo + py3cairo. `sips` is built into macOS.

**If `sips` cannot read the SVG** (CSS in `<style>` tags, external refs):
use only inline `fill=`/`stroke=` attributes (no `<style>`); keep
gradients/defs simple; or fall back to `qlmanage -t -s <size> -o /tmp
favicon.svg` (QuickLook thumbnail generator — handles more SVG variants).

## Gitignore static assets

```
/apps/*/assets/node_modules/
/apps/*/priv/static/assets/
```

## Verification

```bash
mix compile --warnings-as-errors
grep -rni 'phoenix framework\|phoenixframework' lib/ priv/  # must be empty
file priv/static/favicon.ico                                # MS Windows icon resource
```

Visual check of the home page: no "Phoenix Framework" text, no bird logo, no
links to phoenixframework.org / github.com/phoenixframework, title bar shows
the product name, logo renders at navbar size.