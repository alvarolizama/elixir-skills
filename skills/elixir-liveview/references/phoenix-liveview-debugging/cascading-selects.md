# Cascading Selects in LiveView

When a form needs to load options dynamically based on a previous select's
value (e.g. provider → credential → model), use cascading `phx-change`
events with async fetches via `send(self(), {:fetch_models, ...})`.

## Pattern

### 1. Provider select — loads only that provider's active credentials

```elixir
def handle_event("select_provider", %{"target" => %{"provider_id" => id}}, socket) do
  credentials =
    if id != "" do
      from(c in Credential,
        where: c.provider_id == ^id and c.status == "active",
        order_by: [asc: c.name]
      ) |> Repo.all()
    else
      []
    end

  {:noreply,
   socket
   |> assign(:selected_provider_id, if(id == "", do: nil, else: id))
   |> assign(:available_credentials, credentials)
   |> assign(:selected_credential_id, nil)
   |> assign(:available_models, [])
   |> assign(:selected_model, nil)}
end
```

### 2. Credential select — triggers async model fetch from provider's `/models`

```elixir
def handle_event("select_credential", %{"target" => %{"credential_id" => id}}, socket) do
  if id != "" and socket.assigns.selected_provider_id do
    send(self(), {:fetch_models, socket.assigns.selected_provider_id, id})
  end

  {:noreply,
   socket
   |> assign(:selected_credential_id, id)
   |> assign(:loading_models, true)
   |> assign(:available_models, [])
   |> assign(:selected_model, nil)}
end
```

### 3. Model select — populated when handle_info returns

```elixir
def handle_info({:fetch_models, provider_id, credential_id}, socket) do
  provider = Providers.get_provider(provider_id)
  credential = Providers.get_credential(credential_id)

  models =
    if provider && credential do
      case OpenAIAdapter.list_models(provider, credential) do
        {:ok, models} -> models
        {:error, _} -> []
      end
    else
      []
    end

  {:noreply,
   socket
   |> assign(:available_models, models)
   |> assign(:loading_models, false)}
end
```

## Template — each select in its own `<.form>` for independent `phx-change`

```heex
<.form for={%{}} phx-change="select_provider" id="provider-form" class="contents">
  <select name="target[provider_id]" class="select select-bordered select-sm">
    <option value="">Proveedor…</option>
    <option :for={p <- @providers} value={p.id} selected={@selected_provider_id == p.id}>
      {p.name}
    </option>
  </select>
</.form>

<.form for={%{}} phx-change="select_credential" id="credential-form" class="contents">
  <select name="target[credential_id]" class="select select-bordered select-sm"
    disabled={is_nil(@selected_provider_id)}>
    <option value="">Credencial…</option>
    <option :for={c <- @available_credentials} value={c.id}>{c.name}</option>
  </select>
</.form>

<.form for={%{}} phx-change="select_model" id="model-form" class="contents">
  <select name="target[model]" class="select select-bordered select-sm"
    disabled={is_nil(@selected_credential_id)}>
    <%= if @loading_models do %>
      <option value="">Cargando modelos…</option>
    <% else %>
      <option value="">Modelo…</option>
      <option :for={m <- @available_models} value={m} selected={@selected_model == m}>{m}</option>
    <% end %>
  </select>
</.form>

<button phx-click="add_target"
  phx-value-provider_id={@selected_provider_id}
  phx-value-credential_id={@selected_credential_id}
  phx-value-model={@selected_model}
  disabled={is_nil(@selected_provider_id) or is_nil(@selected_credential_id) or is_nil(@selected_model)}
  class="btn btn-ghost btn-sm gap-2">
  <.icon name="hero-plus" class="w-4 h-4" /> Agregar
</button>
```

## Pitfalls

- **`class="contents"`** on each `<.form>` wrapper so the grid layout
  treats each form's child as a direct grid child (the `<form>` element
  itself doesn't create a grid cell).
- **`disabled={is_nil(@...)}`** not `disabled={not @...}` — `not nil`
  raises `ArgumentError`. See `references/heex-render-pitfalls.md`.
- **Add button with `phx-value-*`** sends flat params; handler must
  normalize. See `references/heex-render-pitfalls.md`.
- **`handle_info` fetch is synchronous within the process** — the HTTP
  call to the provider's `/models` endpoint blocks the LiveView process.
  For providers with slow `/models` endpoints, consider `Task.async` +
  `handle_info` with a ref instead.
- **Reset cascade on each step** — when provider changes, clear
  `selected_credential_id`, `available_models`, and `selected_model`.
  When credential changes, clear `available_models` and `selected_model`.
  Not doing this leaves stale options visible from a previous selection.
