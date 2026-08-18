---
name: phoenix-liveview-debugging
description: "Debug and build Phoenix LiveView: assign-flow tracing, forms, testing, realtime UI, stream traps, and CRUD patterns. Umbrella skill for all LiveView work."
version: 2.0.0
author: Álvaro Lizama
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [phoenix, liveview, debugging, elixir, heex, troubleshooting, testing, forms, realtime, crud]
    related_skills: [systematic-debugging, elixir-build-troubleshooting, phoenix-heex-design-system]
---

# Phoenix LiveView — Umbrella Skill

All Phoenix LiveView work: debugging, forms, testing, realtime UI, CRUD patterns.

## Quick Navigation

| Task | Reference |
|------|-----------|
| **Debugging assigns, events, stale UI** | This file (core principles below) |
| **Testing LiveViews (LV 1.2+ API)** | `references/testing.md` |
| **CRUD forms — add/edit modals, consistency** | `references/forms.md` |
| **Realtime UI — Presence, in-flight, drag-drop, PubSub** | `references/realtime.md` |
| **Form/select traps (silent failures)** | `references/form-select-traps.md` |
| **Stream vs assign (when to use which)** | `references/liveview-stream-vs-assign.md` |
| **Heroicon attribute traps** | `references/heroicon-attr-traps.md` |
| **On-mount assign flow** | `references/on-mount-assign-flow.md` |
| **HEEx parser and clause bugs** | `references/heex-parser-and-clause-bugs.md` |
| **Layout assign boundary** | `references/layout-assign-boundary.md` |

## When to Use

- Debugging any Phoenix LiveView symptom: wrong/empty values in the UI, stale
  assigns, missing updates after events, session/auth context issues, or layout
  components that render defaults instead of real data.
- Writing or fixing LiveView tests (LV 1.2+ API changes).
- Building or refactoring CRUD forms (inline → modal, add/edit consistency).
- Adding realtime UI: Presence, in-flight counters, drag-drop, PubSub-driven tables.

## Core Principle

LiveView has a **two-layer assign boundary** that is the source of most
non-crash bugs:

1. **Socket assigns** — set in `mount/3`, `handle_event/3`, `handle_params/3`
2. **Function component assigns** — passed as arguments to components

The boundary between them is where data gets lost. See the detailed references
above for specific failure modes and fixes.

## Stream vs Assign — The One Rule

| Use `stream` when… | Use `assign` when… |
|---|---|
| The list is large (100+ items) and mostly read-only | The list is small (<50 items) |
| Items are independent — no global state affects them | Items contain interactive sub-panels driven by global assigns |
| You only append/prepend/delete (chat messages, log entries) | You need inline forms, toggles, or conditional sections inside items |
| Performance matters (avoid full re-render) | Correctness matters (content must reflect current assigns) |

See `references/liveview-stream-vs-assign.md` for the full debugging path.

## The `<.form>` Wrapper Rule

A bare `<select phx-change>` outside a `<.form>` **silently fails** — the
event never reaches the server. Always wrap:

```heex
<%!-- BROKEN --%>
<select phx-change="set-timezone" name="timezone">...</select>

<%!-- FIXED --%>
<.form for={%{}} phx-change="set-timezone">
  <select name="timezone">...</select>
</.form>
```

See `references/form-select-traps.md` for the full pattern.

## Common Tasks

### Debug a stale assign

1. Check which assign the template reads (`@current_user.timezone` vs `@timezone`)
2. Check the event handler updates BOTH the flat assign AND the source struct
3. Add `IO.inspect` to the handler to trace the assign chain
4. Verify the form wrapper (if applicable)

### Write a LiveView test (LV 1.2+)

See `references/testing.md` — `view.assigns` was removed in LV 1.2. Assert on
`render(view)` HTML or parsed data attributes instead.

### Convert inline form to modal

See `references/forms.md` — full recipe for add/edit consistency, modal
conversion, and field parity.

### Add Presence or in-flight tracking

See `references/realtime.md` — Phoenix.Presence setup, ETS in-flight registry,
PubSub debouncing, drag-drop sortable rows.

## Verification Checklist

- [ ] The assign the template reads matches the assign the handler updates
- [ ] `<select>` elements with `phx-change` are wrapped in `<.form>`
- [ ] Stream items don't depend on global assigns (or use `assign` instead)
- [ ] Tests use `render(view)` not `view.assigns` (LV 1.2+)
- [ ] Event handlers update both the flat assign and the source struct
- [ ] `mix test <file>` passes before committing

LiveView has a **two-layer assign boundary** that is the source of most
non-crash bugs:

1. **Socket assigns** — set in `mount/3` and `handle_event/3` via
   `Phoenix.Component.assign/2`. These live on the LiveView process.
2. **Function-component attrs** — passed explicitly in HEEx via
   `<Layouts.app attr={@assign}>`. Function components do **NOT** inherit
   socket assigns. They only see what the render block explicitly forwards.

When a function component shows a default/empty value, the bug is almost always
a missing attr-forwarding in the render block, NOT a data or type problem.

## The Silent-Default Pitfall (most common LiveView UI bug)

```elixir
# layouts.ex — the component declares a default
attr :page_counts, :map, default: %{}

def context_selector(assigns) do
  ~H"""
  {Map.get(@page_counts, ctx.id, 0)}  <%-- shows 0 even when data exists --%>
  """
end
```

```elixir
# some_live.ex — the LiveView sets the assign but DOESN'T forward it
def mount(_params, session, socket) do
  {socket, _} = Auth.assign_to_socket(socket, session)  # sets :page_counts
  {:ok, socket}
end

def render(assigns) do
  ~H"""
  <Layouts.app
    flash={@flash}
    contexts={@contexts}
    <%-- page_counts={@page_counts} IS MISSING --%>
  >
    ...
  </Layouts.app>
  """
end
```

The attr's `default: %{}` silently masks the missing forwarding. No error, no
warning — just `0` or an empty map in the UI. The data layer is correct; the
wiring is broken.

### Investigation Path for "value shows as default/empty in UI"

1. **Find where the assign is SET** on the socket — `search_files` for
   `assign.*:the_assign_name` across `lib/`.
2. **Find where the value is READ** — `search_files` for `@the_assign_name` or
   `Map.get(@the_assign_name` in `.ex`/`.heex` files.
3. **Check the boundary**: is the read site inside a **function component**
   (declared with `attr`)? If yes, the `@` refers to the **attr**, not the socket
   assign. The attr must be explicitly forwarded in every `<Component ...>` call.
4. **Grep for the forwarding**: `search_files` for `the_assign_name=` (with the
   equals sign, in HEEx attr-passing position) across the LiveView directory.
   Zero matches = confirmed missing forwarding.
5. **Check the attr declaration**: does it have `default: ...`? That's what's
   silently masking the bug.

### Why direct DB / type checks are a red herring here

When the symptom is "shows 0/empty", the instinct is to check types (binary_id
mismatch? string vs atom key?) and DB state. In LiveView attr-forwarding bugs,
both are correct — the data never reaches the component. Verify the wiring
first (steps 1–4 above) before reaching for DB probes.

## Root-Cause Fix Options (ranked by blast radius)

Once confirmed as a missing attr-forwarding, there are three fixes — pick by
how many callers would need touching:

### 1. Per-caller attr forwarding (22+ files) — last resort

Add `the_assign={@the_assign}` to every `<Layouts.app ...>` call. Correct but
touches every LiveView and silently breaks again the next time someone adds a
LiveView and forgets the attr.

### 2. Self-fetch in the component with explicit-attr override — preferred for app-wide layout assigns

Make the component compute the value itself when the attr wasn't passed,
keeping the attr as an explicit override:

```elixir
def app(assigns) do
  # If the caller didn't forward page_counts, compute them here so the
  # sidebar never silently shows "Context (0)".
  page_counts =
    case assigns[:page_counts] do
      m when is_map(m) and map_size(m) > 0 -> m
      _ ->
        try do
          MyApp.Brain.page_counts_by_context()
        rescue
          _ -> %{}
        catch
          _, _ -> %{}
        end
    end

  assigns = assign(assigns, :page_counts, page_counts)
  ~H\"\"\" ... \"\"\"
end
```

Properties:
- **Zero caller changes** — all existing LiveViews keep working, and future
  ones get correct behavior for free.
- **Explicit attr still wins** — a caller that passes `page_counts={...}` (or
  a test that injects a fixture) overrides the fetch, because the `case` only
  falls through on `nil` / `%{}`.
- **`try/rescue/catch` fallback** — matches the existing `compute_counts/1`
  pattern in the same file; if the DB isn't up (tests, seeds, `mix run`), the
  component degrades to `%{}` instead of crashing. Without the rescue, tests
  that render the layout without a repo will blow up.
- **Non-empty guard** (`map_size > 0`) — treat an explicitly-passed empty map
  the same as "not passed". This matters when the plug assigns `%{}` on
  sessions with no contexts.

This is the right fix when the assign is app-wide (page counts, current user,
locale) and sourced from a single context function. Used in production on the
MyApp page-count bug — 22 LiveViews fixed with one component edit, 250/250
tests green.

### 3. LiveComponent with its own `update/2` — only when the layout needs its own events

Heavier; justified only if the layout itself handles events for the data.

## Connected vs Disconnected Mount

LiveView `mount/3` runs **twice**: once disconnected (initial HTTP request) and
once connected (WebSocket). Code that depends on `connected?/1`:

```elixir
def mount(params, session, socket) do
  if connected?(socket), do: Process.send_after(self(), :tick, 1000)
  {:ok, socket}
end
```

- Data assigned only in the connected branch won't exist on first paint.
- Subscriptions (`Phoenix.PubSub.subscribe`) only in the connected branch are
  correct, but events from them arrive only after WebSocket upgrade.
- If a value is missing on first load but appears after an interaction, suspect
  a `connected?` branch split.

## Session and Auth Context Flow

Auth/context data flows through the LiveView `session` map (set by plugs in the
browser pipeline), not through the LiveView's own params:

```
Router :browser pipeline → plugs (fetch_session, auth, fetch_context_cookie)
  → session map → LiveView mount(_params, session, socket)
    → assign_to_socket(socket, session) → socket assigns
      → render → <Layouts.app attr={@assign}>
```

When debugging "wrong context" or "missing user" in a LiveView:

1. Check the **plug pipeline** in `router.ex` — is the auth/context plug in the
   `:browser` pipeline or a specific `:auth` pipeline? Is the LiveView route
   behind the right pipeline?
2. Check `assign_to_socket` (or equivalent) — does it read all needed keys from
   `session`? Does it set all assigns the render block forwards?
3. Signed cookies (e.g. `dran_last_context`) are restored by a plug **before**
   the LiveView connects — verify the plug runs in the right pipeline.

### LiveView session keys are STRINGS, plug session keys are atoms

A plug does `put_session(:user_id, id)` and reads it back as `conn` session
atom keys — but in `on_mount/4` and `mount/3`, the LiveView session map has
**string keys**. An on_mount hook that does `session[:user_id]` gets `nil`
every time and redirects to /login even with a perfectly valid session — the
telltale is `live()` tests returning `{:error, {:redirect, %{to: "/login"}}}`
right after a successful login post. Read defensively:

```elixir
defp fetch_user(session) do
  case session["user_id"] || session[:user_id] do
    nil -> nil
    id -> Accounts.get_user(id)
  end
end
```

### `live_session` placement pitfalls (router)

Two silent killers when adding a `live_session` to the router:

1. **Outside an aliased `scope`, bare module names resolve to top-level
   `Elixir.*`.** `live "/dashboard", DashboardLive` inside a bare
   `live_session` block (not wrapped in `scope "/", MyAppWeb`) compiles the
   route to `Elixir.DashboardLive` — which doesn't exist. Symptom: router
   `__checks__` warning "DashboardLive.__live__/0 is undefined (module
   DashboardLive is not available or is yet to be defined)", fatal under
   `--warnings-as-errors`, and it survives `mix compile` because the beam
   for the REAL module exists. Fix: wrap the `live_session` in
   `scope "/", MyAppWeb do ... end`.
2. **No `pipe_through :browser` = no session, no plugs.** A `live_session`
   outside the browser pipeline never runs `fetch_session` or your auth
   plugs, so `session` in `mount` is empty and every authenticated route
   redirects. The `live_session` must sit inside a scope that pipes through
   `:browser`.

