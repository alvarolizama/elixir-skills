# E2E Repro Toolkit for LiveView Client-State Bugs

**Symptom:** a bug lives only in the real browser (dialog open state,
canvas/JS-widget state, focus/scroll anchoring) and LiveViewTest cannot
see it — it asserts on serialized HTML, so `dialog.open` is invisible
and only the `data-open` attribute shows. Only a real browser + a real
patch source catches it.

## Toolchain

- `playwright-core` (npm i in a scratch dir) + Chromium already cached
  by Playwright. No browser download needed.
- If an in-session browser tool refuses localhost/private URLs, go
  straight to local playwright.

## Generating REAL patches (stream_insert) without external providers

To make a PubSub-driven patch fire while the modal is open, drive the
real HTTP path with disposable SQL fixture rows + a fake upstream:

1. **Fixture script** — inserts rows with fixed UUIDs
   (`99999999-…`) into the dev DB: team + user (bcrypt hash via
   `mix run -e 'IO.puts(Bcrypt.hash_pwd_salt(...))'`) + membership +
   api key (key_hash = sha256 hex of token) + credential + provider
   **member-exclusive** (so the real upstream is never touched), and
   points the provider `base_url` to `http://127.0.0.1:9999`.
2. **Fake upstream** — tiny Node http server answering the chat
   completion endpoint (streaming + non-streaming) with a valid
   completion. Start it BEFORE any request: a routing circuit breaker
   marks the credential in error on the FIRST failure, and routing then
   short-circuits before capture happens.
3. **Restart the dev server after inserting rows** — a routing cache in
   ETS (60s TTL) won't see new providers otherwise.
4. **Fire the real endpoint** (curl with the fixture API key) → the
   capture handler runs → PubSub broadcast → `stream_insert` patch
   lands in the already-open LiveView.

⚠️ **The most expensive pitfall: `mix run -e` is a SEPARATE BEAM node**
with its own ETS and PubSub. The cache and broadcasts live IN the server
node. Injecting data from a `mix run` process will NOT produce a patch
in the browser. Drive the real HTTP/controller path that mutates the
data — or align the transport with the real data flow. (`mix run` CAN
seed shared DB rows the server sees, because the server reads the DB —
respect cache TTLs.)

## Playwright snippets that mattered

- Login: form fill + `page.waitForURL(/dashboard/, { timeout: 15000 })`
  (a glob under strict matching timed out in one run).
- Click rows via
  `page.evaluate(() => document.querySelector('#table tr').click())` —
  locator clicks can hang when a modal backdrop intercepts pointers.
- State checks must distinguish: `dialog.open` (client),
  `dialog.dataset.open` (server intent), `sameNode` (was the node
  replaced?), a MutationObserver on `attributes/open` with
  `attributeOldValue`, and `close`/`cancel` listeners (expect them NOT
  to fire for morph closes).
- Who-dun-it: `page.addInitScript` wrapping
  `Element.prototype.removeAttribute` yields the exact stack
  (`morphAttrs → morphEl → morphChildren`).
- Chrome headless with CDP needs `--remote-allow-origins=*` or the
  WebSocket handshake gets a 403.

## Scenario matrix (modal vs stream patch)

| Scenario | Steps | PASS condition |
|---|---|---|
| Patch keeps the modal open | open modal (click row) → trigger real patch → wait for new row in stream | `dialog.open === true` after patch, no JS errors |
| Patch after user close | open → close with Escape (dispatch `cancel` event + fallback `d.close()`) → trigger real patch | `dialog.open === false` after patch (does not reopen) |

## Why unit/server tests aren't enough

LiveViewTest only sees `data-open="true"` in HTML (the assign), never
the client-only `dialog.open` — the bug is exclusively DOM. Only a real
browser catches it. Pair this recipe with
`client-dom-vs-morphdom.md` for the fix pattern.

## Teardown & harness hygiene

- Revert every mutated row (base_url, status, enabled, regenerated key)
  and delete all fixture rows (`99999999-…`); kill the fake upstream and
  the dev server (`lsof -t -iTCP:4000 -sTCP:LISTEN`, kill the beam PID —
  `pkill -f` may not match argv).
- Verify liveness with `lsof -nP -iTCP:<port> -sTCP:LISTEN`, don't trust
  an echo — watcher notifications from killed processes keep arriving
  after cleanup.
- A single flaky metrics/timestamp test can fail a full suite; re-run it
  alone before assuming your change broke it (only when provably
  unrelated — e.g. your diff is JS-only and the failure is Elixir).

## E2E without app login (hook-level fixture)

For canvas/DAG hook math only: serve a static fixture dir
(`python3 -m http.server`) replicating the DOM, then mount the real
hook manually — bundle hook files into ONE classic script (strip
`import`/`export`; `file://` blocks ES modules), `Object.create(Hook)`,
stub `pushEvent` into `window.__events`, call `mounted()`, drive with
synthetic `PointerEvent` sequences. Caveats: MutationObserver callbacks
are microtasks (assert after `setTimeout(0)`); removing a node directly
does NOT trigger the observer — mutate the observed parent's childList.
The fixture CANNOT catch server-patch interactions; those need the real
app.