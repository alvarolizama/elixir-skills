# README Authoring and Screenshots — codebase-verified docs

Symptom: a README rewrite or screenshot refresh lands claims the code
doesn't back — features that don't exist, defaults that drifted, pages that
were refactored away. Mechanism: docs are written from memory of the code,
not from the code. Fix: every claim gets a grep; every pixel gets a gate.

## Part 1 — README authoring, every claim verified

### Core rule

**Every claimed feature must exist in the codebase, and every UI claim must
have real UI (a route/page/component).** No invented features, no roadmap
items presented as shipped.

### Workflow

1. **Confirm the project first** (cwd / git remote) — don't assume from
   stack markers.
2. **Extract the old doc's claims as a checklist:** feature bullets, env
   vars + defaults, endpoints, every "X is persisted/audited/exported"
   statement.
3. **Enumerate ground truth from code, not from the old doc:**
   - Pages: the router file is the page inventory. `live_session` blocks
     give the access role; "managers can X" claims must match the session +
     in-module hooks.
   - Each page's purpose: batched moduledoc reads of LiveViews/controllers
     (`sed -n '/@moduledoc \"\"\"/,/\"\"\"/p'` in a loop). `@moduledoc false`
     means read the render/events — the page still exists.
   - Config: read `config/runtime.exs` for real
     `System.get_env("VAR", "default")` lines — never copy defaults from the
     old README (they drift).
   - Install/deploy: seeds file (default credentials + override env vars),
     Dockerfile (port, entrypoint, build ARGs), `mix.exs` (Elixir
     requirement, `setup` alias — the real quick-start command).
4. **Verify each claim individually with grep**, never carry a claim
   without a code hit. Claimed mechanism → grep ALL call sites, write the
   REAL scope ("admin actions are audited" may mean exactly one controller).
   Claimed response headers → grep the `put_resp_header` site, not
   moduledoc mentions. Claimed endpoints → confirm method + path in the
   router.
5. **Separate user-facing from internals** — adapters/workers/topology go
   in a short "Platform" section at most.
6. **Write the doc, then REPORT the discrepancies explicitly** — which old
   claims were removed/corrected (with the grep that disproved each) and
   which verified features were added. The report is part of the deliverable.

### Pitfalls

- **Framework boilerplate comments are not config.** `runtime.exs` ships
  commented-out blocks with placeholder vars; grep finds them but they're
  inert. Read 5–10 lines of context around every hit.
- **Orphan modules exist** — a LiveView in `lib/` with no route is not a
  feature; the router is the truth.
- **Doc comments can promise what code doesn't do** — verify the
  implementation, not the documentation.
- **Screenshots can outlive pages** — a PNG existing doesn't prove the page
  still exists; cross-check the router.
- **UI language differs from README language** — if UI strings are
  hardcoded non-English, note it prominently (an English README for a
  Spanish UI surprises users).

### Output conventions

- Env vars as tables: `Var | Default | What it tunes`; required-in-prod
  vars in their own table FIRST.
- Quick start = clone → `mix setup` → run → seeded-credentials table
  (with override env vars) → first milestone.
- One hero screenshot; verify the referenced file exists in the repo.
- Structure that works: pitch + hero → UI-language note → features grouped
  (with real paths) → Platform (compressed) → requirements → quick start →
  usage → tables → deploy/Docker → license.

## Part 2 — UI screenshot capture

Not exploratory QA: retaking a named set of documentation screenshots.

1. **Login (if required) and confirm it LANDED** — check
   `window.location.pathname` is OFF `/login` before shooting. A click
   returning success does not mean the session cookie was set; capturing
   right after the click yields a beautiful screenshot of the login page.
2. **Viewport (optional):** `window.moveTo(0,0); window.resizeTo(W,H)` —
   `resizeTo` sets OUTER size; inner viewport is smaller (browser chrome).
   Fine for docs; don't chase exact pixels.
3. **Per screenshot:** navigate → wait 2–3s (4s for graph/canvas-heavy
   pages) → capture + vision-gate in one call (right page? correct theme?
   no login wall? content loaded?) → `cp` to the target path IMMEDIATELY
   (never batch copies at the end).
4. **Verify the batch:** fresh timestamps, >20KB each, and every PNG
   visually checked — no login/blank/error pages.

### Credentials via curl, CSRF attribute-order trap

Get the session cookie via the REAL login flow (hand-signing a Phoenix
session cookie fails in multiple non-obvious ways):

```bash
CSRF=$(curl -s -c /tmp/jar.txt $BASE/login | grep _csrf_token \
  | grep -oE 'value="[^"]*"' | head -1 | sed 's/value="//;s/"$//')
curl -s -b /tmp/jar.txt -c /tmp/jar.txt -X POST $BASE/session \
  --data-urlencode "_csrf_token=$CSRF" \
  --data-urlencode "user[username]=admin" --data-urlencode "user[password]=secret" \
  -o /dev/null -w "%{http_code}"      # expect 302
```

- Phoenix renders the hidden input `name="_csrf_token" type="hidden"
  hidden value="..."` — a grep for `name="_csrf_token" value="..."` matches
  NOTHING and the login POST 403s with a good jar. Grep the line, extract
  the value (above). A 403 on the login POST = wrong/empty CSRF token.
- Form fields are namespaced (`user[username]`, not bare `username`) — read
  the session controller's pattern match first; bare fields return 400.
- Headless Chrome `--screenshot` doesn't accept `--cookie` (silently renders
  the login page) and `--virtual-time-budget` hangs on LiveView websockets —
  cookie injection via the driver API is the reliable path.

### LiveView / SPA navigation

- A click that "succeeds" but doesn't change the URL = LiveView intercepted
  the navigation. Extract the real href and navigate directly:
  `Array.from(document.querySelectorAll('a')).filter(a =>
  a.textContent.includes('...')).map(a => a.href)`.
- Password refs go stale after typing the username (form re-renders) —
  submit via one JS expression:
  `document.querySelector('input[type=password]').value='...';
  document.querySelector('form').submit(); 'ok'`.
- Flaky LiveView login (dead websocket): don't loop the click — re-navigate
  to the login URL (fresh load reconnects), re-type, click once, verify the
  path.

### Time-sensitive pages and staging

- Rolling-window KPI pages: seed FRESH rows IMMEDIATELY before that page's
  shot (5-minute windows expel early seeds), shoot it FIRST, sanity-check
  the rendered numbers against what you seeded.
- Reach conditional state by clicking the real UI when reachable; restore
  afterwards so later shots don't inherit it. Icon-only buttons: select by
  attribute (`a[title="..."]`) or id — they have no text.
- Stage the UI before shooting (open collapsed sections, activate tabs,
  scroll into view). DOM-injection staging is legitimate ONLY if (1) derived
  UI stays consistent (a staged "2 pending" section needs the counter that
  would show 2), and (2) it's disclosed and never presented as live data.
- Retake only pages the change touches — grep the docs for referenced
  screenshots; a full-set retake risks clobbering good shots.

## Verification

- Every README claim has a code hit recorded (grep + file:line); every
  endpoint confirmed in the router.
- Discrepancy report delivered: removed/corrected claims with their greps,
  added verified features.
- Screenshots: all paths exist, fresh, >20KB, visually verified — login
  wall / blank / error pages = retake.