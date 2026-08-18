# Sidebar Organization Audit

Worked reference for auditing and reorganizing a Phoenix LiveView sidebar
that has accumulated items in wrong sections or duplicate group headers.
Verified on MyApp's `layouts.ex` sidebar (2026-07-28).

## The problem

Over time, sidebar nav items get added to whatever group was convenient at
the time. The result: duplicate group labels (two "Acceso" sections), items
in wrong sections (Logs under "Acceso" instead of "Monitoreo"), and
admin-only items locked behind a group-level `:if` that hides
all-user items.

## Audit pattern

### 1. Flatten all nav items and identify their access level

Read `router.ex` to map each route to its `live_session`:

```elixir
# live_session :dashboard — all authenticated users
live "/dashboard/teams", TeamsLive
live "/dashboard/logs", LogsLive

# live_session :admin — admin only
live "/dashboard/providers", ProvidersLive
live "/dashboard/users", UsersLive
```

### 2. Group by domain logic

| Group | Domain | Typical items |
|---|---|---|
| Configuración | Infrastructure setup | Proveedores, Modelos, Equipos |
| Acceso | User/credential management | Usuarios, API Keys |
| Monitoreo | Runtime observability | Logs, Alertas, Créditos |

### 3. Per-item admin guard (not group-level)

Move the `:if={admin?(...)}` from the group `<div>` to each `<.sidebar_link>`:

```heex
<div class="space-y-1">
  <p class="px-3 text-xs font-semibold uppercase tracking-wide text-base-content/40">
    Configuración
  </p>
  <.sidebar_link
    :if={admin?(@current_scope)}
    href={~p"/dashboard/providers"}
    label="Proveedores"
    icon="hero-server-stack"
  />
  <.sidebar_link
    :if={admin?(@current_scope)}
    href={~p"/dashboard/models"}
    label="Modelos"
    icon="hero-rectangle-stack"
  />
  <.sidebar_link href={~p"/dashboard/teams"} label="Equipos" icon="hero-user-group" />
</div>
```

This lets all-user items (Equipos) share a group with admin-only items
(Proveedores, Modelos) without leaking admin routes to regular users.

### 4. Deduplicate group headers

A common bug is having two `<div>` blocks with the same label:

```heex
<!-- BEFORE — two "Acceso" sections -->
<div class="space-y-1">
  <p>Acceso</p>
  <.sidebar_link href={~p"/dashboard/teams"} .../>
</div>
<div class="space-y-1">
  <p>Acceso</p>
  <.sidebar_link href={~p"/dashboard/logs"} .../>
</div>
```

Merge into one, or reclassify items into the correct group (Logs → Monitoreo).

### 5. Ordering within groups

When the user specifies an order, respect it exactly. Example:
"Configuración: Proveedores → Modelos → Equipos" means Proveedores first,
then Modelos, then Equipos — even if they were previously in a different
order (Modelos before Proveedores).

## Pitfalls

- **Group-level `:if` hides all-user items** — if you put
  `:if={admin?(@current_scope)}` on the group `<div>`, all-user items
  in that group (e.g. Equipos) become invisible to regular users.
  Move the guard to each `<.sidebar_link>`.
- **Duplicate group labels** — search for the group label text in
  `layouts.ex` to find duplicates before merging.
- **Forgetting to check the router** — don't guess which routes are
  admin-only. Read `router.ex` to confirm which `live_session` each
  route belongs to.
