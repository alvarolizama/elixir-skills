# Stream Re-render Trap — show/hide content inside stream items

## The trap

When a LiveView renders a list with `phx-update="stream"`, the **item bodies only
re-render when the stream itself changes** (a `stream_insert`/`stream_delete`/
`stream_configure` op touches that item). A plain `assign(socket, :some_flag, x)`
on a *different* assign — e.g. an `expanded_alias_ids` `MapSet` used to drive
`:if` inside each stream item — does **not** re-render the items.

Symptom: clicking a per-card header to expand/collapse a section inside the card
does nothing visible. In tests, `element("#toggle-...") |> render_click()` then
`render(view)` still shows the collapsed markup, or the click event itself errors
because the target `:if`-hidden node was never sent to the client.

Root cause: `@streams.foo` is its own assign, diffed against the previous stream;
the item template captures the other assigns at stream-diff time and is not
re-evaluated for unrelated assign changes.

## The fix — client-side toggle (no server round-trip)

For a pure show/hide toggle, don't keep state in the socket at all. Drive it in
the DOM with `JS.toggle` / `JS.toggle_class`:

```elixir
# Public helper (template-visible; keep it `def`, not `defp`, to match the
# other template helpers in the module — LiveView render can call defp, but the
# codebase convention is public `def` for anything the ~H calls).
def toggle_providers_js(id) do
  JS.toggle(to: "#alias-providers-#{id}", display: "block")
  |> JS.toggle_class("rotate-90", to: "#alias-chevron-#{id}")
end
```

Template:

```heex
<%!-- Clickable header — pure client-side toggle --%>
<div id={"alias-header-#{model_alias.id}"} phx-click={toggle_providers_js(model_alias.id)}
     class="flex-1 cursor-pointer" title="Expandir / colapsar">
  <span id={"alias-chevron-#{model_alias.id}"} class="text-base-content/40 transition-transform">
    <.icon name="hero-chevron-right" class="w-4 h-4" />
  </span>
  {model_alias.name}
</div>

<%!-- Collapsible body — rendered but hidden by default --%>
<div id={"alias-providers-#{model_alias.id}"}
     class="mt-4 pt-4 border-t border-base-200" style="display: none">
  ...providers table + action buttons...
</div>
```

## Key details / pitfalls

- `JS.toggle/2` toggles **inline `display`** (the `:display` option is the value
  used when *showing*, default `"block"`). So mark the section initially hidden
  with `style="display: none"`, NOT a `hidden` attribute and NOT a `:if` (a `:if`
  removes it from the DOM and — per the trap above — won't come back on an assign
  change anyway).
- The content stays in the DOM (just `display:none`), so **LiveView tests still
  `has_element?` the inner buttons** — no need to simulate the expand click before
  asserting/clicking provider buttons. (If you switch to server-side `:if`, every
  existing test that clicks `#new-ap-*`/`#edit-ap-*`/`#toggle-ap-*` starts failing
  because the nodes aren't rendered.)
- Chevron rotation via `JS.toggle_class("rotate-90", ...)` needs the chevron span
  to have a stable `id` and a `transition-transform` class for the animation.
- Give the collapsible container a **per-item `id`** (`#alias-providers-<id>`) so
  the `JS.toggle(to: ...)` selector targets exactly one card — never a shared
  class across all stream items.

## When you DO need server-side per-item state

If collapse state must persist across reconnects or be shared, keep the flag on
the *stream item* itself (e.g. a struct field), or force a re-render by
re-`stream_insert`ing the affected item. Don't try to key it off a side `MapSet`
assign — that's the trap.