### Test pattern: session login then `live/2`

The canonical way to drive an authenticated LiveView test through the real
session controller (not a hand-rolled `conn |> init_test_session`):

```elixir
conn =
  conn
  |> post(~p"/login", %{email: user.email, password: password})
  |> recycle()                       # carries the session cookie forward

{:ok, view, html} = live(conn, ~p"/dashboard")
```

Without `recycle/1`, the post-login conn is already a 302 response and
`live/2` on it re-triggers the on_mount redirect (`{:error, {:redirect, ...}}`
with the login flash still in it — confusing, looks like an auth bug).

And when asserting on LiveView HTML: `live/2`'s returned `html` is the
**static disconnected render** — content that only exists after the connected
mount (or behind a data-conditional like an empty state) isn't there. Use
`render(view)` for assertions about the live state, `html` only for
static-shell checks.

## PubSub Event Flow

When a LiveView doesn't update after a background change:

1. **Subscribe** — `Phoenix.PubSub.subscribe/2` in `mount` (usually guarded by
   `connected?/1`). Topic string must match the broadcast topic exactly.
2. **Broadcast** — the context/worker module calls `Phoenix.PubSub.broadcast/3`
   with the same topic. Check for string-interpolation mismatches
   (`"brain:#{id}"` vs `"brain:" <> id` — same result, but verify `id` is the
   same value/type at both sites).
3. **Handle** — `handle_info/2` in the LiveView must pattern-match the event
   tuple shape broadcast. A `{:page_changed, :updated, page}` broadcast needs a
   matching `handle_info({:page_changed, _action, _page}, socket)`.

### Canonical wiring: realtime list/board that follows background writes

The complete pattern for "page should update live when an agent/MCP/another
tab writes" — used on the MyApp kanban board:

```elixir
# 1. Broadcast lives in the context layer (added once, benefits all LVs):
def broadcast_page_change(context_id, action, page) do
  Phoenix.PubSub.broadcast(MyApp.PubSub, "brain:#{context_id}", {:page_changed, action, page})
end

# 2. LiveView mount — subscribe only when connected:
def mount(_params, session, socket) do
  {socket, context} = Auth.assign_to_socket(socket, session)
  if connected?(socket) and context do
    Phoenix.PubSub.subscribe(MyApp.PubSub, "brain:#{context.id}")
  end
  {:ok, socket}
end

# 3. handle_info — reload the collection, guarded by live_action:
@impl true
def handle_info({:page_changed, _action, _page}, socket) do
  if socket.assigns.live_action == :index and socket.assigns.context do
    {:noreply, assign(socket, items: MyContext.list_items(socket.assigns.context.id))}
  else
    {:noreply, socket}
  end
end
def handle_info(_message, socket), do: {:noreply, socket}  # catch-all REQUIRED
```

Key points:
- **Catch-all `handle_info/2` is mandatory** once you subscribe — unmatched
  messages crash the LiveView process.
- **Guard the reload by `live_action`** — a `:show` view usually shouldn't
  blow away its assigns when an unrelated page changes.
- **Reload from the DB, don't patch from the payload** — re-running the list
  query keeps ordering/filters/joins correct; patching locally reimplements
  query logic and drifts.
- **Test it without sleep**: create/update via the context (which broadcasts),
  then `render(view)` and assert — the test process receives the PubSub
  message synchronously. Never `Process.sleep` to wait for it.

### PubSub reload must refresh EVERY list the view renders

When an index view renders more than one collection (e.g. an active list
`@items` plus an archived list `@archived_items` behind a toggle), the
`handle_info({:page_changed, ...})` reload clause must re-assign ALL of
them. Refreshing only the active list leaves the archived count stale —
caught in production by a LiveView test that archived a todo externally and
watched the toggle still report the old count. Pattern:

```elixir
{:noreply,
 assign(socket,
   items: Brain.list_todos(ctx.id),
   archived_items: Brain.list_todos(context_id: ctx.id, archived: true)
 )}
```

Test it: create → assert row present → `Brain.update_page(todo, %{archived: true})`
→ `render(view)` → assert row gone AND archived toggle count changed.

## LiveComponent Upload Constraint (allow_upload does NOT work in components)

A LiveComponent cannot call `allow_upload/3` — uploads are scoped to the parent LiveView, not the component. This is a hard framework constraint (verified against `phoenix_live_view` source in `deps/`). Symptoms:

- Calling `allow_upload` in a LiveComponent's `mount/1` or `update/2` raises or silently does nothing.
- `<.live_file_input upload={@uploads.file} />` inside a component renders but the upload never appears in `socket.assigns.uploads`.

### When this bites

Global widgets rendered in the root layout (chat widgets, FABs, command palettes) that need file uploads. Putting `allow_upload` in the parent LiveView is impractical because every page would need it.

### The workaround: JS hook with FileReader + base64

Instead of `allow_upload`, use a plain HTML `<input type="file">` + a JS hook that reads the file client-side and pushes it as base64:

```elixir
# In the LiveComponent render:
~H"""
<input
  type="file"
  id={"#{@id}-file-input"}
  phx-hook="FileReader"
  phx-target={@myself}
  accept="image/*,audio/*"
  class="hidden"
/>
<button type="button" phx-click="trigger-file-input" phx-target={@myself}>
  <.icon name="hero-paper-clip" />
</button>
"""

# Handle the event pushed by the hook SYNCHRONOUSLY — no Task.start:
def handle_event("file-read", %{"name" => name, "type" => mime, "data" => b64}, socket) do
  bytes = Base.decode64!(b64)

  text =
    cond do
      String.starts_with?(mime, "image/") ->
        case MyApp.Inference.Vision.describe(bytes) do
          {:ok, desc} -> "[Imagen: #{desc}]"
          _ -> "[Imagen: #{name}]"
        end

      String.starts_with?(mime, "audio/") ->
        case MyApp.Inference.ASR.transcribe(bytes, name) do
          {:ok, t} -> "[Audio: #{t}]"
          _ -> "[Audio: #{name}]"
        end

      true ->
        "[Archivo: #{name}]"
    end

  {:noreply, assign(socket, :input, socket.assigns.input <> "\n" <> text)}
end
```

**CRITICAL — synchronous processing in handle_event:** Do NOT wrap the processing in `Task.start` + `send_update`. In tests, the `send_update` from a spawned Task races with `render_hook` and `render(view)` — the attachment never appears before the assertion, causing `eventually` timeouts. The fix is to process inline in `handle_event`; when inference is not configured (tests), the fallback path is instant so the event returns immediately. When inference IS configured (production), the Vision/ASR HTTP call happens synchronously and the user sees the result in the same render cycle. This is simpler and more predictable than async.

**Fallback pattern for external inference calls:** Always wrap Vision/ASR calls in a `try/rescue/catch` AND guard with `Inference.enabled?()`. In tests the inference queue processes aren't running, so even though the module is loaded, the call raises or exits. The `enabled?` check short-circuits to the fallback string before any queue interaction:

```elixir
defp describe_image(bytes) do
  if Code.ensure_loaded?(MyApp.Inference.Vision) and MyApp.Inference.enabled?() do
    case MyApp.Inference.Vision.describe(bytes) do
      {:ok, desc} -> desc
      {:error, _} -> "no se pudo procesar"
    end
  else
    "descripción no disponible"
  end
rescue
  _ -> "no se pudo procesar"
catch
  _, _ -> "no se pudo procesar"
end
```

**phx-update="ignore" placement:** Put `phx-update="ignore"` on the `<input type="file">` itself, NOT on a wrapper div. If the wrapper has it, LiveView skips updating any children — including the button's `disabled` attribute — so the button never reflects loading state. The input needs `ignore` to avoid being reset by LiveView re-renders; the button does not.

```js
// assets/js/app.js — register the hook
let Hooks = {}
Hooks.FileReader = {
  mounted() {
    this.el.addEventListener("change", (e) => {
      const file = e.target.files[0]
      if (!file) return

      const reader = new FileReader()
      reader.onload = (ev) => {
        const base64 = ev.target.result.split(",")[1]
        this.pushEvent("file-read", {
          name: file.name,
          type: file.type,
          data: base64
        })
      }
      reader.readAsDataURL(file)
    })
  }
}
```

**Why this works:** It bypasses LiveView's upload machinery entirely. The file never touches the server until it's already base64 text in a `phx-change`/`phx-submit` event. No `allow_upload`, no `consume_uploaded_entries`, no parent LiveView involvement.

**Trade-off:** Larger payload (base64 is ~33% bigger) and no built-in progress bar. For files > 10MB, chunking or a proper upload channel is better. For chat widgets with images/audio under a few MB, this is the simplest path.

See `references/livecomponent-upload-workaround.md` for the full chat-widget integration example.

## CSS Layout / Scroll Bugs (overflow clipping)

LiveView bugs aren't always in assigns or events — sometimes the data is
correct and the symptom is **content clipped or unreachable by scroll**. These
present as "I can't see the bottom of the page" or "the version history is
cut off" and are caused by a Tailwind/CSS `overflow` class on a layout wrapper
that is shorter than its content.

### Root pattern

A flex shell (`flex h-screen`) wraps a sidebar + a main content area. If the
main wrapper has `overflow-hidden` (or `overflow: clip`), content taller than
the viewport is **clipped, not scrollable** — there is no scrollbar and no way
to reach it. Detail pages that don't set their own scroll container are the
victims; pages that *do* (e.g. a kanban with `h-[calc(100vh-4rem)]`) survive
only because they happen to be shorter than the wrapper.

### Diagnosis via browser_console (the fast path)

Don't guess at CSS — **measure it in the running browser**. Use
`browser_console` with a JS `expression` to compare `scrollHeight` vs
`clientHeight` on the suspect wrapper:

```js
// 1. Confirm the bug: wrapper can scroll but overflow is hidden
(() => {
  const e = document.querySelector('div.flex-1.overflow-hidden.flex.flex-col.w-full');
  return JSON.stringify({
    scrollHeight: e.scrollHeight,
    clientHeight: e.clientHeight,
    canScroll: e.scrollHeight > e.clientHeight,   // true = content overflows
    overflow: getComputedStyle(e).overflow       // "hidden" = clipped
  });
})()
```

If `canScroll: true` AND `overflow: "hidden"`, that's the bug — content exists
but is unreachable. Then **verify the fix reaches the bottom** by scrolling
programmatically and checking a known bottom element:

```js
// 2. After fix: scroll to bottom, confirm last element is in viewport
(() => {
  const e = document.querySelector('div.flex-1.overflow-y-auto.flex.flex-col.w-full');
  e.scrollTop = e.scrollHeight;
  const h = Array.from(document.querySelectorAll('h3'))
    .find(el => el.textContent.includes('Historial de cambios'));
  const r = h.getBoundingClientRect();
  return JSON.stringify({
    scrolledToBottom: e.scrollTop >= e.scrollHeight - e.clientHeight - 1,
    bottomElementInViewport: r.top < window.innerHeight && r.bottom > 0
  });
})()
```

### The fix

Change the wrapper's `overflow-hidden` → `overflow-y-auto`. This is a
**root fix**: every detail page (notes, concepts, goals, …) that relies on the
layout for scroll is fixed at once, with zero per-page changes.

### Pitfall: nested double-scroll after the root fix

If a page *already* had its own `overflow-y-auto h-full` inner div (common on
docs/settings pages that pre-date the layout fix), the root fix creates a
**nested double-scroll**: the inner div scrolls while the wrapper doesn't (or
both do, fighting each other). After applying the root fix, grep for redundant
scroll containers and simplify them to rely on the wrapper:

```
search_files "overflow-y-auto h-full" path=lib/dran_web
```

Remove the `overflow-y-auto h-full` from inner divs — they should just be
`p-6 w-full` (padding + width, no own scroll). The wrapper handles scrolling.

### Verifying the kanban / fullscreen pages survive

Pages that need to be full-viewport (kanban boards, dashboards) must NOT
generate a page scroll after the root fix. Verify with the same measurement —
the wrapper's `canScroll` should be `false` (scrollHeight === clientHeight)
because the board's explicit height (`h-[calc(100vh-4rem)]`) is shorter than
the wrapper:

