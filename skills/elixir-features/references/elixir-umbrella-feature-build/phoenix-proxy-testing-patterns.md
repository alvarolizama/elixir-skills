# Phoenix proxy / streaming / HTTP-adapter testing patterns

Validated building my_app_gateway (OpenAI-compatible LLM proxy, 2026-07-25): 418 tests
green, zero mock libraries — everything runs against live in-test Bandit servers
and the real supervision tree. Use when testing provider adapters, webhook
workers, SSE/streaming controllers, or any code that calls out over HTTP.

## 1. Bandit as an in-test HTTP server (no mock deps)

Bandit + Plug are already Phoenix deps — start a tiny plug as the fake upstream
instead of adding Bypass/mock:

```elixir
setup do
  :persistent_term.put({TestPlug, :test_pid}, self())
  start_supervised!({Bandit, plug: TestPlug, scheme: :http, ip: :loopback, port: 41234})
  :ok
end
```

`async: false` + a fixed high port per test file (41234, 41235, 41236…) — port 0
gives no easy way to learn the assigned port.

### Marker path segments for error routes

The adapter under test appends its own path (`base_url <> "/v1/chat/completions"`),
so you can't route by full path. Use marker segments and match on `path_info`:

```elixir
defp route(conn, body) do
  cond do
    "slow"    in conn.path_info -> Process.sleep(200); json(conn, 200, %{"ok" => true})
    "limited" in conn.path_info -> json(conn, 429, %{"error" => "slow down"})
    "broken"  in conn.path_info -> json(conn, 500, %{"error" => "boom"})
    conn.request_path == "/v1/chat/completions" -> chat(conn, body)
    true -> json(conn, 404, %{})
  end
end

# Test: point the provider at "http://localhost:41234/limited"
```

Gotcha: `"limited" in conn.path_info` is EXACT list membership — a segment named
`"stream_limited"` does NOT match `"limited"`. Keep markers single-segment.

### Capturing requests (passthrough verification)

To assert the payload went through byte-for-byte (transparent proxy contract),
the plug mails the raw body to the test pid via `:persistent_term`:

```elixir
def call(conn, _opts) do
  {:ok, body, conn} = read_body(conn)
  if pid = :persistent_term.get({__MODULE__, :test_pid}, nil) do
    send(pid, {:captured, %{body: body, auth: get_req_header(conn, "authorization")}})
  end
  route(conn, body)
end

# Test: assert_receive {:captured, %{body: raw}}; assert Jason.decode!(raw) == payload
```

## 2. Chunked (SSE) conn tests: thread conn through EVERY Plug.Conn.chunk

In Phoenix conn tests, each `Plug.Conn.chunk/2` returns a NEW conn carrying the
accumulated `resp_body`. Discarding it loses those bytes from the final response:

```elixir
# BAD — the "[DONE]" frame never appears in resp_body
_ = Plug.Conn.chunk(conn, "data: [DONE]\n\n")
finish(conn)

# GOOD
conn =
  case Plug.Conn.chunk(conn, "data: [DONE]\n\n") do
    {:ok, conn} -> conn
    {:error, _closed} -> conn
  end
```

Symptom: `List.last(frames) == "data: [DONE]"` fails — the last frame is the one
before the discarded chunk. Applies to every helper that chunks (stream loops,
finish functions), not just the final one.

Asserting SSE responses in conn tests: `conn.state == :chunked`,
`response(conn, 200)` returns the full buffered body; split frames on `"\n\n"`.

## 3. Decimal equality in assertions — `Decimal.equal?/2`, never `==/2`

`Decimal.round(x, 6)` yields `Decimal.new("0.012500")`; `==` compares struct
coef+exp, so `== Decimal.new("0.0125")` FAILS on numerically-equal values:

```elixir
# BAD
assert costs.cost_usd == Decimal.new("0.000150")

# GOOD
assert Decimal.equal?(costs.cost_usd, Decimal.new("0.000150"))
```

For floats in JSON responses, `assert_in_delta body["cost_usd"], 0.00015, 1.0e-7`.

## 4. Money in ETS counters: micro-USD integers

For atomic `:ets.update_counter` money tracking (budgets, metrics), store
micro-USD (`Decimal.mult(usd, 1_000_000) |> Decimal.round(0) |> Decimal.to_integer`)
— integers stay atomic and exact; floats drift. Convert back with
`Decimal.new(micro) |> Decimal.div(1_000_000)`. Verified exact over 10k accumulations.

## 5. Oban manual-mode in conn tests

The endpoint enqueues jobs (request logs, webhooks); test env runs
`testing: :manual` so nothing executes until drained:

```elixir
use Oban.Testing, repo: MyApp.Repo

assert_enqueued(worker: MyApp.Logs.WriteWorker)
assert %{success: 1} = Oban.drain_queue(queue: :logs)
# now assert the DB row exists — Repo.one(from l in RequestLog, ...)
```

Job args are JSON — Decimal fields arrive as strings; the changeset casts them
back. Design worker args accordingly (serialize Decimals with
`Decimal.to_string(d, :normal)`).

## 6. App-tree singletons in test setup

When the app supervision tree starts the singletons (Registry, ETS-owning
GenServers), test setups must reuse them:

```elixir
setup do
  pid = Process.whereis(MySingleton) || start_supervised!(MySingleton)
  if :ets.whereis(:my_table) != :undefined, do: :ets.delete_all_objects(:my_table)
  :ok
end
```

Full pattern (incl. alias shadowing of `Supervisor` and the `already_started`
cascade): see the `riel-delegate` skill §3.

## 7. First-token timeout tests without sleeping the suite

Testing a "fallback when the provider's first SSE chunk never arrives" path:
override the config in the test, point the provider at a slow marker route, and
restore in `on_exit`:

```elixir
Application.put_env(:MyApp, :first_token_timeout_ms, 50)
on_exit(fn -> Application.put_env(:MyApp, :first_token_timeout_ms, previous) end)
# provider plug's "slowstream" marker: Process.sleep(300) then stream
```

The SLEEP lives in the fake provider (fine — it's the upstream being slow), not
in the test process. Assert the fallback status (503), never timing internals.
