# LiveView / SPA Navigation Workarounds

## Problem

`browser_click` on a link in a Phoenix LiveView app (or SPA with client-side routing) sometimes succeeds without error but does not change the URL or navigate. The accessibility snapshot shows the same page. This is because LiveView intercepts link clicks to do patch-based navigation, and the browser automation's click may not trigger the JS hook correctly.

## Diagnosis

Check the current URL after a click:

```
browser_console(expression="window.location.href")
```

If it still shows the old URL, the click didn't navigate.

## Fix: Extract href and navigate directly

### Step 1 — Find the link's href

Use `browser_console` to query the DOM for the link by its text content:

```javascript
// Find by partial text match
Array.from(document.querySelectorAll('a'))
  .filter(a => a.textContent.includes('Daily'))
  .map(a => a.href)
```

Returns: `["http://localhost:4000/notes/daily-2026-07-17"]`

### Step 2 — Navigate directly

```
browser_navigate(url="http://localhost:4000/notes/daily-2026-07-17")
```

This bypasses the LiveView click handler and does a full page load, which is more reliable for screenshot capture.

## When to use this

- Clicking a link in the accessibility snapshot doesn't change the URL.
- You need to navigate to a specific note/page and know its slug.
- The app is Phoenix LiveView, LiveView Native, or any SPA with client-side routing.

## When NOT to use this

- If the click works (URL changes), don't bother with the workaround.
- If you don't know the URL pattern, first try clicking. Only fall back to href extraction if the click fails.

## Alternative: query all links on the page

To see all navigable URLs at once:

```javascript
Array.from(document.querySelectorAll('a[href]'))
  .map(a => ({ text: a.textContent.trim().substring(0, 50), href: a.href }))
  .filter(l => l.href && !l.href.includes('#'))
```

This gives you a map of link text → URL, useful for building a sitemap of where to navigate.
