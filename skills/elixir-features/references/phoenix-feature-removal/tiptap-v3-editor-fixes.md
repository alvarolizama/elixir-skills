# TipTap v3 Editor Fixes (my_app)

Session-specific reference for debugging and fixing the TipTap v3 markdown
editor in my_app (`assets/js/hooks/markdown_editor.js`). TipTap v3 changed
several APIs from v2 — code written against v2 silently breaks.

## API changes that broke things

### `editor.storage.markdown` → `editor.markdown`

**v2 (broken):**
```js
const md = this.editor.storage.markdown?.getMarkdown() || this.editor.getHTML()
const parsed = this.editor.storage.markdown.parser.parse(md)
```

**v3 (working):**
```js
const md = this.editor.getMarkdown()  // public method on editor
const json = this.editor.markdown?.parse(md)  // markdown manager on editor.markdown
if (json) {
  this.editor.commands.setContent(json, { emitUpdate: false })
} else {
  this.editor.commands.setContent(md)  // fallback: plain text
}
```

The `@tiptap/markdown` extension in v3 sets `editor.markdown` (a
`MarkdownManager` instance) and `editor.getMarkdown()` directly on the
editor. The old `editor.storage.markdown` storage object no longer exists.

### `getMarkdown` existence check

The old code used `this.editor.getMarkdown ? this.editor.getMarkdown() : ""`
as a ternary. In v3, `editor.getMarkdown` always exists (the Markdown
extension defines it), so this works but is unnecessary — just call
`this.editor.getMarkdown()` directly.

## Heroicon name verification

TipTap toolbar buttons use `hero-<icon-name>` classes. The icon names must
match actual SVG filenames in `deps/heroicons/optimized/24/outline/`.

**Broken names found and fixed:**

| Wrong | Correct | Notes |
|-------|---------|-------|
| `hero-table` | `hero-table-cells` | Table icon doesn't exist as `hero-table` |
| `hero-list-bullet` (for orderedList) | `hero-numbered-list` | Was using same icon as bulletList |

**Verification command:**
```bash
ls deps/heroicons/optimized/24/outline/ | grep -i <keyword>
```

## Custom CodeBlock NodeView for mermaid preview

To render mermaid diagrams inline in the editor (code on top, SVG preview
below), create a custom NodeView that intercepts `codeBlock` nodes with
`language: "mermaid"`:

### Architecture

1. **Disable StarterKit's codeBlock**: `StarterKit.configure({ codeBlock: false })`
2. **Extend CodeBlock with custom NodeView**: `CodeBlock.extend({ addNodeView() { return mermaidNodeView(this.editor) } })`
3. **NodeView factory** returns different rendering based on `node.attrs.language`:
   - `mermaid` → `<div class="mermaid-codeblock"><pre><code>code</code></pre><div class="mermaid-preview">SVG</div></div>`
   - Other → standard `<pre><code>` (ProseMirror manages content)

### Key implementation details

- **`contentDOM`**: for mermaid blocks, set `contentDOM: code` so ProseMirror
  manages the text content natively. Don't manually sync textContent with
  `editor.view.dispatch(tr)` — that's fragile and causes cursor jumps.
- **MutationObserver**: observe the `code` element for content changes to
  trigger debounced (400ms) mermaid re-renders. ProseMirror updates
  `contentDOM` directly, so the observer catches edits.
- **`ignoreMutation`**: return `true` for mutations on the preview div so
  ProseMirror doesn't try to reconcile SVG changes.
- **Stale render guard**: use a counter (`renderCounter++`) to cancel
  superseded renders — mermaid CDN load is async.
- **Mermaid CDN**: load lazily from
  `https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js`. Cache the
  promise so it only loads once.
- **Non-mermaid fallback**: the NodeView factory must return a valid
  NodeView object for ALL code blocks, not just mermaid. For non-mermaid,
  return `{ dom: pre, contentDOM: code }` — a simple `<pre><code>` structure
  that ProseMirror manages natively.

### CSS needed

```css
.mermaid-codeblock { border, border-radius, overflow: hidden }
.mermaid-code-input { dark background, monospace, code editor style }
.mermaid-preview { centered, scrollable, SVG max-width 100% }
.mermaid-preview-error { error color }
.mermaid-preview-empty { italic placeholder }
```

### Markdown round-trip

The `@tiptap/markdown` extension handles serialization automatically — a
`codeBlock` with `language: "mermaid"` serializes to ` ```mermaid\n...\n``` `
in markdown. No custom serialization needed.

### Testing approach

Use `browser_console` to verify the NodeView works:

```js
// Insert mermaid via toolbar command
document.querySelector('[data-cmd="mermaid"]').click()

// Wait 2s for CDN load + render, then check DOM
setTimeout(() => {
  const block = document.querySelector('.mermaid-codeblock')
  const svg = document.querySelector('.mermaid-preview svg')
  // Both should exist
}, 2000)

// Test edit → preview update
const code = document.querySelector('.mermaid-code-input code')
code.textContent = code.textContent.replace('graph TD', 'graph LR')
code.dispatchEvent(new Event('input', {bubbles: true}))
// Wait 600ms (400ms debounce + 200ms render), check SVG viewBox changed
```

### Pitfall: returning null from NodeView factory

In TipTap v3, `addNodeView` must return a function that returns a NodeView
object for EVERY node of that type. Returning `null` for non-mermaid blocks
does NOT fall back to default rendering — ProseMirror doesn't know what to
do. The factory must handle both cases and return a valid `{ dom, contentDOM }`
for non-mermaid code blocks too.
