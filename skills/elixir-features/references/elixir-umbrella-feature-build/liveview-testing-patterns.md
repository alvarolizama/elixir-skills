# my_app LiveView Testing Patterns

Reference for writing LiveView tests in the my_app Phoenix app. my_app had no
LiveView tests until the 3D graph view integration — these patterns were
established then and should be followed for all future LiveView tests.

## Prerequisites

### 1. Import `Phoenix.LiveViewTest` in ConnCase

`test/support/conn_case.ex` must import `Phoenix.LiveViewTest` so tests can use
`live/2`, `element/2`, `render_click/1`, `render/1`:

```elixir
# test/support/conn_case.ex
using do
  quote do
    @endpoint DranWeb.Endpoint
    use DranWeb, :verified_routes
    import Plug.Conn
    import Phoenix.ConnTest
    import Phoenix.LiveViewTest        # ← add this
    import DranWeb.ConnCase
  end
end
```

### 2. Session setup — `init_test_session` required

my_app's auth is session-based (`Plug.Conn.get_session(:user)`). The ConnCase
builds a bare conn without piping through the browser pipeline, so
`fetch_session/2` is never called. Calling `put_session/2` directly raises
`ArgumentError: session not fetched, call fetch_session/2`.

**Fix:** call `Plug.Test.init_test_session/1` first:

```elixir
conn =
  conn
  |> Plug.Test.init_test_session(%{})
  |> Plug.Conn.put_session(:user, "test_user")
  |> Plug.Conn.put_session(:context_slug, "personal")
```

### 3. Disable inference in test setup

`Brain.create_page/1` triggers `PageAugmenter.schedule/1` and
`Embeddings.schedule/1`, which attempt HTTP calls to the inference API. In
tests, disable inference entirely:

```elixir
setup do
  original = Application.get_env(:my_app, :inference)

  Application.put_env(:my_app, :inference,
    base_url: nil,           # ← key: makes Inference.enabled?/0 return false
    api_key: nil,
    embedding_model: nil,
    rerank_model: nil,
    markitdown_model: nil,
    timeout: 100,
    schedule_async: false
  )

  on_exit(fn ->
    if is_nil(original) do
      Application.delete_env(:my_app, :inference)
    else
      Application.put_env(:my_app, :inference, original)
    end
  end)

  :ok
end
```

`base_url: nil` is what makes `my_app.Inference.Config.enabled?()` return `false`,
short-circuiting the augmenter before any HTTP call.

### 4. Test database must have the "personal" context seeded

my_app's tests rely on `Brain.get_context_by_slug("personal")` returning a
context. The test DB is seeded by `mix ecto.reset` (which runs
`priv/repo/seeds.exs`). If the test DB is fresh or missing the context, all
tests that use it will fail with `MatchError` on `nil`.

```bash
MIX_ENV=test mix ecto.reset   # creates test DB + runs migrations + seeds
```

## Test structure

### Basic LiveView test template

```elixir
defmodule DranWeb.SomeLiveTest do
  use DranWeb.ConnCase, async: false

  alias my_app.Brain

  setup %{conn: conn} do
    # Disable inference (see above)
    # ...

    context = Brain.get_context_by_slug("personal")

    # Create test data
    {:ok, _page} = Brain.create_page(%{
      context_id: context.id,
      title: "Test Page",
      body: "test body",
      page_type: "note"
    })

    # Log in
    conn =
      conn
      |> Plug.Test.init_test_session(%{})
      |> Plug.Conn.put_session(:user, "test_user")
      |> Plug.Conn.put_session(:context_slug, "personal")

    {:ok, conn: conn}
  end

  test "renders the page", %{conn: conn} do
    {:ok, view, html} = live(conn, ~p"/some-route")

    assert html =~ "Test Page"
  end
end
```

### Testing event handlers (toggle, click, form submit)

Use `element/2` + `render_click/1` to fire `phx-click` events:

```elixir
test "toggles view mode", %{conn: conn} do
  {:ok, view, html} = live(conn, ~p"/graph")

  # Assert initial state
  assert html =~ ~s(phx-hook="GraphPanZoom")
  refute html =~ ~s(phx-hook="Graph3D")

  # Click the toggle button
  view
  |> element("button[phx-value-mode='3d']")
  |> render_click()

  html = render(view)

  # Assert new state
  assert html =~ ~s(phx-hook="Graph3D")
  refute html =~ ~s(phx-hook="GraphPanZoom")
end
```

