# Icon-only toggle buttons: icon + title must encode the action, not the state

When a row action is icon-only (no text, common for inline edit/delete/enable
clusters), a static icon that suggests one operation communicates wrong:
users see `hero-arrow-path` and assume "refresh", or see `hero-power` and
assume "kill". Default to a state-pair icon + `title` tooltip that names
the action being performed.

## Pattern (MyApp 2026-08-01)

```heex
<button
  phx-click="toggle_model_provider"
  phx-value-id={ap.id}
  class="btn btn-xs btn-ghost"
  id={"toggle-ap-#{ap.id}"}
  title={if ap.enabled, do: "Desactivar", else: "Activar"}
>
  <.icon
    name={if ap.enabled, do: "hero-pause", else: "hero-play"}
    class="w-3 h-3"
  />
</button>
```

The `title` updates in lockstep with the icon so hover always tells the truth.

## Rules of thumb

- The `title=` text describes the **action the click will perform**, not the
  current state. ("Desactivar" if it's currently enabled, "Activar" if
  disabled — never "Click me" or "Estado: ...").
- The icon pair is **bidirectional**: `hero-play` ↔ `hero-pause`,
  `hero-lock-open` ↔ `hero-lock-closed`, `hero-eye` ↔ `hero-eye-slash`,
  `hero-bell` ↔ `hero-bell-slash`, `hero-check-circle` ↔ `hero-x-circle`.
  Pick a pair whose semantics match the two states.
- Never reuse generic icons like `hero-arrow-path`, `hero-power`,
  `hero-cog-6-tooth`, or `hero-check` for a toggle — they read as
  "refresh / shutdown / settings / done", not "switch state".
- Keep the button icon-only when siblings in the row are also icon-only
  (edit / delete). Mixing "icon + text" with bare icons in the same cluster
  looks broken.
- Verify the icon pair exists in
  `deps/heroicons/optimized/20/solid/` before relying on the name:

  ```bash
  ls deps/heroicons/optimized/20/solid/ | grep -E "pause|play"
  ```

  Word order also matters — Heroicons inverts pairs on filenames (`lock-closed`
  not `lock-close`); check the actual file before using the name.

## When a toggle ISN'T the right control

A toggle button is right for **binary state changes without intermediate
states**. For multi-step flows or destructive actions with side effects
(circuit breaker, scope restriction, anything that requires reasoning before
it commits), use a confirmation modal or a `<.input type="select">` next to
a label. Add `data-confirm=...` to the toggle when a stray click could
silently flip a delicate state.
