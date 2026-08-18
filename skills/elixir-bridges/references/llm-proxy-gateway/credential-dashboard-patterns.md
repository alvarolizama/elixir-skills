# Credential Dashboard CRUD Patterns

## Partial API Key Update (anti-destroy pattern)

When editing a credential in the admin dashboard, the API key field is
displayed as `type="password"` (masked in the DOM, never rendered as
plaintext). On submit: **if the field is empty, strip it from params**
so the existing key survives intact.

**The pattern** (LiveView `handle_event("save_credential", ...)`):

```elixir
editing_id = socket.assigns[:editing_credential_id]

if editing_id do
  cred = Providers.get_credential!(editing_id)

  # ⚠️ CRITICAL: strip blank api_key or the stored value gets blanked
  cred_params =
    if cred_params["api_key_encrypted"] in [nil, ""] do
      Map.drop(cred_params, ["api_key_encrypted"])
    else
      cred_params
    end

  case Providers.update_credential(cred, cred_params) do
    {:ok, _cred} ->
      {:noreply,
       socket
       |> put_flash(:info, "Credencial actualizada.")
       |> assign(:credential_form, nil)
       |> assign(:editing_credential_id, nil)
       |> load_providers()}

    {:error, changeset} ->
      {:noreply, assign(socket, :credential_form, to_form(changeset, as: :credential))}
  end
else
  # Create path — api_key_encrypted is REQUIRED via validate_required
  ...
end
```

### Template hints for the partial-update UX

```heex
<.input
  field={@credential_form[:api_key_encrypted]}
  type="password"
  label={"API key#{if @editing_credential_id, do: " (dejar vacío = misma)", else: ""}"}
  placeholder={if @editing_credential_id,
    do: "sk-... (dejar vacío para mantener)",
    else: "sk-..."}
  hint={if @editing_credential_id,
    do: "Solo si quieres cambiarla.",
    else: "El token que entrega el proveedor (sk-...)."}
/>
```

And the submit button text reflects the mode:

```heex
<button type="submit">
  {@editing_credential_id && "Actualizar" || "Guardar"}
</button>
```

## Form Mode Pattern (single form assign)

Avoid 3 separate form assigns for create / edit / reset-password. Track
mode with a single atom or optional id:

| Assign | Create | Edit |
|--------|--------|------|
| `@credential_form` | blank changeset (only provider_id + status) | changeset from `change_credential(cred)` (all fields pre-filled) |
| `@editing_credential_id` | `nil` | `cred.id` |

`save_credential` dispatches on `editing_credential_id`:
- `nil` → `Providers.create_credential/1`
- binary → `Providers.update_credential/2`

Both paths clear both form assigns on success + `load_providers()` to
re-query with updated data.

## Credential Status Lifecycle

```
                    ┌──────────┐
                    │  active  │ ◄──────── toggle_credential
                    └────┬─────┘
                         │
               auth_error (401/402/403)
               disabled by proxy_controller
                         │
                         ▼
                    ┌──────────┐
                    │  error   │ ◄── reactivate_credential ──► active
                    └──────────┘
                         │
                    toggle_credential
                         │
                         ▼
                    ┌──────────┐
                    │ disabled │ ◄── toggle_credential ──► active
                    └──────────┘
```

### Dashboard action gating

| Status | Available actions |
|--------|-------------------|
| `active` | Toggle → disabled, Edit, Delete |
| `disabled` | Toggle → active, Edit, Delete |
| `error` | Reactivate (→ active + reset breaker), Edit, Delete. **Cannot toggle** — must reactivate first. |

### Circuit breaker reset on reactivation

```elixir
def reactivate_credential(%Credential{} = credential) do
  case update_credential(credential, %{status: "active", error_reason: nil, error_at: nil}) do
    {:ok, cred} ->
      MyApp.Routing.CircuitBreakerManager.reset(credential.id)
      {:ok, cred}

    {:error, changeset} ->
      {:error, changeset}
  end
end
```

`CircuitBreakerManager.reset` is called SYNCHRONOUSLY — the breaker must
be closed before the credential is eligible for routing. Fire-and-forget
would leave a window where the credential is active but the breaker is
still open → routes fail unnecessarily.

## Testing the partial update

```elixir
# Create → edit with blank api_key → verify existing key survives
view |> element("#edit-credential-#{cred.id}") |> render_click()

view
|> form("#credential-form",
  credential: %{
    name: "New Alias",
    api_key_encrypted: "",     # ← intentionally blank
    max_rpm: "300"
  }
)
|> render_submit()

assert html =~ "Credencial actualizada."

[updated] = Providers.list_credentials_for_provider(provider.id)
assert updated.api_key_encrypted == "original-key"  # ← NOT blanked
assert updated.max_rpm == 300
assert updated.name == "New Alias"
```

## Reference: MyApp implementation

- `lib/my_app_web/live/providers_live.ex` — full LiveView with provider +
  credential CRUD
- `lib/MyApp/providers.ex` — `create_credential/1`, `update_credential/2`,
  `reactivate_credential/1`, `change_credential/2`
- `lib/MyApp/providers/credential.ex` — schema + changeset with
  `validate_required([:provider_id, :api_key_encrypted, :status])`
- `test/my_app_web/live/providers_live_test.exs` — test: create → edit with
  blank api_key → verify not lost → toggle → delete
