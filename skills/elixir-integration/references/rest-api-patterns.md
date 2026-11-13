# REST API Patterns in Elixir

Controller/router conventions, public health endpoints, token auth with
`Req.Test` stubbing, and attachment downloads — built from real API work.
Symptom → mechanism → fix → verification.

## Controller conventions

**Symptom.** Error responses differ per endpoint; clients parse three
shapes of failure.

**Fix.** One shape for success, one for failure, everywhere:

```elixir
# success
json(conn, %{data: %{...}})
# failure
conn |> put_status(status) |> json(%{errors: %{detail: message}})
# changeset
conn
|> put_status(:unprocessable_entity)
|> json(%{errors: Ecto.Changeset.traverse_errors(changeset, & &1)})
```

The context returns `{:ok, resource}` / `{:error, :reason}` / `{:error, %Ecto.Changeset{}}`;
the controller `case`s on it. No context function returns a conn.

## Router conventions

One `/api` scope:

```elixir
scope "/api", MyAppWeb do
  pipe_through [:api, :api_auth]
  resources "/records", RecordController
end
```

- `:api_auth` validates `Authorization: Bearer <hashed token>` read from
  env at runtime (not compiled into the binary).
- Route helpers come from `MyAppWeb.Router.Helpers` — verify with
  `~p"/api/..."` and `routes/0` (the `verify_routes: true` / route
  verification compile-time feature catches typos).

## Public health endpoints

**Symptom.** The load balancer marks the whole node down because `/health` is inside `:api_auth` and returns 401.

**Fix.** Health/status is PUBLIC by contract: own controller OUTSIDE the
API namespace, top-level `/health` route, `:api` pipeline only (no auth
plug), DB probe:

```elixir
def health(conn, _) do
  case Repo.query("SELECT 1") do
    {:ok, _}  -> json(conn, %{status: "ok", db: "up"})
    {:error, _} -> conn |> put_status(:service_unavailable) |> json(%{status: "degraded", db: "down"})
  end
end
```

A 503 that still reports `db: "up"` lies to the load balancer and to the
on-call engineer: the probe failed, so the DB is DOWN as far as this node can
tell. `status: "degraded"` + `db: "down"` is the honest contract.

**Verification.** Two curls, both required:

```bash
# healthy path
curl -s -w "\n%{http_code}\n" http://localhost:4000/health
# expect {"status":"ok","db":"up"} and HTTP 200

# degraded path: stop the DB (or point the runtime host at a dead port), then
curl -s -w "\n%{http_code}\n" http://localhost:4000/health
# expect {"status":"degraded","db":"down"} and HTTP 503 — never 503 + "db":"up"
```

## Token auth plug

**Symptom.** Tokens are stored in plaintext, or compared with `==` (timing
leak), or read from `get_req_header` twice.

**Fix.** Hash tokens with a KDF (e.g. Bcrypt/Argon2) at issue time; store
only hashes. Compare with `Plug.Crypto.secure_compare/2`:

```elixir
def call(conn, _opts) do
  with ["Bearer " <> token] <- get_req_header(conn, "authorization"),
       {:ok, user} <- Auth.authenticate_token(token) do
    assign(conn, :current_user, user)
  else
    _ -> conn |> send_resp(401, "unauthorized") |> halt()
  end
end
```

Read the header ONCE. Never log the raw token.

## `Req.Test` stubbing

**Symptom.** Tests hit the real network (flaky, rate-limited) because outbound `Req`/`HTTPoison` calls are unmocked.

**Fix.** Register the stub for the test process and run `Req.Test` in
`async: false` tests (or use the per-test allowlist):

```elixir
describe "fetch" do
  setup do
    Req.Test.allow(MyApp.Http, self(), test_process: self())
    Req.Test.stub(MyApp.Http, fn conn ->
      case conn.request_path do
        "/records" -> Plug.Conn.resp(conn, 200, ~s({"records":[]}))
        _ -> Plug.Conn.resp(conn, 404, "{}")
      end
    end)
    :ok
  end
end
```

Gotchas:

- **Routing stub:** stub the `request_path` AFTER
  `Phoenix.Router`-style rewriting, not the raw path — otherwise the
  pattern never matches.
- **Cross-process counter:** `Req.Test.stub/2` is per-process; a counter
  incremented inside the stub does not propagate to the test process.
  Return the count in the response body, or use an `:atomics` counter
  shared across processes.
- Never stub via a global mutable env — flaky with `async: true`.

## Attachment downloads

**Symptom.** `send_file(conn, 200, path)` serves the file but leaks the
full server path in `Content-Disposition`, and browsers cache stale copies.

**Fix.**

```elixir
conn
|> put_resp_header("content-disposition", ~s(attachment; filename="#{sanitized}"))
|> put_resp_header("cache-control", "private, max-age=0, must-revalidate")
|> send_file(200, path)
```

Sanitize the filename (strip path separators, control chars); never echo a
client-supplied filename verbatim. Serve only files inside the configured
storage dir — a `../` traversal must resolve to nothing.

**Verification.** `curl -I` shows the sanitized filename and
`cache-control: private`.

## Verification commands

```bash
mix compile --warnings-as-errors && mix test

# health endpoint public AND honest about the degraded case
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:4000/health   # 200
# with the DB unreachable, same endpoint:
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:4000/health   # 503, body has "db":"down"

# no plaintext token comparison anywhere
grep -rn "== token\|token ==" lib/ | wc -l                              # expect 0
```