```js
// Kanban must stay full-viewport — wrapper should NOT scroll
(() => {
  const w = document.querySelector('div.flex-1.overflow-y-auto.flex.flex-col.w-full');
  const k = document.getElementById('kanban-board');
  return JSON.stringify({
    wrapperCanScroll: w.scrollHeight > w.clientHeight,  // false = good
    kanbanHeight: k.offsetHeight,                         // ~ viewport - 4rem
    columnsEqualHeight: new Set(
      Array.from(document.querySelectorAll('[data-kanban-status]'))
        .map(c => c.offsetHeight)
    ).size === 1                                          // true = stretched
  });
})()
```
See `references/css-overflow-scroll-debugging.md` for the full worked example
(layout `overflow-hidden` → `overflow-y-auto`, docs double-scroll cleanup,
kanban preservation check). Includes the browser_console JS measurement
snippets for diagnosis and verification.

## Full-viewport page with internal column scroll (the inverse pattern)

The section above fixes pages that **can't** scroll because the wrapper clips
them. The inverse problem: a page that should fill the viewport with **no
page-level scroll at all**, scrolling only inside its own sub-regions (kanban
columns, chat panes, multi-pane dashboards). The wrapper is already
`overflow-y-auto` (the good state), so the page must opt out of that scroll
**locally** without touching `layouts.ex`.

### The pattern

```heex
<div class="flex h-screen flex-col overflow-hidden">       <!-- root: own bounded box -->
  <div class="... shrink-0">header</div>                    <!-- fixed -->
  <div class="... shrink-0">filters</div>                   <!-- fixed -->
  <div class="flex ... flex-1 min-h-0" id="kanban-board">   <!-- fills rest, min-h-0 CRITICAL -->
    <div class="w-72 shrink-0 flex flex-col min-h-0 h-full ...">  <!-- column -->
      <div class="... shrink-0">column header</div>
      <div class="... min-h-0 flex-1 overflow-y-auto">     <!-- scroll region -->
        <!-- cards -->
      </div>
    </div>
  </div>
</div>
```

### Why `h-full` / `min-h-full` don't work

The wrapper is a scrolling flex column. A child's `h-full` resolves against
the parent's content height, which is `auto` in a scrolling flex column — so
`h-full` is a no-op and the child grows with its content, re-engaging the
wrapper scroll. Use `h-screen` (the wrapper's rendered height is exactly
`100vh` because the shell is `flex h-screen` — no header above it to subtract)
plus `overflow-hidden` on the page root to create a self-contained box.

### The `min-h-0` chain (the #1 silent failure)

Every flex item between the root and the scroll region needs `min-h-0`.
Flex items default to `min-height: auto`, which prevents children from
scrolling — the child's `overflow-y-auto` has nothing to clip against
because the parent grew to fit its content. `min-h-0` lets each flex item
shrink below its content so the descendant scrollbars engage. Apply it to:
the board (`flex-1 min-h-0`), each column (`flex flex-col min-h-0 h-full`),
and the inner list (`flex-1 min-h-0 overflow-y-auto`).

### The `min-h-[200px]` trap

Do not put `min-h-[200px]` on the scroll region "so empty columns are
visible." On short viewports this forces the region taller than its flex
parent and re-engages the wrapper scroll. Use `min-h-0`; empty columns still
show their placeholder at natural height.

### Decision rule: page-local vs layout change

When ONE page needs to opt out of a shared scroll container, encapsulate the
opt-out in that page's root element (`h-screen overflow-hidden`). Do NOT
parameterize the layout with a `fluid` attr or conditional overflow class.
The blast radius of a layout change is the whole app; the blast radius of a
page change is one file.

See `references/full-viewport-page-internal-scroll.md` for the full worked
example (MyApp kanban), the class-by-class before/after table, the
`h-screen` vs `h-[calc(100vh-Npx)]` comparison, and the browser_console
verification snippets for both the kanban and the other pages.

## Empty `phx-click-away=""` Swallows Clicks on the Whole Container

A `phx-click-away` binding with an **empty string value** (`phx-click-away=""`)
is not a no-op — it registers a click-away listener with no event to fire, and
in current LiveView JS it consumes clicks bubbling through the element's
subtree. Symptom: `phx-click="show_page"` on a card does nothing; clicking the
card or buttons inside it produces NO navigation, NO error, and — telltale
sign — the server receives the event, replies with a full re-render diff
(`{"status":"ok","response":{"rendered":{...}}}` in the phx_reply), but the
client never applies the `push_navigate`.

Diagnosis path that confirmed it (browser_console, ~10 min):

```js
// 1. The event IS reaching the server:
const view = window.liveSocket.main;
view.channel.on("phx_reply", (p) => console.log(Object.keys(p.response)));
// click → logs ["pid","liveview_version","rendered"] but NO "live_redirect" key

// 2. The event fires correctly:
view.channel.push  // monkey-patch → logs show_page {"slug":"..."} as expected
```

If the server emits `live_redirect` but the client never navigates (and a
`Phoenix.LiveViewTest` `render_click` on the same element DOES navigate —
proving server-side is correct), suspect a client-side binding conflict, not
the handler. Grep for the suspect binding:

```bash
grep -rn 'phx-click-away=""' lib/ --include="*.ex" --include="*.heex"
```

**Fix: delete the empty binding.** A click-away with no handler name is never
intentional — either give it a real event (`phx-click-away="close"`) or remove
it. After removal, clicks navigate immediately.

Key diagnostic discriminator: **if `render_click()` in a LiveView test
navigates but the real browser doesn't, the bug is in the client-side JS
bindings (attributes, hooks), not in `handle_event`.** Don't burn time
re-reading the handler — instrument the channel as above.

## SVG/Canvas hook inside a hidden tab panel renders collapsed (0-size bounding rect)

Symptom: a graph (svg-pan-zoom, D3, canvas) that lives inside a client-side tab
panel (`data-detail-panel` with `class="hidden"`) shows nodes as tiny dots
jammed in a corner when the tab is first opened. The hook's `mounted()` ran
while the panel was `display:none`, so `getBoundingClientRect()` was 0×0 and
every fit/zoom/center calculation was wrong.

**Fix: re-fit on visibility change with an IntersectionObserver in the hook:**

```js
mounted() {
  this.init()           // runs with 0-size rect when panel is hidden
  this._visibilityObserver = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (e.isIntersecting) requestAnimationFrame(() => this.fitToContent())
    })
  })
  this._visibilityObserver.observe(this.el)
},
destroyed() {
  if (this._visibilityObserver) { this._visibilityObserver.disconnect(); this._visibilityObserver = null }
  // ...existing teardown
}
```

Cheaper than listening for the tab-switch event (which is a LiveView JS
command, not a DOM event the hook can subscribe to) and also covers
resize-first-paint races. Applies to ANY hook that measures its element in
`mounted()` when the element can start inside a hidden container (tabs,
collapsibles, modals).

## Merging two tab bars into one (server-side + client-side tabs coexisting)

When a shared `page_detail` component renders a first-row tab bar with
client-side JS-command tabs (Content/Graph via `switch_detail_tab`), and each
page-type LiveView injects its own SECOND-row tab bar (server-side
`switch_tab` + `@active_tab`) inside a `<:tabs>` slot, the user may ask to
"merge them into one bar" so all tabs sit side by side.

This is NOT the same as "Two tab rows → promote a tab" (below), which moves
ONE tab up. Here you're merging the entire second-row bar INTO the first row,
and the two tab mechanisms (JS client-side vs server-side) must coexist in a
single `<nav>`.

### The architecture

The shared `page_detail` component gains three things:

1. **`slot :extra_tabs`** — server-side tab buttons rendered inside the
   shared `<nav>` alongside Content/Graph.

2. **`slot :extra_content`** — server-side tab content rendered as a SIBLING
   of `detail-panel-content`, NOT inside it. This is critical: the server-side
   tab content must render OUTSIDE the `detail-panel-content` div because that
   div gets `hidden` when a server-side tab is active.

3. **Two attrs** so the shared component can toggle its own Content/Graph
   tabs based on server state:
   - `content_hidden` — when true, `detail-panel-content` gets `class="hidden"`.
   - `graph_active` — when true, the Graph tab shows active styling.

### The conditional `phx-click` pattern

Content and Graph tabs fire DIFFERENT events depending on whether server-side
tabs are in play. When `content_hidden` is true, clicking Content/Graph must
fire a server `switch_tab` event. When false (normal pages), they fire the
client-side `switch_detail_tab` JS command:

```heex
<button
  phx-click={if @content_hidden, do: "switch_tab", else: switch_detail_tab("content")}
  phx-value-tab="overview"
  class={[
    "px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors duration-150",
    not @content_hidden && "border-primary text-primary",
    @content_hidden && "border-transparent text-base-content/60 hover:text-base-content"
  ]}
>
  {gettext("Content")}
</button>
```

The `if @content_hidden, do: "switch_tab", else: switch_detail_tab("graph")`
is valid HEEx — it returns either a string (server event) or a
`%Phoenix.LiveView.JS{}` struct (client command). LiveView accepts both.

### CRITICAL PITFALL: server-side tab content inside `detail-panel-content` is invisible

If you put the kanban/todos content inside `<:tabs>` (which renders inside
`detail-panel-content`), it will be hidden when `content_hidden` is true.
Symptom: clicking a server-side tab highlights it correctly but the content
area is blank. **Fix:** use `<:extra_content>` (a sibling of
`detail-panel-content`) for ALL server-side tab content.

### LiveView wiring

The LiveView passes `content_hidden` and `graph_active` based on `@active_tab`,
and splits content between `<:tabs>` (overview only) and `<:extra_content>`
(everything else including graph):

```heex
<.page_detail
  content_hidden={@active_tab not in ["overview", "graph"]}
  graph_active={@active_tab == "graph"}
  editing={@editing}
>
  <:extra_tabs>
    <button :for={{tab, label} <- @project_tabs}
      phx-click="switch_tab" phx-value-tab={tab}
      class={[..., @active_tab == tab && "border-primary text-primary", ...]}>
      {label}
    </button>
  </:extra_tabs>

  <:tabs>
    <div :if={@active_tab == "overview"}>...</div>
  </:tabs>

  <:extra_content>
    <div :if={@active_tab == "kanban"}>...</div>
    <div :if={@active_tab == "graph"}>
      <.page_graph id="project-page-graph" nodes={@graph_nodes} edges={@graph_edges} />
    </div>
  </:extra_content>
</.page_detail>
```

Key conventions:
- **"Overview" is removed as a tab name** — the overview content shows under
  "Content". The LiveView's default `@active_tab` stays `"overview"` but maps
  to the Content tab visually.
- **Graph moves from `<:graph>` to `<:extra_content>`** with
  `:if={@active_tab == "graph"}`.
- **`switch_detail_tab` JS is untouched** — works for normal pages (notes,
  concepts) that don't have server-side tabs.

### `content_tab_value` attr — different LiveViews use different switch_tab values

Not all LiveViews use `"overview"` as their default `@active_tab`. Plan uses
`"content"`, others may use `"overview"`. The Content tab's `phx-value-tab`
must match the LiveView's default value so clicking Content from another
server-side tab returns to the right state. Add a `content_tab_value` attr
(default `"overview"`) to `page_detail` and pass it explicitly:

```heex
<.page_detail
  content_hidden={@active_tab not in ["content", "graph", "related"]}
  graph_active={@active_tab == "graph"}
  content_tab_value="content"   <%-- plan_live passes "content" --%>
  ...
>
```

Without this, clicking Content on a plan page fires `switch_tab` with
`phx-value-tab="overview"` — the handler sets `@active_tab = "overview"`,
which matches no `:if` block and renders a blank page.

### Silent attr omission across N LiveViews (the graph tab bug)

The `page_detail` component declares `graph_active` with `default: false` and
`content_tab_value` with `default: "overview"`. LiveViews that DON'T pass
these attrs get the defaults — which means the graph tab button renders and
highlights on click, but the graph panel never shows (because `graph_active`
is always `false`) and the content panel never hides (because `content_hidden`
defaults to `false` and `graph_active` never flips it).

This is the **silent-default pitfall** (above) applied to tab visibility. The
7 "simple" LiveViews (note, todo, query, reference, comparison, concept,
entity) all had the `<:graph>` slot wired and the `handle_event("switch_tab")`
handler, but never passed `graph_active` or `content_tab_value` to
`<.page_detail>`. The tab appeared, the click fired, the assign updated —
but the component never knew.

