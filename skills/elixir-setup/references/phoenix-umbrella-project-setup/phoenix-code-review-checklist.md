# Phoenix Code Review Checklist

Distilled from a full-codebase review of a Phoenix 1.8 LiveView project
(doquant — agents, chat, OpenAI-compatible API client). The project compiled
cleanly and all tests passed, yet these bugs were hiding in plain sight.

## How to use this checklist

1. Read every `.ex`, `.exs`, and `.heex` file in `lib/` and `priv/`.
2. For each file, scan for the patterns below.
3. Run `mix compile --warnings-as-errors && mix test` to establish baseline.
4. Fix bugs by category (critical first, UI/UX second).
5. Re-run the full suite after each batch of fixes.

## Critical bugs (silent, compiles fine, tests pass)

### 1. Type mismatch between Ecto schema and migration

**Pattern:** schema says `field :tool_calls, {:array, :map}` (expects `jsonb[]`)
but migration says `add :tool_calls, :map` (creates `jsonb`).

**Why it's silent:** Ecto doesn't validate schema-vs-migration at compile time.
Tests pass if they never exercise the type mismatch path (e.g., the test that
saves a list of tool_calls will fail, but only that test).

**Fix:** Align both to `{:array, :map}`. Verify the DB column type:

```bash
psql -d myapp_dev -tAc "SELECT atttypid::regtype FROM pg_attribute \
  WHERE attrelid = 'my_table'::regclass AND attname = 'my_column'"
# Should print: jsonb[]
```

**CRITICAL — never modify the original migration.** Always create a NEW
migration with `mix ecto.gen.migration alter_<table>_<change>` to ALTER the
column type. Modifying a committed migration breaks any database that already
ran it. The user will catch this — "no agregaste la migración" or "falta una
no?".

**Casting `jsonb` to `jsonb[]` in Postgres** requires a USING clause with
ARRAY[]:

```sql
-- First, wrap existing non-array values in a JSON array
UPDATE agent_messages SET tool_calls = jsonb_build_array(tool_calls)
WHERE tool_calls IS NOT NULL AND NOT jsonb_typeof(tool_calls) = 'array';

-- Then alter the column type with a USING clause
ALTER TABLE agent_messages ALTER COLUMN tool_calls TYPE jsonb[]
USING CASE WHEN tool_calls IS NULL THEN NULL ELSE ARRAY[tool_calls]::jsonb[] END;
```

A bare `ALTER TABLE ... TYPE jsonb[]` fails with `cannot cast type jsonb to
jsonb[]` — Postgres cannot cast a scalar jsonb to an array type without
explicit wrapping.

### 2. `runtime.exs` config leaking to all environments

**Pattern:** endpoint `http:` config placed outside the `if config_env() == :prod`
block, overriding dev/test settings.

```elixir
# BAD — runs in ALL environments, overwrites dev.exs ip: {127,0,0,1}
config :MyApp, MyappWeb.Endpoint,
  http: [port: String.to_integer(System.get_env("PORT", "4000"))]

if config_env() == :prod do
  ...
end
```

**Fix:** Move all endpoint `http:` config inside the `:prod` block. Dev/test
have their own endpoint config in `dev.exs`/`test.exs`.

### 3. Blocking `handle_info/2` in LiveView

**Pattern:** a `handle_info` callback makes a synchronous HTTP/API call directly:

```elixir
# BAD — freezes LiveView for the entire API call duration
def handle_info({:chat_request, agent, messages}, socket) do
  result = OpenAIClient.chat(agent, messages)  # 30s blocking call
  ...
end
```

**Fix:** Use `Task.Supervisor.async_nolink/2`:

```elixir
def handle_event("send", _params, socket) do
  Task.Supervisor.async_nolink(MyApp.TaskSupervisor, fn ->
    OpenAIClient.chat(agent, messages)
  end)
  {:noreply, assign(socket, :loading, true)}
end

def handle_info({ref, result}, socket) when is_reference(ref) do
  Process.demonitor(ref, [:flush])
  # handle result, stream_insert, etc.
  {:noreply, assign(socket, :loading, false)}
end

def handle_info({:DOWN, _ref, :process, _pid, _reason}, socket) do
  {:noreply, assign(socket, :loading, false)}
end
```

### 4. Pattern-match crash in LiveView helpers

