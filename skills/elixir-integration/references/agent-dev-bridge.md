# Agent ↔ Elixir Dev Bridge

Patterns for wiring a coding agent into a live Elixir node: connection
modes, tool layers, supervision, the wire contract, and testing. Same
discipline as any integration surface — but the bridge sees the whole BEAM,
so its failure modes are the app's failure modes.

## Same BEAM = same state

**Symptom.** The agent's evaluation of `Repo.all/0` returns data the web UI
does not show — or vice versa.

**Mechanism.** If the bridge runs as a Plug inside the app's BEAM, it shares
GenServers, ETS, Repo, and Logger with the app. If it runs as an external
process, it sees a different node (often an empty one).

**Fix.** Decide deliberately: same-BEAM bridge (Plug) when the agent must
see live app state; external bridge only for stateless codegen. Never mix
the two mental models in one tool set.

## Three connection modes

| Mode | Mechanism | Latency | State | Reliability |
|---|---|---|---|---|
| Static | `mix run -e` | ~seconds | empty (fresh boot) | always works |
| remsh | `iex --sname X --remsh` | ~100ms | full | needs `--sname` |
| MCP HTTP | hex package server | ~50ms | full | any start method |

`mix phx.server` boots as `nonode@nohost`. When remsh is required, start the
app named: `iex --sname MyApp -S mix phx.server`.

Static mode is the SAFE mode: it cannot corrupt live state. Side effects
through remsh/MCP HTTP hit the real app — route them through explicit,
reviewed tools only.

## Three tool layers

1. **Build tools** (mix, compile, deps) — plain CLI; no running app needed.
2. **BEAM runtime tools** (eval, SQL, process/ETS inspection) — require a
   live node; implement via remsh RPC or same-BEAM eval.
3. **Filesystem/git tools** — only a plugin OUTSIDE the BEAM should do
   these; in-BEAM file writes tangle with code-reloading and the release.

Layer assignment is a design decision: a "run the tests" tool is layer 1
even though it feels like layer 2, because tests must not depend on a
long-lived node's state.

## Server implementation gotchas

- Tool arguments arrive as STRING-keyed maps from the wire; convert to
  atoms at one boundary (`String.to_existing_atom/1`) — sprinkling
  conversions through tools leaks `ArgumentError`s into results.
- Registry-before-server in the supervision tree: `use GenServer,
  start: {Registry, keys: :unique, name: MyApp.ToolRegistry}` style child ordering
  — the server's `start_link` looks up the registry.
- Reply contract: return `{:ok, %Frame{...}}` shaped structs, not raw
  strings — one shape lets the client render every tool uniformly.
- Sanitize JSON payloads before crossing the wire: strip
  `%ElectroDeriveProtocol{}`-style structs (they raise on Jason encoding),
  PIDs, references, and function captures.

## Wire contract

Same as MCP HTTP (see `mcp-server-development.md`), with one addition for
bridges: long-running evals must stream progress or enforce a deadline —
an agent waiting on a stuck `Repo.all/1` blocks its whole loop. Implement
tools as `Task.Supervisor.async_nolink` + timeout, returning a structured
timeout frame rather than hanging the connection.

## Real-HTTP testing

Test the bridge the way it is consumed:

1. Start the endpoint (`mix phx.server` or `Endpoint.start_link` in test).
2. Drive it over HTTP with `Req` — not by calling plug functions directly.
3. Assert on the decoded envelope, not on internal state.

```elixir
test "eval tool returns structured frame" do
  req = Req.post(url: "http://localhost:4002/api/mcp",
    json: %{jsonrpc: "2.0", id: 1, method: "tools/call",
            params: %{name: "myapp_eval", arguments: %{"expr" => "1 + 1"}}})
  assert {:ok, %{status: 200, body: body}} = req
  assert %{"result" => %{"content" => [%{"text" => "2" <> _}]}} = body
end
```

Static-mode tools are tested with plain `ExUnit` — no server needed.
