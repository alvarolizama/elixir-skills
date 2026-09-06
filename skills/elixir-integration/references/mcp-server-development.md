# MCP Server Development in Elixir

Distilled from building and operating MCP servers inside Phoenix apps:
tool naming, identity resolution, per-user context auth, internal-agent
reuse, and execution smoke tests. Each pattern is symptom → mechanism →
fix → verification.

## Tool naming: prefix with the server name

**Symptom.** An agent connected to several MCP servers calls the wrong
server's tool, or errors with "tool not found" on a name that exists.

**Mechanism.** Agents flatten every connected server's tools into one
namespace. Two servers both exposing `search` collide; the agent's
resolution is first-match or error.

**Fix.** Prefix every tool with the server name: `myapp_search`,
`myapp_create_record`. A rename is a BREAKING change — there is no
deprecation path for tool names, so pick the prefix before the first
external user.

**Verification.** `Enum.each(MyApp.MCP.Server.tool_schemas/0, ...)` — every
name matches `~r/^myapp_/`.

## Descriptions are routing logic

**Symptom.** The agent invokes a tool with plausible-but-wrong arguments, or
never invokes an expensive tool that should be last-resort.

**Mechanism.** The model chooses tools purely from name + description. A
description that only says what the tool does omits the decision inputs:
when to use it, and when NOT to.

**Fix.** Every description carries three clauses: what it does, when to use
it, when NOT to use it ("Do not use for X — use Y instead"). Keep them
short; the model reads all of them on every turn.

## Identity → ownership in the domain layer

**Symptom.** Records created through MCP have `owner: nil`, or the field is
set from a client-supplied parameter (spoofable).

**Mechanism.** Ownership is derived from the caller's identity, but each
entry point (MCP tool, REST controller, LiveView) resolves identity
differently — so each resolves ownership differently, and clients that can
set `owner` will.

**Fix.** Resolve identity → ownership fields in ONE domain-layer function:

```elixir
def ownership_fields(%User{} = user), do: %{owner_id: user.id}
def ownership_fields(:admin), do: :all
```

Context functions apply it after authorization. Clients never pass `owner`.
MCP, REST, and web share the single resolver.

**Verification.** Test: tool call with `arguments: %{"owner_id" => other.id}`
still records the CALLER as owner.

## Per-user context auth

**Symptom.** A user sees another user's records through an MCP tool, while
the web UI scopes correctly.

**Mechanism.** The web pipeline scopes queries by assigns; the MCP transport
does not run that pipeline. Without explicit context validation, the tool
runs unscoped.

**Fix.** Controller-level `with` chain: authenticate → validate the
requested context belongs to the caller → execute. Model context as:
admin is `:all`, users carry a preloaded list of allowed contexts — match
BOTH shapes in the validator.

Inject the caller's default context at `params["arguments"]["context"]`.
Injecting at `params["context"]` is the classic silent bug: it compiles,
runs, and is ignored by tool dispatch — one level up from where the tool
actually reads.

**Verification.** Test: user B's context id in the arguments →
`{:error, :unauthorized}`; user B's id at `params["context"]` (wrong level)
→ tool still runs with B's DEFAULT context, not B's requested one.

## Internal agents reuse the same tools

**Symptom.** An in-app agent (LLM function calling) implements its own
half-copy of the tool logic and diverges from the MCP behavior.

**Mechanism.** Someone re-implements validation/dispatch instead of going
through the MCP envelope, or calls `execute_tool/2` directly — skipping
validation and error wrapping.

**Fix.**

1. Expose `tool_schemas/0` and convert to function-calling format for the
   LLM provider.
2. Dispatch agent tool calls through the `tools/call` JSON-RPC envelope via
   `process_message/1` — the same path a remote MCP client takes.

**Verification.** The agent's tool call and the MCP client's call produce
byte-identical result envelopes for the same arguments.

## Execution smoke: schema checks lie

**Symptom.** All tools pass a schema/conformance check, then crash the first
time a real agent calls them. Some "succeed" but return error text.

**Mechanism.** Schema checks validate shape, not runtime behavior. Plugin
shims and evaluated code can embed eval errors INSIDE a successful-looking
result payload, so even non-crashing responses can be failures.

**Fix.** Smoke test with the server RUNNING over real HTTP (not
`mix run -e`): initialize, then call every tool once with valid arguments.
Classify each result TEXT into: `TOOL_OK`, `PLUGIN_OK_NEEDS_ARGS`,
`PLUGIN_OK_DEP_GATED`, or failure. Only the OK classifications may pass.
Gate the suite on this classification, not on HTTP 200.

## Wire contract (transport-level)

- `POST` with `Accept: application/json, text/event-stream` — a plain
  `application/json` Accept is rejected by conformant clients/servers.
- `initialize` handshake returns an `mcp-session-id` header; every later
  request must carry it.
- Errors are JSON-RPC error objects at HTTP 200 for tool-level failures;
  transport failures are real HTTP errors. Test both layers separately.
