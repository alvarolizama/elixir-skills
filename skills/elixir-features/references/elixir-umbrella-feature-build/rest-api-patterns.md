# my_app REST API patterns

Reference for building new REST API endpoints in the my_app Phoenix app.
my_app is a single-app Phoenix project (not umbrella), so all modules live
under `lib/my_app/` and `lib/dran_web/`.

## Directory structure

| Layer | Path | Example |
| --- | --- | --- |
| Domain context | `lib/my_app/brain.ex` | `my_app.Brain` — public API for pages, contexts, relations |
| Schema | `lib/my_app/brain/<name>.ex` | `my_app.Brain.Page`, `my_app.Brain.Context`, `my_app.Brain.Relation` |
| Standalone module | `lib/my_app/<module>.ex` | `my_app.Exporter` — non-domain logic (export, serialization) |
| API controller | `lib/dran_web/controllers/api/<name>_controller.ex` | `DranWeb.API.ContextController` |
| Router | `lib/dran_web/router.ex` | `scope "/api", DranWeb.API do ... end` |
| Test | `test/dran_web/api/<name>_controller_test.exs` | `DranWeb.API.ExportControllerTest` |

## Controller conventions

```elixir
defmodule DranWeb.API.MyController do
  use DranWeb, :controller

  alias my_app.Brain          # or alias my_app.MyModule

  def show(conn, %{"slug" => slug}) do
    case MyModule.do_thing(slug) do
      {:ok, data} ->
        json(conn, data)

      {:error, :not_found} ->
        conn
        |> put_status(:not_found)
        |> json(%{errors: %{detail: "not found"}})
    end
  end
end
```

- All API controllers are under the `DranWeb.API` namespace.
- Use `use DranWeb, :controller` (not `use DranWeb, :api`).
- Success: `json(conn, %{data: ...})` or `json(conn, data)`.
- Error: `conn |> put_status(:status) |> json(%{errors: %{detail: "message"}})`.
- Created: `conn |> put_status(:created) |> json(%{data: ...})`.
- Changeset errors: `Ecto.Changeset.traverse_errors/2` → `json(%{errors: format_errors(changeset)})`.

## Router

All API routes live inside one scope with token auth:

```elixir
scope "/api", DranWeb.API do
  pipe_through [:api, :api_auth]
  # ...
  get "/contexts/:slug/export", ExportController, :show
end
```

- `:api` pipeline accepts JSON only.
- `:api_auth` pipeline checks `Authorization: Bearer <token>` via `require_api_token/2`.
- Default token: `"my_app-token"` (set via `DRAN_API_TOKEN` env var).

## Test conventions

```elixir
defmodule DranWeb.API.MyControllerTest do
  use DranWeb.ConnCase, async: false

  setup %{conn: conn} do
    {:ok, conn: put_req_header(conn, "authorization", "Bearer my_app-token")}
  end

  test "does the thing", %{conn: conn} do
    context = Brain.get_context_by_slug("personal")
    # ... create test data ...
    conn = get(conn, ~p"/api/my-endpoint")
    assert json_response(conn, 200)
  end
end
```

- `DranWeb.ConnCase` sets up SQL sandbox and provides `Phoenix.ConnTest`.
- Tests use `async: false` (shared sandbox mode) when they touch inference config.
- Auth header: `put_req_header(conn, "authorization", "Bearer my_app-token")`.
- The `personal` context always exists (seeded in the test DB).
- Use `~p"/api/..."` verified routes in tests for compile-time route checking.
- For endpoints that call inference (search, semantic), stub with `Req.Test.stub(my_app.Inference.Client, fn conn -> ... end)` and set the `:inference` app env (see `references/req-test-stubs.md`).

## Key schemas (for reference)

### Context

```elixir
@derive {Jason.Encoder, only: [:id, :name, :slug, :inserted_at]}
schema "contexts" do
  field :name, :string
  field :slug, :string
  timestamps(type: :utc_datetime, updated_at: false)
end
```

No `description` field — if an export/serialization needs it, return `nil`.

### Page

```elixir
@derive {Jason.Encoder, only: [:id, :context_id, :title, :slug, :body,
  :page_type, :summary, :tags, :meta, :kb_confidence, :kb_source_url,
  :kb_contested, :body_hash, :version, :owner, :created_by,
  :updated_by, :on_behalf_of, :inserted_at, :updated_at]}
```

Page types: `note, comparison, plan, todo, goal, entity, concept,
reference, artifact, query`.

### Relation

```elixir
@derive {Jason.Encoder, only: [:id, :source_id, :target_id, :relation_type, :inserted_at]}
```

