---
name: ui-screenshot-capture
author: Álvaro Lizama
description: "Capture UI screenshots for documentation using browser tools: login, navigate, wait for render, screenshot, copy to target paths, verify content. Covers LiveView/SPA navigation workarounds and session persistence."
version: 1.2.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [screenshots, documentation, browser, web, ui]
    related_skills: [dogfood]
---

# UI Screenshot Capture for Documentation

## Overview

Systematically capture UI screenshots of a web application and save them to specific file paths (e.g., `docs/screenshots/`). This is the task of retaking or refreshing a set of named screenshots that document an app's pages — not exploratory QA (see the `dogfood` skill for that).

## When to use

- User asks to "retake", "refresh", "recapture", or "update" UI screenshots.
- A `docs/screenshots/` (or similar) directory exists with named PNGs that need to reflect the current UI.
- User provides a list of pages/routes and corresponding output filenames.

## Prerequisites

- Browser toolset available (`browser_navigate`, `browser_snapshot`, `browser_click`, `browser_type`, `browser_vision`, `browser_console`).
- **Dev Browser plugin** (`dev_browser_*` tools) is preferred for local apps — it runs inside the Hermes desktop app's embedded Chromium, so session cookies persist across navigations and viewport is controllable via `dev_browser_set_viewport`. Use `dev_browser_navigate`, `dev_browser_screenshot`, `dev_browser_type`, `dev_browser_click`. For login, type credentials and press Enter via `dev_browser_press(key="Enter")` instead of clicking submit (avoids stale ref issues). Fall back to `browser_*` tools only when dev browser is unavailable (remote apps, non-localhost).
- The target app running and accessible (user provides URL, typically `http://localhost:PORT`).
- Credentials if the app requires login.
- The output directory path (e.g., `docs/screenshots/`).

## Workflow

### 1. Login (if required)

1. `browser_navigate` to the app root — you'll typically be redirected to `/login`.
2. `browser_snapshot` to find the username/password fields and submit button by ref.
3. `browser_type` into each field, then `browser_click` the submit button.
4. `browser_snapshot` to confirm you landed on the authenticated page (look for nav elements, user name, etc.).

**Session persistence pitfall:** the browser session may lose the login cookie between navigations. If a `browser_navigate` lands you on `/login` again, re-login. Don't assume the session persists.

**Confirm the login actually landed:** after the submit click, do NOT capture immediately. Check `browser_console(expression="window.location.pathname")` (or navigate to the target URL) and confirm you're OFF `/login` before shooting. A click returning `success: true` does not mean the session cookie was set — if you capture right after the click you often get a beautiful, full-size screenshot *of the login page*, which then gets copied over a real doc screenshot.

### 1.5. Set viewport size (optional)

If the user specifies target dimensions (e.g. "1280×720"), set the browser
window size before capturing:

```
browser_console(expression="window.moveTo(0,0); window.resizeTo(1280,720); window.innerWidth + 'x' + window.innerHeight")
```

**Outer-vs-inner caveat:** `resizeTo` sets the *outer* window size. The
inner viewport (what gets screenshotted) is smaller because of browser
chrome (e.g. 1280×633 instead of 1280×720). This is fine for documentation
screenshots — don't chase the exact pixel count. If pixel-exact dimensions
matter, use the platform's headless browser config instead.

### 2. For each screenshot

For each page to capture:

1. **Navigate** to the target URL with `browser_navigate`.
2. **Wait 2-3 seconds** for LiveView/WebSocket connection and content render. Use `terminal` with `sleep 3` (or 4 for graph/canvas-heavy pages).
3. **Capture + verify in one call** with `browser_vision`:
   ```
   browser_vision(question="Is this the <page name> page showing <key elements>? Is the dark/light theme correct? Is content loaded (no login wall, no blank page)? Describe what's visible.")
   ```
   The response includes a `screenshot_path` under `~/.hermes/cache/screenshots/`.
   **Use the vision analysis as a gate:** if it reports a login wall, blank
   page, or wrong content, re-navigate and re-capture *before* copying. Only
   copy screenshots that passed the visual check.
4. **Copy** the screenshot to the target path:
   ```bash
   cp ~/.hermes/cache/screenshots/<hash>.png /path/to/docs/screenshots/<name>.png
   ```
   Use the `terminal` tool for the `cp`.

