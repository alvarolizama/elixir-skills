# MyApp: Hard-delete user with cascade FK + modal confirmation

## Context

Álvaro wanted the ability to permanently delete a user (not just suspend). The
existing `delete_user/1` was a plain `Repo.delete/1` that would crash on FK
constraints. Analysis revealed a User → TeamMember → (ApiKey + RequestLog)
chain where `request_logs` is a partitioned append-only table with
`team_member_id NOT NULL`.

Álvaro chose **option 1: hard cascade** — delete everything. History loss is
acceptable; the admin is warned via a modal.

## Migration pattern (partitioned tables need raw SQL)

Four FK constraints changed in one migration:

| Table | FK | Before | After |
|---|---|---|---|
| `team_members.user_id` | RESTRICT | **CASCADE** |
| `api_keys.team_member_id` | RESTRICT | **CASCADE** |
| `request_logs.team_member_id` | RESTRICT | **CASCADE** (raw SQL — partitioned) |
| `audit_logs.user_id` | RESTRICT | **SET NULL** (keep audit trail, lose attribution) |

Key details:
- `request_logs` is `PARTITION BY RANGE` — Ecto's `references(on_delete: ...)`
  in `alter table` doesn't work. Must use raw `execute` with
  `ALTER TABLE ... DROP CONSTRAINT IF EXISTS ...` +
  `ALTER TABLE ... ADD CONSTRAINT ... ON DELETE CASCADE`.
- Use the two-argument `execute(up, down)` form for reversibility.
- `audit_logs.user_id` is nullable → `SET NULL` works (keeps the row, nilifies FK).
- After the migration, `Repo.delete(user)` cascades automatically at the DB
  level — no need for an explicit transaction in the context function.

## LiveView handler pattern (modal instead of data-confirm)

Destructive actions that cascade-delete multiple tables should use a **modal**
(`<dialog>`), not `data-confirm`. The modal lists exactly what gets deleted.

### JS hook (app.js)

```javascript
const Modal = {
  mounted() {
    this.handleEvent("open_modal", ({id}) => {
      const el = document.getElementById(id)
      if (el && typeof el.showModal === "function") el.showModal()
    })
    this.handleEvent("close_modal", ({id}) => {
      const el = document.getElementById(id)
      if (el && typeof el.close === "function") el.close()
    })
  }
}
// Add to LiveSocket hooks: {...colocatedHooks, Modal}
```

### Template (DaisyUI `<dialog>`)

```heex
<dialog id="delete-user-modal" class="modal" phx-hook="Modal">
  <div class="modal-box max-w-md">
    <h3 class="text-lg font-bold text-error flex items-center gap-2">
      <.icon name="hero-exclamation-triangle" class="w-5 h-5" />
      Eliminar usuario
    </h3>
    <div class="py-4 space-y-3">
      <p class="text-sm">
        ¿Seguro que quieres eliminar a
        <span class="font-semibold" id="delete-user-email">{@delete_target_email}</span>?
      </p>
      <div class="alert alert-warning text-sm">
        <.icon name="hero-exclamation-triangle" class="w-5 h-5 shrink-0" />
        <div>
          <p class="font-semibold">Esta acción es irreversible.</p>
          <ul class="mt-1 list-disc list-inside space-y-0.5 text-xs">
            <li>Membresías de equipos</li>
            <li>Claves API</li>
            <li>Todo el historial de consumo (request_logs)</li>
            <li>Los logs de auditoría perderán la atribución al usuario</li>
          </ul>
        </div>
      </div>
    </div>
    <div class="modal-action">
      <form method="dialog">
        <button class="btn btn-ghost btn-sm" id="cancel-delete-user">Cancelar</button>
      </form>
      <button phx-click="confirm_delete_user" phx-value-id={@delete_target_id}
        class="btn btn-error btn-sm" id="confirm-delete-user">
        Sí, eliminar permanentemente
      </button>
    </div>
  </div>
  <form method="dialog" class="modal-backdrop"><button>close</button></form>
</dialog>
```

### Two-event handler pattern

1. `open_delete_modal` — sets `delete_target_id` + `delete_target_email` assigns,
   pushes `open_modal` event to show the `<dialog>`.
2. `confirm_delete_user` — validates root-admin and self-delete protections,
   calls `Accounts.delete_user/1`, pushes `close_modal` on success.

```elixir
def handle_event("open_delete_modal", %{"id" => user_id, "email" => email}, socket) do
  {:noreply,
   socket
   |> assign(:delete_target_id, user_id)
   |> assign(:delete_target_email, email)
   |> push_event("open_modal", %{id: "delete-user-modal"})}
end

def handle_event("confirm_delete_user", %{"id" => user_id}, socket) do
  user = Accounts.get_user!(user_id)
  cond do
    root_admin?(user) -> {:noreply, put_flash(socket, :error, "...")}
    user.id == socket.assigns.current_user.id -> {:noreply, put_flash(socket, :error, "...")}
    true ->
      case Accounts.delete_user(user) do
        {:ok, _} -> {:noreply, socket |> put_flash(:info, "...") |> push_event("close_modal", ...) |> load_users()}
        {:error, _} -> {:noreply, put_flash(socket, :error, "...")}
      end
  end
end
```

## Protection rules

- **Root admin** (seed user) cannot be deleted — no delete button rendered.
- **Self-delete** prevented — no delete button for `@current_user`.
- Both checks repeated in the `confirm_delete_user` handler (defense-in-depth).

## Test pattern

Tests must create a user WITH dependent data (team_member + api_key + request_log)
before asserting the cascade works. A test that only creates a user won't catch a
missing cascade.

```elixir
test "confirming delete removes user and all associated data", %{conn: conn} do
  # Setup: user with team_member + api_key + request_log
  %{owner: target, member: member} = team_with_log()

  # Open modal, confirm delete
  view |> element("#delete-#{target.id}") |> render_click()
  html = view |> element("#confirm-delete-user") |> render_click()

  assert html =~ "Usuario eliminado permanentemente"
  assert Accounts.get_user(target.id) == nil
  refute Repo.get(TeamMember, member.id)        # cascade
  refute Repo.get(ApiKey, member.id)            # cascade
end
```

Also test: root admin has no delete button, admin cannot delete self, opening
modal sets target email.

## Verification

- `mix ecto.migrate` (test env auto-migrates)
- `mix test test/my_app_web/live/users_live_test.exs` — 19 passed
- `mix test` — 604 passed (full suite)