### Testing LiveComponents: `render_hook` is for JS hooks, NOT `phx-click` (CRITICAL)

**This section previously said "test a stateful LiveComponent by targeting its root and using `render_hook/3`." That is only true when the component carries an actual `phx-hook` JS hook on the element you're targeting.** `render_hook/3` fires a LiveView *hook event* — it only works on elements that have a `phx-hook` attribute. If the component's interactions are plain `phx-click` / `phx-submit` on inner `<button>`/`<form>` elements (no JS hook), `render_hook` raises:

```
** (ArgumentError) element selected by "#chat-widget" does not have phx-hook attribute
```

This bit the chat widget (2026-07-17): the CommandPalette tests used `render_hook("toggle", %{})` successfully because CommandPalette has a `phx-hook="CommandPalette"` JS hook on its root. The chat widget has no JS hook — its FAB is a plain `<button phx-click="toggle">` — so every `render_hook` call failed.

**Choose the driver by what the element actually carries:**

| Component interaction | Test driver |
|---|---|
| Root/element has `phx-hook="SomeHook"` (real JS hook) | `render_hook/3` |
| Plain `<button phx-click="event" phx-target={@myself}>` | `element("#id") \|> render_click()` |
| `<form phx-submit="event" phx-target={@myself}>` | `element("#id-form") \|> render_submit(%{"field" => "val"})` |

For `phx-click`/`phx-submit` components, add **stable DOM IDs** to the interactive elements in the HEEx so tests don't depend on classes or structure:

```heex
<button id={"#{@id}-fab"} phx-click="toggle" phx-target={@myself} ...>
<form id={"#{@id}-form"} phx-submit="send" phx-target={@myself} ...>
<button id={"#{@id}-clear"} phx-click="clear" phx-target={@myself} ...>
```

Then:

```elixir
test "toggle opens the chat panel", %{conn: conn} do
  {:ok, view, _html} = live(conn, ~p"/")
  view |> element("#chat-widget-fab") |> render_click()
  assert render(view) =~ t("Brain Copilot")
end

test "send shows the optimistic message", %{conn: conn} do
  {:ok, view, _html} = live(conn, ~p"/")
  view |> element("#chat-widget-fab") |> render_click()
  view |> element("#chat-widget-form") |> render_submit(%{"text" => "Hello"})
  assert render(view) =~ "Hello"
end
```

**Asserting a panel is closed:** don't `refute html =~ t("Panel Title")` — the title may legitimately appear in an always-visible `aria-label` on the FAB. Assert on an element that only exists when the panel is open:

```elixir
# GOOD — the form only renders when open
refute html =~ ~s(id="chat-widget-form")
# BAD — "Brain Copilot" is also in the FAB's aria-label
refute html =~ t("Brain Copilot")
```

The `render_hook` examples below are kept for components that genuinely use JS hooks (CommandPalette). Verify which mechanism your component uses before copying either pattern.

### Testing LiveComponents via `render_hook` (stateful components with a real JS hook)

When a stateful LiveComponent is rendered inside a parent LiveView via
`<.live_component module={...} id="..." />`, you test it by targeting the
component's root element and using `render_hook/3` (not `render_click`):

```elixir
test "toggle event opens the modal", %{conn: conn} do
  {:ok, view, _html} = live(conn, ~p"/")

  # The component's root div has id="command-palette"
  view
  |> element("#command-palette")
  |> render_hook("toggle", %{})

  html = render(view)
  assert html =~ ~s(role="dialog")
end

test "typing a query shows search results", %{conn: conn} do
  {:ok, view, _html} = live(conn, ~p"/")

  view
  |> element("#command-palette")
  |> render_hook("toggle", %{})

  html =
    view
    |> element("#command-palette")
    |> render_hook("search", %{"query" => "Elixir"})

  assert html =~ "Elixir Concurrency Guide"
end
```

**Key points:**
- `render_hook/3` sends a LiveView event to the element — the component must
  have `phx-target={@myself}` on its root for events to route to its
  `handle_event/3`.
- `render_hook` returns the updated HTML of the whole view (not just the
  component), so you can assert on any part of the rendered output.
- For `phx-keyup` events, send the event name as the second argument and
  the form params as the third: `render_hook("search", %{"query" => "..."})`.
- You can also test the closed state by asserting on the initial `live/3`
  HTML before any hooks are fired:

```elixir
test "renders root container but no overlay when closed", %{conn: conn} do
  {:ok, _view, html} = live(conn, ~p"/")

  assert html =~ ~s(id="command-palette")
  assert html =~ ~s(phx-hook="CommandPalette")
  refute html =~ ~s(role="dialog")
end
```

### HEEx HTML-escapes data attributes (CRITICAL)

HEEx HTML-escapes quotes in attribute values. JSON in a `data-graph`
attribute will have `"` rendered as `&quot;` in the test HTML output.

```elixir
# WRONG — fails because the HTML has &quot;nodes&quot;: not "nodes":
assert html =~ ~s("nodes":)

# RIGHT — match on the bare key name without quotes:
assert html =~ "nodes"
assert html =~ "edges"
```

This applies to any attribute that contains JSON or quoted strings. When
asserting on attribute content in LiveView tests, either:
- Match on bare substrings without quotes, or
- Use `Floki`/regex to parse and decode the attribute value, or
- Assert on the rendered DOM structure rather than raw HTML string matching.

### `async: false` for tests that modify Application env

Tests that call `Application.put_env/3` in setup should use `async: false`
to avoid race conditions with other tests running in parallel that might
read the same env config.

## Asserting on localized (gettext) strings in tests (CRITICAL)

my_app's default locale is `"es"` (`DranWeb.Gettext` with `default_locale: "es"`).
This means **all rendered HTML comes back in Spanish**, not English. A test
that asserts `assert html =~ "Activity"` will FAIL because the rendered text
is `"Actividad"`.

### The problem: `gettext/1` is undefined in test modules

`DranWeb.ConnCase` does NOT import the `gettext` macro. Calling
`gettext("Activity")` in a test file fails at compile time:

```
error: undefined function gettext/1 (expected DranWeb.ActivityLiveTest to
define such a function or for it to be imported, but none are available)
```

This is different from LiveView source files, which get `gettext` via
`use DranWeb, :live_view` → `html_helpers()` → `use Gettext, backend: DranWeb.Gettext`.

### The fix: call the Gettext backend function directly

```elixir
defmodule DranWeb.SomeLiveTest do
  use DranWeb.ConnCase, async: false

  # Runtime gettext — resolves to the es translation at test time
  defp t(msgid), do: Gettext.gettext(DranWeb.Gettext, msgid)

  test "renders the header", %{conn: conn} do
    {:ok, _view, html} = live(conn, ~p"/activity")

    assert html =~ t("Activity")        # matches "Actividad"
    assert html =~ t("Created")         # matches "Creado"
  end
end
```

**Key points:**
- `Gettext.gettext(DranWeb.Gettext, msgid)` is the **runtime function** form
  (module + function), not the compile-time macro. It works anywhere.
- `DranWeb.Gettext.gettext(msgid)` does NOT work — `gettext/1` is not a
  public function on the backend module. The error suggests `lgettext/4` or
  `lngettext/6` as alternatives, but `Gettext.gettext/2` is the correct API.
- For strings that haven't been extracted/translated yet (new msgids not in
  the `.po` files), `Gettext.gettext/2` returns the msgid unchanged — so
  `t("just now")` returns `"just now"` (English) until a translation is added.
  This is expected gettext behavior for untranslated strings.
- For interpolation in tests, use `Gettext.gettext(DranWeb.Gettext, msgid, bindings)`:
  `t = Gettext.gettext(DranWeb.Gettext, "%{n}m ago", n: 5)`.

### When to use `t/1` vs raw strings in tests

| Assertion target | Use `t/1`? | Why |
|---|---|---|
| UI labels rendered via `gettext()` | **Yes** | They're translated to es |
| Slugs, titles, body content from DB | No | Not localized |
| CSS classes, HTML attributes | No | Not localized |
| New strings not yet in `.po` files | Either works | `t/1` returns the English msgid |

## Testing PubSub `handle_info` live updates

When a LiveView subscribes to a PubSub topic (e.g. `"brain:<context_id>"`)
and updates its assigns in `handle_info({:page_changed, _action, _page}, socket)`,
you can test the live update by:

1. Mount the LiveView (which subscribes to the topic).
2. Trigger the action that broadcasts (e.g. `Brain.create_page/1`).
3. `Process.sleep(50)` to let the message propagate.
4. `render(view)` and assert on the updated HTML.