### 3. Verify

After all screenshots are captured:

1. **Check file sizes and timestamps** with `ls -la <output_dir>/`. All files should be fresh (current timestamp) and non-trivial in size (>20KB; graph/canvas pages are typically larger).
2. **Visually verify each screenshot** with `vision_analyze` — confirm it shows the intended page, NOT a login page, blank page, or error page. Retake any that came out wrong.

## Pitfalls

### LiveView/SPA link clicks that don't navigate

**Symptom:** `browser_click` on an `<a>` link succeeds (no error) but `browser_snapshot` or `window.location.href` shows you're still on the same page. This happens with Phoenix LiveView links and SPA routers where the click handler intercepts navigation.

**Fix — extract href via JS and navigate directly:**
```
browser_console(expression="Array.from(document.querySelectorAll('a')).filter(a => a.textContent.includes('<link text>')).map(a => a.href)")
```
This returns the actual URL. Then `browser_navigate` to it directly. This is more reliable than clicking for LiveView apps.

### Canvas/graph pages need extra render time

Graph visualizations (D3, force-directed, WebGL) need time to compute layout and render. Wait 4 seconds instead of 2-3, or the screenshot may capture a half-rendered canvas.

### Remote browser session dies mid-batch (Browserbase timeouts)

**Symptom:** partway through a multi-screenshot batch, `browser_navigate` / `browser_console` start returning `Command timed out after 30/60 seconds` for every call.

**Fix:** this is the remote browser session dying or being recycled — not the app (verify the app with `curl -s -o /dev/null -w "%{http_code}" <url>`). Wait ~20 seconds and call `browser_navigate` again — a fresh session is created automatically, **but the login cookie is gone**, so re-login before continuing. To protect a long batch: `cp` each screenshot to its target path immediately after capture (never batch the copies for the end), so a dead session costs at most one retake.

### Hermes browser can't save screenshots to arbitrary paths — playwright-core + cached ms-playwright chromium

**Symptom:** `browser_vision` captures fine but you can't direct the output file to `docs/screenshots/<name>.png`, and the viewport is whatever the agent browser happens to be. Batch-retaking a README screenshot set this way is fragile.

**Fix that worked (MyApp, 2026-07):** drive the app with **playwright-core + the chromium already cached by a previous `npx playwright install`** — no browser download, no new deps beyond one npm package in a scratch dir:

```js
// /tmp/shots/shoot.js — npm i playwright-core first
const { chromium } = require('playwright-core');
const browser = await chromium.launch({
  executablePath: process.env.HOME +
    '/Library/Caches/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-mac-arm64/chrome-headless-shell',
  headless: true,
});
const ctx = await browser.newContext({ viewport: { width: 1280, height: 633 } });
await ctx.addCookies([{ name: 'SESSION_COOKIE_NAME', value: COOKIE, domain: 'localhost', path: '/' }]);
// per page: goto({waitUntil:'networkidle'}) → waitForTimeout(2.5–5s for graphs) → screenshot({path})
```

Key points:
- `ls ~/Library/Caches/ms-playwright/` first — pick the headless-shell build actually present (version dir varies).
- **Headless Chrome's `--screenshot` flag does NOT accept `--cookie`** (it silently renders the login page) and `--virtual-time-budget` hangs on LiveView websockets. Cookie injection via `ctx.addCookies` is the reliable path.
- **Get the session cookie via the real login flow with curl**, not by hand-signing one. Hand-signing a Phoenix session cookie outside the app fails in multiple non-obvious ways (Plug.Crypto KeyGenerator ETS cache missing without the app booted — fix via `Application.ensure_all_started(:plug_crypto)`; atom-vs-string session keys; secret divergence between config files and runtime env). The curl login flow always works:
  ```bash
  CSRF=$(curl -s -c /tmp/jar.txt $BASE/login | grep -oE 'name="_csrf_token" value="[^"]*"' | head -1 | sed 's/.*value="//;s/"$//')
  curl -s -b /tmp/jar.txt -c /tmp/jar.txt -X POST $BASE/session \
    --data-urlencode "_csrf_token=$CSRF" \
    --data-urlencode "login[username]=admin" --data-urlencode "login[password]=MyApp" \
    -o /dev/null -w "%{http_code}"   # expect 302
  grep "_dran_key" /tmp/jar.txt | awk '{print $7}' > /tmp/dran_cookie.txt
  ```
  Note the form field namespacing (`login[username]`, not bare `username`) — read the session controller's pattern match first; a bare field returns a 400.
