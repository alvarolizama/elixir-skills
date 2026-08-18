# Proxy Controller Integration Tests — Upstream Stubbing Pattern

Reusable test pattern for Elixir/Phoenix controllers that proxy to an upstream
HTTP API (OpenAI-compatible gateways, model providers, payment APIs, etc.).
Allows assertions on what the proxy actually forwards — not just what the
controller returns to the client.

## When to use

You're testing a Phoenix controller that:
- Calls `Req.post` (or any HTTP client) to an external service, and
- You need to verify the controller mutates the payload before forwarding
  (header injection, prompt optimization, model name rewriting, guard rails, …).

The naive alternatives (`Mox`, `:meck` on the HTTP client) work but lose
fidelity and don't exercise the real serialization / encoding path.

## The pattern: in-process test plug + `:persistent_term` test_pid

Two pieces wired together via a persistent_term:

1. **`ProviderPlug`** — a tiny `Plug` module running on `Bandit` inside the test
   process. It receives the upstream call, decodes the JSON body, forwards the
   decoded map to the test pid, and returns a canned response.
2. **`:persistent_term`** — stores the test pid so `ProviderPlug.call/2` can
   find it without process registry dance.

```elixir
defmodule ProviderPlug do
  import Plug.Conn

  def init(opts), do: opts

  def call(conn, _opts) do
    {:ok, body, conn} = read_body(conn)

    if pid = :persistent_term.get({__MODULE__, :test_pid}, nil) do
      send(pid, {:provider_request, Jason.decode!(body)})
    end

    conn
    |> put_resp_content_type("application/json")
    |> send_resp(200, Jason.encode!(%{
      "id" => "chatcmpl-test",
      "choices" => [%{"message" => %{"role" => "assistant", "content" => "ok"}}],
      "usage" => %{"prompt_tokens" => 1, "completion_tokens" => 1, "total_tokens" => 2}
    }))
  end
end

setup do
  :persistent_term.put({ProviderPlug, :test_pid}, self())
  start_supervised!({Bandit, plug: ProviderPlug, scheme: :http, ip: :loopback, port: 41236})
  :ok
end
```

Then in any test:

```elixir
test "controller rewrites the model name before forwarding", %{conn: conn} do
  # ... set up auth, alias, credential pointing at http://localhost:41236 ...

  conn = post(conn, ~p"/v1/chat/completions", %{"model" => "alias-foo", "messages" => [...]})
  assert json_response(conn, 200)

  # Captured upstream payload — this is what the provider actually received.
  assert_receive {:provider_request, upstream_payload}
  assert upstream_payload["model"] == "real-provider-model-id"
  assert hd(upstream_payload["messages"])["role"] == "system"
end
```

## Why this beats Mox / `:meck`

- **Real serialization**: the body goes through real `Plug.Parsers` →
  `Jason.encode!` → `Req.post` → Bandit → `Plug.Conn.read_body` → `Jason.decode!`.
  If your payload mutation produces invalid JSON, you'll find out.
- **Real content-type negotiation**: headers, `receive_timeout`, streaming —
  all exercise the real `Req` path.
- **One plug handles streaming + non-streaming**: branch in `call/2` on
  `conn.path_info` or the decoded `payload["stream"]`. For streaming use
  `send_chunked/2` + `chunk/2`.
- **No mock bookkeeping**: no `expect/3`, no verifying call counts, no
  `:meck` unloading in `on_exit`.

## Per-test flag variation without bloating fixtures

When the controller behavior depends on per-alias flags (e.g.
`lazy_cleanup_enabled`, `prompt_cache_enabled`), resist the urge to add
keyword options to the shared fixture. Instead:

```elixir
test "lazy_cleanup dedupes tool messages", %{conn: conn} do
  %{token: token, alias: model_alias} = proxy_fixture()

  # Flip the flag on the fixture alias — minimal, isolated, no fixture churn.
  {:ok, alias_optimized} =
    Providers.update_model_alias(model_alias, %{lazy_cleanup_enabled: true})

  conn =
    conn
    |> authed_conn(token)
    |> post(~p"/v1/chat/completions", noisy_payload(alias_optimized.name))

  assert_receive {:provider_request, upstream_payload}
  # assertions on upstream_payload["messages"]...
end
```

Benefits:
- The shared fixture stays focused on the common path (auth + budget +
  routing boilerplate).
- Each test's variation is right next to its assertions, self-documenting.
- Other tests using `proxy_fixture()` keep getting the schema defaults —
  no surprise behavior changes.

## Pitfalls

- **`:persistent_term` outlives the test process.** If a test sends a request
  but the upstream plug fires *after* `assert_receive` has timed out, the
  message lands in the test pid's mailbox and pollutes the next test. Always
  pair with `start_supervised!` for the Bandit server so `on_exit` cleans up.
  If you `assert_receive` only conditionally, drain the mailbox at the end:
  `flush_messages()` or `assert_receive ... , 0` patterns.
- **Don't use `Process.send` for the test pid in async tests.** Use
  `Phoenix.ConnTest` and `start_supervised!` per the project guidelines;
  `use MyAppWeb.ConnCase, async: false` is the safe default when one
  shared upstream stub is in play.
- **The plug's port must be unique per test run.** Use `System.unique_integer/1`
  in the `@port` module attribute or pick a high port unlikely to clash.
- **Streaming tests need extra plumbing.** The non-streaming branch above
  uses `send_resp`; for streaming, use `send_chunked/2` + `chunk/2` and a
  separate consumer pid the controller monitors. See existing
  `stream:` tests in the same file for the full pattern.
- **Don't assert on `provider_request` for tests that exercise error paths**
  (rate limits, breaker trips, fallbacks). Those paths may short-circuit
  before the upstream is called.