**Fix pattern for N LiveViews at once:**

1. Add `graph_active={@active_tab == "graph"}` and
   `content_tab_value="content"` (or `"overview"`) to every `<.page_detail>`
   call.
2. **Preserve `active_tab` across `handle_params`** — the simple LiveViews
   reset `active_tab: "content"` (hardcoded) on every `handle_params` call,
   which means switching to the graph tab and then triggering a re-render
   (save, edit toggle) resets back to content. Fix with:
   ```elixir
   active_tab = Map.get(socket.assigns, :active_tab, "content")
   ```
   in `handle_params`, same as project_live already does.
3. Verify with `mix compile` — no warnings, no errors. The attrs are
   optional with defaults, so omission compiles fine.

**Audit grep** — find LiveViews that render `<.page_detail>` but don't pass
`graph_active`:

```bash
# LiveViews that call page_detail:
grep -rln 'page_detail' lib/<app>_web/live/*.ex
# LiveViews that pass graph_active:
grep -rln 'graph_active=' lib/<app>_web/live/*.ex
# diff the two lists — every file in list 1 missing from list 2 is a bug
```

Same audit works for `content_tab_value=` and `content_hidden=`.

### Global Related tab — appears on ALL page types

Related is not just for project/goal — it appears on EVERY page type (notes,
concepts, entities, etc.). For normal pages it's client-side
(`switch_detail_tab("related")`), showing inbound/outbound relations from
`@relations`. For project/goal it's server-side (`switch_tab` with
`phx-value-tab="related"`), showing custom related content from
`<:extra_content>`.

The `related_active` attr hides the shared `detail-panel-related` when
server-side related content is shown (to avoid double-rendering):

```heex
<div id="detail-panel-related" data-detail-panel
  class={["hidden", (@content_hidden || @related_active) && "hidden"]}>
  ...inbound/outbound relations...
</div>
```

When `related_active` is true (project/goal on "related" tab), the shared
panel is hidden and the server-side content from `<:extra_content>` shows
instead. When false (normal pages), the shared panel shows via
`switch_detail_tab` JS.

### Panel placement — Graph and Related panels INSIDE the content column

The `detail-panel-graph` and `detail-panel-related` divs must live INSIDE the
`<div class="flex-1 min-w-0 space-y-6">` content column, as siblings of
`detail-panel-content` and `extra_content`. If placed AFTER the two-column
layout's closing `</div>` (i.e., after the sidebar `</aside>`), they render
below the sidebar and are not visible in the main content area — the user
sees them floating below the page, disconnected from the tab bar.

Correct structure:

```
<div class="flex flex-col lg:flex-row gap-6">     <!-- two-column layout -->
  <div class="flex-1 min-w-0 space-y-6">          <!-- main content column -->
    <div id="detail-panel-content" ...>...</div>  <!-- Content tab -->
    {render_slot(@extra_content)}                  <!-- server-side tabs -->
    <div id="detail-panel-related" ...>...</div>  <!-- Related tab -->
    <div id="detail-panel-graph" ...>...</div>    <!-- Graph tab -->
  </div>
  <aside ...>sidebar</aside>
</div>
```

### Tab order — Graph always last, Related before Graph

User preference (Álvaro): the tab bar order is always
`Content | [extra_tabs...] | Related | Graph`. Graph is the last tab on every
page type, and Related is second-to-last. This means `render_slot(@extra_tabs)`
is rendered BETWEEN Content and Related in the `<nav>`, and Graph comes after
Related.

### Bulk `tabs_bar` removal from N LiveViews

When cleaning up the redundant second-row `tabs_bar` from multiple LiveViews
at once (note, concept, entity, reference, query, artifact, comparison, todo,
plan), three things must be removed from each file:

1. **`<.tabs_bar tabs={@tabs} active_tab={@active_tab} />`** — the HEEx call
   inside `<:tabs>`.
2. **`@tabs [...]` module attribute** — the tab definition at the top of the
   module.
3. **`tabs: @tabs,`** — the assign in the `mount`/`handle_params` return.

A Python script doing `re.sub` across all files is faster and more reliable
than patching each file individually. After the script, verify with
`mix compile --warnings-as-errors` — undefined `@tabs` attribute warnings
catch any missed references. Also check for leftover `</div>` tags from removed
`:if={@active_tab == "content"}` wrapper divs — the regex removes the opening
tag but the closing `</div>` must be manually cleaned up.

For LiveViews that had MORE than just a "content" tab in their `tabs_bar`
(e.g. plan_live had "content" + "todos"), the non-content tabs must be
migrated to `:extra_tabs` / `:extra_content` (same pattern as project/goal).

## Two tab rows on the same detail page — promote a tab via a dedicated component slot

When a shared detail component (`<.page_detail>`) renders a first-row tab bar
(Content/Metadata/Relations/Versions/Activity) whose panels are switched by
pure-client `Phoenix.LiveView.JS` commands, and each page-type LiveView injects
its own second-row tab bar (Graph/Content/Todos/...) via a slot, moving one of
the second-row tabs UP to the first row is a **component change, not 11
LiveView rewrites**:

1. Add a dedicated slot to the shared component (`slot :graph`), render its
   content inside a new `data-detail-panel` div, and add the tab entry to the
   first-row `tabs` list — the existing `switch_detail_tab` JS command handles
   it for free.
2. In each LiveView: move the graph markup into `<:graph>...</:graph>`, remove
   the tab from the second-row list, and **revert any default `active_tab`
   change** you previously made for the old layout (leaving
   `active_tab: "graph"` when "graph" is no longer in the second-row list
   renders nothing).
3. The second-row tab bar stays for the page-type-specific tabs
   (Todos/Kanban/Goals...) inside the Content panel.

Same slot-promotion recipe works for any "this section deserves first-row
status" request — the JS-command tab switcher doesn't care which panel the
slot renders into.

## Colocated Hook for Pure-Client Component Behavior (tag input, etc.)

For component behavior that needs NO server round-trips (adding/removing tag
chips, local expand/collapse), use a **colocated hook** —
`<script :type={Phoenix.LiveView.ColocatedHook}>` inside the component — the
same pattern as the MyApp KanbanBoard hook. Key facts from building the
MyApp tag_input (zero new deps, no phx-change per keystroke):

- The hook mounts by **module-qualified name** when rendered outside a
  LiveView: in component tests, assert
  `phx-hook="DranWeb.MarkdownEditorComponents.TagInput"`, NOT `".TagInput"`.
- The **hidden input carries the form field name**; chips are display-only.
  All mutations (Enter/comma → add chip, Backspace on empty → pop last,
  × → remove) rewrite the hidden input's `value` as canonical comma-separated
  text. The server save path needs ZERO changes — it still receives
  `params["page"]["tags"]` as a string.
- Normalize on render AND on save: server-side, `String.split(value, ",") |>
  map(&trim) |> reject(&=="")` before `Enum.join(",")` so the stored value is
  canonical regardless of what the client sent.
- `attr :value` accepts comma-separated string OR list — normalize both in the
  component (`List.wrap` when list, split when binary) so the edit form
  (DB array) and new form (param string) both work with one code path.
- Component test pattern: `render_component(&Mod.tag_input/1, %{id: ..., name: ...})`
  — the colocated `<script>` tag renders inline in the HTML string, and its
  hook name appears module-qualified (see first bullet).

See `references/tag-input-colocated-hook.md` for the full component source
(attrs, hook JS, chip rendering) and the 6-test coverage matrix.

## Shared Component Fires Event the LiveView Doesn't Handle (FunctionClauseError crash)

A shared function component (e.g. a page-list card used by several LiveViews)
dispatches `phx-click="some_event"` unconditionally. Any LiveView that renders
the component but has **no matching `handle_event/3` clause** crashes with:

```
** (FunctionClauseError) no function clause matching in MyAppWeb.SomeLive.handle_event/3
    MyAppWeb.SomeLive.handle_event("show_page", %{"slug" => "..."}, %Socket{...})
```

The user-visible symptom is subtle: **clicking does nothing** (no navigation,
no error page) — the LV process dies, the client rejoins and remounts, and the
page looks identical to before the click. No 500, no redirect, just a dead
click. In the browser console you see `view crashed` and a fresh `MOUNT`.

Real case: `PageListComponents` cards fire `phx-click="show_page"` and
TodoLive/KanbanLive/TagLive all had the handler — but the newer ProjectLive
(cloned from GoalLive, whose cards use real links) didn't. The project index
was unopenable from day one and nobody noticed because there is no
`project_live_test.exs`.

### Diagnosis

```js
// browser_console — find what the clickable element actually dispatches:
(() => {
  const card = document.querySelector('[phx-click]');
  return card.getAttribute('phx-click');   // "show_page"
})()

// then click it and read the console:
card.click()
// → look for "GenServer terminating ** (FunctionClauseError) ... handle_event"
```

Then grep the LiveView for a handler:

```bash
grep -n 'handle_event("show_page"' lib/my_app_web/live/some_live.ex   # no match = bug
```

### Fix

Add the missing clause, following the sibling LiveViews' convention:

```elixir
def handle_event("show_page", %{"slug" => slug}, socket) do
  {:noreply, push_navigate(socket, to: ~p"/projects/#{slug}")}
end
```

### Prevention / audit

When you introduce a shared component that dispatches events, audit every
LiveView that can render it. Mechanical check:

```bash
# every LV whose templates mention the shared component or the event:
grep -rln 'show_page' lib/my_app_web/live/*.ex | while read f; do
  grep -q 'def handle_event("show_page"' "$f" || echo "MISSING handler: $f"
done
```

And note the deeper lesson: **an untested LiveView (`some_live_test.exs`
missing) is where this class of bug hides.** Click-through tests with
`Phoenix.LiveViewTest.element/2 |> render_click()` would have caught it on
day one.

### Adding a NEW event to a shared handler module — wire every delegating LiveView

Same bug class, inverse direction: you add a `handle_event("archive_page", ...)`
clause to a shared handler module (e.g. `PageEdit`) and a button for it in a
shared component (`page_detail`). It compiles and renders everywhere — but the
click crashes/dead-ends in EVERY LiveView because each LiveView needs its own
delegation clause; LiveView event dispatch goes to the LiveView module, not
the shared handler. Grep-based wiring recipe:

```bash
# 1. Find every LV that delegates to the shared handler:
grep -rln 'PageEdit.handle_event' lib/my_app_web/live/*.ex
# 2. Check which have the new event wired:
grep -rln 'handle_event("archive_page"' lib/my_app_web/live/*.ex
# diff the two lists — every LV in list 1 missing from list 2 crashes on click
```

**Mind the two delegation styles in the same codebase** — older LVs use
multi-line `def handle_event("x", params, socket),\n  do: PageEdit.handle_event(...)`,
newer ones use one-liners `def handle_event("x", p, s), do: PageEdit.handle_event("x", p, s)`.
A scripted patch that only matches one style silently misses half the files
(match the anchor style per file, or handle both). Verify with the grep above
after wiring, then prove the flow with a LiveView test that clicks the button
and asserts the DB side-effect.

## Parent `phx-click` swallows child control interactions (select, buttons)

A card or list-item `<div>` with `phx-click="show_page"` on the **parent** and
interactive controls (status `<select>`, health-dot buttons, archive button)
**inside** it: clicking the control also fires the parent's `phx-click`,
causing unwanted navigation. The `phx-change` on the `<select>` fires
correctly, but the click event bubbles up to the parent and triggers
`push_navigate` — the user ends up on the detail page instead of changing
the status.

### Why `phx-click="noop"` is a band-aid, not a fix

Adding `phx-click="noop"` on a wrapper div around the controls stops
propagation to the parent, but it's fragile — every new control added inside
needs its own wrapper, and the `noop` handler must exist in every LiveView
that renders the component. The real fix is structural.

### The fix: title-as-link, no parent click

Remove `phx-click` from the card entirely. Make the **title** a
`<.link navigate={...}>` so clicking the title navigates, and controls
work independently without any propagation concerns:

```heex
<%!-- BEFORE: parent click swallows everything --%>
<div class="surface-2 ..." phx-click="show_page" phx-value-slug={page.slug}>
  <span class="font-medium flex-1">{page.title}</span>
  <form phx-change="change_status" ...>
    <select name="status" ...>...</select>
  </form>
</div>

<%!-- AFTER: title is a link, controls are independent --%>
<div class="surface-2 ...">
  <.link navigate={PageTypes.page_show_path(page)} class="font-medium flex-1 hover:text-primary">
    {page.title}
  </.link>
  <form phx-change="change_status" ...>
    <select name="status" ...>...</select>
  </form>
</div>
```

