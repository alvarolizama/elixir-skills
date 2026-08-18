# Elixir Umbrella Gotchas

Non-obvious failures encountered building a Phoenix umbrella project (Elixir 1.20, Phoenix 1.7+, June 2026). Each caused real test failures or compilation crashes.

## 1. Directory names must match OTP app names (Elixir 1.20+)

**Symptom:** `mix compile` fails with obscure path/module resolution errors.

**Root cause:** Elixir 1.20 enforces that umbrella app directories match their OTP app names. `apps/core/` for `:money_bot_core` does not work.

**Fix:** Use full names: `apps/money_bot_core/`, `apps/money_bot_sites/`, `apps/money_bot_admin/`. Always. No shortcuts.

**Planning tip:** When writing plans or dispatching subagents, always reference the full directory name. Don't say `apps/core/` — say `apps/money_bot_core/`. Subagents that follow the plan literally will create wrong directories.

## 2. Phoenix.PubSub in a non-Phoenix app

**Symptom:** App crashes on start:
```
Application money_bot_core exited: MoneyBotCore.Application.start(:normal, []) returned an error: shutdown: failed to start child: Phoenix.PubSub.Supervisor
  ** (EXIT) shutdown: failed to start child: Phoenix.PubSub.PG2
      ** (EXIT) shutdown: failed to start child: MoneyBot.PubSub.Adapter
```

**Root cause:** Core app uses `Phoenix.PubSub` in its Application children but doesn't have `:phoenix` or `:phoenix_pubsub` as a dependency. The module isn't available at runtime.

**Fix:** Add `{:phoenix_pubsub, "~> 2.1"}` to the core app's deps in `mix.exs`. You don't need full `:phoenix` — just `:phoenix_pubsub`.

## 3. Ecto UUID autogeneration: autogenerate: false returns nil IDs

**Symptom:** After `Repo.insert`, the struct has `id: nil`. Tests fail with:
```
** (Ecto.NoPrimaryKeyValueError) struct is missing primary key value
```

**Root cause:** `@primary_key {:id, :binary_id, autogenerate: false}` tells Ecto to NOT generate the ID and NOT read it back from the DB. Even though the migration has `default: {:fragment, "gen_random_uuid()"}`, Ecto doesn't read DB defaults for primary keys when `autogenerate: false`.

**Fix:** Use `@primary_key {:id, :binary_id, autogenerate: true}`. Ecto will:
1. NOT send `id` in the INSERT (letting the DB `default: gen_random_uuid()` kick in)
2. Read the generated UUID back after insert

```elixir
# WRONG — id will be nil after insert
@primary_key {:id, :binary_id, autogenerate: false}

# RIGHT — DB generates UUID, Ecto reads it back
@primary_key {:id, :binary_id, autogenerate: true}
```

## 4. Ecto Sandbox pool not applied in test

**Symptom:** All tests fail with:
```
** (RuntimeError) cannot invoke sandbox operation with pool DBConnection.ConnectionPool.
To use the SQL Sandbox, configure your repository pool as:
    pool: Ecto.Adapters.SQL.Sandbox
```

Even though `config/test.exs` has `pool: Ecto.Adapters.SQL.Sandbox`.

**Root cause:** `config/config.exs` configures the Repo with `pool_size: 10` (no `pool:` → defaults to `DBConnection.ConnectionPool`). When `Application.ensure_all_started(:money_bot_core)` runs in `test_helper.exs`, the Repo starts with that pool. `config/test.exs` IS loaded but the Repo is already running.

**Fix options (pick one):**

### Option A: Conditional pool in Application.start/2
```elixir
def start(_type, _args) do
  pool = if Mix.env() == :test, do: Ecto.Adapters.SQL.Sandbox, else: DBConnection.ConnectionPool
  children = [
    {MoneyBot.Repo, pool: pool},
    {Phoenix.PubSub, name: MoneyBot.PubSub}
  ]
  Supervisor.start_link(children, strategy: :one_for_one, name: MoneyBotCore.Supervisor)
end
```

