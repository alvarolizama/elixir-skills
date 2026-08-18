# TipTap v3 Editor: API Migrations and Custom NodeView Patterns

Verified against my_app's TipTap editor (assets/js/hooks/markdown_editor.js +
mermaid_codeblock.js), Jul 2026. Use when upgrading TipTap editor hooks,
fixing broken toolbar commands, or adding custom NodeViews.

## TipTap v3 breaking API changes (from v2)

| v2 API (broken) | v3 API (correct) | Notes |
|---|---|---|
| `editor.storage.markdown?.getMarkdown()` | `editor.getMarkdown()` | v3 moves the markdown serializer to a top-level method on the editor. `storage.markdown` no longer exists as a property with `getMarkdown()`. |
| `editor.storage.markdown.parser.parse(md)` | `editor.markdown.parse(md)` | The parser is now `editor.markdown` (a `MarkdownManager` instance), not `editor.storage.markdown.parser`. Returns JSON (ProseMirror node), not HTML. |
| `editor.commands.setContent(md)` with string | `editor.commands.setContent(editor.markdown.parse(md))` | In v3, `setContent` with a raw string inserts it as text. To parse markdown into ProseMirror JSON, use `editor.markdown.parse(md)` first, then pass the JSON to `setContent`. |

**Diagnostic:** if `toggleMode` (WYSIWYG ↔ raw markdown) silently does nothing,
check that `getMarkdown()` is called without `storage.markdown` in the chain.
The old `parseMarkdown()` helper method that wrapped `editor.storage.markdown.parser`
should be deleted entirely — inline the `editor.markdown.parse(md)` call.

## Heroicons: names that don't exist

Phoenix's heroicons plugin reads SVG filenames from `deps/heroicons/optimized/24/outline/`.
If you pass `hero-<name>` to the `<.icon>` component and the SVG file doesn't exist,
the icon renders as an **empty span** — no error, no warning. Common gotchas:

| Wrong name | Correct name | Exists |
|---|---|---|
| `hero-table` | `hero-table-cells` | ✅ `table-cells.svg` |
| `hero-list-bullet` (for ordered lists) | `hero-numbered-list` | ✅ `numbered-list.svg` — `list-bullet` exists too but is for bullet lists |

**Verification:** `ls deps/heroicons/optimized/24/outline/ | grep <keyword>`
before using a heroicon name for the first time.

## Custom NodeView for CodeBlock (mermaid preview pattern)

To render a live preview below a code block (e.g. mermaid SVG), extend the
CodeBlock extension with a custom `addNodeView`. The NodeView intercepts every
codeBlock node and decides how to render it.

### Key structural pattern

```js
import CodeBlock from "@tiptap/extension-code-block"

// In the Editor config:
StarterKit.configure({ codeBlock: false }),  // disable default codeBlock
CodeBlock.extend({
  addNodeView() {
    return mermaidNodeView(this.editor)
  },
}),
```

The `mermaidNodeView` factory returns a function `({ node, getPos, HTMLAttributes }) => NodeView | null`:
- For `node.attrs.language === "mermaid"`: return a custom NodeView with code + preview DOM.
- For other languages: return a standard `<pre><code>` NodeView (ProseMirror manages content).

### Critical implementation details

1. **`contentDOM` must point to the `<code>` element**, not the `<pre>`. ProseMirror
   manages text inside `contentDOM` — if you point it to `<pre>`, the cursor lands
   outside the `<code>` tag and markdown serialization breaks.

2. **`MutationObserver` for live preview updates.** ProseMirror updates `contentDOM`
   in place (it doesn't recreate it). A `MutationObserver` on the `<code>` element
   detects content changes and triggers a debounced re-render of the preview.

3. **`ignoreMutation` must return `true` for mutations in the preview div.**
   Otherwise ProseMirror sees the SVG insertion as a DOM change it didn't make
   and tries to reconcile, causing cursor jumps or lost edits.

4. **`update(updatedNode)` must check `updatedNode.attrs.language`.** If the
   language changes from mermaid to something else (or vice versa), the NodeView
   returns `false` so ProseMirror destroys and recreates it with the right view.

5. **Mermaid CDN loading.** Load `mermaid@11` lazily from CDN (same as the
   read-mode hook). Use a module-level Promise cache so multiple codeBlocks
   share the same load. `window.mermaid` is the loaded instance.

6. **Stale render guard.** Use a `renderCounter` (integer incremented per render
   call). After each `await mermaid.render()` and `await loadMermaid()`, check
   `myId !== renderCounter` and bail — a newer render started while we were
   waiting for the CDN or the SVG generation.

### Non-mermaid fallback NodeView

When `node.attrs.language !== "mermaid"`, return a basic `<pre><code>` structure:

```js
const pre = document.createElement("pre")
const code = document.createElement("code")
if (node.attrs.language) code.className = `language-${node.attrs.language}`
pre.appendChild(code)
return { dom: pre, contentDOM: code }
```

This mimics TipTap's default codeBlock rendering. Do NOT return `null` —
TipTap v3 does not have an automatic fallback for null NodeViews.

## Markdown round-trip verification

After any editor change, verify markdown round-trips correctly:

```js
// 1. Set content from markdown
const json = editor.markdown.parse(markdownString)
editor.commands.setContent(json)

// 2. Get it back
const roundTripped = editor.getMarkdown()

// 3. Compare — mermaid blocks must preserve as ```mermaid\n...\n```
```

The `@tiptap/markdown` extension's `Markdown.configure()` handles the
bidirectional serialization. Custom nodes (Wikilink, Embed) need their own
`markdownTokenName`, `markdownTokenizer`, `parseMarkdown`, and `renderMarkdown`
methods to round-trip correctly.