This mirrors the `/todos` index pattern where each row has `phx-click` on the
row but the status buttons are `<button phx-click="change_status">` with
their own handlers — except cleaner because there's no parent click to
conflict with at all.

### When the parent click IS wanted (todos index)

The `/todos` index uses `phx-click="show_page"` on the row AND status
buttons inside it. This works because the status buttons are `<button>`
elements with their own `phx-click` — LiveView dispatches the button's
event, not the parent's. The issue only arises with `<select>` (which uses
`phx-change`, not `phx-click`) and with controls that don't stop
propagation. If you must keep the parent click, use `<button>` for child
controls (not `<select>`), or add `phx-click="noop"` on a wrapper.

## Grouping list items by status/health (mirroring a plugin's modal layout)

When a web index page should group items the same way a Hermes desktop plugin
modal does (dot + label + count per group, only non-empty groups shown), the
pattern is:

1. **Define group config** per page type — a list of `{key, label, color_dot_class}`
   tuples in display order. Projects: active/draft/on_hold/done. Goals:
   red/yellow/green (health). Plans: active/draft/done.

2. **Group with `Enum.group_by`** keyed by the meta field (`status` or
   `health`), then filter to only groups that have items, preserving the
   config's display order.

3. **Render** each group as a section: header (dot + label + count) followed
   by the cards. Use a `cond` in the template to switch between grouped
   layout (project/plan/goal) and flat layout (notes, concepts, etc.).

4. **Extract the card** into its own function component so it's reused in
   both grouped and flat layouts without duplication.

```elixir
defp group_config("project"), do: [
  {"active", gettext("Active"), "bg-green-500"},
  {"draft", gettext("Draft"), "bg-base-300"},
  {"on_hold", gettext("On Hold"), "bg-yellow-500"},
  {"done", gettext("Done"), "bg-green-400"}
]
defp group_config("goal"), do: [
  {"red", gettext("At Risk"), "bg-red-500"},
  {"yellow", gettext("Caution"), "bg-yellow-500"},
  {"green", gettext("Healthy"), "bg-green-500"}
]
defp group_config(_), do: nil  # flat list for non-grouped types

defp grouped_pages(pages, page_type) do
  case group_config(page_type) do
    nil -> nil
    groups ->
      grouped = Enum.group_by(pages, &group_key(&1, page_type))
      groups
      |> Enum.filter(fn {key, _label, _color} -> Map.has_key?(grouped, key) end)
      |> Enum.map(fn {key, label, color} -> {key, label, color, grouped[key]} end)
  end
end
```

Template uses `cond` to pick grouped vs flat:

```heex
<%= cond do %>
  <% @page_type in ["project", "plan", "goal"] -> %>
    <div class="space-y-6">
      <div :for={{_gkey, glabel, gcolor, gitems} <- grouped_pages(@pages, @page_type)}>
        <div class="flex items-center gap-2 px-1 py-1">
          <span class={"size-2 rounded-full " <> gcolor}></span>
          <span class="text-sm font-medium text-base-content/60">{glabel}</span>
          <span class="text-xs text-base-content/40">({length(gitems)})</span>
        </div>
        <div class="space-y-2">
          <.page_card :for={page <- gitems} page={page} page_type={@page_type} />
        </div>
      </div>
    </div>
  <% true -> %>
    <div class="space-y-2">
      <.page_card :for={page <- @pages} page={page} page_type={@page_type} />
    </div>
<% end %>
```

Key: the `data-testid="page-card-#{slug}"` stays on the card regardless of
layout, so existing tests that assert on `page-card-` continue to pass.

## `phx-change` on a form with NO matching `handle_event` — dead-on-select crash

A `<.form>` with `phx-change="some_event"` but **no `handle_event("some_event", ...)` clause** in the LiveView. The form renders fine and the submit (`phx-submit`) works, but the instant the user interacts with ANY field — selecting from a `<select>`, typing in an `<input>`, checking a checkbox — LiveView dispatches the `phx-change` event, finds no handler, and the process crashes with `FunctionClauseError`.

This is the **inverse** of the "Shared Component Fires Event the LiveView Doesn't Handle" section above: there the event comes from a shared component's `phx-click`; here the event comes from the form's own `phx-change` binding. The crash mechanism is identical.

### Symptom

The user reports "da error al seleccionar X" — the form opens fine, fields render, but selecting from a dropdown or typing in a field immediately errors. In the browser console: `view crashed` + fresh `MOUNT`. The page looks unchanged (the LV died and remounted to the same state).

### Diagnosis

```bash
# 1. Find the phx-change binding in the template:
grep -n 'phx-change=' lib/my_app_web/live/some_live.html.heex
# → phx-change="provider_form_changed"

# 2. Check if a handler exists for that event name:
grep -n 'handle_event("provider_form_changed"' lib/my_app_web/live/some_live.ex
# → no match = confirmed bug
```

The gap is visible in the grep output: the event name in the template has zero matching `handle_event` clauses.

### Two fixes (pick by need)

**Option 1: Remove `phx-change` (no live validation needed).** If the form only needs to validate on submit, delete the `phx-change` attribute. Simplest fix — the form works with just `phx-submit`.

**Option 2: Add the handler (live validation wanted).** If you want server-side validation as the user types/changes fields:

```elixir
def handle_event("provider_form_changed", %{"model_provider" => params}, socket) do
  changeset =
    socket.assigns.provider_form_alias_id
    |> case do
      :new -> Providers.change_model_provider(%ModelProvider{model_alias_id: ...})
      id -> Providers.get_model_provider!(id) |> Providers.change_model_provider(params)
    end
    |> Map.put(:action, :validate)

  {:noreply, assign(socket, :provider_form, to_form(changeset, as: :model_provider))}
end
```

### Prevention

When adding `phx-change` to a form, always add the handler in the same commit. The binding compiles and renders without a handler — there is no compile-time check that the event name matches a `handle_event` clause. A grep-based audit catches it:

```bash
# Find all phx-change bindings and their event names:
grep -roh 'phx-change="[a-z_]*"' lib/my_app_web/live/*.heex | sort -u
# Then verify each event name has a handler:
grep -rn 'handle_event("event_name"' lib/my_app_web/live/*.ex
```

## Dynamic dependent select — fetch options from external API on field change

When a form field (e.g. `provider_model`) should be a `<select>` whose options
depend on the value of another field (e.g. `credential_id`), the pattern is:

1. **Form has `phx-change`** — fires on every field change, including the
   credential select.
2. **Handler checks which field changed** — compare `credential_id` from
   params against a tracked assign (`provider_form_credential_id`). Only
   fetch when the credential actually changed, not on every keystroke.
3. **Async fetch via `Task.start` + `send/2`** — the handler spawns a task
   that calls the external API (e.g. `OpenAIAdapter.list_models/2`) and sends
   the result back to the LiveView process. The handler returns immediately
   (non-blocking).
4. **`handle_info` receives the result** — updates `provider_models` assign
   and clears the loading flag.
5. **Template conditionally renders** — while loading: spinner; when models
   arrive: `<select>` with the fetched options; when empty/fallback: text input.

```elixir
def handle_event("provider_form_changed", %{"model_provider" => ap_params}, socket) do
  credential_id = ap_params["credential_id"]

  cond do
    credential_id in ["", nil] ->
      {:noreply, assign(socket, :provider_models, [])}

    credential_id != socket.assigns[:provider_form_credential_id] ->
      {:noreply,
       socket
       |> assign(:provider_form_credential_id, credential_id)
       |> assign(:provider_models_loading, true)
       |> fetch_provider_models(credential_id)}

    true ->
      {:noreply, socket}
  end
end
```elixir
defp fetch_provider_models(socket, credential_id) do
  credential = Enum.find(socket.assigns.credentials_for_select, &(&1.id == credential_id))

  if credential do
    lv_pid = self()    # CRITICAL: capture LV pid BEFORE Task.start

    Task.start(fn ->
      result = OpenAIAdapter.list_models(credential.provider, credential)
      send(lv_pid, {:provider_models_result, result})   # send to LV, not to self()
    end)
    socket
  else
    socket |> assign(:provider_models, []) |> assign(:provider_models_loading, false)
  end
end

@impl true
def handle_info({:provider_models_result, result}, socket) do
  case result do
    {:ok, models} ->
      {:noreply, socket |> assign(:provider_models, models) |> assign(:provider_models_loading, false)}
    {:error, _} ->
      {:noreply, socket |> assign(:provider_models, []) |> assign(:provider_models_loading, false)
        |> put_flash(:error, "No se pudieron cargar los modelos del proveedor.")}
  end
end
```

Template pattern (conditional select vs text fallback):

```heex
<%= if @provider_models_loading do %>
  <div class="flex items-center gap-2 text-sm text-base-content/50 py-2">
    <span class="loading loading-spinner loading-xs"></span>
    Cargando modelos del proveedor…
  </div>
<% end %>

<%= if @provider_models_loading == false and @provider_models != [] do %>
  <.input
    field={@provider_form[:provider_model]}
    type="select"
    label="Modelo del proveedor"
    options={@provider_models}
    prompt="Selecciona un modelo"
    required
    hint="Modelos disponibles para esta credencial, obtenidos en vivo del proveedor."
  />
<% else %>
  <.input
    field={@provider_form[:provider_model]}
    type="text"
    label="Modelo del proveedor"
    required
    placeholder="Primero selecciona una credencial"
    hint="Selecciona una credencial para ver los modelos disponibles."
  />
<% end %>
```

**Key points:**
- **Track the last-fetched credential ID** (`provider_form_credential_id`)
  to avoid re-fetching on every `phx-change` (which fires for ALL fields,
  not just the credential select). Without this guard, every keystroke in
  any field would trigger an HTTP call.
- **`Task.start` not `Task.async`** — we don't need to await or link. The
  task sends a message back via `send/2`. If the LiveView dies before the
  task completes, the message is simply lost (acceptable for a UI fetch).
- **Always clear `provider_models` on cancel/close** — stale model lists
  from a previous credential selection will show in the next form open if
  the assign isn't reset.
- **The `phx-change` handler must exist BEFORE the template uses it.**
  This is the same class of bug as the section above — a `phx-change`
  binding with no handler crashes the LiveView on first interaction.

## Nested form params from `to_form(%{}, as: :name)` — handler must match the nesting

When you build a form with `to_form(%{}, as: :danger)` (or any `as:` option),
the submitted params arrive **nested under that atom/string key**, not flat.
A handler that pattern-matches flat params crashes with
`FunctionClauseError`:

```elixir
# Template — form named :danger
<.form for={to_form(%{}, as: :danger)} id="reset-context-form" phx-submit="reset_context">
  <.input field={to_form(%{}, as: :danger)[:confirmation]} type="text" />
</.form>

# WRONG — flat match, crashes
def handle_event("reset_context", %{"confirmation" => confirmation}, socket) do
  # params are %{"danger" => %{"confirmation" => "..."}}, not %{"confirmation" => "..."}
end

# CORRECT — match the nesting
def handle_event("reset_context", %{"danger" => %{"confirmation" => confirmation}}, socket) do
  ...
end
```

The error in the log shows the actual param shape:
```
** (FunctionClauseError) no function clause matching in MyAppWeb.SettingsLive.handle_event/3
    handle_event("reset_context", %{"danger" => %{"confirmation" => ""}}, ...)
```

**Rule of thumb:** the `as:` option in `to_form/2` namespaces all field
params under that key. Always match `%{<as_value> => %{<field> => value}}`
in the handler. This is easy to miss because the form compiles and renders
fine — the crash only happens on submit.

## `<.input>` bound to a `:map` Ecto field crashes with `Phoenix.HTML.Safe not implemented for Map`

A form field whose schema column is `:map` (e.g. webhook `headers` with
`default: %{}`) bound directly to `<.input field={@form[:headers]} type="textarea">`
crashes the LiveView when the form renders:

```
** (Protocol.UndefinedError) protocol Phoenix.HTML.Safe not implemented for Map
Got value: %{}
    (phoenix_html) Phoenix.HTML.Form.normalize_value/2
    (app) core_components.ex:278  input (textarea clause)
