# HEEx Template & LiveView Event Pitfalls

Runtime crashes that only surface when the LiveView is live in the browser —
not at compile time. Each one cost a production deploy cycle to discover.

## Pitfall 1 — `not @assign` raises ArgumentError when assign is nil

In HEEx templates, Elixir's `not` operator requires a strict boolean operand.
When an assign is `nil` (the default for many socket assigns on mount),
`not @assign` raises `ArgumentError: argument error` at render time.

```heex
<!-- BROKEN — crashes on first render when selected_provider_id is nil -->
<select disabled={not @selected_provider_id}>
<select disabled={not @selected_credential_id or not @selected_model}>
```

The server log shows:
```
** (ArgumentError) argument error
    lib/my_app_web/live/my_live.html.heex:162
```

**Fix — use `is_nil/1`:**

```heex
<select disabled={is_nil(@selected_provider_id)}>
<select disabled={is_nil(@selected_credential_id) or is_nil(@selected_model)}>
```

`is_nil/1` returns a real boolean for any input (nil → true, anything else →
false). `not` only works on `true`/`false` — it does NOT coerce nil to falsy.

**Rule:** in HEEx `disabled=`, `if=`, and `:if=` attributes, never use
`not @assign` when the assign can be nil. Use `is_nil(@assign)` instead.
For truthiness checks, `@assign` alone works in `:if=` (HEEx coerces), but
`not @assign` does NOT — the explicit negation triggers the strict boolean
path.

**Seen in:** my_app_gateway BenchmarksLive — 3 `disabled=` attrs crashed on
initial mount because `selected_provider_id`, `selected_credential_id`,
and `selected_model` start as nil.

## Pitfall 2 — `phx-value-*` on buttons sends flat params, not nested

A `<button phx-click="add" phx-value-foo={@bar}>` sends params as a flat map:
`%{"foo" => "bar", "value" => "add"}`. But a `<.form phx-submit="add">` sends
params nested under the form name: `%{"target" => %{"foo" => "bar"}}`.

If your handler pattern-matches only one shape, it crashes on the other:

```elixir
# BROKEN — only matches form-submit shape, crashes on button-click shape
def handle_event("add", %{"target" => params}, socket) do
  # ...
end

# When the button fires, params is %{"foo" => "bar", "value" => "add"}
# → no "target" key → no function clause matches → BadArityError / crash
```

**Fix — normalize both shapes in the handler:**

```elixir
def handle_event("add", params, socket) do
  # Flat from phx-value-* button, or nested under "target" from form submit
  target = Map.get(params, "target", params)
  provider_id = target["provider_id"] || ""
  # ...
end
```

`Map.get(params, "target", params)` returns the nested map when it exists
(form submit), or falls back to `params` itself (button click). Both shapes
then work uniformly.

**Rule:** when a LiveView has BOTH a `<.form phx-submit>` and a
`<button phx-click>` that fire the same event, the handler must accept a
generic `params` map and normalize — not pattern-match on a specific shape.

**Seen in:** my_app_gateway BenchmarksLive — add_target handler crashed when
the "Agregar" button (using `phx-value-*`) fired, because the handler
expected `%{"target" => params}` from the form.

## Pitfall 3 — daisyUI alert color classes have low contrast

daisyUI's `alert-success` renders a light green background. Adding
`text-base-content/60` to text inside it produces near-invisible text —
`base-content` is tuned for `base-100` (dark or light surface), not for
colored alert backgrounds.

```heex
<!-- BROKEN — text barely visible on light green -->
<div class="alert alert-success">
  <h3 class="text-sm font-bold">Ganador: gpt-4o</h3>
  <p class="text-xs text-base-content/60">42.9 t/s · TTFT 3148ms</p>
</div>
```

**Fix — inherit the alert's content color with opacity:**

```heex
<div class="alert alert-success">
  <h3 class="text-sm font-bold">Ganador: gpt-4o</h3>
  <p class="text-xs opacity-80">42.9 t/s · TTFT 3148ms</p>
</div>
```

`opacity-80` inherits the daisyUI `success-content` text color (which is
already tuned for contrast on the alert's background) and just dims it
slightly for visual hierarchy. The title stays at full opacity.

**Rule:** inside daisyUI `alert-*`, `badge-*`, or any colored component,
use `opacity-*` to dim text — not `text-base-content/*`. The `base-content`
color is designed for the page background, not for colored surfaces.

**Seen in:** my_app_gateway BenchmarksLive winner banner — metrics text was
unreadable on the green success alert until `text-base-content/60` was
replaced with `opacity-80`.