- ⚠️ **CSRF grep must be attribute-order tolerant.** Phoenix renders the hidden input as `name="_csrf_token" type="hidden" hidden value="..."` — the recipe's `grep -oE 'name="_csrf_token" value="[^"]*"'` silently matches NOTHING (attribute order differs) and the login POST then 403s with a perfectly good cookie jar. Grep the line, then extract value: `curl -s -c /tmp/jar.txt $BASE/login | grep _csrf_token | grep -oE 'value="[^"]*"' | head -1 | sed 's/value="//;s/"$//'`. Rule: a 403 on the login POST = wrong/empty CSRF token, always re-check the extraction.
- **Verify each PNG with `vision_analyze` before committing** — the classic failure is a perfectly-sized screenshot of the login page.
- Template the whole thing as repo scripts (`scripts/gen_session_cookie.sh` + `scripts/screenshot.sh` + `scripts/screenshot/shoot.js`) so the next refresh is one command. MyApp has these — reuse them.

### Rolling-window / time-sensitive KPI pages: seed FRESH data immediately before the shot

**Symptom (MyApp, 2026-07):** seeded 3 request_logs, then shot two other pages first; by the time the logs page was captured, the 5-minute rolling window had expelled the seed rows — the KPI cards showed Req/min 0.4 and Errores 0 while the table below still listed a 429 row. Looked like a bug; it was just stale staging.

**Fix:** for pages whose numbers derive from a rolling time window (last-5-min cards, "today" dashboards), (1) seed the rows RIGHT before that page's capture — after any other captures, not batched at the start; (2) shoot the time-sensitive page FIRST when you can; (3) sanity-check the rendered numbers against what you seeded (count/window_minutes = req/min, avg of seeded latencies, error rate) with `vision_analyze` before accepting the PNG. `mix run -e` with an explicit `inserted_at: DateTime.add(now, -seconds, :second)` is the fast way to seed rows inside the window.

### Reach state by clicking the real UI when it's reachable — restore afterwards

For conditional chrome that a real click can produce (e.g. an impersonation banner after clicking "Ver como"), prefer driving the UI over DOM-injecting the banner: it exercises the real flow and can't drift from the template. Playwright: register `page.on('dialog', d => d.accept())` BEFORE clicking anything with `data-confirm`, then `waitForURL` after the click. Afterwards, undo the state (click "Volver a mi cuenta" / stop impersonation) when the session cookie gets reused for other captures — otherwise later screenshots inherit the banner. Reserve DOM-injection staging (above) for state the UI genuinely can't reach.

**Icon-only buttons have no text:** a `.link`/button that renders only an `<.icon>` matches nothing with `:has-text("...")` — select by attribute instead: `a[title="Ver como este usuario"]`, or the id (`#impersonate-<id>`).

### Password field ref goes stale after typing the username

**Symptom:** `browser_type` into the username field succeeds, but the follow-up `browser_type` into the password field fails with `Could not locate element with role=textbox name=••••••` — even though a fresh snapshot still shows the password field.

**Cause:** typing into the first field re-renders the form (LiveView or framework JS), invalidating the refs captured in the previous snapshot. The password field's ref is dead by the time you type into it.

**Fix:** after typing the username, submit the password via JS in `browser_console` — one expression, no refs involved:

```
browser_console(expression="document.querySelector('input[type=password]').value='<password>'; document.querySelector('form').submit(); 'ok'")
```

Then `browser_navigate` to the target page to confirm the session took. This also bypasses the flaky-submit pitfall below in one step.

### Login submit flaky on the remote browser (LiveView form, dead websocket)

**Symptom:** `browser_click` on the Sign-in button succeeds but the page stays on `/login`; `browser_press(Enter)` and JS `fetch('/session', ...)` fallbacks also fail (fetch returns 200 but no session cookie gets set).

**Fix that worked:** don't fight the form — re-issue `browser_navigate` to the login URL (fresh page load reconnects the LiveView websocket), re-type the credentials, click once, then verify with `browser_console(expression="window.location.pathname")` before navigating on. Never loop the click on a stale page.

### Tag/chip links on list pages don't open records

**Symptom:** On a list page, you click what looks like an item's link but
land on a tag-filter page (URL shows `?tag=escritura`) instead of the
record detail.

**Cause:** tag chips and record links look similar in the snapshot; tag
chips are often rendered as `<a>` links that filter the current list.

**Fix:** Don't click tags to find a record. Instead, hit the app's REST API
to get valid slugs, then navigate directly to a record URL:
```bash
curl -s -H "Authorization: Bearer <token>" "http://localhost:PORT/api/index?context=<ctx>" -o /tmp/idx.json
grep -o '"slug":"[^"]*"' /tmp/idx.json | head
```
Then `browser_navigate` to `http://localhost:PORT/<type>/<slug>`. This is
both faster and avoids the filter trap.

### Don't commit to git

Unless the user explicitly asks, do NOT `git add`/`git commit` the screenshots. Just overwrite the files.

### Don't start or stop servers

Assume the app is already running. Do not start, restart, or stop any server processes.

> For detailed LiveView/SPA navigation workarounds (href extraction, sitemap building), see `references/liveview-navigation-workarounds.md`.

## Tools Reference

| Tool | Purpose |
|------|---------|
| `browser_navigate` | Go to a URL (also returns a compact snapshot) |
| `browser_snapshot` | Get DOM text snapshot (accessibility tree) with ref IDs |
| `browser_click` | Click an element by ref (`@eN`) |
| `browser_type` | Type into an input field by ref |
| `browser_vision` | Screenshot + AI analysis; returns `screenshot_path` |
| `browser_console` | Evaluate JS in page context (extract hrefs, check URL) |
| `vision_analyze` | Verify a saved screenshot shows the intended content |
| `terminal` | `cp` screenshots to target paths, `ls` to verify, `sleep` to wait |

## Tips

- **Stage the UI before shooting.** The default render is not always the state you want to document. Before `browser_vision`, use `browser_console` to open collapsed sections, activate tabs, and scroll the target into view:
  ```
  browser_console(expression="const s=document.querySelector('[data-testid=\"archived-section\"]'); s.open=true; s.scrollIntoView({block:'center'}); 'ok'")
  ```
  Watch out: re-running the same `const` declaration in `browser_console` throws `SyntaxError: Identifier 's' has already been declared` — redeclare with a different name or drop the `const` and chain the calls in one expression. For tabbed views (e.g. a project kanban tab), click the tab with `browser_click` first, then capture.
- **Batch independent reads:** when checking file sizes and verifying screenshots, batch `vision_analyze` calls (up to 3-5 per turn) since they're independent.
- **Retake only what the change affects:** grep the README/docs for which screenshots are referenced, then retake just the pages whose UI the feature touched (e.g. new board view → kanban.png; new sidebar → dashboard.png). A full-set retake costs a login + ~1 min per page and risks clobbering good shots with bad ones (login walls, half-rendered canvases) when the session degrades mid-batch.
- **Use `browser_console` to check current URL** if you're unsure whether a click navigated: `browser_console(expression="window.location.href")`.
- **The `browser_vision` screenshot_path** is under `~/.hermes/cache/screenshots/` with a hash filename. Always copy it immediately — the cache may be cleaned.
- **For chat/widget screenshots** (e.g., a copilot panel), click the "open" button first, wait for the widget to render, then capture.
- **Staging server-rendered conditional sections (docs-only).** Some sections only render with live state you can't produce (e.g. an "in-flight requests" card when no requests are running, and the server runs without distribution so you can't inject events). For docs screenshots it's legitimate to inject the EXACT template markup client-side — copy the HEEx/HTML from the template verbatim — via `page.evaluate(el => ...insertAdjacentHTML...)` (playwright) or `browser_console`. Two rules: (1) keep derived UI consistent — if the staged section says "2 pending", also patch the KPI counter that would show 2, or the screenshot self-contradicts; (2) disclose it in your report ("sección stageada por DOM injection") and never present staged state as a live-data capture. Only stage when the real state is genuinely unreachable — real data beats staging every time.
