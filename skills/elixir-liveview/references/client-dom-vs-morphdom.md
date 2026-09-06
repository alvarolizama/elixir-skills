# Client-DOM State vs LiveView morphdom

**Symptom:** element state that exists only in the client DOM —
`<dialog open>` from `showModal()`, focus, canvas content, JS-widget
state — silently reverts or dies when a LiveView patch arrives
(`stream_insert`, PubSub-triggered update, form change), even though the
server-side assigns never touched that state.

## Mechanism (verified, LiveView 1.2.x)

1. The server always renders the element WITHOUT the client-only
   attribute (`<dialog>` without `open`, since the hook opens it via
   `showModal()`).
2. Any patch makes morphdom sync attributes — it removes the client-set
   attr (`morphAttrs` → `removeAttribute('open')`). For a `<dialog>`
   that closes it.
3. This close fires NO `close` and NO `cancel` event (unlike
   `dialog.close()`). Listener-based server sync never learns about it.
4. The element is morphed in place — the hook is NOT re-mounted, so a
   `mounted()` re-open never runs for patches.

Confirm the culprit in one step — wrap `Element.prototype.removeAttribute`
in an init script and log the stack. It shows
`morphAttrs → morphEl → morphChildren` from the LiveView bundle.

## Fix pattern: hook lifecycle, NOT observers

In the hook that owns the state:

```js
beforeUpdate() { this.__wasOpen = this.el.open },
updated() {
  if (this.__wasOpen && this.el.dataset.open === "true" && !this.el.open &&
      typeof this.el.showModal === "function") {
    this.el.showModal()
  }
}
```

- `beforeUpdate` records pre-patch state. `updated()` runs synchronously
  right after the morph of that element → restores state in the same
  tick, no flicker.
- The server keeps an authoritative marker (`data-open="true|false"`)
  so the client knows whether the modal SHOULD be open.
- User-initiated closes via **Escape/backdrop** close the dialog
  natively (`close` fires, `open` removed) → `__wasOpen=false` and the
  close-sync flips `data-open="false"` client-side → `updated()` never
  re-opens, even if a patch lands before the round-trip.
- ⚠️ A `phx-click="close_modal"` button is NOT optimistic: it takes a
  round-trip. Between click and response (~<100ms) `__wasOpen=true` and
  `data-open="true"` still hold, so a stream patch in that window
  re-opens the modal transitorily — it self-corrects when the patch
  carrying `data-open="false"` lands. If that flicker matters, fix it
  with an optimistic close: flip `data-open="false"` client-side on
  click, exactly like the `close` listener does for Escape/backdrop.
- `__wasOpen` covers the race where a patch lands while the close event
  is in flight — stale `data-open="true"` cannot pop the modal back
  open because the dialog was already closed pre-patch.

## Alternatives that fail (all verified)

- **MutationObserver on the attribute** — REJECTED. Callbacks run as a
  *microtask*, the native `close` event is queued as a *task*. The
  observer runs FIRST, sees `data-open="true"` still set, and re-opens a
  dialog the user just closed (transitory flash + callback churn).
- **`mounted()` re-open only** — dead end. Patches morph in place, never
  re-mount the hook. Only full subtree replacement re-mounts.
- **`phx-update="ignore"` on the `<dialog>`** — stops the close but
  FREEZES all server-rendered content inside the modal, breaking
  "click another row while modal is open". Use only for stateless shells.
- **`close`/`cancel` events** — never fire for morph-stripped `open`.

## Debug workflow

1. Reproduce with a real browser + a real patch source (see
   `e2e-repro-toolkit.md`).
2. Instrument — native `close`/`showModal` wrappers, MutationObserver on
   the element, `removeAttribute` stack-trace wrapper via addInitScript.
3. Read the signs — no events, same node, attr removed ⇒ morphdom, not
   hook logic.
4. Read the shipped LiveView JS
   (`deps/phoenix_live_view/priv/static/*.esm.js`, `view.ts`,
   `dom_patch.ts`) to confirm the sync path.

## Tabs + hidden-textarea structured editor under `phx-update="ignore"`

Pattern: tabs whose state lives ONLY in the client DOM, plus a visual
row editor that serializes to a hidden textarea that is the single
source of truth for the server form.

- **Tabs**: plain `[data-tab]` buttons + `[data-panel]` panes toggled by
  a hook; wrap each pane's container in `phx-update="ignore"` (it needs
  its own DOM `id` — Phoenix raises without one) so patches never touch
  hook-built rows.
- **Per-entity hook id** (`step-editor-tabs-#{step_id}`): switching
  entities replaces the id → hook remounts → fresh rows from the new
  entity's JSON. A static id + `phx-update="ignore"` would leak the
  previous entity's rows.
- **Hidden textarea under `phx-update="ignore"` lives in the real
  form.** Visual rows read it on mount, write it on every input, then
  dispatch a native `input` event so `phx-change="validate"` (server
  lint) fires — live lint badge without optimistic server state.
- **Selects whose options are built at runtime**: assigning `.value`
  before the options exist silently resets the select to the first
  option. Stash `dataset.pendingValue` ONLY when
  `select.options.length === 0` (template options get direct
  assignment); the option-sync pass applies pending values after
  building options. Run the sync at the END of the initial fill.
- **Save button outside the `<.form>`** (footer) works via
  `form={form_id}` — but don't select `form button[type=submit]` in E2E;
  find the button by text.
- **E2E proof**: assert through the real DB read-back, not just DOM
  state; add then remove the mutation in the same session to leave data
  pristine.

## Hook selector mismatch: `querySelector` returns null → silent early return

A JS hook calls `this.el.querySelector("[data-something]")` but no
template element carries that attribute. Any guard like
`if (this.jsonEl && this.visualBody)` in `mounted()` fails and ALL
subsequent initialization silently skips — no error, no warning, just
dead functionality. Root cause: a refactor removed or renamed the
wrapper element but the hook still references the old selector.
Invisible to server-side LiveViewTest (which never runs JS).

Fix pattern:

1. Verify the element exists in served HTML via LiveViewTest:
   `assert render(view) =~ "data-visual-body"`.
2. If missing, add it to the template as a direct child of the
   hook-bound element (`id={@id}` with `phx-hook="MyHook"`).
3. Move `hidden` from the wrapper div onto the actual toggleable element
   (e.g. the textarea) — the hook toggles `jsonEl.hidden` where `jsonEl`
   IS the textarea; `hidden` on a parent div makes the element
   unreachable regardless of toggle state.
4. In `updated()`, re-assert mode state after morphdom restores
   server-rendered attrs (re-set `hidden` + button text from a
   `this.__mode` flag).

## Pitfalls

- Don't trust a passing server-side LiveViewTest for this bug class. It
  asserts only `data-open="true"` in HTML, which stays true — the DOM
  state is client-only. Only a real browser catches it.
- Design-note comments describing hook behavior rot fast. When the
  mechanism changes, rewrite the notes block too.
- A shared hook used by dialogs without the sync attribute must guard
  strictly (`=== "true"`) — preexisting `data-open="false"` writes into
  dialogs that never had the attribute are harmless only with an exact
  match.
