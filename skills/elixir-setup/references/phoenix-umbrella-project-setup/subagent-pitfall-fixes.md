# Subagent pitfall fixes for Phoenix 1.8 umbrella setup

Concrete errors seen when delegating this setup to subagents, with the exact fix.

## `PhoenixHTMLHelpers.Form.__using__/1 is undefined`

**Symptom:**

```
** (UndefinedFunctionError) function PhoenixHTMLHelpers.Form.__using__/1 is undefined or private
```

**Cause:** subagent wrote `use PhoenixHTMLHelpers.Form/Link/Tag` in `*Web.html/0`.

**Fix:** import, do not use:

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

## `Phoenix.Template.embed_templates/1` conflict

**Symptom:**

```
conflicting embed_templates/1 import from modules Phoenix.Template and Phoenix.Component
```

**Cause:** layout module imports `Phoenix.Template, only: [embed_templates: 1]` while also `use Phoenix.Component` (which already brings `embed_templates`).

**Fix:**

```elixir
defmodule SitesWeb.Layouts do
  use SitesWeb, :html
  import Phoenix.Controller, only: [get_csrf_token: 0]
  embed_templates "layouts/*"
end
```

## `<.live_title>` undefined in layout

**Symptom:**

```
undefined function live_title/1 (expected SitesWeb.Layouts to define such a function)
```

**Cause:** `*Web.html/0` does not `use Phoenix.Component`.

**Fix:** add `use Phoenix.Component` at the top of the `html` macro.

## Missing `Phoenix.LiveReloader` / `Phoenix.Ecto.CheckPendingStatus`

**Symptom while compiling with `--warnings-as-errors`:**

```
warning: Phoenix.LiveReloader.call/2 is undefined
warning: Phoenix.Ecto.CheckPendingStatus.call/2 is undefined
```

**Cause:** generated endpoint includes an `if code_reloading? do ... end` block with `Phoenix.LiveReloader`, `Phoenix.CodeReloader`, `Phoenix.Ecto.CheckPendingStatus`. `Phoenix.LiveReloader` requires `phoenix_live_reload` dev dep.

**Fix if you don't want live reload yet:** remove the block entirely:

```elixir
# Removed for now; add back when phoenix_live_reload is added as a dev dep
# if code_reloading? do
#   socket "/phoenix/live_reload/socket", Phoenix.LiveReloader.Socket
#   plug Phoenix.LiveReloader
#   plug Phoenix.CodeReloader
#   plug Phoenix.Ecto.CheckPendingStatus
# end
```

Or add `{:phoenix_live_reload, "~> 1.6", only: :dev}` to both `sites` and `admin` `mix.exs` and run `mix deps.get`.

## `secret_key_base` missing in tests

**Symptom:**

```
** (RuntimeError) missing secret key base for SitesWeb.Endpoint
```

**Cause:** `config/test.exs` only configures the admin endpoint.

**Fix:** add both endpoint configs in `config/test.exs`:

```elixir
config :sites, SitesWeb.Endpoint,
  secret_key_base: "a_test_secret_key_base_for_sites_at_least_64_chars_total",
  http: [ip: {127, 0, 0, 1}, port: 5002]

config :admin, AdminWeb.Endpoint,
  secret_key_base: "a_test_secret_key_base_for_admin_at_least_64_chars_total_xxx",
  http: [ip: {127, 0, 0, 1}, port: 5003]
```

## Subagent race on `web.ex`

**Symptom:**

The file compiles but has a mangled macro: missing `use Phoenix.Component`, duplicated imports, or `verify_routes()` not included in `:live`/`:component`.

**Cause:** two sibling subagents edited the same `*web.ex` file concurrently.

**Fix:** re-read the file and rewrite it cleanly with `write_file`, then run `mix compile --warnings-as-errors`.

## `.env` multiline secrets break `mise`

**Symptom:**

```
malformed value in .env
```

**Cause:** a subagent pasted base64 secrets with line continuations (`\`).

**Fix:**

```bash
# Paste as single-line strings, no backslashes
SECRET_KEY_BASE_SITES=longsinglelinebase64stringhere
SECRET_KEY_BASE_ADMIN=anotherlongsinglelinebase64stringhere
```

Then `mise trust` and `mise exec -- elixir --version`.

## `mix.lock` corruption after parallel app scaffolding

**Symptom:**

```
** (Mix.Error) Your mix.lock contains invalid data
```

**Cause:** parallel subagents both ran `mix deps.get` and overwrote `mix.lock`.

**Fix:**

1. Regenerate from scratch: `mix deps.get` (then `mix deps.update --all` if needed).
2. Commit `mix.lock` yourself before dispatching the next batch.