**Pattern:** `{:ok, result} = Context.create(...)` in `handle_params` or
private functions — crashes the LiveView process if the DB call fails.

**Fix:**

```elixir
defp create_session!(agent_id) do
  case Agents.create_session(%{agent_id: agent_id}) do
    {:ok, session} -> session
    {:error, changeset} -> raise "Failed to create session: #{inspect(changeset.errors)}"
  end
end
```

### 5. API key exposed in edit form

**Pattern:** `type="password"` input pre-filled with the current `api_key`
value from the changeset. The secret travels to the browser.

**Fix:** Don't pre-fill. Use placeholder "Leave unchanged to keep current key"
and have `update_agent/2` skip the field when empty:

```elixir
def update_agent(%Agent{} = agent, attrs) do
  attrs =
    if is_map_key(attrs, "api_key") and attrs["api_key"] == "" do
      Map.delete(attrs, "api_key")
    else
      attrs
    end

  agent |> Agent.changeset(attrs) |> Repo.update()
end
```

### 6. Empty system message sent to API

**Pattern:** `build_api_messages/2` always prepends the agent's `soul` as
`%{role: "system", content: agent.soul}` — even when `soul` is `""`.

**Fix:** Conditionally prepend:

```elixir
if agent.soul && agent.soul != "" do
  [%{role: "system", content: agent.soul} | history]
else
  history
end
```

### 7. Silent error swallowing in background tasks

**Pattern:** `{:error, _reason} -> :ok` in `Task.Supervisor.start_child`
workers — failures are invisible.

**Fix:**

```elixir
{:error, reason} ->
  require Logger
  Logger.warning("Embedding failed for message #{message_id}: #{inspect(reason)}")
  :ok
```

### 8. `stream: true` option without SSE parser

**Pattern:** the API client accepts a `:stream` option that passes `stream: true`
to the provider, but `parse_chat_response/1` expects a JSON body, not SSE.

**Fix:** Remove the `:stream` option until streaming is implemented. Don't
ship an option that silently breaks the parser.

## UI/UX issues (compiles, tests pass, but bad UX)

### 9. Inline `<script>` in HEEx templates

AGENTS.md forbids inline `<script>` tags. The Phoenix scaffold ships a
theme-toggle `<script>` in `root.html.heex`. Move it to `app.js` as an IIFE:

```javascript
// app.js — runs before first render, avoids FOUC
;(() => {
  const setTheme = (theme) => { ... }
  if (!document.documentElement.hasAttribute("data-theme")) {
    setTheme(localStorage.getItem("phx:theme") || "system")
  }
  window.addEventListener("phx:set-theme", (e) => setTheme(e.target.dataset.phxTheme))
})()
```

### 10. Layout `max-w-2xl` constraining all pages

The default scaffold wraps `<main>` in `<div class="mx-auto max-w-2xl">`.
Too narrow for chat, dashboards, grids. Remove the wrapper and add per-page
containers:

- `max-w-6xl` for index/grid pages
- `max-w-4xl` for detail pages
- `max-w-3xl` for form pages

### 11. Scaffold cruft in navbar and home page

Clean the navbar to only app-specific links + theme toggle. Replace the
scaffold home page (Phoenix logo, "Peace of mind...") with a real landing
page.

## Verification recipe

```bash
# Full precommit (the project's own quality gate)
mix precommit

# Or manual:
mix compile --warnings-as-errors
mix format --check-formatted
mix deps.unlock --unused
mix ecto.drop --quiet && mix ecto.create --quiet && mix ecto.migrate --quiet
mix test
```

For targeted verification of specific fixes, write a shell script that
checks each changed behavior:

```bash
# Example: verify tool_calls column is jsonb[]
COL_TYPE=$(psql -d myapp_dev -tAc \
  "SELECT atttypid::regtype FROM pg_attribute \
   WHERE attrelid = 'agent_messages'::regclass AND attname = 'tool_calls'")
echo "$COL_TYPE" | grep -q "jsonb\[\]" && echo "PASS" || echo "FAIL"

# Example: verify no inline <script> in templates
INLINE=$(grep -rn '<script>' lib/myapp_web/ 2>/dev/null | wc -l | tr -d ' ')
[ "$INLINE" -eq 0 ] && echo "PASS" || echo "FAIL"
```
