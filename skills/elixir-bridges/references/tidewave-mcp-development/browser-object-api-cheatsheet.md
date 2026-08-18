# Tidewave Browser Object API Cheatsheet

Quick reference for all `browser` object methods available inside `browser_eval`.

## Navigation

```javascript
// Navigate to a path
await browser.reload("/path");

// Reload current page
await browser.reload();
```

## Snapshots

```javascript
// Full page snapshot
await browser.snapshot();

// Snapshot of a specific element
await browser.snapshot(browser.getBySnapshotRef('e42'));

// Snapshot with pagination (for large pages)
await browser.snapshot(null, { offset: 200, limit: 200 });
```

## Element Location

```javascript
// By snapshot ref (preferred — always works)
const el = browser.getBySnapshotRef('e42');

// By simple CSS selector
browser.locator('input[name="email"]');

// By button/link text
browser.locator('button', { hasText: 'Save' });
browser.locator('a', { hasText: 'Dashboard' });

// AVOID: complex selectors with pseudo-classes
// browser.locator('h3:has-text("Title")')  // fails with empty error {}
```

## Interaction

```javascript
// Click an element
const el = browser.getBySnapshotRef('e42');
await browser.click(el);

// Fill an input
const input = browser.getBySnapshotRef('e42');
await browser.fill(input, "text value");

// Form submission (inside browser.eval)
form.dispatchEvent(new Event('submit', { bubbles: true }));
```

## Evaluation

```javascript
// Run code on the page — has access to document, window, etc.
await browser.eval(() => {
  const el = document.querySelector('#my-element');
  console.log('Found:', el?.textContent);
});

// Pass locators as arguments
await browser.eval(
  (el1, el2) => {
    console.log('Element 1:', el1.textContent);
    console.log('Element 2:', el2.textContent);
  },
  [browser.getBySnapshotRef('e42'), browser.getBySnapshotRef('e43')]
);
```

## Waiting

```javascript
await browser.wait(500);  // ms
```

## Resize (for responsiveness testing)

```javascript
await browser.resize(768, 1024);  // width, height
```

## Complete Navigation + Interaction Example

```javascript
// 1. Navigate
await browser.reload("/graph");
await browser.wait(500);

// 2. Snapshot to find refs
console.log('Snapshot: ', await browser.snapshot());

// 3. Click using ref
const btn = browser.getBySnapshotRef('e507');
await browser.click(btn);
await browser.wait(300);

// 4. Verify
console.log('After: ', await browser.snapshot(browser.getBySnapshotRef('e506')));
```

## Parallel SQL + Browser Pattern

Call `execute_sql_query` and `browser_eval` in the same assistant turn for concurrent
execution:

```
// Assistant turn:
//   1. browser_eval → navigate to /kanban
//   2. execute_sql_query → SELECT * FROM pages WHERE page_type = 'todo'
// Both execute concurrently.
```

## What NOT to Do

```javascript
// ❌ window.location not available in top-level scope
window.location.href = "/graph";

// ❌ element.click() inside browser.eval — use browser.click(locator)
document.querySelector('button').click();

// ❌ form.submit() — dispatch event instead
form.submit();

// ❌ Complex CSS selectors in snapshot
browser.snapshot(browser.locator('div:has(> .class)'));

// ❌ Returning values from browser.eval — use console.log
await browser.eval(() => { return document.title; });  // won't see result

// ✅ Correct
await browser.eval(() => { console.log(document.title); });
```

## Snapshot Output Format

The snapshot returns a YAML-like accessibility tree:

```
- document [ref=e1]:
  - generic [ref=e2]:
    - heading "Page Title" [level=1] [ref=e3]
    - button "Save" [ref=e4] [cursor=pointer]
    - textbox "Email" [ref=e5]
    - link "Dashboard" [ref=e6] [cursor=pointer]:
      - /url: /dashboard
```

Key markers:
- `[ref=eNNN]` — reference ID for `getBySnapshotRef`
- `[cursor=pointer]` — clickable
- `[level=N]` — heading level
- `/url: /path` — link href
