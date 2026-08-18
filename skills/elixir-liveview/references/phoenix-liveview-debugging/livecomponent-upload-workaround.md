# LiveComponent Upload Workaround — Chat Widget Integration

Full worked example of adding image/audio uploads to a global chat widget (LiveComponent rendered in the root layout) using the FileReader + base64 JS hook pattern. Extracted from my_app's Brain Copilot implementation (July 2026).

## Why not `allow_upload`

The chat widget is a `LiveComponent` rendered in the app layout on every page. `allow_upload/3` is LiveView-scoped — components can't call it. Adding `allow_upload` to every LiveView in the app just to support the widget is impractical.

## Complete Implementation

### 1. LiveComponent (`lib/my_app_web/components/chat_widget.ex`)

```elixir
defmodule MyAppWeb.ChatWidget do
  use MyAppWeb, :live_component

  def mount(socket) do
    {:ok,
     socket
     |> assign(:open, false)
     |> assign(:messages, [])
     |> assign(:input, "")
     |> assign(:loading, false)
     |> assign(:attachments, [])}
  end

  def render(assigns) do
    ~H"""
    <div id={@id} phx-target={@myself}>
      <!-- ... chat panel ... -->

      <!-- Attachment preview -->
      <div :if={@attachments != []} class="flex flex-wrap gap-2 px-3 pt-2">
        <div :for={a <- @attachments} class="badge badge-outline gap-1">
          <.icon name="hero-document" class="size-3" />
          <span class="text-xs">{a["name"]}</span>
          <button type="button" phx-click="remove-attachment" phx-value-name={a["name"]} phx-target={@myself}>
            <.icon name="hero-x-mark" class="size-3" />
          </button>
        </div>
      </div>

      <!-- Input form -->
      <form phx-submit="send" phx-target={@myself} class="flex items-center gap-2 p-3">
        <label for={"#{@id}-file-input"} class="btn btn-sm btn-ghost" title="Attach file">
          <.icon name="hero-paper-clip" class="size-4" />
        </label>
        <input
          type="file"
          id={"#{@id}-file-input"}
          phx-hook="FileReader"
          phx-target={@myself}
          accept="image/*,audio/*"
          class="hidden"
        />
        <input type="text" name="text" value={@input} phx-change="input_change" phx-target={@myself} class="input input-sm flex-1" />
        <button type="submit" class="btn btn-sm btn-primary" disabled={@loading}>
          <.icon name="hero-paper-airplane" class="size-4" />
        </button>
      </form>
    </div>
    """
  end

  def handle_event("file-read", %{"name" => name, "type" => mime, "data" => b64}, socket) do
    bytes = Base.decode64!(b64)

    attachment = %{
      "name" => name,
      "type" => mime,
      "text" => process_file(name, mime, bytes)
    }

    {:noreply, assign(socket, :attachments, socket.assigns.attachments ++ [attachment])}
  end

  def handle_event("remove-attachment", %{"name" => name}, socket) do
    attachments = Enum.reject(socket.assigns.attachments, &(&1["name"] == name))
    {:noreply, assign(socket, :attachments, attachments)}
  end

  def handle_event("send", %{"text" => text}, socket) do
    # Combine user text with attachment descriptions
    attachment_texts = Enum.map(socket.assigns.attachments, & &1["text"])
    full_text = Enum.join([text | attachment_texts], "\n\n")

    # ... send to chat server with full_text ...

    {:noreply, assign(socket, :attachments, [])}
  end

  defp process_file(name, mime, bytes) do
    cond do
      String.starts_with?(mime, "image/") ->
        case MyApp.Inference.Vision.describe(bytes) do
          {:ok, desc} -> "[Imagen: #{desc}]"
          _ -> "[Imagen adjunta: #{name}]"
        end

      String.starts_with?(mime, "audio/") ->
        case MyApp.Inference.ASR.transcribe(bytes, name) do
          {:ok, text} -> "[Audio: #{text}]"
          _ -> "[Audio adjunto: #{name}]"
        end

      true ->
        "[Archivo: #{name}]"
    end
  end
end
```

### 2. JS Hook (`assets/js/app.js`)

```js
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

      // Reset input so same file can be selected again
      e.target.value = ""
    })
  }
}

let liveSocket = new LiveSocket("/live", Socket, { hooks: Hooks, ... })
```

### 3. Test (`test/my_app_web/components/chat_widget_test.exs`)

```elixir
test "accepts file upload via file-read event", %{conn: conn} do
  {:ok, view, _html} = live(conn, ~p"/")

  view
  |> element("#chat-widget-fab")
  |> render_click()

  # Simulate the JS hook pushing the event
  view
  |> element("#chat-widget")
  |> render_hook("file-read", %{
    "name" => "test.png",
    "type" => "image/png",
    "data" => Base.encode64("fake-image-bytes")
  })

  html = render(view)
  assert html =~ "test.png"
end
```

## Key Points

- **No `allow_upload`** anywhere — the file never touches LiveView's upload machinery.
- **Base64 payload** — ~33% size overhead. Fine for chat attachments (< 5MB). For larger files, use chunked uploads or a dedicated channel.
- **`phx-target={@myself}`** on both the file input and the hook — ensures the event routes to the component, not the parent LiveView.
- **Reset `e.target.value = ""`** in the hook — allows selecting the same file twice.
- **`render_hook/3`** in tests — simulates the JS hook pushing the event without needing a browser.