```

The textarea input clause calls `Phoenix.HTML.Form.normalize_value("textarea", @value)`
and a raw map has no `Phoenix.HTML.Safe` implementation. The initial page render is
fine (the form is behind an `:if`); it only fires when the form actually opens — a
`render_click("new_webhook")` test or the user clicking "new" is the tripwire.

### The fix — an explicit `value` wins over the field value

Phoenix's default `input(%{field: field})` clause ends with
`assign_new(:value, fn -> field.value end)` — so an explicit `value={...}` passed
ALONGSIDE `field=` takes precedence. Convert the map to a JSON string for display:

```heex
<.input
  field={@form[:headers]}
  value={headers_to_string(@form[:headers].value)}
  type="textarea"
/>
```

```elixir
def headers_to_string(%{} = headers) when map_size(headers) == 0, do: ""
def headers_to_string(%{} = headers), do: Jason.encode!(headers)
def headers_to_string(_), do: ""
```

The submit handler must do the inverse (decode the textarea string back to a map
before casting). Handle invalid JSON gracefully — e.g. keep `%{"_raw" => original}`
and have the helper return the raw string for that shape, so a validation-error
re-render shows the user's text instead of silently blanking it.

### Telltale: the dead helper

When a LiveView already contains a helper like `headers_to_string/1` with ZERO
callers, suspect exactly this bug — someone wrote the fix and never wired it into
the template. Grep for callers before writing a new helper; wiring the existing
one is often the entire fix (verified on the MyApp teams_live webhook form,
where the unwired helper had been sitting dead since the form was built).

## `Task.start` + `self()` inside the task sends to the wrong PID

When a LiveView spawns a `Task.start(fn -> ... send(self(), {:result, data}) end)`
to fetch data asynchronously, `self()` inside the Task closure is the **Task
PID**, not the LiveView PID. The message goes to the Task process (which exits
immediately) — the LiveView never receives it. The UI shows a perpetual
loading spinner or never updates.

### Symptom

- Loading spinner appears and never clears.
- No crash, no error in logs — the message simply vanishes.
- The adapter/API call works when tested directly (`mix run -e '...'`).

### The fix

Capture the LiveView PID in a variable **before** the `Task.start` call:

```elixir
defp fetch_data(socket, id) do
  lv_pid = self()          # capture LV pid here

  Task.start(fn ->
    result = ExternalAPI.fetch(id)
    send(lv_pid, {:data_result, result})   # send to LV, not to self()
  end)

  socket
end
```

### Why `Task.async` doesn't have this problem

`Task.async/1` links to the caller and `Task.await/2` receives the reply
directly — no manual `send` needed. But `Task.async` **blocks** the caller
until the result arrives, which defeats the purpose of async fetches in a
LiveView. `Task.start` is the right tool for fire-and-forget async work, but
you must capture the PID explicitly.

### Same applies to `Process.send_after`

`Process.send_after(self(), :tick, 1000)` inside `mount/3` is fine — `self()`
in `mount` is the LiveView. But inside a `Task.start` or any spawned process,
capture the PID first.

## HEEx `${expr}` Inside `if` Renders as Literal Text

When you write `{if condition, do: "${some_func(var)}", else: "∞"}` in HEEx,
the `${...}` is **string interpolation in Elixir string literals**, not HEEx
template evaluation. It renders the literal text `${some_func(var)}` in the
browser — the function is never called.

### The bug pattern

```heex
<%!-- BUG: renders literal "${format_decimal(t.daily_limit)}" --%>
/ {if t.daily_limit, do: "${format_decimal(t.daily_limit)}", else: "∞"}
```

### Why it happens

In Elixir, `"${expr}"` is a plain string — Elixir string interpolation uses
`#{}`, not `${}`. But even `"#{format_decimal(t.daily_limit)}"` inside a HEEx
`{if ...}` expression is still wrong: the `if` is evaluated as Elixir code,
and the string `"#{...}"` would work — but only if it's actually Elixir
interpolation. The issue is that HEEx `{}` expressions evaluate Elixir, and
inside an `if` you're building a string. The cleanest fix is to not build
strings — call the function directly:

### The fix

```heex
<%!-- CORRECT: function called directly in the if expression --%>
/ <%= if t.daily_limit, do: format_decimal(t.daily_limit), else: "∞" %>
```

Use `<%= %>` to evaluate the `if` expression and insert its result. The
`if` returns the formatted decimal or `"∞"` directly — no string interpolation
needed.

### Rule

In HEEx templates, when you need to conditionally call a function and render
its result:
- **Use `<%= if cond, do: func(var), else: "fallback" %>`** — evaluates the
  function and renders the result.
- **Never use `"$#{func(var)}"` or `"${func(var)}"` inside `{if ...}`** —
  the first is Elixir interpolation (works but is convoluted), the second
  is literal text (always wrong).
- **For simple value display**, `{if cond, do: format_decimal(var), else: "∞"}`
  without `<%= %>` also works in tag bodies — but when in doubt, use
  `<%= %>` which always evaluates.

## HEEx Class List Literal Pitfall (hardcoded class always renders)

In a HEEx class list `["literal-class", condition && "conditional-class"]`, the
**literal string is always included** in the rendered `class` attribute,
regardless of the condition. This is not a bug in HEEx — it's how list syntax
works — but it produces a silent failure when the literal was meant to be
conditional.

### The bug pattern

```heex
<%!-- BUG: "hidden" is ALWAYS rendered — panel is never visible --%>
<div id="detail-panel-graph" class={["hidden", @graph_active && "hidden"]}>
  {render_slot(@graph)}
</div>
```

The intent was "show `hidden` when graph is NOT active." But `"hidden"` as a
literal first element means the div ALWAYS has `class="hidden ..."`. The
conditional `@graph_active && "hidden"` is redundant — it adds a second
`hidden` when true, but the first one is already there. The panel is
permanently `display:none`.

### The fix

Remove the literal; make the class fully conditional:

```heex
<div id="detail-panel-graph" class={[not @graph_active && "hidden"]}>
  {render_slot(@graph)}
</div>
```

When `@graph_active` is `true`, the list is `[false]` → renders no `hidden`.
When `false`, the list is `["hidden"]` → panel hidden. Correct.

### Same bug in the inverse direction (content panel)

The content panel had the same shape but with a different condition:

```heex
<%!-- BUG: content stays hidden when graph tab is active --%>
<div id="detail-panel-content" class={["space-y-6", @content_hidden && "hidden"]}>

<%!-- FIX: also hide when graph_active (graph tab replaces content) --%>
<div id="detail-panel-content" class={["space-y-6", (@content_hidden or @graph_active) && "hidden"]}>
```

Here `"space-y-6"` is a legitimate always-on literal (layout, not visibility).
The bug was that `@content_hidden` alone didn't account for `@graph_active` —
when the graph tab is active, `content_hidden` may be `false` (because the
LiveView's `content_hidden={@active_tab not in ["overview", "graph"]}` includes
"graph" in the visible list), but the content panel should STILL be hidden
because the graph panel replaces it.

### Rule

**Never put a visibility class (`hidden`, `invisible`, `opacity-0`) as a literal
in a HEEx class list unless it is truly unconditional.** If the visibility
depends on any state, make it a conditional element: `condition && "hidden"` or
`not condition && "hidden"`. A literal `"hidden"` in the list is a permanent
`display:none` that no condition can remove.

### Diagnosis

The symptom is "tab/button highlights correctly but panel is blank" — the tab
bar shows the right active state, but the panel content never appears. This
mimics a missing slot or empty data, but the real cause is the CSS class. Check

---

## Pitfalls

### HEEx comment corruption during patching

When using the `patch` tool on HEEx templates, the fuzzy match can silently
corrupt HEEx comments. The closing tag `--%>` becomes `-->` (HTML comment
style), which breaks the HEEx parser with a confusing error:

```
** (Phoenix.LiveView.TagEngine.Tokenizer.ParseError)
unmatched closing tag. Expected </div> for <div> at line N, got: </Layouts.dashboard>
```

The error points at the *last* tag in the file, not at the corrupted comment.
This wastes debugging cycles counting divs when the real issue is a corrupted
comment elsewhere.

**Diagnosis**: Run `grep -n '<!--.*-->' lib/.../template.heex` looking for
lines with `-->` that should be `--%>`. HEEx comments must always close with
`--%>`.

**Fix**: Patch the corrupted comment back to `--%>`.

**Prevention**: After any patch that touches HEEx code near comments, verify
the comment syntax survived intact with a quick grep.
the panel div's `class` attribute in the rendered HTML — if `hidden` is always
present regardless of tab state, it's this bug.

## `Float.round/2` with an Integer Argument (the `max/2` integer trap)

`Float.round/2` requires a **float** as its first argument — passing an integer
crashes with `FunctionClauseError`. This bites in HEEx inline math where you
compute a percentage with `max/2` to enforce a minimum width:

```elixir
# CRASH: max(ratio * 100, 2) returns INTEGER when ratio is a float
style={"width: #{Float.round(max(row.value / @max_value * 100, 2), 1)}%"}
# → ** (FunctionClauseError) no function clause matching in Float.round/2
#    Float.round(2, 1) — 2 is an Integer
```

### Why `max/2` returns an int

`max(a, b)` returns the type of its arguments based on **Erlang term ordering**,
not result-of-division semantics. `ratio * 100` is a float (Elixir division
returns a float), but `max(the_float, 2)` with a literal integer `2` returns
`2` (an integer) when the percentage is below 2%. `Float.round` has no clause
for integers.

### The fix: make the minimum a float

Change the literal to `2.0` so `max` always returns a float:

```elixir
style={"width: #{Float.round(max(row.value / @max_value * 100, 2.0), 1)}%"}
```

### Diagnosis pattern

The error message always shows the exact argument that failed:

```
** (FunctionClauseError) no function clause matching in Float.round/2
    Float.round(2, 1)
```

The `2` is the giveaway — it's an integer where a float was expected. Grep for
`Float.round(max(.*` in your HEEx/inline Elixir to find all offenders.

### General rule

When combining `max/2` or `min/2` with a literal number and `Float.round/2`,
always use a float literal (`2.0`, `5.0`) instead of an integer — `max`
preserves the type of the winning argument, and `Float.round` is strict about
receiving a float.

## HEEx Comment Syntax Pitfall (`--` inside `<%!-- --%>`)

HEEx comments use `<%!-- content --%>` and the tokenizer is greedy about the
closing `--%>`. If the comment **body** contains `--` (an em-dash `—`, two
hyphens, or a box-drawing run like `──`), the parser can read `──%>` as `─`
followed by the closer `--%>` — and then fail to find a *second* closing
`--%>`, surfacing as a misleading `MatchError` pointing at the line *after*
the comment (e.g. `<% end %>`), not at the comment itself.

### Symptom

```
** (MatchError) no match of right hand side value:
    {:error, "expected closing '--%>' for EEx expression\n    |\n133 |                 <% end %>\n    |                 ^"
```

The error points at `<% end %>` (or the next tag) — **not** at the offending
comment. This misdirection is the real time-sink: you start editing the wrong
line.

### Rule

- HEEx comments: `<%!-- ... --%>`. The closer is literally `--%>`.
- **Never put `--`, `—`, or `──` inside a HEEx comment body.** Use plain prose
  with single hyphens or no hyphens. Section markers like
  `<%!-- Section name --%>` (single hyphens around the body) are fine — the
  issue is a `--` run that the tokenizer can mistake for the closer.
- HTML comments `<!-- -->` are NOT affected — this rule only covers the
  `<%!-- --%>` and `<% %>` HEEx/EEx forms.

### Quick fix when you hit this

```bash
# Find offending comments (em-dash or double-hyphen runs inside HEEx comments)
grep -nE '<%!--.*—|<%!--.*──|<%!--.*[^-]--[^-]' lib/<app>_web/live/*.ex
```

Replace the body to remove `--`/`—`/`──`, keep `--%>` as the closer. Do **not**
"fix" by dropping the `--` from the closer itself — `<%!-- content %>` is also
invalid and produces the same error class.

## `~p` Route Sigil Compile-Time Verification

