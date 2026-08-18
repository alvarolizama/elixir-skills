# Browser Tool Form Submission Pitfall

## Symptom

Using `browser_navigate` + `browser_type` + `browser_click` to log in to a
Phoenix app with a classic HTML form (`<form action="/session" method="post">`)
leaves the page on the same URL after clicking "Sign in". The POST never
fires. This affects HTML forms but NOT LiveView `phx-submit` forms (which
use JS interception).

## Reproduction (my_app login page, 2026-07-17)

1. `browser_navigate("http://localhost:4000/login")` → shows login form
2. `browser_type(ref, "admin")` → fills username
3. `browser_type(ref, "my_app")` → fills password
4. `browser_click(ref)` → click "Sign in"
5. `browser_vision(...)` → still on login page, no navigation occurred

## Workaround: curl-based session verification

When you need to verify that authenticated pages work (not screenshots, just
HTTP status + content), use curl with cookie persistence:

```bash
# 1. Get login page + CSRF token
rm -f /tmp/cookies.txt
curl -s -c /tmp/cookies.txt http://localhost:4000/login | grep -o 'name="_csrf_token" value="[^"]*"' | head -1

# 2. Extract CSRF token and POST login
CSRF=$(curl -s -c /tmp/cookies.txt -b /tmp/cookies.txt http://localhost:4000/login | grep -o 'name="_csrf_token" value="[^"]*"' | head -1 | sed 's/.*value="\([^"]*\)".*/\1/')
curl -s -c /tmp/cookies.txt -b /tmp/cookies.txt -X POST http://localhost:4000/session \
  -d "_csrf_token=${CSRF}&login[username]=admin&login[password]=my_app" \
  -o /dev/null -w "%{http_code} %{redirect_url}\n"
# Expected: 302 http://localhost:4000/notes

# 3. Verify authenticated page loads
curl -s -b /tmp/cookies.txt -L http://localhost:4000/ | head -c 500
# Should return HTML with lang="es" (if i18n is active)
```

## Workaround: Playwright screenshot with login

For actual screenshots of authenticated pages, use Playwright with a script
that performs the login via DOM interaction (not the Hermes browser tool):

```javascript
// capture.js
const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });

  // Login
  await page.goto('http://localhost:4000/login');
  await page.fill('input[name="login[username]"]', 'admin');
  await page.fill('input[name="login[password]"]', 'my_app');
  await page.click('button[type="submit"]');
  await page.waitForURL('**/notes');

  // Screenshot dashboard
  await page.goto('http://localhost:4000/');
  await page.waitForTimeout(2000);
  await page.screenshot({ path: 'docs/screenshots/dashboard.png', fullPage: false });

  await browser.close();
})();
```

Run with: `npx playwright install chromium && node capture.js`

## Why this happens

The Hermes `browser_tool` uses a lightweight DOM interaction layer that
does not fully implement the HTML form submission algorithm. LiveView forms
work because they use `phx-submit` which triggers JS event handlers that
the tool CAN intercept. Classic `<form method="post">` requires full
browser navigation which the tool does not perform.

## Prevention

- For LiveView apps: use `phx-submit` forms (they work with browser_tool)
- For classic HTML forms: use curl for verification, Playwright for screenshots
- Never assume browser_tool successfully submitted a form without verifying
  the resulting page URL or content
