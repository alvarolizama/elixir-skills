# FormField & to_form traps in LiveView

## Why `<.input field={%FormField{...}}>` always fails

`<.input field={...}>` and `<.form for={...}>` from `core_components.ex`
expect a real `Phoenix.HTML.FormField` struct (built by `to_form/2`,
`form_for/4`, `Phoenix.Component.form/1`).

A hand-rolled struct like this DOES NOT WORK:

```heex
<.input field={
  %Phoenix.HTML.FormField{
    name: :status_class, id: nil, form: nil,
    field: :status_class, errors: [], value: @filters["status_class"]
  }
} type="select" ...
/>
```

**Symptoms** (runtime, not compile):
- `(BadMapError) expected a map, got: nil`
- `(ArgumentError) errors must be a list, got: ...`
- The component silently renders the wrong field name (`filter[status_class]`
  vs `filter[scope_status_class]`).
- The form submits without values for that field.

**Fix**: assign a real form in mount and stream events through it.

```elixir
socket =
  socket
  |> assign(:filters, default_filters())
  |> assign(:form, to_form(default_filters(), as: :filter))

def handle_event("filter", params, socket) do
  filter_params = params |> Map.get("filter", %{}) |> then(&Map.merge(default_filters(), &1))
  socket
  |> assign(:filters, filter_params)
  |> assign(:form, to_form(filter_params, as: :filter))   # re-build on every change
  |> ...
end
```

HEEx:
```heex
<.form for={@form} id="..." phx-change="filter">
  <.input field={@form[:status_class]} type="select" ... />
  ...
</.form>
```

## Reassigning `@form` on every event is mandatory

`to_form/1` captures the field values at the moment it's called. If you
update `@filters` but forget to reassign `@form`, the rendered inputs keep
displaying the OLD values (no error — silent staleness).

Always pair `assign(:filters, ...)` with `assign(:form, to_form(...))`.

## Raw maps as `<.form for={...}>` break the same way

`<.form for={%{"a" => 1}}>` produces:
```
** (ArgumentError) conn must be a Plug.Conn or a Phoenix.LiveView socket
```
or `(BadMapError)` deep in `form/1`. Pass a form, not a plain map.

## When to NOT use a form at all

If the inputs don't submit as one transaction (e.g. independent filters
that each fire `phx-change` and you read params from `socket.assigns`
elsewhere), you don't need `<.form>` and don't need FormFields at all —
just put inputs inside a `<div>` and read their values from assigns.
Less wiring, no FormField plumbing required.

## `to_form/1` accepts both a map and a changeset

`to_form(attrs, opts)` and `to_form(changeset, opts)` both return a `%Form{}`
with `:source` set to the original. Use whichever your data is — for plain
maps (config-style filters), `to_form(map)` is simpler than building a
changeset.