`~p"/path"` is verified against the router at **compile time** (Phoenix's
route verifier). If the route doesn't exist, compilation fails. This bites
whenever a task adds navigation entries or `push_navigate(~p"/foo")` calls
**before** the corresponding route has been added to `router.ex` — common in
phased refactors where one task touches `layouts.ex` /
`dashboard_live.ex` / `command_palette.ex` and a *different* task (explicitly
scoped out) touches `router.ex`.

### Symptom

```
Compiling N files (.ex)
== Compilation error in file lib/<app>_web/components/layouts.ex ==
** (ArgumentError) no route found for path "/projects"
```

### Workaround

Use a plain string literal `"/projects"` instead of `~p"/projects"`. This
skips compile-time verification — the link renders correctly and only breaks
at runtime if a user actually clicks it before the route exists.

```elixir
# ❌ fails compile if /projects route isn't defined yet
%{key: "projects", path: ~p"/projects", ...}

# ✅ compiles; works once the route is added
%{key: "projects", path: "/projects", ...}
```

### When to use which

| Situation | Use |
|-----------|-----|
| Route exists | `~p"/path"` — get compile-time safety + verified params |
| Route will be added in a later/sibling task you don't own | `"/path"` literal — unblock compile now |
| Query-string params (`~p"/kanban?goal=#{slug}"`) | `~p` is fine — query params don't need routes |

After the route lands, grep for the literal and upgrade to `~p`:

```bash
grep -rn 'path: "/[a-z]' lib/<app>_web/  # find string-literal paths to upgrade
```

## `~p` Query Param Interpolation with `nil` Crashes on `live_patch` (LEFT JOIN group)

A verified route with query-param interpolation — `~p"/path?filter=#{row.filter_id}"` — crashes the whole LiveView when the interpolated value is `nil`:

```
** (ArgumentError) cannot convert nil to param
    (phoenix) lib/phoenix/param.ex: Phoenix.Param.Atom.to_param/1
    (phoenix) lib/phoenix/verified_routes.ex: __encode_query__/2
```

The whole LiveView process dies on `live_patch` — the page goes blank and remounts. This is NOT a compile-time issue; the route and params are valid, only the value is nil.

### Where the nil comes from (the classic source)

An aggregation query with a `LEFT JOIN` + `group_by` on the joined table:

```elixir
|> join(:left, [rl], ma in ModelAlias, on: rl.model_alias_id == ma.id)
|> group_by([model_alias: ma], ma.id)
|> select([rl, model_alias: ma], %{model_id: ma.id, ...})
```

Parent rows whose FK is nil (or orphaned) aggregate into a single group with `model_id: nil`. The query is CORRECT — the nil is a legitimate "unlinked bucket." The template is where the crash lives.

### The fix — conditional link in the template

Render the link only when the id exists; otherwise render the name as plain text:

```heex
<%= if row.model_id do %>
  <.link patch={~p"/dashboard/stats/models?period=#{@period}&model_id=#{row.model_id}"}>
    {row.model_name}
  </.link>
<% else %>
  {row.model_name}
<% end %>
```

This preserves the drill-down for linked rows and shows the nil bucket (usually displayed as "—" via a `|| "—"` fallback in the query map) as non-clickable text.

### Diagnosis pattern

The stack trace shows `__encode_query__` inside a render fn — grep the template for `~p` sigils with query-param interpolation (`?...=#{...}`), then check whether the interpolated field can be nil. Fields from LEFT JOIN selects are the prime suspects. A `row.id || "unknown"` fallback on the row's DOM `id` attribute nearby is a telltale: someone handled nil for the DOM id but forgot the link.

### Rule

**Never interpolate a potentially-nil FK/id into a `~p` query param or path segment without a nil guard.** Path segments crash identically (`~p"/models/#{row.model_id}"` with nil → same ArgumentError). Options: conditional link (above), filter nil rows out of the list, or provide a sentinel value — but never let nil reach `to_param/1`.

## Verification Without a Full App Boot

`mix run -e '...'` with `--no-start` fails for Ecto repos (DBConnection pool
needs the application supervision tree). Options:

- **Query the running server**: if `mix phx.server` is up, `curl` the page and
  grep the rendered HTML for the symptom. Auth-protected pages need a session
  cookie — log in via the session controller endpoint first.
- **IEx remote shell**: `iex --remsh` into the running node to inspect assigns
  and call context functions live.
- **Direct SQL**: `psql` to verify DB state without needing Ecto. Useful for
  ruling out data/type issues, but cannot verify the assign-wiring layer.
- **browser_console JS measurement**: for CSS/layout/scroll bugs, the running
  browser is the only source of truth — measure `scrollHeight` vs
  `clientHeight` directly (see the CSS Layout section above).

### SQL-fixture E2E loop (when the UI can't create the data itself)

