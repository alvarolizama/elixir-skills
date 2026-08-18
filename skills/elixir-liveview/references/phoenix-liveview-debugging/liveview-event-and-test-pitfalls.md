# LiveView event-binding and test-API pitfalls

Two recurring LiveView footguns hit during UI work (verified on Phoenix 1.8 /
LiveView 1.2, Elixir 1.20).

## 1. `onclick="event.stopPropagation()"` silently kills `phx-click`

Symptom: a button nested inside a clickable card (the card has `phx-click` to
navigate, the button is meant to do something else, e.g. archive) looks right,
clicking it does NOTHING — no event reaches the server, no console error, no
flash. Meanwhile the same button's `phx-click` works fine in a LiveView test
(`render_click` dispatches directly to the server, bypassing the browser).

Root cause: Phoenix LiveView uses **event delegation** — it listens for the
event on the LiveView root and finds the `phx-click` binding via
`e.target.closest("[phx-click]")`. An inline `onclick="event.stopPropagation()"`
on the inner button stops the bubble before it reaches the root, so LiveView
never sees the click. `stopPropagation()` does NOT stop other listeners on the
SAME element — but LiveView's listener is on the root (an ancestor), which the
bubble never reaches.

Fix: use LiveView's own binding attribute **`phx-click-stop-propagation`**
(boolean, no value) on the button, alongside `phx-click`. LiveView processes
the child's `phx-click` first, THEN stops propagation so the parent's `phx-click`
does not fire.

```heex
<div phx-click="show_page" phx-value-slug={item.slug}>
  <button
    type="button"
    phx-click="archive_todo"
    phx-value-slug={item.slug}
    phx-click-stop-propagation
  >
    archive
  </button>
</div>
```

Scope the fix: this applies to any element that has BOTH a `phx-click` AND needs
to not trigger an ancestor's `phx-click`. Links (`.link navigate=`) inside a
clickable card are NOT affected — their navigation binding lives on the same
`<a>` element, so an inline `onclick stopPropagation` there does not break the
navigate (only suppresses the ancestor's `phx-click`). Grep for
`onclick="event.stopPropagation()"` when hunting this class of bug:
`rg -n 'onclick="event.stopPropagation' lib/`.

## 2. LiveView 1.2 test API removed `view.assigns`

Symptom: `view.assigns.nodes` (or any `view.assigns`) crashes with
`KeyError: key :assigns not found in: #Phoenix.LiveViewTest.View<...>`.

Root cause: in LiveView 1.2 the `Phoenix.LiveViewTest.View` struct no longer
exposes `assigns` (struct fields are now `id, module, pid, proxy, endpoint,
target`). There is no public accessor for live assigns in the test API.

Fix: assert on the **rendered HTML** — `render(view)` and parse it. For data
carried in a JSON attribute (e.g. a 3D graph hook reading `data-graph`), parse
the attribute back and assert on the decoded map:

```elixir
defp graph_from_html(html) do
  [_, encoded] = Regex.run(~r/data-graph="([^"]*)"/, html)
  encoded
  |> String.replace("&quot;", "\"")
  |> String.replace("&amp;", "&")
  |> String.replace("&#39;", "'")
  |> Jason.decode!()
end

defp graph_from_view(view), do: view |> render() |> graph_from_html()
```

Then assert `graph_types(graph)`, node counts, etc. For state-toggle UI, drive
it via `render_hook(view, "event", %{...})` (or `element(...) |> render_click()`)
then `render(view)` again and assert on the new HTML. Events sent via
`render_hook`/`render_click` reach the server directly, so they pass even when
a client-side delegation bug (see pitfall 1) would break the real browser click.
