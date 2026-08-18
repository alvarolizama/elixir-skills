# my_app LiveView — Floating Widgets & Plan Conventions

Session-specific patterns and conventions learned while planning my_app's
platform improvements (agents, chat copilot, embeds, relations).

## Floating widget pattern (chat copilot, any global FAB)

my_app already has the pattern for global always-available UI: the
`CommandPalette` LiveComponent mounted in `Layouts.app/1`. A floating chat
widget (or any FAB-style panel) reuses the **same mount point and event
routing**, differing only in that the root is a fixed-position FAB, not a
modal overlay.

### Mount point (same as CommandPalette)

In `lib/dran_web/components/layouts.ex`, inside `app/1`, before
`<.flash_group>`:

```heex
<.live_component
  module={DranWeb.ChatWidget}
  id="chat-widget"
  context_slug={@context_slug}
  current_user={@current_user}
/>
```

### Component skeleton

```heex
<div id={@id} class="fixed bottom-4 right-4 z-50 flex flex-col items-end gap-2">
  <div :if={@open} class="w-96 h-[32rem] bg-base-100 border border-base-300
                          rounded-2xl shadow-2xl flex flex-col overflow-hidden">
    <!-- header / messages / input form -->
  </div>
  <button phx-click="toggle" phx-target={@myself}
          class="btn btn-primary btn-circle shadow-lg">
    <.icon name={if @open, do: "hero-chevron-down", else: "hero-chat-bubble-left-right"} />
  </button>
</div>
```

Key points (inherited from the CommandPalette pattern):

- Root `<div>` always rendered so JS hooks stay attached; only the panel is
  conditional via `:if={@open}`.
- `phx-target={@myself}` on every interactive element routes events to the
  LiveComponent, not the parent LiveView.
- State in `mount/1`: `open`, `input`, `messages`, `loading`, plus any pid
  (e.g. a GenServer chat session) started lazily in `update/2` when
  `connected?(socket)`.

### Async reply pattern (LLM or slow backend inside a LiveComponent)

Do NOT block `handle_event` on a slow call (LLM, HTTP). Optimistic-render +
`send_update/3` from a Task:

```elixir
def handle_event("send", %{"message" => text}, socket) do
  socket = assign(socket, loading: true, input: "")
  user_msg = %{"role" => "user", "content" => text}
  socket = assign(socket, :messages, socket.assigns.messages ++ [user_msg])

  component_id = socket.assigns.id
  parent = self()

  Task.start(fn ->
    {:ok, reply, sources} = MyBackend.answer(text)
    send_update(parent, __MODULE__, id: component_id, reply: reply, sources: sources)
  end)

  {:noreply, socket}
end

# Second update/2 clause — MUST come before the generic assigns clause
def update(%{reply: reply, sources: sources}, socket) do
  msg = %{"role" => "assistant", "content" => reply, "sources" => sources}
  {:ok, assign(socket, loading: false, messages: socket.assigns.messages ++ [msg])}
end

def update(assigns, socket), do: {:ok, assign(socket, assigns)}
```

Pitfall: `update/2` clause order matters — the `%{}`-matching async-reply
clause must precede the generic `assigns` clause or every normal re-render
crashes on missing keys.

### Scroll-to-bottom hook (5 lines, assets/js/app.js)

```javascript
const ScrollBottom = {
  updated() { this.el.scrollTop = this.el.scrollHeight }
}
```

Attach with `phx-hook="ScrollBottom"` on the messages container. Remember:
LiveView 1.2+ requires an `id` on any element with `phx-hook`.

## Chat backend: GenServer per user+context (survives LiveView navigation)

A LiveComponent dies/re-mounts on every `push_navigate`. To keep chat
history alive across page navigation, back the widget with a GenServer keyed
by `{context_id, user}` under a `DynamicSupervisor` + `Registry`, and
persist messages to a `chat_sessions` table (JSONB `messages` column) so
history also survives server restarts.

```elixir
# find_or_start in the Supervisor module
def find_or_start(context_slug, user) do
  key = {context_slug, user}
  case Registry.lookup(my_app.ChatRegistry, key) do
    [{pid, _}] -> pid
    [] ->
      {:ok, pid} = DynamicSupervisor.start_child(
        my_app.ChatSupervisor,
        {my_app.Chat.Server, context_slug: context_slug, user: user}
      )
      pid
  end
end
```

Widget keeps only the pid in assigns; `history/1` re-hydrates `messages` in
`update/2` after each navigation.

## Context-aware answers ("esta página")

To make a chat/agent aware of the page the user is viewing:

1. Detail LiveViews (`NoteLive :show`, etc.) assign `page_slug` in mount.
2. Layout passes it through: `<.live_component ... page_slug={assigns[:page_slug]} />`.
3. Backend checks for deictic references before searching:

```elixir
defp references_current_page?(question) do
  q = String.downcase(question)
  String.contains?(q, ["esta página", "esta nota", "este concepto",
                       "this page", "aquí", "esto"])
end
```

If matched and `current_page` is loaded, skip search and answer from that
page's body directly.

## Plan-phase ordering convention (Álvaro)

When building multi-phase improvement plans for Álvaro's projects, phase
order is fixed:

1. **Feature phases** (foundations first, then features by dependency)
2. **Cleanup / bug audit / optimization / E2E validation** — after ALL
   features, so the audit covers the final state of the code
3. **Metrics/dashboard polish** that depends on cleaned-up queries (so you
   don't profile twice)
4. **Documentation (SKILL.md, README)** — ALWAYS last, because docs must
   describe what shipped, not what was planned

He corrected this twice in one session: "La fase 5 del skill debe ir al
final cuando ya todo este listo no?" and "el paso de limpieza, bugs,
optimizacion y validacion va al final y despues de ese actualizar README y
SKILL". Never slot docs or cleanup mid-plan.

## Verifying inference retry claims before planning retries

Before writing a plan task "add retry to X HTTP client", grep the actual
client for `retry:` — `Req` supports `retry: :transient` natively and my_app's
`my_app.Inference.Client.request/3` already sets it. Engine-level retry then
applies ONLY to API errors (`{:http_error, 429|5xx, _}`), not transport
errors. Planning both duplicates work.
