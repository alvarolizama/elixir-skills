# hermes_mcp server-side gotchas (verified crash transcripts)

Contract details for building an MCP server with `hermes_mcp ~> 0.14`
(Hermes.Server + components + Streamable HTTP Plug). Every item below was
verified by a real crash during the extools build — these pass direct unit
tests and explode only over real HTTP.

## 1. Tool arguments arrive with ATOM keys

`tools/call` validates arguments against the component's `schema do ... end`
and hands `execute/2` an **atom-keyed** map:

```
** (FunctionClauseError) no function clause matching in Extools.Tools.ProjectEval.execute/2
    Extools.Tools.ProjectEval.execute(%{code: "1+1"}, #Frame<[...]>)
    (hermes_mcp 0.14.1) lib/hermes/server/handlers/tools.ex:64
```

A head like `execute(%{"code" => code}, _frame)` never matches. Fix — a
shared normalizer called first in every tool:

```elixir
def execute(params, frame) do
  params = Extools.Tools.Params.normalize(params)  # atom keys -> string keys
  code = params["code"]
  ...
end
```

Blast radius: the raise kills the MCP server GenServer. The supervisor
restarts it, but session state is lost — every later request on that session
fails with `invalid_request: "Server not initialized"`. When you see
not-initialized AFTER a successful handshake, look for a crashed tool first.

## 2. The reply tuple must carry the %Frame{}

`Hermes.Server.Base.server_request/2` matches:

```elixir
{:reply, response, %Frame{} = frame} -> ...
```

Returning `%{}` as the third element:

```
** (CaseClauseError) no case clause matching:
    {:reply, %{"content" => [%{"text" => "2", "type" => "text"}], "isError" => false}, %{}}
    (hermes_mcp 0.14.1) lib/hermes/server/base.ex:542
```

Pattern: `def execute(params, frame) do` (NOT `_frame`) and end every
return path with `, frame}`. Private helpers that build replies must take
`frame` as a parameter. Watch multi-line tuples — a reply ending in
`\n     %{}}` on its own line is easy to miss in a blanket edit.

## 3. Component naming

`component MyApp.Tools.GetAppState` registers the tool as
`"get_app_state"` — last module segment, `Macro.underscore/1`. There is no
separate name field unless you pass `component Mod, name: "custom"`.
Name tool modules after the tool name you want on the wire.

## 4. Supervision tree

Your Application must start the registry BEFORE the server:

```elixir
children = [
  Hermes.Server.Registry,                          # "unknown registry" without this
  {Extools.MCPServer, transport: :streamable_http}
]
```

The server child_spec comes free from `use Hermes.Server`
(`Hermes.Server.Supervisor.start_link(module, opts)`).

## 5. NEVER Supervisor.which_children/1 an arbitrary pid

Probing "is this pid a supervisor?" with `which_children` sends
`:which_children` as a GenServer call — a non-supervisor has no
`handle_call` clause and the FUNCTION CLAUSE ERROR CRASHES THE CALLEE:

```
** (FunctionClauseError) no function clause matching in
    Hermes.Server.Transport.StreamableHTTP.handle_call(:which_children, ...)
```

Use the child spec tuple `{id, pid, type, modules}` from the PARENT's
`which_children` — `type` is `:worker` or `:supervisor`; recurse only on
`:supervisor`. Also: child `id`s can be tuples (`{Bandit, #Reference<...>}`)
— format with `inspect/1`, and via-registered pids have no plain registered
name, so pass the child-spec id down as the display name.

## 6. JSON payload safety

`Hermes.Server.Response.json/1` encodes with `JSON.encode!` — these raise
`Protocol.UndefinedError`: ETS table ids (`#Reference<...>`), tuples, pids,
ports, funs. Sanitize recursively before replying:

```elixir
defp sanitize(t) when is_tuple(t), do: inspect(t)
defp sanitize(t) when is_pid(t) or is_reference(t) or is_port(t), do: inspect(t)
defp sanitize(t) when is_list(t), do: Enum.map(t, &sanitize/1)
defp sanitize(t) when is_map(t), do: Map.new(t, fn {k, v} -> {k, sanitize(v)} end)
defp sanitize(t), do: t
```

Named ETS tables are atoms (`to_string`), unnamed ones are tids (Reference)
— `:ets.all()` returns both.

## 7. :dbg needs :runtime_tools

`trace_function`-style tools using `:dbg.tracer/tp/p/stop` warn
"module :dbg is not available" without it:

```elixir
def application do
  [extra_applications: [:logger, :runtime_tools], mod: {Extools.Application, []}]
end
```

Also: `:dbg.stop_clear/0` is deprecated (OTP 27+) — use `:dbg.stop/0`.

## 8. MCP Streamable HTTP client contract

Verified against `Hermes.Server.Transport.StreamableHTTP.Plug`:

- Requests MUST send `Accept: application/json, text/event-stream` —
  json-only accept gets **406 Not Acceptable**.
- Handshake is mandatory: `initialize` (capture the `mcp-session-id`
  RESPONSE header) → `notifications/initialized` (200/202) → then
  `tools/list` / `tools/call` with the `mcp-session-id` request header.
  Skipping it: `-32600 invalid_request "Server not initialized"`.
- `ping` after the handshake returns `{"id":N,"jsonrpc":"2.0","result":{}}`.
- `tools/call` success shape:
  `{"result":{"content":[{"text":"2","type":"text"}],"isError":false}}`.

## 9. Testing strategy that catches all of the above

Direct `Mod.execute(params, %{})` unit tests skip: param normalization (you
pass string keys yourself), the Frame contract (%{} is fine locally), the
handshake, and JSON encoding of your payload. The minimum honest suite:

```elixir
setup_all do
  {:ok, _} = start_supervised(
    {Bandit, plug: Extools, scheme: :http, ip: {127, 0, 0, 1}, port: 14_040})
  session = mcp_session()  # full initialize handshake, returns mcp-session-id
  [session: session]
end
```

Then over Finch (`Hermes.Finch` is started by the hermes_mcp app):
`ping` (assert `result` present), `tools/list` (assert exact tool names +
count), `tools/call` round-trip. Unit-test the pure logic (log buffers,
parsers, schema enumeration) directly; integration-test the wire contract.
