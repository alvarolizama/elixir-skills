# HEEx Pitfalls: `not @assign` and Cascading Selects

## `not @assign` ArgumentError

In HEEx templates, `not @some_assign` raises `ArgumentError` when the assign is
`nil` — `Kernel.not/1` requires a strict boolean, and `nil` is not one. This
crashes the LiveView render with a 500 on initial render (before any event sets
the assign).

**Symptom**: `** (ArgumentError) argument error` in `some_live.html.heex:162`
on initial page load.

**Fix**: use `is_nil/1` instead of `not @assign`:

```heex
<!-- BROKEN: crashes when @selected_provider_id is nil -->
disabled={not @selected_provider_id}

<!-- FIXED: works for nil and binary values -->
disabled={is_nil(@selected_provider_id)}
```

For compound conditions with `or`:

```heex
<!-- BROKEN -->
disabled={not @selected_provider_id or not @selected_credential_id or not @selected_model}

<!-- FIXED -->
disabled={is_nil(@selected_provider_id) or is_nil(@selected_credential_id) or is_nil(@selected_model)}
```

**Rule**: in HEEx, never use `not @assign` for nil-checking. Always use
`is_nil(@assign)`. Reserve `not` for assigns you know are booleans
(e.g. `not @loading_models` where `loading_models` is always `true` or `false`).

## Cascading selects (provider → credential → model)

When a form needs dependent selects where picking the first loads options for
the second, and picking the second fetches data for the third:

### Pattern

1. **Three separate `<.form>` wrappers** with `phx-change` each — not one big
   form. Each select fires its own event on change. Use `class="contents"` on
   each form so the wrapper doesn't break grid layout.

2. **Each `handle_event` loads the next select's data** and resets downstream
   selects (clear `selected_credential_id`, `available_models`, etc.).

3. **Async fetch** (e.g. hitting an external API for models) uses
   `send(self(), {:fetch_models, ...})` + `handle_info`:

```elixir
def handle_event("select_credential", %{"target" => %{"credential_id" => id}}, socket) do
  send(self(), {:fetch_models, socket.assigns.selected_provider_id, id})
  {:noreply, socket |> assign(:loading_models, true) |> assign(:available_models, [])}
end

def handle_info({:fetch_models, provider_id, credential_id}, socket) do
  models = fetch_models_from_api(provider_id, credential_id)
  {:noreply, socket |> assign(:available_models, models) |> assign(:loading_models, false)}
end
```

4. **Loading state** in the template while the async fetch runs:

```heex
<%= if @loading_models do %>
  <option value="">Cargando modelos…</option>
<% else %>
  <option value="">Modelo…</option>
  <%= for model <- @available_models do %>
    <option value={model}>{model}</option>
  <% end %>
<% end %>
```

5. **Add button** uses `phx-click` with `phx-value-*` from assigns (not form
   submit), disabled until all three selects have values. Use `is_nil/1` for
   the disabled condition.

### Pitfalls

- **`disabled` on selects**: disabled selects don't fire `phx-change`, which
  is the desired behavior — the user can't pick a credential before picking
  a provider.
- **Reset downstream selects**: when the provider changes, clear
  `selected_credential_id`, `available_models`, and `selected_model`. When
  the credential changes, clear `available_models` and `selected_model`.
- **`class="contents"` on forms**: the three forms need to lay out as a grid
  alongside the button. `class="contents"` makes the form wrapper invisible
  to the grid layout.
