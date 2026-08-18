---
name: phoenix-liveview-testing
description: "Use when writing Phoenix LiveView tests (LV 1.2+ API)."
---

# Phoenix LiveView Testing

## When to Use

- Writing ExUnit tests for LiveViews (`test/<app>_web/live/*_test.exs`).
- Debugging failing LiveView tests — especially `KeyError: key :assigns not found`.
- Verifying a LiveView's rendered state/payload that the UI receives (filters, graphs, hooks).

## Setup pattern

```elixir
use MyAppWeb.ConnCase, async: false
import Phoenix.LiveViewTest

setup %{conn: conn} do
  # Disable external calls (inference/embeddings/HTTP) that page mutations trigger,
  # else async tasks race test stubs. Restore in on_exit.
  # See elixir-build-troubleshooting "Flaky suite failures from env-injected inference"
  # for the env-stripped suite verification (env -u DRAN_INFERENCE_API_URL ... mix test).

  conn =
    conn
    |> Plug.Test.init_test_session(%{})
    |> Plug.Conn.put_session(:user, "test_user")
    |> Plug.Conn.put_session(:context_slug, "personal")

  {:ok, conn: conn}
end
```

Tests are sandboxed per test even at `async: false` — create the pages/relations each test needs in its own setup; nothing leaks between tests.

## CRITICAL: LiveView 1.2 removed `view.assigns`

In `phoenix_live_view` ≥ 1.2 the `Phoenix.LiveViewTest.View` struct has **no `assigns` field** (only `id, module, pid, proxy, endpoint, target`). `view.assigns.nodes` raises `KeyError`. This is the #1 failure when porting tests from LiveView 0.x–1.0 tutorials.

**Never read `view.assigns`.** Assert on what the user sees:

- `render(view)` → HTML string; `assert html =~ "..."`.
- For structured payloads the page renders into a data attribute (e.g. `data-graph={Jason.encode!(...)}`), parse it back. Phoenix HTML-escapes attribute values, so JSON quotes arrive as `&quot;` — unescape before decoding:

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

## Dispatching events

- Server event without a DOM element: `view |> render_hook("toggle_type", %{"type" => "todo"})` — then `render(view)` again for fresh HTML.
- UI-driven event: `view |> element("button", t("Nueva tarea")) |> render_click()`.
- Form submit: `view |> form("#form-id", %{...}) |> render_submit()`.

## Per-item buttons (many share one label)

Buttons carrying `phx-value-slug` (or any `phx-value-*`) make unambiguous selectors when many buttons share the same label — e.g. one "Archive" per kanban card:

```elixir
view |> element(~s(button[phx-value-slug="#{todo.slug}"])) |> render_click()
assert Brain.get_page_by_slug(todo.slug, context.id).archived == true
```

- `data-confirm` is client-side only — `render_click` fires the event without a dialog, so tests pass cleanly.
- A button nested inside a card that has its own `phx-click` (e.g. draggable kanban cards that navigate on click) needs `onclick="event.stopPropagation();"` in the template (my_app badges already do this). The `element(...)` selector targets only the inner button in tests, but real browsers need the guard or the card's event fires too.

## Gettext-aware assertions

When the app's default locale is Spanish (my_app), assertions must match the translated msgstr, not the English msgid:

```elixir
defp t(msgid), do: Gettext.gettext(DranWeb.Gettext, msgid)
assert html =~ t("Todo created.")
```

## Property-style assertions for filter/graph views

For views that filter nodes/edges, assert structural invariants instead of exact counts (DB state varies):

```elixir
defp assert_edges_connect_visible_nodes(graph) do
  ids = MapSet.new(graph["nodes"], & &1["id"])
  Enum.each(graph["edges"], fn e ->
    assert MapSet.member?(ids, e["source_id"])
    assert MapSet.member?(ids, e["target_id"])
  end)
end
```

## Testing LiveViews that load data via `start_async` / `assign_async`

When a LiveView kicks off async work (`start_async(socket, :name, fn -> ... end)` or `assign_async/3`) in `mount`/`handle_params`/`handle_event`, `live(conn, url)` returns **before** the task finishes. Assertions on data-driven markup race the task and flake: same seed passes solo, fails in a full run.

Sync the test with the LiveView process via `:sys.get_state/1` (flushes the mailbox, so any already-delivered async message has been processed), then poll a loading flag until the task lands:

