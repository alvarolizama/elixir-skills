# Credential Management (Partial Update)

Applies when building a provider/credential CRUD page into the proxy's admin dashboard.

## Separate create/update changesets for partial edits

A credential has `api_key_encrypted` with `validate_required`. On edit, the user should be able to change other fields (name, RPM, timeout) **without re-entering the API key**. A single `changeset/2` with `validate_required([:api_key_encrypted])` blocks this because the field is absent from params.

**Pattern — two changesets in the schema module:**

```elixir
@shared ~w(provider_id name max_rpm max_concurrent receive_timeout_ms
    status error_reason error_at)a

def create_changeset(credential, attrs) do
  credential
  |> cast(attrs, @shared ++ [:api_key_encrypted])
  |> validate_required([:provider_id, :api_key_encrypted, :status])
  |> validate_inclusion(:status, @statuses)
  |> foreign_key_constraint(:provider_id)
end

def update_changeset(credential, attrs) do
  credential
  |> cast(attrs, @shared ++ [:api_key_encrypted])
  |> validate_required([:provider_id, :status])    # api_key NOT required
  |> validate_inclusion(:status, @statuses)
  |> foreign_key_constraint(:provider_id)
end

# Default changeset = create (backward compat)
def changeset(credential, attrs), do: create_changeset(credential, attrs)
```

The context function uses the right one:

```elixir
def update_credential(%Credential{} = credential, attrs) do
  credential
  |> Credential.update_changeset(attrs)
  |> Repo.update()
end
```

## LiveView: bifurcated save based on editing_id

```elixir
def handle_event("save_credential", %{"credential" => cred_params}, socket) do
  editing_id = socket.assigns[:editing_credential_id]

  if editing_id do
    cred = Providers.get_credential!(editing_id)

    # Remove empty api_key so update_changeset doesn't overwrite with nil
    cred_params =
      if cred_params["api_key_encrypted"] in [nil, ""] do
        Map.drop(cred_params, ["api_key_encrypted"])
      else
        cred_params
      end

    case Providers.update_credential(cred, cred_params) do
      {:ok, _cred} -> ...flash + reset editing_credential_id
      {:error, changeset} -> assign form
    end
  else
    case Providers.create_credential(cred_params) do
      {:ok, _cred} -> ...flash
      {:error, changeset} -> assign form
    end
  end
end
```

## Template: dynamic label/placeholder for api_key field

```heex
<.input
  field={@credential_form[:api_key_encrypted]}
  type="password"
  label={"API key#{if @editing_credential_id, do: " (dejar vacío = misma)", else: ""}"}
  placeholder={if @editing_credential_id, do: "sk-... (dejar vacío para mantener)", else: "sk-..."}
/>
```
