# Favicon generation (macOS)

Generate a multi-resolution `favicon.ico` from an SVG source on macOS without ImageMagick.

## Prerequisites

- `sips` — macOS built-in (Scriptable Image Processing System)
- Python 3 — any version with `struct` (stdlib, no extras needed)

## Recipe

### 1. Create the SVG favicon

A 64×64 or larger square SVG. Use the project's existing logo, or create a simplified/icon version.

```bash
# Place it in priv/static/ (Phoenix convention)
cp path/to/logo.svg priv/static/favicon.svg
```

### 2. Convert SVG to PNG at the base size

```bash
sips -s format png priv/static/favicon.svg --out /tmp/favicon_64.png
```

Verify output: `file /tmp/favicon_64.png` should say `PNG image data, 64 x 64, ... RGBA`.

### 3. Resize to target ICO sizes and build the ICO

Standard ICO sizes: 16×16, 32×32, 48×48, 64×64 (some browsers prefer 32×32 for tab icons; 64×64 for high-DPI).

```python
import subprocess, struct, os

base = "/tmp/favicon_64.png"
sizes = [16, 32, 48, 64]
images = []

for size in sizes:
    if size == 64:
        out = base
    else:
        out = f"/tmp/favicon_{size}.png"
        subprocess.run(["sips", "-z", str(size), str(size), base, "--out", out], capture_output=True)
    with open(out, "rb") as f:
        images.append((size, size, f.read()))

def create_ico(images):
    count = len(images)
    header = struct.pack("<HHH", 0, 1, count)  # reserved(0), type(1=ico), count
    entries = []
    pixel_data = b""
    offset = 6 + 16 * count
    for w, h, png in images:
        w_byte = 0 if w >= 256 else w
        h_byte = 0 if h >= 256 else h
        entries.append(struct.pack("<BBBBHHII", w_byte, h_byte, 0, 0, 1, 32, len(png), offset))
        pixel_data += png
        offset += len(png)
    return header + b"".join(entries) + pixel_data

ico = create_ico(images)
with open("priv/static/favicon.ico", "wb") as f:
    f.write(ico)

# Cleanup
for s in sizes:
    p = f"/tmp/favicon_{s}.png"
    if os.path.exists(p) and s != 64:
        os.remove(p)
```

### 4. Register in Phoenix static paths

```elixir
# in lib/app_web.ex
def static_paths, do: ~w(assets fonts images favicon.ico favicon.svg robots.txt)
```

### 5. Add to root layout

```heex
<link rel="icon" type="image/svg+xml" href={~p"/favicon.svg"} />
<link rel="alternate icon" href={~p"/favicon.ico"} sizes="any" />
```

Modern browsers pick the SVG first; `.ico` is fallback for bookmarks and legacy browsers.

## Why not ImageMagick / Pillow / cairosvg?

- ImageMagick (`convert`) is not installed by default on macOS and requires a full brew install.
- Pillow (`PIL`) often has broken native extensions in hermetic Python environments (Hermes venv, Nix shells).
- `cairosvg` requires Cairo + py3cairo — heavy deps for a one-time task.
- `sips` is built into macOS and handles SVG→PNG reliably.
- Python's `struct` module (stdlib) writes the ICO binary format — no extra dependencies.

## If `sips` cannot read the SVG

Some SVG features (CSS in `<style>` tags, external references) confuse `sips`. Workarounds:

1. Use only inline `fill="..."` `stroke="..."` attributes — no `<style>` blocks.
2. Keep gradients/defs simple — complex `radialGradient` with multiple stops may flatten to wrong colors.
3. Convert via the browser instead: open the SVG in Safari, Cmd+Opt+I to open DevTools, take a screenshot of just the element, crop to exact size.
4. Fall back to macOS `qlmanage -t -s <size> -o /tmp favicon.svg` (QuickLook thumbnail generator — works on more SVG variants than `sips`).