```elixir
defp wait_loaded(view, attempts \\ 200)
defp wait_loaded(view, attempts) when attempts > 0 do
  state = :sys.get_state(view.pid)
  case get_in(state, [Access.key(:socket), Access.key(:assigns), Access.key(:stats_loading)]) do
    false -> view
    _other -> Process.sleep(10); wait_loaded(view, attempts - 1)
  end
end
defp wait_loaded(_view, 0), do: raise("async data never loaded")
```

Notes:

- `:sys.get_state(view.pid)` returns the GenServer state map; the socket lives under `:socket`, assigns under `:assigns`. Use `Access.key/1` chains — the struct has more keys than tutorials show.
- Poll a plain boolean assign the LiveView flips in `handle_async` (e.g. `stats_loading`), or pattern-match `%Phoenix.LiveView.AsyncResult{ok?: true}` when using `assign_async`.
- Call it right after `live/2` and after any `render_click` that re-triggers a load, **before** asserting on query-backed HTML. Tests that only check redirects, static chrome, or button classes don't need it.
- Do NOT fix the race with a bare `Process.sleep(500)` — that slows the suite and still flakes under load.
- `Postgrex.Protocol ... disconnected: client exited` in test logs is benign sandbox noise from the async task's DB connection closing, not a failure.

## Testing fire-and-forget `Task.start` + `handle_info` flows

A different async shape from `start_async`: the LiveView spawns a raw
`Task.start(fn -> result = Work.run(); send(parent, {:work_done, result}) end)`
inside `handle_event` and catches the message in `handle_info` (no
`handle_async`, no `%AsyncResult{}`). Neither the `:sys.get_state` poll above
nor `render_async/2` (LV ≥ 1.2 — only awaits `assign_async`/`start_async`
pids) can see that task. Test it in two deterministic halves — no sleeps:

