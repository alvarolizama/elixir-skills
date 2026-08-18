# Phoenix LiveView Testing in Umbrella Apps

Non-obvious failures when testing LiveViews in a Phoenix umbrella app with Ecto Sandbox (Phoenix 1.7+, LiveView 1.2+, Elixir 1.20, June 2026).

## 1. `live_isolated` does NOT support `assign:` option

**Symptom:** LiveView test passes `assign: %{site: site}` but the LiveView's `mount/3` gets `socket.assigns[:site]` as `nil`. All DB queries using that site return empty results.

**Root cause:** `live_isolated/3` accepts `session:` but NOT `assign:`. The `assign:` key is silently ignored. The `conn.assigns` are passed to the socket (via `assign_new: {conn.assigns, []}` in `Utils.configure_socket/3`), but only assigns already on the conn, not from the `assign:` option.

**Fix:** Pass data via `session:` and load it from the DB in `mount/3`:

```elixir
# TEST — wrong
live_isolated(build_conn(), MyLive, assign: %{site: site})

# TEST — correct
live_isolated(build_conn(), MyLive, session: %{"site_id" => site.id})

# LIVEVIEW — load site from session
def mount(:not_mounted_at_router, session, socket), do: do_mount(session, socket)
def mount(_params, session, socket), do: do_mount(session, socket)

defp do_mount(session, socket) do
  site = load_site(session, socket)
  # ...
end

defp load_site(session, socket) do
  case socket.assigns[:site] do
    nil ->
      site_id = session["site_id"]
      if site_id, do: Sites.get_site(site_id), else: nil
    site -> site
  end
end
```

The `load_site/2` pattern checks `socket.assigns[:site]` first (for when the plug pipeline already loaded it), then falls back to session. This makes the LiveView work both in router-mounted mode (plug assigns site) and in isolated test mode (session provides site_id).

## 2. `live_isolated` passes `:not_mounted_at_router` as first arg to `mount/3`

**Symptom:** `(FunctionClauseError) no function clause matching in Access.get/3` or `(FunctionClauseError) no function clause matching in MyLive.mount/3`.

**Root cause:** When `live_isolated` mounts a LiveView that's NOT connected to a router, it passes `:not_mounted_at_router` (an atom) as the first argument to `mount/3`, NOT a map. If `mount/3` does `params["slug"]` or pattern-matches `%{"slug" => slug}`, it crashes.

**Fix:** Add a dedicated clause for `:not_mounted_at_router`:

```elixir
# WRONG — crashes when params is :not_mounted_at_router
def mount(params, session, socket) do
  slug = params["slug"] || session["slug"]
end

# RIGHT — handle both router-mounted and isolated
def mount(:not_mounted_at_router, session, socket), do: do_mount(session, socket)
def mount(%{"slug" => slug} = params, session, socket), do: do_mount(Map.merge(session, params), socket)

defp do_mount(session, socket) do
  slug = session["slug"]
  # ...
end
```

## 3. ConnCase needs `Sandbox.mode({:shared, self()})` for LiveView tests

**Symptom:** LiveView tests fail with `(Postgrex.Error) ERROR 57014 (query_canceled)` or DB queries return empty results even though data was inserted in `setup`.

**Root cause:** LiveView tests spawn processes (the LiveView process) that need to access the test's sandbox transaction. Without `{:shared, self()}`, only the test process can see the data.

**Fix:** Add shared mode to the ConnCase setup:

```elixir
# test/support/conn_case.ex
setup _tags do
  :ok = Ecto.Adapters.SQL.Sandbox.checkout(MoneyBot.Repo)
  Ecto.Adapters.SQL.Sandbox.mode(MoneyBot.Repo, {:shared, self()})  # ADD THIS
  {:ok, conn: Phoenix.ConnTest.build_conn()}
end
```

Also add `import Phoenix.LiveViewTest` to the `using` block if LiveView tests will use `live_isolated`.

## 4. Tests with `async: true` and shared sandbox need unique slugs

**Symptom:** `(Ecto.ConstraintError) constraint error when attempting to insert struct: "domains_site_id_fkey"` or `unique_constraint` violations on `slug`.

**Root cause:** Multiple test modules with `async: true` all use the same hardcoded slug (e.g., `"test"`). With `{:shared, self()}`, each test's sandbox transaction is isolated, BUT `create_site/4` uses a `with` chain (design → site → domain) where a unique constraint failure on the site insert causes the `with` to return `{:error, _}`, and the domain insert never runs — OR the domain insert raises a `ConstraintError` because it lacks `foreign_key_constraint/3` in its changeset.

**Fix:** Use dynamic slugs in every test setup:

```elixir
# WRONG — slug conflicts in async tests
setup do
  {:ok, site} = Sites.create_site("Test Site", "test", "test.example.com")
  {:ok, site: site}
end

# RIGHT — unique per test run
setup do
  slug = "test-#{System.unique_integer([:positive])}"
  {:ok, site} = Sites.create_site("Test Site", slug, "#{slug}.example.com")
  {:ok, site: site}
end
```

Also add `foreign_key_constraint(:site_id)` to the Domain changeset so FK violations become `{:error, changeset}` instead of raising.

### When unique slugs aren't enough: use `async: false`

If tests still fail with constraint errors even with unique slugs (e.g., `Sites.list_sites()` in a LiveView sees sites from other test transactions), set `async: false` on the test module:

```elixir
# Nuclear option — eliminates all parallel-interference issues
use MyConnCase, async: false
```

This is the pragmatic fix when LiveView tests do broad queries (like listing all sites) that can see data from parallel test transactions via the shared sandbox. Use unique slugs first, but don't hesitate to drop to `async: false` if the LiveView's query pattern makes isolation impossible.

## 5. HEEx module attributes vs assigns

**Symptom:** `(KeyError) key :canvas_width not found in assigns` when a function component uses `@canvas_width` in a `~H` sigil.

**Root cause:** In HEEx templates, `@variable` looks up `assigns.variable`, NOT the module attribute `@variable`. If you define `@canvas_width 1920` at the module level and use `@canvas_width` in the template, HEEx tries to find `assigns.canvas_width` which doesn't exist.

**Fix:** Copy module attributes into assigns before rendering:

```elixir
# WRONG — @canvas_width in template looks up assigns, not module attr
@canvas_width 1920

def canvas(assigns) do
  ~H"""
  <div data-canvas-width={@canvas_width}>  # KeyError!
  """
end

# RIGHT — copy to assigns first
@canvas_width 1920

def canvas(assigns) do
  assigns = assign(assigns, :canvas_width, @canvas_width)
  ~H"""
  <div data-canvas-width={@canvas_width}>  # works
  """
end
```

## 6. `put_session` in a Plug without `fetch_session` crashes test conns

**Symptom:** `(ArgumentError) session not fetched, call fetch_session/2` or `(ArgumentError) cannot fetch session without a configured session plug`.

**Root cause:** A custom plug calls `put_session/2` but the test conn hasn't gone through `fetch_session/2`. In production, the `:browser` pipeline does `fetch_session` before the plug. In unit tests that call the plug directly, there's no pipeline.

**Fix:** Either:
1. Remove `put_session` from the plug (assigns are enough for most cases), OR
2. Call `fetch_session(conn)` at the top of the plug's `call/2` (but this fails without a session plug configured on the conn)

For plugs that just need to pass data to the controller/LiveView, `assign/2` is sufficient — no session needed.

## 7. `Repo.get_by` and Ecto queries with nil arguments raise

**Symptom:** `(ArgumentError) nil given for :user_id. Comparison with nil is forbidden as it is unsafe.` or `(ArgumentError) comparing 'lp.user_id' with 'nil' is forbidden as it is unsafe.`

**Root cause:** Both `Repo.get_by(MyModel, user_id: nil)` and Ecto queries like `from(x in MyModel, where: x.user_id == ^nil)` raise because Ecto forbids nil comparisons (they're ambiguous — `WHERE x = NULL` never matches in SQL). This happens when `current_user` is nil (anonymous visitor).

**Fix:** Add guard clauses for ALL functions that receive a potentially-nil user_id:

```elixir
# Repo.get_by pattern
def get_membership(nil, _site_id), do: nil
def get_membership(user_id, site_id) do
  Repo.get_by(Membership, user_id: user_id, site_id: site_id)
end

# Ecto query pattern
def get_progress(_classroom_id, nil), do: []
def get_progress(classroom_id, user_id) do
  from(lp in LessonProgress,
    join: l in Lesson, on: l.id == lp.lesson_id,
    where: l.classroom_id == ^classroom_id and lp.user_id == ^user_id
  )
  |> Repo.all()
end
```

## Summary checklist for LiveView tests

```
[ ] ConnCase has Sandbox.mode({:shared, self()})
[ ] ConnCase imports Phoenix.LiveViewTest
[ ] Tests use unique slugs (System.unique_integer)
[ ] Tests pass data via session: not assign:
[ ] LiveView mount/3 handles :not_mounted_at_router
[ ] LiveView loads site from session["site_id"] when assigns[:site] is nil
[ ] Function components copy module attrs to assigns before ~H
[ ] Changesets have foreign_key_constraint to avoid raises in tests
[ ] Repo.get_by guarded against nil arguments
```