```elixir
test "updates live when a new page is created (handle_info)", %{conn: conn} do
  {:ok, view, html} = live(conn, ~p"/activity")
  assert html =~ t("Created")

  context = Brain.get_context_by_slug("personal")

  {:ok, _page2} =
    Brain.create_page(%{
      context_id: context.id,
      title: "Second Page",
      body: "Another page",
      page_type: "note"
    })

  # The broadcast from create_page reaches the LiveView's handle_info.
  # Give it a moment to process the message and re-render.
  Process.sleep(50)

  html = render(view)
  assert html =~ "second-page" or html =~ "Second Page"
end
```

**Why `Process.sleep(50)`:** PubSub broadcasts are asynchronous. The
`Brain.create_page/1` call broadcasts `{:page_changed, :created, page}` to
`"brain:<context_id>"`, but the LiveView's `handle_info` runs in a separate
process. The 50ms sleep gives the BEAM time to deliver and process the
message before the test asserts on the re-rendered HTML. If 50ms is flaky on
CI, bump to 100ms — the test is still fast.

**Alternative without sleep:** use `Phoenix.PubSub.broadcast/3` directly in
the test to control timing, then `render(view)` immediately. But the
`Brain.create_page/1` approach is more realistic (tests the real broadcast
path) and the sleep is negligible.

## Testing page detail views with relations (backlinks)

When testing a page detail LiveView that renders the `page_detail` shared
component with a `relations` assign, create two pages and a relation between
them in setup, then mount the target page and assert on the backlinks
section content.

### Setup pattern

```elixir
setup %{conn: conn} do
  # Disable inference (standard pattern — see above)
  # ...

  context = Brain.get_context_by_slug("personal")

  # Create source page (will link TO the target)
  {:ok, source} =
    Brain.create_page(%{
      context_id: context.id,
      title: "Source Page",
      body: "This page links to the target",
      page_type: "note"
    })

  # Create target page (will receive the backlink)
  {:ok, target} =
    Brain.create_page(%{
      context_id: context.id,
      title: "Target Page",
      body: "This page is linked from the source",
      page_type: "note"
    })

  # Create a relation: source -> target (so target has an inbound backlink)
  {:ok, _relation} =
    Brain.create_relation(%{
      source_id: source.id,
      target_id: target.id,
      relation_type: "related"
    })

  # Log in (standard session setup)
  conn =
    conn
    |> Plug.Test.init_test_session(%{})
    |> Plug.Conn.put_session(:user, "test_user")
    |> Plug.Conn.put_session(:context_slug, "personal")

  {:ok, conn: conn, source: source, target: target}
end
```

### Assertion patterns

```elixir
test "shows 'Linked from (1)' with source title on the target page", %{
  conn: conn,
  target: target,
  source: source
} do
  {:ok, _view, html} = live(conn, ~p"/notes/#{target.slug}")

  # The backlinks section header with count (localized via t/1)
  assert html =~ t("Linked from")
  assert html =~ "(1)"

  # The source page title appears as a backlink
  assert html =~ source.title

  # The source page is a link to its detail view
  assert html =~ "href=\"/notes/#{source.slug}\""

  # The relation type badge is present
  assert html =~ "related"
end

test "shows 'No backlinks yet' empty state on a page with no inbound", %{
  conn: conn,
  source: source
} do
  {:ok, _view, html} = live(conn, ~p"/notes/#{source.slug}")
  assert html =~ t("No backlinks yet")
end
```

**Key points:**
- `Brain.create_relation/1` accepts a map with `source_id`, `target_id`, and
  `relation_type`. The relation is directed: source → target. The target
  page sees it as an inbound (backlink) relation.
- Use `t/1` for all gettext strings — the rendered HTML is in Spanish.
- The count `(1)` is a plain string in the HTML, not localized — assert on
  it directly.
- The relation type (`"related"`) is a DB value, not localized — assert on
  it directly.
- For the empty state, visit the SOURCE page (which has no inbound
  relations, only outbound).

## runtime.exs endpoint conflict

my_app's `config/runtime.exs` unconditionally sets `server: true` and
`port: 4000` (lines 24-26) for ALL environments, overriding the test config's
`server: false`. If a dev server is running on port 4000, `mix test` fails
with `:eaddrinuse`.

This is a pre-existing config issue. The workaround is to stop any running
dev server before running tests. Do NOT modify `runtime.exs` for this — it's
out of scope for feature work.
