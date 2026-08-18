# HEEx & LiveView Event Pitfalls

Durable pitfalls encountered building my_app_gateway's benchmarks LiveView.

## `not @assign` crashes with ArgumentError in HEEx

In HEEx templates, `not @some_assign` raises `ArgumentError: argument error`
when the assign is `nil` — which is the **initial state** for most assigns
set in `mount/3`. The `not` operator requires a strict boolean (`true` or
`false`), and `nil` is neither.

This commonly appears in `disabled={...}` attributes:

```heex
<!-- ❌ Crashes on mount when @selected_id is nil -->
<select disabled={not @selected_id}>

<!-- ❌ Same crash in a compound expression -->
<button disabled={not @a or not @b or not @c}>
```

**Fix:** use `is_nil/1` which handles `nil` correctly:

```heex
<!-- ✅ Works for nil, string, or any value -->
<select disabled={is_nil(@selected_id)}>

<!-- ✅ Compound -->
<button disabled={is_nil(@a) or is_nil(@b) or is_nil(@c)}>
```

Always use `is_nil/1` (or an explicit nil-check pattern) in HEEx boolean
attributes when the assign starts as `nil`. Reserve `not` for assigns you
guarantee are booleans (e.g., `not @loading` where `loading` defaults to
`false`).

## `phx-value-*` flat params vs form nested params

When a LiveView event handler receives params, the **shape depends on the
source**:

- **`phx-click` button with `phx-value-*` attrs** → flat params:
  `%{"provider_id" => "abc", "credential_id" => "def"}`

- **`phx-submit` form with `name="target[field]"`** → nested params:
  `%{"target" => %{"provider_id" => "abc", "credential_id" => "def"}}`

If the handler pattern-matches one shape (`%{"target" => params}`), it
crashes with `(ArgumentError) argument error` when the other source fires
the same event.

**Fix:** accept generic `params` and normalize:

```elixir
def handle_event("add_target", params, socket) do
  # Works for both flat (button) and nested (form) params
  target = Map.get(params, "target", params)
  provider_id = target["provider_id"] || ""
  # ...
end
```

This is especially common when you have a `<button phx-click="add_target"
phx-value-...>` alongside a `<.form phx-submit="add_target">` — both fire
the same event with different shapes.

## Cascading selects (provider → credential → model)

When building dependent `<select>` dropdowns in LiveView:

1. Each select fires its own `phx-change` event.
2. The handler loads data for the **next** select only (not all at once).
3. For async data (e.g., fetching models from an API), use
   `send(self(), {:fetch_models, ...})` + `handle_info` to avoid blocking
   the event handler.
4. Reset downstream selects when an upstream changes:
   changing provider clears credential + model selections.
5. Use `is_nil/1` for `disabled` attrs (see pitfall above).

Pattern from my_app_gateway benchmarks page:

```elixir
# Select provider → load only that provider's credentials
def handle_event("select_provider", %{"target" => %{"provider_id" => id}}, socket) do
  creds = if id != "", do: Repo.all(from c in Credential, where: c.provider_id == ^id), else: []
  {:noreply, socket |> assign(:available_credentials, creds) |> assign(:selected_credential_id, nil)}
end

# Select credential → async fetch models from provider API
def handle_event("select_credential", %{"target" => %{"credential_id" => id}}, socket) do
  send(self(), {:fetch_models, socket.assigns.selected_provider_id, id})
  {:noreply, assign(socket, :loading_models, true)}
end

def handle_info({:fetch_models, provider_id, cred_id}, socket) do
  {:ok, models} = OpenAIAdapter.list_models(provider, credential)
  {:noreply, assign(socket, :available_models, models, :loading_models, false)}
end
```
