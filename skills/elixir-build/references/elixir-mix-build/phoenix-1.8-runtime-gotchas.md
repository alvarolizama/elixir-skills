# Phoenix 1.8 Runtime Gotchas

Runtime crashes and warnings that appear when running `mix phx.server` in dev, not caught by compilation or tests (Phoenix 1.8, LiveView 1.2+, Elixir 1.20, June 2026).

## 1. `Phoenix.CodeReloader` listener warning

**Symptom:** Every code reload in dev logs:
```
warning: a Mix listener expected by Phoenix.CodeReloader is missing.
Please add the listener to your mix.exs configuration, like so:
    def project do
      [..., listeners: [Phoenix.CodeReloader]]
    end
```

**Fix:** Add `listeners: [Phoenix.CodeReloader]` to the umbrella root `mix.exs`:

```elixir
# mix.exs (umbrella root, NOT sub-app)
def project do
  [
    apps_path: "apps",
    version: "0.1.0",
    start_permanent: Mix.env() == :prod,
    deps: deps(),
    listeners: [Phoenix.CodeReloader]  # ADD THIS
  ]
end
```

Code reload works without it but spams the log. This is a Phoenix 1.8 requirement.

## 2. Admin app inaccessible in dev (RequireAdmin redirect to nonexistent /login)

**Symptom:** `curl http://localhost:3001/` returns 302 → `/login` → `Phoenix.Router.NoRouteError`.

**Root cause:** The admin app has a `RequireAdmin` plug that redirects to `/login` when no admin user is in session. But the admin router has no `/login` route (auth is handled by the public sites app). In dev, there are no users in the DB, so every request redirects and crashes.

**Fix:** Make `RequireAdmin` dev-aware:

```elixir
defmodule MyAppAdminWeb.Plugs.RequireAdmin do
  import Plug.Conn
  import Phoenix.Controller

  def call(conn, _opts) do
    case conn.assigns[:current_user] do
      %{role: "admin"} -> conn
      _ ->
        if Mix.env() == :dev do
          # Dev bypass: auto-assign a fake admin
          assign(conn, :current_user, %{id: "dev", role: "admin", name: "Dev Admin"})
        else
          conn |> redirect(to: "/login") |> halt()
        end
    end
  end
end
```

## 3. `PubSub.subscribe` crashes when site is nil

**Symptom:** `** (BadMapError) expected a map, got: nil` at `Phoenix.PubSub.subscribe(MyApp.PubSub, "site:#{site.id}:topic")`.

**Root cause:** In dev, visiting `localhost:3000` when no site is configured for "localhost" means `site` is nil. Interpolating `nil` into the topic string produces `"site::topic"` which doesn't crash, but if the code does `site.id` before the subscribe, it crashes with `BadMapError` on `nil.id`.

**Fix:** Guard the subscribe call:

```elixir
# WRONG — crashes when site is nil
Phoenix.PubSub.subscribe(MyApp.PubSub, "site:#{site.id}:social_proof")

# RIGHT
if site do
  Phoenix.PubSub.subscribe(MyApp.PubSub, "site:#{site.id}:social_proof")
end
```

## 4. Function components crash when list attrs receive nil from template

**Symptom:** `(Protocol.UndefinedError) protocol Enumerable not implemented for Atom. Got value: nil` when iterating over an attr that should be a list.

**Root cause:** Template passes `badges={@home_config["trust_badges"]}` where `@home_config` is `%{}` (no site configured). The key doesn't exist, so the value is `nil`. Even though the component declares `attr :badges, :list, default: []`, the default only applies when the attr is NOT passed at all — when `nil` is explicitly passed, it stays `nil`.

**Fix:** Normalize at the top of the function component:

```elixir
# WRONG — @badges can be nil from template
def cta_block(assigns) do
  ~H"""
  <div :for={badge <- @badges}>  # crash if @badges is nil
  """
end

# RIGHT — normalize nil to [] before rendering
def cta_block(assigns) do
  badges = assigns[:badges] || []
  assigns = assign(assigns, :badges, badges)
  ~H"""
  <div :for={badge <- @badges}>  # safe
  """
end
```

This pattern applies to ANY function component that receives list-like attrs from template variables that might be nil (home_config keys, map fields, etc.).

## 5. Map-not-list crash in components with fallback logic

**Symptom:** `(Protocol.UndefinedError) protocol Enumerable not implemented for Map` when a component tries to use a map as a list.

**Root cause:** Some components have fallback logic like `items = if items == [], do: config, else: items` where `config` is a map, not a list. When `items` is empty, the fallback assigns a map, and then `Enum.with_index(@items)` or `:for={item <- @items}` crashes.

**Fix:** Always ensure the result is a list:

```elixir
# WRONG — config might be a map
items = if items == [], do: config, else: items

# RIGHT — guard the type
items = if items == [], do: Map.get(config, "faq", items), else: items
items = if is_list(items), do: items, else: []
```