Relation types: `related, contradicts, supersedes, part_of, embeds, semantic`.

All schemas use `:binary_id` (UUID) primary keys and `@foreign_key_type :binary_id`.

## Public endpoints (no auth)

Some endpoints must be reachable without authentication — health checks,
status probes, readiness endpoints. These do NOT go under `DranWeb.API` or
inside the `:api_auth` scope.

### Controller (top-level namespace, not API)

```elixir
defmodule DranWeb.HealthController do
  use DranWeb, :controller

  def show(conn, _params) do
    case Ecto.Adapters.SQL.query(my_app.Repo, "SELECT 1") do
      {:ok, _result} ->
        conn
        |> put_status(:ok)
        |> json(%{status: "ok", db: "up", timestamp: DateTime.utc_now()})

      {:error, _reason} ->
        conn
        |> put_status(:service_unavailable)
        |> json(%{status: "error", db: "down"})
    end
  end
end
```

- Controller lives at `lib/dran_web/controllers/health_controller.ex` (not `controllers/api/`).
- Module is `DranWeb.HealthController` (not `DranWeb.API.HealthController`).
- DB probe uses `Ecto.Adapters.SQL.query(my_app.Repo, "SELECT 1")` — returns `{:ok, result}` or `{:error, exception}`.

### Router (separate scope, no auth pipeline)

```elixir
# ── Public health check (no auth) ──

scope "/", DranWeb do
  pipe_through :api

  get "/health", HealthController, :show
end
```

- Place this OUTSIDE all authenticated scopes (`:auth`, `:api_auth`).
- Uses `:api` pipeline only (JSON format negotiation).
- Route path is `/health` (top-level, not under `/api`).

### Manual end-to-end verification

After `mix compile --warnings-as-errors` and `mix test` pass, verify the
endpoint works at runtime:

```bash
# Start server in background
PORT=4099 mix phx.server &

# Wait for startup, then curl
sleep 5
curl -s -w "\nHTTP %{http_code}\n" http://localhost:4099/health
# Expected: {"status":"ok","timestamp":"2026-07-17T...","db":"up"} HTTP 200

# Kill the server
kill %1  # or lsof -ti:4099 | xargs kill
```

When the dev database is down or unreachable, the endpoint correctly
returns 503 with `{"status":"error","db":"down"}` — this is the expected
error path, not a bug. If you see it during manual testing, check whether
Postgres is running before investigating the controller.

## Serialization for export

When building a JSON export that needs slugs instead of IDs (e.g. for
relations), load pages first, build an `id → slug` lookup map, then
map over relations translating `source_id`/`target_id` to slugs:

```elixir
pages = Repo.all(from p in Page, where: p.context_id == ^context_id)
slug_by_id = Map.new(pages, &{&1.id, &1.slug})

relations
|> Enum.map(fn rel ->
  %{source_slug: slug_by_id[rel.source_id], target_slug: slug_by_id[rel.target_id], ...}
end)
```

Or preload `:source`/`:target` on relations and read `.source.slug` / `.target.slug`
directly (handles preloaded structs; use a fallback map for safety).

## Attachment / download endpoints (`content-disposition`)

When an endpoint should trigger a browser "Save as..." dialog instead of
inline JSON rendering, set the `content-disposition` response header to
`attachment; filename="..."` before calling `json/2`:

```elixir
def full(conn, %{"context" => context_id}) do
  case Exporter.full_export(context_id) do
    {:ok, data} ->
      filename = "my_app-export-#{context_id}.json"

      conn
      |> put_resp_header("content-disposition", "attachment; filename=\"#{filename}\"")
      |> json(data)

    {:error, :not_found} ->
      conn
      |> put_status(:not_found)
      |> json(%{errors: %{detail: "context not found"}})
  end
end
```

- Use `put_resp_header(conn, "content-disposition", ...)` — not
  `put_resp_content_type` (the content type stays `application/json`;
  the disposition header is what tells the browser to save).
- The filename in the header should be quoted and URL-safe. Including
  the context id makes downloads from different contexts distinguishable.
- Test the header with `Plug.Conn.get_resp_header(conn, "content-disposition")`
  and assert it contains `"attachment"`:

```elixir
assert conn.status == 200
assert [disp | _] = Plug.Conn.get_resp_header(conn, "content-disposition")
assert disp =~ "attachment"
```

- The response body is still standard JSON — the header only changes
  browser UX behavior, not the payload shape. `json_response(conn, 200)`
  works normally in tests.
- Route these under the same `[:api, :api_auth]` scope as other API
  endpoints — the auth requirement doesn't change for downloads.
