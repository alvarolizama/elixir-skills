# Sortable Table Columns

Clickable table headers with asc/desc toggle for Phoenix LiveView stats pages.

## Assigns

In `mount/3` (field MUST be a key the rollup rows actually carry — see
"default sort field" pitfall below):

```elixir
|> assign(:sort_field, :request_count)
|> assign(:sort_direction, :desc)
```

## Handle event — MUST re-sort the loaded lists

The classic bug: the handler updates `sort_field`/`sort_direction` and stops.
The arrow flips but the rows never move, because `sort_rows` only ran inside
`load_breakdowns` at page load. The handler MUST re-apply `sort_rows` to the
breakdown lists already in the socket (in-memory, no DB round-trip):

```elixir
@sortable_breakdowns [
  :breakdown_model,
  :breakdown_member,
  :breakdown_team,
  :breakdown_provider,
  :breakdown_service,
  :member_models
]

def handle_event("sort", %{"field" => field}, socket) do
  field = String.to_existing_atom(field)
  {sort_field, sort_direction} =
    if socket.assigns.sort_field == field do
      {field, toggle_direction(socket.assigns.sort_direction)}
    else
      {field, :desc}
    end

  {:noreply,
   socket
   |> assign(:sort_field, sort_field)
   |> assign(:sort_direction, sort_direction)
   |> resort_breakdowns(sort_field, sort_direction)}
end

defp resort_breakdowns(socket, field, direction) do
  Enum.reduce(@sortable_breakdowns, socket, fn key, acc ->
    case acc.assigns[key] do
      nil -> acc
      rows -> assign(acc, key, sort_rows(rows, field, direction))
    end
  end)
end
```

## CRITICAL: default sort field must exist on the rows

`assign(:sort_field, :requests)` when the rollup rows only have
`:request_count` makes every `Map.get(row, :requests)` return `nil` — the
initial order is silently arbitrary (stable DB order), and the "active" arrow
points at a column that isn't really sorted. Grep the template's
`phx-value-field=` values and use one of THOSE as the mount default
(e.g. `:request_count`), not a hand-invented atom.

defp toggle_direction(:asc), do: :desc
defp toggle_direction(:desc), do: :asc
```

## Sort function (guard empty list!)

```elixir
@doc "Sort a breakdown list by field and direction."
def sort_rows([], _field, _direction), do: []

def sort_rows(rows, field, direction) do
  Enum.sort_by(rows, &Map.get(&1, field), fn a, b ->
    case {a, b} do
      {nil, nil} -> true
      {nil, _} -> direction == :asc
      {_, nil} -> direction == :desc
      {a, b} ->
        if direction == :asc do
          compare_values(a, b) != :gt
        else
          compare_values(a, b) != :lt
        end
    end
  end)
end

defp compare_values(a, b) when is_struct(a, Decimal) and is_struct(b, Decimal), do: Decimal.compare(a, b)
defp compare_values(a, b) when is_binary(a) and is_binary(b), do: if(a <= b, do: :lt, else: :gt)
defp compare_values(a, b), do: if(a <= b, do: :lt, else: :gt)
```

## Sort icon component

```elixir
def sort_icon(assigns) do
  ~H"""
  <span class="inline-block w-3 text-center">
    <%= if @current == @field do %>
      <%= if @direction == :asc do %>▲<% else %>▼<% end %>
    <% end %>
  </span>
  """
end
```

## HEEx header pattern

```heex
<th>
  <button phx-click="sort" phx-value-field="model_name" class="flex items-center gap-1 hover:text-primary">
    Modelo <.sort_icon field={:model_name} current={@sort_field} direction={@sort_direction} />
  </button>
</th>
<th class="text-right">
  <button phx-click="sort" phx-value-field="request_count" class="flex items-center justify-end gap-1 hover:text-primary">
    Requests <.sort_icon field={:request_count} current={@sort_field} direction={@sort_direction} />
  </button>
</th>
```

## CRITICAL: post-load sort pitfall

Apply sort AFTER `load_breakdowns` assigns, reading from the **pipe-result socket** (`base.assigns`), not the stale outer socket:

```elixir
# WRONG — uses stale socket.assigns.breakdown_model (empty from mount)
|> assign(:breakdown_model, sort_rows(socket.assigns.breakdown_model, ...))

# CORRECT — uses the socket returned by the if/else block above
|> assign(:breakdown_model, sort_rows(base.assigns.breakdown_model, ...))
```

The `if/else` returns a NEW socket (`base`); `socket.assigns` still holds the old value.

## Test impact

- Existing `has_element?(view, "table")` tests break if `sort_rows` returns `nil` for empty lists. The `def sort_rows([], _, _), do: []` guard fixes this.
- Default sort is `request_count desc` (a field the rows actually carry) — deterministic order for tests that assert row position.
- DOM row-order assertions without Floki: `Regex.scan(~r/<tr[^>]+id="(bd-model-[^"]+)"/, render(view))` captures row ids in render order — enough to prove a sort re-ordered the table.
