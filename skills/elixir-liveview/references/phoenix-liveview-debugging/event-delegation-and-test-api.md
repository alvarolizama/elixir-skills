# LiveView event delegation, HEEx comments, and the 1.2 test API

Three pitfalls that look unrelated but all bite in the same class of work
(nested clickable elements + LiveView tests + HEEx templates).

## 1. `onclick="event.stopPropagation()"` silently kills `phx-click`

**Symptom:** a button/span inside a clickable card (or any element whose
ancestor has its own `phx-click`) does nothing when clicked. No error in the
browser console, no `HANDLE EVENT` in the server logs — the event simply never
arrives.

**Why:** Phoenix LiveView (1.x) uses **event delegation**: it attaches listeners
at the LiveView root (or document) and relies on the click event *bubbling up* to
find the `phx-click` binding via `event.target.closest("[phx-click]")`. An inline
`onclick="event.stopPropagation()"` on the nested element stops the bubble before
it reaches the root, so LiveView never sees the click. It's an easy trap because
the inline handler *looks* like it's just guarding the parent's `phx-click`.

**Fix:** use LiveView's `phx-click-stop-propagation` attribute instead of a raw
inline `onclick`. LiveView processes the element's own `phx-click` first, *then*
stops propagation, so the child handler fires and the parent's `phx-click` does not.

```heex
<!-- Broken: phx-click="archive_todo" never fires -->
<button phx-click="archive_todo" phx-value-slug={todo.slug}
        onclick="event.stopPropagation();">archive</button>

<!-- Correct -->
<button phx-click="archive_todo" phx-value-slug={todo.slug}
        phx-click-stop-propagation>archive</button>
```

**Scope the fix to the class, not the site:** every element that pairs
`onclick="event.stopPropagation()"` with a `phx-click` is broken. Grep for
`onclick="event.stopPropagation` across the whole `lib/` before declaring the bug
fixed — badges, rows, and card actions all tend to use the same copy-pasted
pattern.

**Exception — real `<a>` navigation links:** a `<.link navigate=...>` inside a
clickable card uses a *same-element* onclick for the SPA pushState, not root
delegation. `stopPropagation()` there does NOT break the link's navigation (it
only stops the parent `phx-click`). Only convert elements that carry their own
`phx-click`; leave plain navigation links alone.

## 2. HEEx comment syntax: `<%--` is a SyntaxError, `<%!--` is the comment

In a `~H"""` template, `<%-- ... --%>` fails to compile with
`(SyntaxError) syntax error before: '--'`. The Phoenix/Elixir comment delimiter
is `<%!-- ... --%>` (note the `!`). `<!-- ... -->` (HTML comment) also works but
is emitted to the DOM; use `<%!--` for compiler-only comments.

## 3. Phoenix LiveView 1.2 removed `view.assigns` from the test API

In LiveView 1.2 the `Phoenix.LiveViewTest.View` struct no longer has an
`assigns` field (struct fields are now `id, module, pid, proxy, endpoint,
target`). Reading `view.assigns` raises `KeyError: key :assigns not found`.

**Workaround:** assert on the rendered HTML. For components that serialize state
into a data attribute (e.g. a graph passed as `data-graph={Jason.encode!(...)}`),
parse it back:

```elixir
defp graph_from_html(html) do
  [_, encoded] = Regex.run(~r/data-graph="([^"]*)"/, html)
  encoded
  |> String.replace("&quot;", "\"")
  |> String.replace("&amp;", "&")
  |> String.replace("&#39;", "'")
  |> Jason.decode!()
end
```

To toggle a hidden section, click its `data-testid` then `render(view)` and
assert on the newly-rendered nodes — do not assume a previously-always-visible
block is still visible after you make it conditional.