When a feature needs real data to be verified (a kanban column that only
renders cards when todos have the right `project_slug`) but the browser can't
perform the creating interaction (dead websocket, complex drag-drop, a form
the remote browser can't submit), drive the data layer directly and verify
read-only:

```bash
# 1. Inspect current state — what's missing for the feature to show?
psql -U brain -d dran_dev -c \
  "SELECT slug, meta->>'kanban_status', meta->>'project_slug' FROM pages WHERE page_type='todo';"

# 2. Inject the fixture with a targeted UPDATE (JSONB merge for meta fields):
psql -U brain -d dran_dev -c \
  "UPDATE pages SET meta = meta || '{\"project_slug\": \"lanzar-MyApp-v6\"}'
   WHERE slug IN ('todo-a', 'todo-b');"

# 3. Reload the page in the browser (plain navigation re-runs handle_params,
#    which re-queries) and snapshot/vision-verify the feature now shows data.

# 4. CLEAN UP — revert the fixture so you don't pollute the user's data:
psql -U brain -d dran_dev -c \
  "UPDATE pages SET meta = meta - 'project_slug'
   WHERE slug IN ('todo-a', 'todo-b');"
```

Key points:
- **Always clean up.** The verification proves the feature works; leaving the
  fixture behind corrupts the user's real data. The UPDATE is reversible
  (`meta || '{...}'` merges, `meta - 'key'` removes).
- **Reload, don't interact.** A plain `browser_navigate` to the same URL
  re-runs `handle_params`, re-queries the DB, and re-renders — the fixture
  appears without needing any websocket interaction.
- **Report what you did.** Tell the user "linkeé 2 todos reales por SQL para
  verificar el board, luego los deslinkeé" — honest fixture accounting beats
  silently leaving test data.

## Remote/headless browser has a dead LiveView websocket — verify around it

When driving the app through a **remote/headless browser** (Browserbase,
Browser Use cloud), the LiveView websocket can be broken even though plain
HTTP page loads work. Symptoms: `phx-click`/`phx-submit` do nothing, a
"reconnecting" flash banner, `document.cookie` reads empty and JS cookie
injection silently fails.

**Don't retry the UI.** The websocket is not coming back in that session.
Verify the feature through interfaces that don't need it:

1. **Create fixtures via the HTTP API, assert via read-only page loads.**
   Initial page render is plain HTTP and works with a dead websocket:
   `curl -X POST /api/...` to create the record, then `browser_navigate` to
   its show page and snapshot to confirm it renders.
2. **Fire mutations via the API, assert the side effect in the DB.** Proves a
   backend chain (e.g. update → sync → recompute) end-to-end without any
   browser interaction. To trigger a "recompute on change" code path, toggle
   the value (green→yellow→green) so the change branch actually fires.
3. **Login via the real form, not the console.** `document.cookie = ...`
   injection often returns the empty string in remote browsers. Read dev
   credentials from `.env`/config and `browser_type` them into the login form.
4. **List routes without logging in.** A request to a bogus path renders the
   Phoenix `NoRouteError` page which enumerates every registered route — a
   free way to confirm new routes are wired.
5. **`data-confirm` clicks hang the whole remote browser session.** Clicking a
   button with `data-confirm` (native `confirm()` dialog) can freeze the
   remote browser so hard that subsequent `browser_navigate` calls time out —
   even though the Phoenix server stays perfectly healthy. The event also
   never reaches the server, so nothing is persisted. Verify the interactive
   flow with a **LiveView test** instead:
   `view |> element("button", t("Archive")) |> render_click()` + assert the DB
   side-effect. That is a stronger proof than the browser click anyway — it
   exercises the real `handle_event` clause end to end.
6. **Distinguish a hung browser from a hung server.** Server logs
   (`process(action="log")` on the `mix phx.server` session) keep printing
   queries and `GET /...` 200s while the browser is frozen, and
   `curl localhost:PORT/health` answers. If the server responds, the problem
   is the remote browser session — recover with a fresh `browser_navigate`
   to `/login` + re-login; do NOT restart the Phoenix server.

**Report honestly.** If the dead websocket blocked a genuinely interactive
feature (drag-drop, live updates), say "not verified — websocket unstable,
needs a manual pass in your local browser" rather than marking it tested.
An honest gap beats a fake pass and tells the user exactly what to spot-check.

## The `active_nav` Contract (sidebar highlight wiring)

A second instance of the silent-default family, distinct enough to call out:
`Layouts.app` declares `attr :active_nav, :string, default: nil` and forwards
it to `sidebar_nav/1`, which compares `@active == key` per nav entry to decide
whether to highlight it. `default: nil` means a LiveView that doesn't forward
the attr gets **no highlight** — silently, no error.

Two wiring requirements, BOTH mandatory for the highlight to fire:

1. **Set the socket assign** in `mount/3` (or `handle_params/3` for
   type-derived keys like `PageTypes.path(page_type)`):
   ```elixir
   {:ok, assign(socket, ..., active_nav: "notes")}
   ```
2. **Forward the attr in the render block**:
   ```heex
   <Layouts.app
     flash={@flash}
     ...
     active_nav={@active_nav}
   >
   ```

A LiveView that sets the assign but omits the render forwarding compiles, runs,
and silently shows no highlight — same shape as the page-counts bug. A LiveView
that forwards the attr but never sets the assign hits the `default: nil` and
also shows nothing.

### The mismatch variant (assign set to a non-existent sidebar key)

A third, subtler failure: the assign is set AND forwarded, but to a string that
doesn't match any `key:` in `sidebar_nav/1`'s group list. Real cases found in
a single sweep:

- `tag_live.ex` set `active_nav: "tags"` — no sidebar entry for tags (tags are
  reached via `/tags/:tag` but aren't a top-level nav item). Highlight dead.
- `agent_live.ex` set `active_nav: "agents"` in `mount` — no sidebar entry for
  agents. A per-type override in `handle_params` later set it to `"research"`
  or `"ingest"` (which DO exist), so the mount value was dead weight that
  masked the real override until someone grepped.

The fix for the mismatch variant is to **remove the dead assign** (and, if no
other code path sets it, the render forwarding too) — not to add a sidebar
entry for a key that shouldn't be a nav item.

### Diagnosis: the three-way grep

When the symptom is "sidebar doesn't highlight on page X", run three greps:

1. **What keys does the sidebar actually know?**
   ```bash
   search_files "key: \"" path=lib/<app>_web/components/layouts.ex
   ```
   This enumerates the valid `active_nav` values. Anything else is a mismatch.

2. **Which LiveViews set the assign?**
   ```bash
   search_files "active_nav:" path=lib/<app>_web/live
   ```
   Files with zero matches = missing assign (bug class 1).

3. **Which LiveViews forward the attr?**
   ```bash
   search_files "active_nav=" path=lib/<app>_web/live
   ```
   Files in list 2 but not list 3 = missing forwarding (bug class 2). Files in
   list 3 but not list 2 = dangling forwarding (will hit `default: nil`).

4. **Cross-check values against the sidebar key set** from grep 1. Any
   `active_nav: "X"` where `"X"` isn't in the sidebar's key list = mismatch
   (bug class 3).

### Sweep recipe (adding `active_nav` to N LiveViews at once)

When the contract is new or has drifted across many files, the sweep is
mechanical but has two pitfalls:

- **Both sides required.** Adding only the assign OR only the render
  forwarding produces a file that compiles and looks done but still doesn't
  highlight. Always patch both in the same pass.
- **Type-derived keys for "new" pages.** A generic `PageNewLive` that handles
  `/notes/new`, `/concepts/new`, etc. should derive the key from the page
  type: `active_nav: PageTypes.path(page_type)` in `handle_params` (returns
  `"notes"`, `"concepts"`, ...). A hardcoded default in `mount` covers the
  initial render before `handle_params` runs.
- **Concurrent edits to a file in the sweep.** If a sibling subagent owns one
  of the LiveViews (e.g. the parent is adding the `todos` key concurrently),
  add ONLY the `active_nav` assign to that file — nothing else — and note it
  in the report. The parent's changes will land alongside yours; touching
  anything else in that file risks a conflict.
- **Render forwarding for the constrained file.** If you're forbidden from
  touching a file's render block (e.g. `todo_live.ex` is allowed ONLY for the
  assign addition), the assign alone is still correct — the parent's
  concurrent edit will add the render forwarding. Document the gap in the
  report so the parent knows to verify.

### Report format for a sweep

When the task is a sweep across many LiveViews, the user wants a per-file
list of what was added/removed, not a narrative. Format:

```
**Adds (assign + render forwarding):**
- note_live.ex — active_nav: "notes" in mount + active_nav={@active_nav} in render
- concept_live.ex — ...

**Removes (mismatches):**
- tag_live.ex — removed active_nav: "tags" assign + render forwarding (no sidebar key)
- agent_live.ex — removed dead active_nav: "agents" from mount (per-type override stays)

**Untouched (as instructed):** layouts.ex, dashboard_live.ex, kanban_live.ex.
query_live.ex skipped (no sidebar entry for queries).
```

The "Untouched" line is load-bearing — it tells the user which files were
explicitly out of scope, so they can cross-check against their constraint
list.

See `references/active-nav-sweep-recipe.md` for the full worked sweep (12
LiveViews patched, 2 mismatches removed, compile-verified) with the exact
grep sequence and the per-file diff summary.

## Copy-pasted inline edit forms across N LiveViews — consolidate into a shared component

When every page-type detail LiveView carries its own copy of the same edit form (title + slug + summary + tags + meta_fields + markdown_editor + Cancel/Save), any layout change (e.g. adding an attributes sidebar) means editing 11 files identically. Consolidate into ONE shared component in `PageComponents` (already imported into all LiveViews via the `live_view` macro):

```elixir
attr :form, :any, required: true
attr :page, :map, required: true
attr :page_type, :string, required: true
attr :context_id, :any, required: true
attr :save_status, :string, default: "idle"
attr :editor_id, :string, required: true   # per-type: "note-editor", "todo-editor", ...

def page_edit_form(assigns) do
  ~H"""
  <.form for={@form} id="page-edit-form" phx-change="validate_page" phx-submit="save_page">
    ...
  </.form>
  """
end
```

Each LiveView then keeps only its `<%= if @editing do %>` wrapper and calls the component. The component module needs its own imports (`DranWeb.CoreComponents input: 1`, `DranWeb.MarkdownEditorComponents`) — function components do NOT inherit the caller's imports.

Gotchas from the real sweep (11 files):
- The copies DIVERGE over time: some have a slug input, some use gettext labels, some raw English, some wrap in extra grid divs. Don't pattern-match the whole old block — anchor on `<.form ... id="page-edit-form"` … `</.form>` and replace the whole form regardless of inner variation.
- A subagent doing the sweep needs the exact per-file editor_id mapping told up front, or it invents them.
- Verify after: `grep -c "page_edit_form" lib/**/*_live.ex` == 1 per file, and `grep -l 'id="page-edit-form"' lib/` returns only the component file.

## Attributes sidebar layout for create/edit forms (Álvaro's standard)

For page create/edit forms the required layout is two columns: **left = title + markdown editor** (`flex-1 min-w-0`), **right = sticky attributes sidebar** (`w-80 shrink-0 sticky top-6 surface-2 rounded-2xl p-5`) containing tags, summary, "Vincular a…" link pickers, and meta fields. No collapsible "Más opciones" — everything visible at a glance. Action buttons (Cancel/Create) go in a full-width footer row below both columns. Álvaro asked for this explicitly (2026-07-19) after the progressive-disclosure details/summary variant — don't bring back the collapsible.

## Stream items don't re-render `:if` conditions when global assigns change

LiveView streams (`phx-update="stream"`) cache the rendered HTML of each stream
item on the client. When you change a **global assign** (e.g.
`@editing_webhook_team_id`) that an `:if` condition inside a stream item
depends on, LiveView does **NOT** re-render that stream item — the cached HTML
stays as-is. The assign IS updated on the server, but the `:if` never
re-evaluates.

### Symptom

You click a button inside a stream item (e.g. "Agregar webhook" on a team
card). The `handle_event` fires correctly (confirmed via `IO.inspect`), assigns
the new value, and returns `{:noreply, socket}`. But the UI doesn't change —
the button stays visible, the form that should appear doesn't, and there's no
error. `render(view)` in a LiveView test shows the old `editing_*` assign value
as `nil` even though the handler set it.

### Why it happens

Stream items are diffed at the item level, not the attribute level. When
`@editing_webhook_team_id` changes but the stream collection itself hasn't
changed (no items added/removed/reordered), LiveView sends no diff for the
stream items — the client keeps the cached HTML from the initial render.

### The fix — reset the stream in the handler

Call the function that resets the stream (typically the same `load_*` function
from `mount`) at the end of the handler:

```elixir
def handle_event("new_webhook", params, socket) do
  team_id = params["team-id"] || params["team_id"]
  changeset = Observability.change_destination(%Destination{})

  {:noreply,
   socket
   |> assign(:webhook_form, to_form(changeset, as: :destination))
   |> assign(:editing_webhook_team_id, team_id)
   |> assign(:editing_webhook_id, :new)
   |> load_teams()}   # <-- THIS resets the stream, forcing re-render
end
```

`load_teams/1` calls `stream(socket, :teams, teams, reset: true)` which clears
and re-sends all stream items, causing their `:if` conditions to re-evaluate
with the updated assigns.

### Diagnosis path (when `:if` inside a stream won't update)

1. **Confirm the handler runs** — add `IO.puts` or `IO.inspect(params)` at the
   top of `handle_event`. If it prints, the handler is executing.
2. **Confirm the assign is set** — add a debug attribute to the stream item
   template: `data-debug-ewt={inspect(@editing_webhook_team_id)}`. After the
   click, `render(view)` and grep for `data-debug-ewt`. If it shows the old
   value (e.g. `"nil"`) while the handler printed the new value, the stream
   item is cached.
3. **Apply the fix** — add `|> load_teams()` (or equivalent stream-reset call)
   to the handler.
4. **Verify with a LiveView test** — `render_click` + `has_element?(view,
   "#destination-form-#{team.id}")` confirms the form now appears.

### Pitfall: `phx-value-*` key format in `handle_event`

`phx-value-team-id` sends the value under the key `"team-id"` (kebab-case, with
hyphen). But in `render_click/3` tests you can pass either `"team-id"` or
`"team_id"`. If your handler pattern-matches strictly on `%{"team-id" =>
team_id}`, a test that passes `%{"team_id" => ...}` silently fails (no
FunctionClauseError because LiveView catches unmatched events). Use a
catch-all pattern and extract defensively:

```elixir
def handle_event("new_webhook", params, socket) do
  team_id = params["team-id"] || params["team_id"]
  ...
end
```

This also future-proofs against any phx-value key normalization changes.

## Security Audit Cross-Reference

Several LiveView bugs overlap with security vulnerabilities. When debugging a
LiveView, also check for these security issues:

- **handle_event without permission check** — templates hide buttons with
  `:if={@is_admin}` but the handler may not verify. See
  `phoenix-security-audit` skill, Category 1b.
- **PubSub handlers running DB queries without debounce** — a performance bug
  that becomes a DOS vector under high traffic. See `phoenix-security-audit`,
  Category 5c.
  - **Unvalidated client input in handle_event** — enum values (team_role,
  status) from client events should be validated before passing to
  `update_*`. See `phoenix-security-audit`, Category 5e.
  - **`socket.assigns[:key || default]`** — the atom `:key` is always truthy,

  ## Pitfall: removing sections from HEEx templates breaks nesting

  **Symptom:** After removing a block of HTML from a `.html.heex` template, compilation fails with `FunctionClauseError` in `Phoenix.LiveView.TagEngine.Parser.to_tree/4` or `no function clause matching in ...`.

  **Root cause:** HEEx templates have implicit nesting via `<%= if %>` / `<% end %>` and `<div>` / `</div>` pairs. When you delete a section, you must also remove its closing tags — but the closing tags for the *enclosing* blocks live AFTER the section you deleted. It's easy to accidentally remove or leave orphaned tags.

  **Pattern that breaks:** removing a section that was inside an `if` block leaves the `<% end %>` for that `if` orphaned (extra end) or removes the wrong end (missing end). Stray self-closing tags (`/>`) from component calls are also common after bad deletes.

  **Prevention recipe:**
  1. Before deleting, count the nesting: how many `<%= if ... do %>` and `<div>` open BEFORE the section, and how many `<% end %>` and `</div>` close AFTER it.
  2. After deleting, verify: every `<%= if %>` has a matching `<% end %>`, every `<div>` has a matching `</div>`.
  3. Run `mix compile` immediately — HEEx parse errors surface at compile time, not runtime.
  4. If the error mentions `to_tree`, it's almost always a nesting mismatch, not a syntax issue in the content you kept.

  **Also:** when removing a section that contained LiveComponent calls or bar_chart/hbars_chart components, check for stray `/>` on the line AFTER where you cut. Component calls use self-closing `/>` and it's easy to leave a fragment.

  ## Pitfall: Dialyzer warns "conditional will always evaluate to true"

  **Symptom:** Dialyzer warns that `if x && x.field do` will always evaluate to true because `x` was already dereferenced earlier (e.g., `x.id` on a prior line), so the type system knows `x` is never nil.

  **Fix:** Remove the redundant nil guard: `if x.field do` is sufficient when `x` was already used as `x.something` earlier in the same function.

  **Generalizable rule:** in Elixir, once you call `struct.field` on a variable, Dialyzer infers the variable is never nil at that point. A subsequent `if variable && variable.field` is redundant — the `variable &&` part is dead code.
  so the default never applies. A correctness bug that can mask missing
  assigns. See `phoenix-security-audit`, Category 5d.

## References

- `references/duplicated-helpers-pitfall.md` — Duplicated helper functions with inconsistent behavior across layouts and LiveViews (real example: budget_bar_width rounding bug)

- `references/tag-input-colocated-hook.md` — full source of the MyApp
  `tag_input` component (colocated hook, badge chips, hidden-input canonical
  value, datalist suggestions), its wiring into both the edit-form sidebar and
  the create form, and the 6-test component coverage matrix. Use as the
  reference implementation for any pure-client component that must not touch
  server save paths.

- `references/silent-attr-default-worked-example.md` — full trace of the
  page-count bug: assign set in plug → never forwarded to Layouts.app →
  `default: %{}` masks it → UI shows 0. Includes the exact grep commands and
  investigation sequence.
- `references/active-nav-sweep-recipe.md` — full trace of the active_nav
  sweep: 12 LiveViews missing the assign+forwarding, 2 mismatched keys
  (`"tags"`, `"agents"`), the three-way grep diagnosis, the concurrent-edit
  constraint on `todo_live.ex`, and the per-file diff summary. Covers the
  type-derived key pattern for `PageNewLive` and the report format.
- `references/css-overflow-scroll-debugging.md` — full trace of the
  overflow-hidden scroll-clipping bug: layout wrapper `overflow-hidden` clips
  detail pages, root fix to `overflow-y-auto`, docs double-scroll cleanup,
  kanban full-viewport preservation. Includes the browser_console JS
  measurement snippets for diagnosis and verification.
- `references/full-viewport-page-internal-scroll.md` — the inverse pattern:
  making one page fill the viewport with internal column scroll while the
  shared wrapper keeps `overflow-y-auto` for every other page. Covers the
  `h-screen overflow-hidden` + `min-h-0` flex chain, the `min-h-[200px]` trap,
  and the page-local-vs-layout-change decision rule.
- `references/MyApp-liveview-architecture-map.md` — map of the MyApp web layer
  wiring points (page types, sidebar, dashboard, command palette, router,
  empty states). Use before writing a plan or patch that adds a new MyApp
  page type or LiveView. Includes the 9-point wiring checklist, the
  GoalLive → ProjectLive clone pattern (what to rename vs keep verbatim),
  the sidebar/dashboard count-key consistency rule, and the
  inspect-before-rewriting-a-plan-section workflow.