1. **Intermediate ("running") state — assert on the `render_click` RETURN
   VALUE**, never on a later `render(view)` (that races the task's message).
   Mailbox ordering guarantees it: the task's `{:work_done, ...}` message is
   handled only *after* the current event reply is sent, so the returned HTML
   always shows the running state:

   ```elixir
   html = view |> element("#job-run-pagerank_nightly") |> render_click()
   assert html =~ t("Corriendo…")
   # Per-item state (MapSet of running keys — one shared boolean would
   # block every button): only THIS button is disabled.
   assert html =~ ~r/<button(?=[^>]*\bdisabled\b)(?=[^>]*id="job-run-pagerank_nightly")[^>]*>/
   refute html =~ ~r/<button(?=[^>]*\bdisabled\b)(?=[^>]*id="job-run-curation_agent_daily")[^>]*>/
   ```

   The lookahead regex is attribute-order-independent — never rely on
   `id=`/`disabled` render order inside the tag.

2. **Completion — drive `handle_info` directly**, then assert the flash and
   the cleared state:

   ```elixir
   send(view.pid, {:work_done, {:ok, %{}}})
   html = render(view)
   assert html =~ "Job completado"
   refute html =~ t("Corriendo…")
   ```

   The task→side-effect wiring (the real job writing its row) belongs in the
   context module's own test, not the LiveView test.

Notes:

- With `async: false` the sandbox runs in SHARED mode
  (`start_owner!(Repo, shared: not tags[:async])`), so the task's DB calls
  just work — no `Sandbox.allow` needed — and its writes join the test
  transaction (rolled back).
- The REAL task still runs during the test and sends its own duplicate
  message. Keep assertions insensitive to that (same flash text either way;
  assert after your manual `send`, which clears the state first) and clean up
  its rows defensively in `on_exit` if it writes to a shared context.
- `has_element?(view, "#toggle-id[checked]")` — CSS attribute-presence
  selector — asserts a checkbox's checked state without regexing tag order.

## Pitfalls

- **`%JS{}` struct literals don't work in HEEx templates.** Writing
  `%JS{push("event"), JS.dispatch("js:copy", to: "#el")}` inside a
  `phx-click={...}` attribute causes a compilation error:
  `expected key-value pairs in a map, got: push("event")`. Phoenix's `JS`
  module is designed for **chaining**, not struct construction. Two workarounds:
  1. **Colocated hook** (preferred for client-side logic like clipboard):
     Define a `<script :type={Phoenix.LiveView.ColocatedHook} name=".MyHook">`
     inside the `~H` sigil of the parent LiveView (not a function component),
     then reference it with `phx-hook=".MyHook"`.
  2. **Inline `JS` chain** (simple cases): use `JS.push("event") |> JS.dispatch(...)` —
     the pipe syntax works in HEEx because it's a function call, not a struct literal.
- **Core components don't accept arbitrary HTML attributes.** Components like
  `<.icon>`, `<.button>`, `<.input>` etc. only accept their declared `attr`s.
  Adding `data-copy-icon` or extra classes to `<.icon>` is silently ignored
  or warns with `--warnings-as-errors`. Wrap in a plain `<span>` or `<div>`
  when you need extra data attributes or styling:
  ```heex
  <span data-copy-icon><.icon name="hero-check" class="size-4" /></span>
  ```
- **Icon-only buttons break text selectors.** Moving a button (e.g. out of a page
  header into a floating action button / FAB) and restyling it as an icon-only
  circle silently breaks `element("button", t("Archive"))` — LiveViewTest matches
  by visible text. Either keep the gettext label (prefer a pill: icon + text) or
  update the selectors in the same change. Check `rg -n 't\("' test/` for selectors
  that reference the moved button's label before restyling it.
- **Toggle round-trip:** for toggleable UI (visibility filters, expand/collapse),
  dispatch the event twice and assert the state returns to the original — a cheap
  regression guard that catches off-by-one toggles.
- **`@impl true` grouping with `defp` between callbacks** — when adding new
  `handle_event/3` or `handle_info/2` clauses to a LiveView that already has
  existing ones, ALL clauses of the same callback must be contiguous in the
  source. If there's a `defp` helper between two groups of `handle_event/3`
  clauses, the compiler emits a warning (`@impl true def handle_event/3 was
  previously defined`), and with `--warnings-as-errors` it blocks compilation.
  Fix: move all `handle_event/3` clauses together, remove redundant
  `@impl true` annotations between clauses (only the first needs it), and put
  any `defp` helpers AFTER the last `handle_event/3` clause or BEFORE the first.
  Same applies to `handle_info/2` — don't interleave with `defp`.
- **Moving sections between LiveViews** — when refactoring (e.g. migrating alert
  tables from LogsLive to MonitorLive), the move touches 5 layers per section:
  (1) `mount/3` assigns, (2) PubSub subscriptions, (3) `handle_event` + `handle_info`
  handlers, (4) helper functions (`defp` that the template calls — promote to `def`),
  (5) the HEEx template block. After the move, run `mix compile --warnings-as-errors`
  to catch dead imports/aliases left behind in the source LiveView (e.g.
  `import Ecto.Query`, `alias RequestLog`, `alias Repo` that are now unused).
- **Forms with `onsubmit="this.method='delete'"` are unreliable.** That JS hack
  tries to change the form's method attribute on submit, but browsers don't honor
  it consistently and Phoenix never receives the DELETE. The form silently sends
  POST and the logout action never fires. Use Phoenix's standard `_method`
  override instead:

  ```heex
  <form action={~p"/session"} method="post">
    <input type="hidden" name="_method" value="delete" />
    <input type="hidden" name="_csrf_token" value={get_csrf_token()} />
    <button type="submit">Logout</button>
  </form>
  ```

  Test it with `Phoenix.ConnTest`: build a conn with `init_test_session`, post
  with `_method: "delete"`, and assert the redirect lands on `/login`.

## Tabbed LiveView pages (`handle_params` + `/resource/:tab`)

When a settings/admin page grows multiple sections (users, contexts, brain, models, system, danger), split it into tabs via `handle_params` instead of one long scroll. The route gets a `:tab` param; the LiveView assigns `active_tab` and renders conditionally.

**Router:**
```elixir
live "/settings", SettingsLive, :index        # default tab
live "/settings/:tab", SettingsLive, :index   # explicit tab
```

**LiveView:**
```elixir
@tabs ~w(users contexts brain models system danger)

@impl true
def handle_params(params, _url, socket) do
  tab = case params["tab"] do
    t when t in @tabs -> t
    _ -> "users"   # default
  end
  {:noreply, assign(socket, active_tab: tab)}
end
```

**Template:**
```heex
<div class="tabs tabs-border">
  <.link :for={tab <- @tabs} patch={~p"/settings/#{tab}"} class={["tab", @active_tab == tab && "tab-active"]}>
    {tab_label(tab)}
  </.link>
</div>

<div :if={@active_tab == "users"}><.users_section ... /></div>
<div :if={@active_tab == "brain"}><.brain_tuning_section ... /></div>
```

**Testing pitfall:** existing tests that hit `~p"/settings"` will only see the default tab's content. Update them to the explicit tab route (`~p"/settings/brain"`, `~p"/settings/system"`) or they'll fail with "expected to find X in HTML" — X now lives behind a different tab. Tests that assert ordering of sections on one page (e.g. "Brain tuning appears before Inference API") become obsolete — replace with a tab-navigation test.

## E2E auth tests (session + LiveView + controller)

For end-to-end auth flows that test session-based access (admin vs regular user, context scoping), use `init_test_session/2` (NOT `Plug.Conn.fetch_session/2` + `Plug.Conn.put_session/3`):

```elixir
# WRONG — raises ArgumentError: session not fetched
conn
|> Plug.Conn.fetch_session()
|> Plug.Conn.put_session(:user, user.email)

# CORRECT — one-shot session setup for tests
conn
|> init_test_session(%{user: user.email, context_slug: ctx.slug})
```

`Phoenix.LiveViewTest.live/2` returns `{:ok, view, html}` where `html` is already a **plain string** — do NOT pipe it through `Phoenix.HTML.safe_to_string/1` (that function expects `{:safe, iodata}` and crashes with `FunctionClauseError` on a plain string).

```elixir
{:ok, _view, html} = live(conn, ~p"/notes")
# html is already a string — assert directly
assert html =~ ~p"/settings"
refute html =~ ~p"/admin"
```

## Auth-gated routes (admin-only pages)

When a route moves behind an admin/auth plug (e.g. `/settings` piped through
`[:browser, :auth, :admin]`), every existing `live(conn, ~p"/settings")` in that
view's test starts failing with:

```
{:error, {:redirect, %{flash: %{"error" => "Admin access required"}, to: "/"}}}
```

or a bare `{:redirect, ..., to: "/login"}`. This is `live(conn, path)` **not**
raising — it returns `{:error, {:redirect, ...}}`, so the `{:ok, view, _html} =`
match blows up with a `MatchError`. The setup only *claims* a session user
(`Plug.Conn.put_session(:user, "test_user")`); it never inserts a matching row,
so the router's `require_login`/`require_admin` plug can't find the user and
halts with a redirect before the view mounts.

**Fix the setup, not the test bodies.** In `setup`, insert a real user whose
`email` equals the session value the plug looks up (and set `is_admin: true` when
the route is admin-gated). Idempotent create-or-fetch keeps re-runs clean of
`unique_constraint` violations:

```elixir
setup %{conn: conn} do
  # /settings is admin-only; the router's require_admin plug looks the session
  # email up in the DB and halts unless the user has is_admin: true.
  case Accounts.get_user_by_email("test_user") do
    nil -> {:ok, _u} = Accounts.create_user(%{email: "test_user", is_admin: true})
    _ -> :ok
  end

  conn =
    conn
    |> Plug.Test.init_test_session(%{})
    |> Plug.Conn.put_session(:user, "test_user")
    |> Plug.Conn.put_session(:context_slug, "personal")

  {:ok, conn: conn}
end
```

Account context module (`my_app.Accounts.create_user/1`, `get_user_by_email/1`)
already preloads what the view reads; keep using its public API rather than
`Repo.insert`. If you prefer not to touch the app's account context, insert the
`User` struct via `my_app.Accounts.User.changeset` instead — the point is a real
DB row, not how it gets there.

## Browser-side verification (complement to tests)

For LiveView hooks, after navigating to a route **from a login redirect** the hook may not mount on the first page load — reload/direct-navigate to the route to mount it. Read the element's data attribute via `browser_console` to confirm the real payload:

```js
(() => { const el = document.getElementById('graph-3d'); return JSON.stringify({canvas: el.querySelectorAll('canvas').length, graph: el.getAttribute('data-graph').length}) })()
```

## References

- `references/liveview-1.2-test-api.md` — session detail: the failure, the struct evidence, the working helper code.
