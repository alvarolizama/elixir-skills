# Money Bot session fixes — 2026-06-22

Session-run detail for the Money Bot umbrella at `/Users/alvaro/Workspace/repos/money_bot`. These are concrete fixes applied after background subagents left the umbrella non-compiling.

## 1. Subagent-generated `*_web.ex` was broken

### Error
```
** (UndefinedFunctionError) function PhoenixHTMLHelpers.Form.__using__/1 is undefined
```

### Fix
In `apps/sites/lib/sites_web.ex` and `apps/admin/lib/admin_web.ex`, import the helpers, do not `use` them:

```elixir
def html do
  quote do
    use Phoenix.Component

    import Phoenix.HTML
    import Phoenix.HTML.Form
    import PhoenixHTMLHelpers.Form
    import PhoenixHTMLHelpers.Link
    import PhoenixHTMLHelpers.Tag
    import SitesWeb.Gettext

    unquote(verified_routes())
  end
end
```

Also add `use Phoenix.Component` (not just `import`) inside the `live` macro, and unquote `verified_routes()` in every macro (`router`, `controller`, `live`, `component`, `html`).

## 2. Generated endpoint referenced unavailable modules

### Error
```
warning: Phoenix.LiveReloader.Socket.__struct__/1 is undefined
warning: Phoenix.Ecto.CheckPendingStatus.__struct__/1 is undefined
```

### Fix
Either add `{:phoenix_live_reload, "~> 1.6", only: :dev}` to both apps and run `mix deps.get`, or remove the entire `if code_reloading? do ... end` block from `endpoint.ex`. In `phoenix_ecto` 4.7+ the migration-status plug is `Phoenix.Ecto.CheckRepoStatus`.

For this project the cleanest path was to remove the block and rely on endpoint `code_reloader: true` config.

## 3. No error view defined

### Error
```
** (ArgumentError) no "500" html template defined for SitesWeb.ErrorView  (the module does not exist)
```

### Fix
Configure `render_errors` per endpoint in `config/dev.exs` and `config/test.exs`:

```elixir
config :sites, SitesWeb.Endpoint,
  render_errors: [view: SitesWeb.ErrorHTML, accepts: ~w(html json), layout: false]
```

Create modules:
- `apps/sites/lib/sites_web/controllers/error_html.ex`
- `apps/sites/lib/sites_web/controllers/error_json.ex`
- `apps/admin/lib/admin_web/controllers/error_html.ex`
- `apps/admin/lib/admin_web/controllers/error_json.ex`

And templates:
- `apps/sites/lib/sites_web/controllers/errors/404.html.heex`
- `apps/sites/lib/sites_web/controllers/errors/500.html.heex`
- same for admin.

## 4. LiveView signing salt too short / missing

### Error
```
** (ArgumentError) the signing salt for SitesWeb.Endpoint is missing or too short.
```

### Fix
Add `live_view: [signing_salt: "..."]` to endpoint config. Generate with `mix phx.gen.secret`. In dev/test keep fallback values in `config/dev.exs` and `config/test.exs`.

Example test config:
```elixir
config :sites, SitesWeb.Endpoint,
  secret_key_base: "XfaAVgLprJuSIYSc2GzTdvMxkKdkiNcW7xzupGA/iLRyrK8w4pMFNhWABNo5twOA",
  live_view: [signing_salt: "aB3dE5fG7hI9jK1lM2nO3pQ4rS5tU6vW"]
```

## 5. Cookie store rejected short secret_key_base

### Error
```
** (ArgumentError) cookie store expects conn.secret_key_base to be at least 64 bytes
```

### Fix
Use a real `mix phx.gen.secret` value in dev/test endpoint config. Placeholders like "a_64_char_..." counted visually but were rejected; copy-paste the actual 64-byte string.

## 6. Tests were not collected

### Symptom
`mix test apps/sites` produced no output, no errors, no tests.

### Fix
`elixirc_paths(:test)` must include `"test"`:

```elixir
defp elixirc_paths(:test), do: ["lib", "test/support", "test"]
defp elixirc_paths(_), do: ["lib"]
```

Apply to every Phoenix app in the umbrella.

## 7. Member auth route implementation

Decision: write session in controller, protect LiveViews with `on_mount`.

### Controller login (`apps/sites/lib/sites_web/controllers/member_session_controller.ex`)
- Render a plain HTML form (no LiveView components).
- `Core.Members.authenticate(site.id, email, password)`.
- `put_session(:member_id, member.id)` + redirect to `/members`.

### Protection
```elixir
# plug for controllers / non-live redirects
defmodule SitesWeb.RequireMember do
  import Plug.Conn
  import Phoenix.Controller

  def init(opts), do: opts
  def call(conn, _opts) do
    case get_session(conn, :member_id) do
      nil -> conn |> redirect(to: "/login") |> halt()
      _ -> conn
    end
  end
end

# on_mount for LiveViews
defmodule SitesWeb.LiveMemberAuth do
  import Phoenix.LiveView

  def on_mount(:default, _params, session, socket) do
    if session["member_id"] do
      {:cont, socket}
    else
      {:halt, redirect(socket, to: "/login")}
    end
  end
end
```

### Router
```elixir
scope "/", SitesWeb do
  pipe_through :browser

  get "/login", MemberSessionController, :new
  post "/login", MemberSessionController, :create
end

scope "/", SitesWeb do
  pipe_through [:browser, SitesWeb.RequireMember]

  live_session :members,
    on_mount: [SitesWeb.LiveMemberAuth] do
    live "/members", MemberAreaLive, :index
  end
end
```

## 8. Landing page form in LiveView without `<.form>` components

To avoid missing `input/1` components, use plain HTML forms inside `render/1`:

```elixir
<form phx-submit="save">
  <input type="email" name="lead[email]" required />
  <input type="text" name="lead[name]" />
  <button type="submit">Regístrate gratis</button>
</form>
```

Then handle it in `handle_event("save", %{"lead" => params}, socket)` and call `Core.Members.create_lead/1`.

## 9. Assets: initial build and gitignore

After adding Tailwind and esbuild deps:

```bash
mix deps.get
npm --prefix apps/sites/assets install
npm --prefix apps/admin/assets install
mix tailwind.install --if-missing
mix tailwind sites --minify
mix tailwind admin --minify
mix esbuild sites --minify
mix esbuild admin --minify
```

At minimum commit source files:
- `apps/*/assets/css/app.css`
- `apps/*/assets/js/app.js`
- `apps/*/assets/package.json`
- `config/dev.exs` watchers

And add these lines to `.gitignore`:
```
/apps/sites/assets/node_modules/
/apps/admin/assets/node_modules/
/apps/sites/assets/package-lock.json
/apps/admin/assets/package-lock.json
/apps/sites/priv/static/assets/
/apps/admin/priv/static/assets/
```

## 10. Verification command used after every batch

```bash
mix clean && mix compile --warnings-as-errors && mix test
```

Session result: 49 tests passed, 0 warnings, commit `7a4d691`.