### Option B: Don't start the app in test_helper, start Repo manually
```elixir
# test_helper.exs
ExUnit.start()
{:ok, _} = Application.ensure_all_started(:ecto_sql)
# Repo config from config/test.exs (Sandbox) will be used
{:ok, _} = MoneyBot.Repo.start_link()
```

Option A is simpler and more robust.

## 5. Missing errors_on/1 in DataCase

**Symptom:** Tests fail with:
```
error: undefined function errors_on/1
```

**Root cause:** `errors_on/1` is a common test helper that traverses changeset errors, but it's not included in the default Ecto DataCase template.

**Fix:** Add to `DataCase`:
```elixir
def errors_on(changeset) do
  Ecto.Changeset.traverse_errors(changeset, fn {message, opts} ->
    Regex.replace(~r"%{(\w+)}", message, fn _, key ->
      opts |> Keyword.get(String.to_existing_atom(key), key) |> to_string()
    end)
  end)
end
```

## 6. test_helper.exs must start the application

**Symptom:** Tests fail with Repo not started errors.

**Fix:** `test_helper.exs` must include:
```elixir
ExUnit.start()
Application.ensure_all_started(:money_bot_core)
```

Just `ExUnit.start()` alone is not enough if the Application starts the Repo and PubSub.

## 7. Subagent timeout on large tasks

**Symptom:** Subagent dispatched with a large task (create migration + 3 schemas + context + tests) times out after 600s with partial work done.

**Lesson:** Large Elixir tasks (migration + schema + context + tests all in one) can exceed the subagent timeout. If a subagent times out:
1. Check what files were created — the work is often partially done
2. Run `mix compile --warnings-as-errors` to see what compiles
3. Run `mix ecto.migrate` to see if the migration works
4. Finish the remaining work yourself or dispatch a smaller follow-up

## 8. Tailwind v4 vs v3 config mismatch (CSS not loading)

**Symptom:** Browser loads the page but CSS is unstyled. `/assets/app.css` returns 404 or empty.

**Root cause:** The `tailwind` hex package ≥0.3 ships Tailwind CLI v4, but `tailwind.config.js` uses v3 syntax (`content`, `theme.extend`, `require()`). Tailwind v4 ignores `tailwind.config.js` — config lives in CSS via `@theme {}`.

**Fix:** Delete `tailwind.config.js`, migrate to `@theme` in `app.css`, add tailwind profiles to `config/config.exs`, add watchers to `config/dev.exs`, compile with `mix tailwind <profile>`. See `references/phoenix-tailwind-v4-assets.md` for full recipe.

## 9. LiveView tests: `live_isolated` does NOT support `assign:` option

**Symptom:** LiveView receives `socket.assigns[:site]` as nil even though test passes `assign: %{site: site}`.

**Root cause:** `live_isolated/3` silently ignores the `assign:` key. Only `session:` is passed to the LiveView.

**Fix:** Pass data via `session: %{"site_id" => site.id}` and load from DB in `mount/3`. See `references/phoenix-liveview-testing.md` for full pattern.

## 10. LiveView tests: `live_isolated` passes `:not_mounted_at_router` as params

**Symptom:** `(FunctionClauseError) no function clause matching in MyLive.mount/3` or `Access.get/3`.

**Root cause:** `live_isolated` passes the atom `:not_mounted_at_router` as the first arg to `mount/3`, not a map.

**Fix:** Add `def mount(:not_mounted_at_router, session, socket), do: do_mount(session, socket)` clause.

## 11. ConnCase needs shared sandbox mode for LiveView tests

**Symptom:** LiveView tests fail with `query_canceled` or empty query results despite data in setup.

**Fix:** Add `Ecto.Adapters.SQL.Sandbox.mode(MoneyBot.Repo, {:shared, self()})` to ConnCase setup.

For future plans, consider splitting "migration + schemas" and "context + tests" into separate tasks.", "file_type": ".md"}