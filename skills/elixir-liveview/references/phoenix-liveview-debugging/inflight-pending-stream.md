# Fusing pending/in-flight pseudo-entries into a Logs stream

## Pattern

When you have a real-time table that shows both completed rows
(Postgres-backed) and in-flight rows (ETS-backed), you can fuse them
into ONE stream rather than maintaining two separate tables.

## Ingredients

- **Stream with synthetic entries:** create a map with the same shape as
  real rows plus a `__pending__: true` flag.
- **`stream_insert(acc, :logs, entry, at: 0)`** — insert at top when
  the pending request starts.
- **`stream_delete(:logs, %{id: "pending-#{id}"})`** — remove when done.
  Must be a map with `:id`, not a raw string.
- **Template:** check `Map.get(log, :__pending__)` to render pending
  rows differently (bg-warning/20, animated ping dot, "En vuelo" badge).

## Key pitfall

`stream_delete/2` expects a struct or map with `:id` — passing a raw
string like `"pending-abc"` crashes with `ArgumentError: expected stream
:logs to be a struct or map with :id key`.

## LiveView code

```elixir
def handle_info({:inflight_started, entry}, socket) do
  socket
  |> assign(:pending, [entry | socket.assigns[:pending]])
  |> stream_insert(:logs, pending_entry_to_log(entry), at: 0)
end

def handle_info({:inflight_done, id}, socket) do
  socket
  |> assign(:pending, Enum.reject(socket.assigns[:pending], &(&1.id == id)))
  |> stream_delete(:logs, %{id: "pending-#{id}"})
end

defp pending_entry_to_log(entry) do
  %{
    id: "pending-#{entry.id}",
    inserted_at: entry.started_at,
    model_requested: entry.model_requested,
    # ... all fields the template expects ...
    __pending__: true
  }
end
```

## Template

```heex
<tr
  :for={{id, log} <- @streams.logs}
  id={id}
  class={if Map.get(log, :__pending__), do: "bg-warning/20"}
>
  <%= if Map.get(log, :__pending__) do %>
    <td>
      <span class="relative flex h-2 w-2">
        <span class="animate-ping ... bg-warning" />
        <span class="relative ... bg-warning" />
      </span>
      {format_datetime(log.inserted_at, @timezone)}
    </td>
    <td><span class="badge badge-warning">En vuelo</span></td>
  <% else %>
    <!-- normal row -->
  <% end %>
</tr>
```

## Re-insert after filter reset

When filters change → `load_logs(socket, :reset)` wipes the stream.
After reset, re-insert pending:

```elixir
defp load_logs_with_pending(socket, :reset) do
  socket = load_logs(socket, :reset)
  pending = socket.assigns[:pending] || []
  Enum.reduce(pending, socket, fn entry, acc ->
    stream_insert(acc, :logs, pending_entry_to_log(entry), at: 0)
  end)
end
```
