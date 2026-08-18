# Scroll jumps to top after any action — focus + stream reset trap

Applies to: any LiveView page with a streamed list (`phx-update="stream"`) where
handlers re-render the collection after events (toggle / edit / save / delete).

## Symptom

Every action in the list sends the page scroll back to the top; the user may
describe it as "scrolls up or reloads". Happens on ALL pages that re-stream
after events, and ONLY with real mouse clicks — synthetic repro attempts pass.

## Root cause

- Handlers re-render the collection: `stream(socket, :items, items, reset: true)`
  (or refetch + reset).
- The reset replaces the clicked `<button>` node in the DOM.
- A REAL mouse click focuses the button (synthetic `el.click()` does NOT).
- Chrome uses the focused node as its scroll anchor; when morph removes the
  anchored node, the anchor is lost and scroll resets to 0.
- With no focused node (synthetic clicks), Chrome preserves scroll — so naive
  repro attempts "pass" and the bug looks unreproducible.

## Diagnosis recipe (~10 min, no code changes)

1. **Reload vs morph**: in console, `window.__probe = 1`. After the action,
   still `1` = no page reload (morph/focus issue); `undefined` = real reload
   (LiveView reconnect/crash — a different bug; check the socket).
2. **Rule out socket death through a proxy**: `window.liveSocket.isConnected()`
   after 60–90s idle. Still `true` = not a proxy idle-timeout (the symptom
   overlaps: dead ws → remount/reload → scroll to top).
3. **Reproduce faithfully**: scroll to bottom, then
   `btn.focus(); btn.click()` — NOT bare `btn.click()`. Wait ~2s for the patch,
   read `window.scrollY`. `0` = confirmed.
4. **Reproduce on the real deployed instance** when local repro fails: drive
   the user's already-logged-in dev-browser tab (`dev_browser_eval` /
   `dev_browser_click`) — same code can behave differently behind a proxy, and
   you get real data density. A/B the fix there before committing it.

## Fix — global blur listener (pragmatic, one place)

In `assets/js/app.js`, before `liveSocket.connect()`:

```js
// Preserve scroll position across LiveView patches. Action buttons get focus
// on click, and stream resets replace the focused node — Chrome then loses
// its scroll anchor and jumps to the top. Blurring on capture avoids it.
document.addEventListener("click", (e) => {
  const btn = e.target.closest("button")
  if (btn && (btn.hasAttribute("phx-click") || btn.closest("form[phx-submit]"))) btn.blur()
}, true)
```

- Capture phase runs before LiveView's handler; the event still fires normally.
- Covers `phx-click` buttons AND submit buttons inside `phx-submit` forms
  (save flows jump too).
- Verified A/B on a real instance: focused click without listener →
  `scrollY = 0`; with listener → scroll unchanged, action succeeds.

## Alternative — surgical stream updates (cleaner data flow, more code)

Replace per-action `stream(..., reset: true)` with `stream_insert/3`
(toggle/save) and `stream_delete/3`: morph patches the existing row in place
(same DOM id), the focused button survives, scroll anchor intact. Use when rows
map 1:1 to entities. The blur listener is the better default when rows are
composite (grouped/joined rows) or many LiveViews share the pattern.

## Pitfalls

- `element.click()` in tests/repro scripts does NOT focus the element. Any bug
  depending on focus, blur, `activeElement`, or scroll anchoring is INVISIBLE
  to synthetic clicks — reproduce with real input semantics (`focus()` + click,
  CDP `Input.dispatchMouseEvent`, or Playwright `page.click`).
- Coordinate-based clicks in embedded browser panes can silently miss (offset
  viewports). Verify the click landed (form opened / event fired) before
  concluding "no repro"; prefer id-based JS clicks for probing.
- `window.__probe`-style marker variables are the fastest way to split
  "full reload" vs "in-place patch" bugs.
- Verify A/B on the SAME instance where the bug was reported: inject the
  listener via console (`document.addEventListener('click', fn, true)`), re-run
  the repro, and only then commit the fix to `app.js`.

## Verification script

`scripts/scroll-jump-repro.mjs` — headless-Chrome CDP probe: logs into a
Phoenix app, scrolls, focus+clicks a `phx-click` button, asserts (a) the blur
listener fired and (b) `scrollY` survives the patch. Re-runnable against any
environment (local dev or deployed). See the script header for env vars.
