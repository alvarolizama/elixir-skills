# Integrating JS rendering libraries into the TipTap markdown editor

Pattern for adding client-side rendered content (Mermaid diagrams, MathJax,
syntax highlighters, etc.) to a Phoenix LiveView markdown editor that uses
TipTap + MDEx.

## Architecture overview

The my_app editor has two rendering surfaces:

| Surface | File(s) | What happens |
|---|---|---|
| **Edit mode** | `markdown_editor.js` (TipTap hook) + `markdown_editor_components.ex` (HEEx toolbar) | User writes markdown in a TipTap editor with a toolbar |
| **Read mode** | `page_components.ex` (`render_markdown/2` via MDEx) + HEEx template | MDEx converts markdown to HTML, post-processed for embeds/wikilinks |

A JS rendering library needs to hook into BOTH:

1. **Edit mode:** toolbar button + TipTap command to insert a fenced code block with the right language tag (e.g. `language-mermaid`)
2. **Read mode:** a LiveView hook that scans the rendered HTML for `code.language-X` blocks, lazy-loads the JS library from CDN, and replaces them with rendered output (SVG, MathML, highlighted HTML)

## The 5-file integration pattern

### 1. JS hook (`assets/js/hooks/<name>.js`)

Creates a LiveView hook that:
- Scans `this.el` for `code.language-X` blocks on `mounted()` and `updated()`
- Lazy-loads the library from CDN only when blocks exist (keeps bundle small)
- Initializes with theme awareness (check `data-theme` attribute on `<html>`)
- Renders each block, replacing the `<pre><code>` with the rendered output
- Handles errors inline (show the broken source + error message)

Key implementation details:
- **CDN lazy-load:** create a `<script>` tag, resolve a Promise on `onload`.
  Cache on `window` so subsequent navigations don't re-download.
- **Debounce:** use `setTimeout` (50ms) before processing — MDEx HTML may
  arrive via LiveView diff and the DOM needs a tick to settle.
- **Dedup:** mark processed blocks with `dataset.mermaidDone = "true"` to
  avoid re-rendering on `updated()` when LiveView re-patches the container.
- **Unique IDs:** each rendered diagram needs a unique DOM id for the library's
  render function (e.g. `mermaid-${Date.now()}-${i}`).
- **Theme:** read `document.documentElement.getAttribute("data-theme")` —
  the root layout sets this via an inline script before the app loads.

### 2. Hook registration (`assets/js/app.js`)

```js
import Mermaid from "./hooks/mermaid.js"

// In the LiveSocket hooks object:
hooks: {...colocatedHooks, GraphPanZoom, MarkdownEditor, Mermaid, Graph3D, ...}
```

### 3. Toolbar button (`markdown_editor_components.ex`)

Add a button to the `editor_toolbar/1` private component:

```heex
<.tb_btn id={@id} cmd="mermaid" icon="hero-chart-square-bar" label="" />
```

Place it after the table button, with its own separator.

### 4. Editor command (`markdown_editor.js`)

Add a `case` clause to `runCommand(cmd)`:

```js
case "mermaid": {
  const stub = "graph TD\n    A[Start] --> B{Decision}\n    B -->|Yes| C[Action 1]\n    B -->|No| D[Action 2]\n    C --> E[End]\n    D --> E"
  chain.insertContent({
    type: "codeBlock",
    attrs: { language: "mermaid" },
    content: [{ type: "text", text: stub }],
  }).run()
  break
}
```

The stub gives the user a visible starting point — they edit it immediately.

### 5. Read-mode hook attachment (`page_components.ex`)

Attach the hook to the content panel container:

```heex
<div id="detail-panel-content" data-detail-panel class="space-y-6" phx-hook="Mermaid">
```

This is the panel that holds `{@rendered_body}` — MDEx output. The hook
scans it on mount and on every LiveView update.

### 6. CSS styles (`app.css`)

```css
.mermaid-rendered {
  display: flex;
  justify-content: center;
  margin: 1.5rem 0;
  padding: 1.5rem;
  background: oklch(from var(--color-base-200) l c h / 50%);
  border: 1px solid var(--color-base-300);
  border-radius: 0.5rem;
  overflow-x: auto;  /* horizontal scroll for wide diagrams */
}

.mermaid-rendered svg {
  max-width: 100%;
  height: auto;
}

.mermaid-error {
  margin: 1rem 0;
  padding: 1rem;
  border: 1px solid var(--color-error);
  border-radius: 0.5rem;
  background: oklch(from var(--color-error) l c h / 10%);
  color: var(--color-error);
  font-size: 0.875rem;
}
```

## MDEx compatibility

MDEx renders fenced code blocks as `<pre><code class="language-mermaid">`.
The sanitizer config (`@markdown_options` in `page_components.ex`) uses
`render: [unsafe: false]` + `sanitize: [...]` — standard `<pre>` and
`<code>` tags with `class` attributes pass through without needing
explicit sanitizer additions.

No changes to `@markdown_options` are needed for Mermaid support.

## CDN vs bundle trade-off

Mermaid is ~2.5MB minified. Loading from CDN via a lazy `<script>` tag:

- **Pro:** zero impact on the app JS bundle (esbuild), loads only when a page
  has Mermaid blocks
- **Pro:** CDN cached across page navigations and even across my_app instances
- **Con:** requires internet access (offline mode won't render diagrams)
- **Con:** one-time ~1s delay on first diagram render (library download)

For my_app (a personal knowledge app always connected to a server), this is
the right trade-off. If offline support were needed, install mermaid as an
npm dep and import it in the hook.

## Verification checklist

```bash
# 1. JS syntax valid
node --check --input-type=module < assets/js/hooks/mermaid.js
node --check --input-type=module < assets/js/app.js

# 2. Elixir compiles clean
mix compile --warnings-as-errors

# 3. Assets bundle
mix assets.build

# 4. Test suite
mix test
```

## Editor width: removing max-width constraint

The TipTap editor's `.tiptap` CSS class had `max-width: 65ch` (a typography
best practice for reading). Removing it lets the editor use the full width
of its container. The container already has `max-w-none` in the HEEx
component, but the `.tiptap` CSS rule overrides it.

```css
/* Before */
.tiptap {
  min-height: 300px;
  max-width: 65ch;    /* ← remove this line */
  outline: none;
  ...
}
```

The `65ch` unit = 65 characters of the current font's "0" glyph. It's a
legibility guideline, not a hard limit — content isn't truncated, lines
just wrap. Users who want full-width editing prefer it removed.

## Generalizing to other libraries

The same pattern works for:
- **MathJax/KaTeX:** scan `code.language-latex` or `.math` blocks
- **Syntax highlighters:** scan `code.language-*` and apply highlighting
- **PlantUML:** scan `code.language-plantuml`, render via server or CDN
- **Vega-Lite:** scan `code.language-vega`, render charts

Each needs its own hook with the library-specific render call, but the
5-file structure (hook JS, app.js registration, toolbar button, editor
command, read-mode attachment + CSS) is identical.
