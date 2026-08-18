---
name: mcp-server-development
description: "Build and evolve MCP (Model Context Protocol) servers consumed by external AI agents: tool naming and description design for agent routing, safe breaking-change renames, keeping in-app docs/README/SKILL in sync, and live schema verification with a smoke script."
version: 1.0.0
author: Álvaro Lizama
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [mcp, model-context-protocol, agents, tooling, api-design, elixir, phoenix]
    related_skills: [phoenix-liveview-debugging, hermes-agent]
---

# MCP Server Development

## When to Use

Building or changing an MCP server whose tools are called by external AI
agents (Hermes, Claude Desktop, custom scripts): adding tools, renaming them,
writing tool descriptions, removing deprecated tools, or verifying the served
schema matches the code.

## Tool naming: prefix for routing, never rename casually

- **Prefix all tools with the server name** (`dran_search`, not `search`).
  Agents run many MCP servers at once; unprefixed generic names (`search`,
  `get_page`) collide semantically with built-in tools and other servers, and
  the model picks wrong. A prefix makes the tool's origin and intent explicit
  in the tool list.
- **A rename is a BREAKING change** — there is no deprecation mechanism in MCP
  other than keeping the old tool alive. If the user approves a rename:
  1. Grep every consumer first: tool names appear in `@tools` schema entries,
     `execute_tool` clauses, descriptions of OTHER tools ("use X instead"),
     prompts, tests (`call_tool`), in-app docs, README, SKILL.md, and any
     installed copies of the skill on agent machines (`~/.hermes/skills/`).
  2. Do a mechanical sed over docs with word boundaries:
     `sed -E "s/(^|[^_a-zA-Z])old_name([^_a-zA-Z]|$)/\\1new_name\\2/g"` per tool.
     Watch for prose collisions — `search` → `dran_search` will also rewrite
     "Unified search:" → "Unified dran_search:"; re-read and fix those by hand.
  3. Update cross-references inside descriptions — agents read them.
- **Removing a tool**: check it's truly unused (tests, docs, agents). A shim
  that only delegates to another tool (e.g. a deprecated alias) is the safest
  kind to delete. Internal functions with the same name elsewhere in the
  codebase are a different thing — don't touch them.

## Tool descriptions are the agent's routing logic

The LLM picks tools by description alone. Every description should answer
**when to use** and **when NOT to use**:

- Start with the action, then the routing cue: "Use this FIRST whenever you
  need to find anything…", "Use after search to actually read content, not
  before", "Don't use for todos — use create_todo instead."
- Document merge-vs-replace semantics for meta/params ("`meta` is REPLACED
  entirely" vs "MERGED") — agents corrupt data otherwise.
- Document special sentinel values (e.g. `"none"` to list orphans).
- Keep enums in schemas truthful: if the dispatcher accepts 6 agent types,
  the schema enum must list all 6 — a stale enum silently blocks valid calls.
- Status values in descriptions must match the code exactly (`done` vs
  `completed` — read the schema/changeset, don't assume).

## Evolving schemas when the domain model changes

Description-only tuning (see MyApp's `references/mcp-description-tuning.md`)
deliberately avoids touching `inputSchema` — that rule holds for pure
disambiguation passes. But when the domain model itself changes (a new link
type, a new page type, a new filter dimension), updating descriptions is not
enough: you must also **add the new field to the relevant `inputSchema`** and
**wire the new param through the `execute_tool` handler**. A description that
mentions a param the schema doesn't accept is a worse failure than no
description at all — the agent calls with the param, the handler ignores it,
and the feature silently doesn't work.

Concrete pattern (MyApp v6, Jul 2026: links became independent, no precedence):

1. **Description first, schema second, handler third — in that order.** Write
   the new description (what the agent should believe about the model), then
   make the schema accept the params the description names, then wire the
   handler to pass those params to the backend. If you do schema before
   description you'll forget a field; if you do handler before schema the
   param arrives but is silently dropped.
2. **Every inputSchema that lists page types needs the new type added** —
   search the `@tools` list for every `enum` containing the old type set
   (e.g. every `type` filter enum). MyApp had 3 such enums (search, create,
   list) and all 3 needed `project` added in the same pass.
3. **Every filter the description names must be wired in the handler.** A
   `project_slug` filter mentioned in the `dran_list_pages` description is
   useless unless `execute_tool("dran_list_pages", ...)` does
   `Keyword.put(opts, :project_slug, args["project_slug"])`. Grep the handler
   for the param name to confirm.
4. **Verify the backend already supports the param before wiring.** The MCP
   handler is a thin adapter — if `Brain.list_pages/1` doesn't accept
   `:project_slug`, the handler wiring compiles but errors at runtime. Read
   the backend's function head and any `maybe_filter_*` helpers first.
5. **Meta-merge handlers need the new meta key added in two places.** When a
   todo-style tool merges meta (`dran_create_todo`, `dran_update_todo`), the
   new slug key must be added to BOTH the create handler's meta map build AND
   the update handler's merge pipeline. Forgetting one means create works but
   update silently drops the field (or vice versa).
6. **Existing tests almost always keep passing.** ExUnit tests call
   `execute_tool` / `process_message` and assert on the returned text, not on
   `inputSchema` strings — so schema additions and description rewrites don't
   break them. Only assertions that pin exact description text (rare) need
   updating. Run `mix test test/<mcp_test>.exs` to confirm; if a test asserts
   on an old description string, update the assertion.
7. **Verification gate:** `mix compile --warnings-as-errors` clean +
   `PORT=<port> mix test`. Description-only changes compile clean with zero
   warnings; schema/handler changes should too (Ecto/Keyword.put won't warn
   on new keys).

## Auditing field coverage: inputSchema vs schema columns

When an MCP tool's `execute_tool` uses `Map.take(args, [...])` to pick fields
from the incoming args map, the list in `Map.take` is the **actual gate** —
any field not in that list is silently dropped even if the `inputSchema`
accepts it and the Ecto changeset can cast it. This is a common drift class
that silently breaks provenance/ownership updates.

**Audit pattern:**
1. Read the Ecto schema's `changeset/2` `cast` list — that's every field the
   backend can persist.
2. Read the MCP tool's `inputSchema.properties` — that's what agents are told
   they can send.
3. Read the `execute_tool` handler's `Map.take(args, [...])` list — that's
   what actually gets passed through to the backend.
4. Any field in the schema's `cast` list that is NOT in `Map.take` is
   **silently dropped**. The `inputSchema` may or may not list it — if it
   does, the agent sends it and it vanishes; if it doesn't, the agent
   doesn't even know the field exists.

**Concrete case (MyApp, Jul 2026):** `dran_update_page` had
`Map.take(args, ["title", "body", "tags", "meta", "summary", "archived"])`
but the Page schema's changeset also accepted `owner`, `created_by`,
`on_behalf_of`, `kb_confidence`, `kb_source_url`, `kb_contested`. None of
these were in `Map.take`, so updating `owner` or `created_by` via MCP was
impossible — the field was silently dropped. Similarly, `dran_update_todo`
had `updated_by` hardcoded to `"agent"` instead of
`Map.get(args, "updated_by", "agent")`, preventing provenance tracking.

**Fix:** add the missing fields to both `inputSchema.properties` AND the
`Map.take` list (or the explicit `Map.put` calls). The `inputSchema` tells
agents the field exists; `Map.take` lets it through; the changeset persists
it. All three must agree.

**Same audit applies to `dran_create_page` / `dran_create_todo`:** check
that `on_behalf_of` (accepted by the schema) appears in BOTH the
`inputSchema` AND the `execute_tool` attrs map construction.

**`dran_update_todo` special case:** the `updated_by` field was hardcoded
to `"agent"` instead of `Map.get(args, "updated_by", "agent")`. This is
not a `Map.take` omission — it's a hardcoded value masking a parameter.
When auditing update tools, grep for hardcoded string defaults on fields
that should accept parameters: `Map.put(attrs, "updated_by", "agent")` →
should be `Map.get(args, "updated_by", "agent")`.

**Full audit checklist for a single MCP tool:**
1. Read the Ecto schema `changeset/2` → list of `cast` fields (what the DB accepts).
2. Read `inputSchema.properties` → what agents are told they can send.
3. Read `execute_tool` → `Map.take(args, [...])` or individual `Map.put`/`maybe_put` calls (what actually passes through).
4. Cross-check: schema fields NOT in `Map.take` = silently dropped. inputSchema fields NOT in `Map.take` = agent sends but server ignores. inputSchema fields NOT in schema = agent sends, server passes through, changeset rejects.
5. For meta-merge tools (todos): check that `maybe_put_meta` calls cover all meta keys mentioned in the inputSchema.
6. For create tools: check that `maybe_put(:on_behalf_of, ...)` is present in the execute function if `on_behalf_of` is in the inputSchema.

### Adding pagination (limit + offset) to search and list tools

When a tool returns collections, agents may need to paginate. The pattern:

1. **Add `limit` and `offset` to `inputSchema.properties`** with clear
   defaults and hard caps (e.g. `limit` default 20 max 100 for search,
   default 50 max 500 for list).
2. **Wire both in `execute_tool`** — `limit` is usually
   `min(Map.get(args, "limit", 20), 100)` to enforce the cap; `offset` is
   `Map.get(args, "offset", 0)`.
3. **Pass to backend** — `Keyword.put(opts, :limit, limit)` and
   `Keyword.put(opts, :offset, offset)`.
4. **Backend query** — add `|> offset(^offset)` after `|> limit(^limit)` in
   the Ecto query. For search functions with multiple strategies (fts,
   fuzzy, semantic, hybrid), ALL of them need the `offset` clause added
   independently — they build separate queries. The hybrid/fuzzy_fts
   combiners inherit `offset` automatically because they pass `opts` to
   the underlying search functions.

**Pitfall:** `dran_search` had no `limit` param exposed in the MCP tool at
all — the backend defaulted to 20 silently. Adding `limit` to both
`inputSchema` and `execute_tool` lets the agent control result count
without guessing.

1. In-repo `SKILL.md` (agent operating manual) — recipes use tool names in
   call syntax; bump its frontmatter version on breaking changes.
2. README tool lists/tables.
3. In-app docs page (if any) — users copy-paste from it.
4. Remind the user that installed skill copies (`~/.hermes/skills/<name>/`)
   need the updated file — the repo edit doesn't propagate.

### Pitfall: in-app docs prose has no compile-time link to code

The in-app docs page (e.g. Phoenix `docs_live.ex`) is typically **hand-written
HEEx prose**, not derived from the tool schema or module `@moduledoc`s. A
stale, wrong, or entirely fictitious description compiles fine and ships
silently. Concrete case (MyApp, Jul 2026): `docs_live.ex` listed a "QA" agent
described as "audits pages for missing frontmatter, broken links, empty
content" — but no such agent existed. The real `MyApp.Agent.QA` (MCP type
`"ask"`) does Q&A against the knowledge graph. The prose had drifted into a
fictional capability that nobody noticed for months because nothing failed.

**Mitigation:** after any tool/agent change, `grep` the in-app docs module for
each tool name AND every enum value in the dispatcher's `inputSchema` (e.g.
every `agent_type` in the `dran_start_agent` enum). Reconcile the prose
against `README.md`, `SKILL.md`, and the module's `@moduledoc`. Treat the
in-app docs as a third independent surface that can drift, not as a mirror of
the code.

### Auditing agent-facing SKILL.md docs against the served schema

Skill docs (the `MyApp` suite's operating manual) drift from the MCP schema
just like in-app docs — nothing fails, so the stale guide ships silently.
When auditing a skill suite against its backing MCP server, treat
`lib/MyApp/mcp.ex` as the contract, not the skills:

1. **Enumerate tools from code:** `grep -o '"name" => "[^"]*"' lib/MyApp/mcp.ex`
   and count — that is the authoritative tool count. Cross-check any number a
   skill states in prose or examples ("17 tools" vs the real 18; a partial
   per-type update can go stale the moment a tool is added).
2. **Verify param NAMES per tool,** not just presence. Skills that were
   written against an older/assumed signature will call
   `dran_create_relation({from: ..., to: ...})` when the real schema is
   `source_slug`/`target_slug`. Read each tool's `inputSchema.properties`
   keys and grep the skills for `from`/`to`/`dran_*_relation` calls.
3. **Check for internal contradictions:** a skill may warn "params are
   `source_slug`/`target_slug` (NO from/to)" in one recipe yet use `from`/`to`
   in a sibling recipe (delete-relation) or its quick-reference table. Grep
   the whole file, not just one section.
4. **Meta-field accuracy:** cross-check per-type `meta` keys against the
   `dran_create_page` description (e.g. query pages use `answer_status`
   business field, not `done`; goals use `progress_manual`).
5. **Owner/created_by drift after an auth refactor:** when the server
   switches `owner` to be API-key-derived and non-client-settable, skills
   showing `owner: "alvaro"` in recipes are stale — they should say owner is
   ignored and only `created_by` is overrideable.

Real case (MyApp, Aug 2026): the audit of all 10 `skills/*/SKILL.md` files
found wrong `from`/`to` params on `dran_create_relation`/`dran_delete_relation`
in `research-flow`, `note-taking-flow` and `relations-flow`, plus a stale
"17 tools" count in `goal-flow`/`todo-flow` examples. The partially-updated
owner/created_by wording in the already-touched skills matched the new
`Auth.resolve_owner`/`Auth.resolve_created_by` behavior.

## Multi-surface registration (MCP dispatch backends)

When an MCP tool dispatches to multiple backends (e.g. `dran_start_agent` →
6 agent modules), each backend is reachable from the MCP surface by default —
but **other surfaces are independent and must be wired separately**. A
backend missing from a surface fails silently (redirect, 404, or "unknown
type") rather than erroring loudly. MyApp's matrix:

| Surface | File | How to add a backend | Default reach |
| --- | --- | --- | --- |
| MCP (canonical) | `mcp.ex` `start_agent_by_type/4` + `inputSchema` enum | clause + enum entry | all backends |
| Web UI | `agent_live.ex` `@valid_types` guard | add type string + label clause | subset only |
| Mix CLI | `mix/tasks/MyApp/agent.ex` | add `start_agent/2` clause | subset only |
| Scheduler | `config/config.exs` Quantum `jobs` | add job entry | subset only (cron-triggered) |

**Silent-failure trap:** the `@valid_types` guard in `handle_params/2` that
**redirects unlisted types to `/`** means `/agents/ask` silently bounces to
home with no error. If a user reports "the agent page doesn't load", check
`@valid_types` first, not the router. Generalizable: any surface that filters
by a type/enum string will silently exclude backends that the MCP surface
accepts — grep for the enum values across all surface files, not just the MCP
module.

## Per-user auth + context scoping (Streamable HTTP)

When an MCP server scales to multi-user, scope every tool call to the calling
user's context(s). Pattern (MyApp, Aug 2026 — `MCPController` + `MyApp.MCP`):

1. **Controller gate:** `handle_post` runs in a `with` — `authenticate(conn)` →
   `validate_context_access(conn, user)` → process. Return `401`
   (`www-authenticate: Bearer`) on bad token, `403` on context denial.
2. **Authenticate both token classes:** try the **legacy global admin token
   first** (`MyApp.Auth.api_token()`, from env) → an admin map
   `%{is_admin: true, contexts: :all}`; otherwise `Accounts.valid_token?/1`
   (DB lookup) → `{:ok, user}`. The legacy token keeps backward compat.
3. **User's accessible contexts:** the admin map carries `contexts: :all`,
   while a real Ecto user's `contexts` is the loaded `has_many through`
   association (a **list of `%Context{}` structs**, possibly `[]`). Handle
   both with one `case user.contexts do :all -> …; [] -> …; [first|_] -> first.slug end`.
   This `:all`-vs-list union is the recurring shape — pattern-match both.
4. **Pass user through:** `process_message(msg, user: user)`. Extend the
   existing `process_message/1` to `process_message(msg, opts \\ [])` and
   `Keyword.get(opts, :user)` — the default arg keeps every existing
   caller/test that calls `process_message(msg)` working unchanged.

### Injecting a default context into tool calls — GET THE PATH RIGHT

To scope an operation to the user's default context when the agent didn't pass
one, inject it into the `tools/call` params **before dispatch**:

```elixir
defp inject_user_context(msg, nil), do: msg
defp inject_user_context(
       %{"jsonrpc" => "2.0", "method" => "tools/call", "params" => params} = msg, user
     ) when is_map(params) do
  args = params["arguments"] || %{}
  if Map.has_key?(args, "context") do
    msg
  else
    case get_default_context_for_user(user) do
      nil -> msg
      default -> put_in(msg, ["params", "arguments", "context"], default)
    end
  end
end
defp inject_user_context(msg, _user), do: msg
# admin / contexts: :all -> nil (no injection); [first|_] -> first.slug
```

**Pitfall (real spec bug, MyApp Aug 2026):** the requested `context` for a tool
lives at **`params["arguments"]["context"]`, NOT `params["context"]`**. Every
`execute_tool("dran_*", %{"context" => ctx, ...})` clause matches `context` in
the tool **arguments map**. Injecting at `params["context"]` compiles fine and
silently does nothing — the tool then errors or hits the wrong context. Always
`put_in(msg, ["params", "arguments", "context"], default)`.

**Admin never gets injected:** `get_default_context_for_user` returns `nil`
for admins and `:all` users so they keep their explicitly-passed context (or no
default). Injection is purely for single-context (non-admin) users.

**Verify the no-op path:** a `with {:ok, user} <- …, :ok <- …` chain needs an
`else` for BOTH atom errors (`:unauthorized`, `:forbidden`) or the controller
crashes on a bad token instead of returning 401.

### Testing MCP auth in ExUnit — use `post/3`, not `req/4`

`Phoenix.ConnTest` provides `post/3` for controller tests, NOT `req/4`:

```elixir
# WRONG — req/4 doesn't exist in Phoenix.ConnTest
conn
|> Phoenix.ConnTest.req("post", "/api/mcp", %{"context" => ctx.slug})

# CORRECT — post/3 with JSON body
conn
|> Plug.Conn.put_req_header("authorization", "Bearer #{token}")
|> Plug.Conn.put_req_header("accept", "application/json")
|> post("/api/mcp", %{"context" => ctx.slug})
```

`post/3` handles JSON encoding automatically when the body is a map. For
context-scoping tests, assert on `conn.status` (401/403/200) — the MCP JSON-RPC
response body is only meaningful on 200.

## Live schema verification (smoke script)

A running server's served schema is the truth — code review can't confirm
`tools/list` output. Ship a smoke script (`scripts/mcp_smoke.sh`) that:

1. `initialize` via curl with Bearer auth; assert server name + protocol
   version, capture the `mcp-session-id` header.
2. `tools/list`; assert exact expected tool set (missing AND extra = fail).
3. Assert every tool carries the required prefix.
4. Assert key enums (e.g. agent_type) match the dispatcher.
5. Spot-check that descriptions contain their routing cues.

Use `templates/mcp_smoke.sh` in this skill as the starting point. Note: a dev
server with code reloading picks up schema changes without a manual restart —
run the script against the live server right after editing the tool module.

### Token mismatch against a local dev server

A smoke script that defaults to a token like `MyApp-token` will get
`{"errors":{"detail":"invalid token"}}` against a local dev server that was
started with `mise` (or any env loader that applies `.env` before compile).
Reason: the auth module reads `DRAN_API_TOKEN` from `System.get_env/2` at
**compile time** (module attribute), and `.env` has a custom token. The running
BEAM serves the custom token, not the default.

Fix: read the token from `.env` (`grep DRAN_API_TOKEN .env`) and pass it to the
smoke script or curl probe. This does NOT affect `mix test` — tests call
`process_message/1` directly and bypass the HTTP auth layer entirely.

## Testing tool calls in ExUnit

Call `execute_tool` (or the public handler) directly with arg maps — assert on
the returned text/data, not on `inputSchema` internals. When schemas change
(params added), existing tests usually keep passing because they call the
handler, not the schema; only name changes and removed tools break them.

### Pattern-match crash pitfall (handler vs backend return types)

**Class of bug:** an MCP tool handler that `case`s on a backend function's
return value must pattern-match ALL shapes the backend can return — including
`{:error, atom}` tuples. A handler that only matches `{count, []}` and
`{count, errors}` will crash with `Protocol.UndefinedError` when the backend
returns `{:error, :source_not_found}`, because Elixir binds `count = :error`
and `errors = :source_not_found`, then `Enum.join(:source_not_found, ", ")`
trips the Enumerable protocol.

**Concrete case (MyApp, found Jul 2026, fixed in mcp.ex):** `dran_delete_relation`
called `Brain.delete_relation_by_slugs/4` which returns `{:error, :source_not_found}`,
`{:error, :target_not_found}`, or `{count, errors_list}`. The handler only had
clauses for `{count, []}` and `{count, errors}`. Fix: add explicit
`{:error, :source_not_found}` and `{:error, :target_not_found}` clauses BEFORE
the tuple clauses.

**Generalizable rule:** before writing a tool handler, read the backend
function's *full* return type spec or all its clause heads. If the backend can
return `{:error, atom}`, the handler MUST have a clause for it. This applies to
every tool whose backend returns a tagged tuple on failure, not just delete
operations — `create_relation_by_slugs`, `rename_slug`, `validate_url` all have
this shape.

### Exhaustive tool coverage (full-coverage test file)

For a server with N tools, a single full-coverage test file with one `describe`
block per tool catches bugs that minimal per-feature tests miss. Structure:

- **Happy path** per tool: create → read → update → delete lifecycle, asserting
  on both the returned text AND the DB state (fetch the record back and assert
  on fields/meta).
- **Error cases** per tool: non-existent context, non-existent slug, duplicate
  slug, invalid UUID, permission/SSRF errors — at least one per tool.
- **Edge cases**: meta merge vs replace (update_page replaces, update_todo
  merges — assert that keys survive or are dropped), version increment on body
  change, default values, independent links (0/1/2/3 slug links).
- **Protocol surface**: `initialize`, `tools/list` (count + prefix + enum),
  `resources/list` + `resources/read`, `prompts/list` + `prompts/get`,
  unknown method → error code -32601, notifications → nil.

Reference: `test/MyApp/mcp_full_test.exs` in the MyApp repo (69 tests covering
all 18 tools + 3 resources + 3 prompts + protocol methods). The two-slug error
path test (`call_tool("dran_delete_relation", %{source_slug: "no-a", target_slug:
"no-b"})`) is what caught the pattern-match crash above — always test the
"both slugs don't exist" path for tools taking two slug arguments.

## Converting MCP tools to OpenAI function-calling schemas for internal agents

When an internal agent (not an external MCP client) needs to call the same tools, convert the MCP `@tools` schemas to OpenAI `tool_calls` format instead of duplicating tool definitions:

```elixir
# In the MCP module, expose a public accessor:
def tool_schemas, do: @tools

# In the agent module, convert to OpenAI format:
def tools do
  MCP.tool_schemas()
  |> Enum.map(fn schema ->
    %{
      "type" => "function",
      "function" => %{
        "name" => schema["name"],
        "description" => schema["description"],
        "parameters" => schema["inputSchema"]
      }
    }
  end)
end
```

Key points:
- **Single source of truth**: the MCP `@tools` list is the canonical schema. The agent converts at runtime — add a tool once, both the MCP server and internal agents get it.
- **Context injection**: internal agents often need to inject defaults (e.g. `context_slug`) that external MCP clients pass explicitly. Do this in the agent's `execute_tool`, not in the MCP handler.
- **The `done` tool**: the Agent.Engine requires a `done` tool to finish the session. Append it to the converted MCP tools — it's not an MCP tool, it's the agent's control signal.
- **Dispatch via `process_message`**: for consistency, route agent tool calls through `MCP.process_message/1` with a `tools/call` JSON-RPC envelope rather than calling `execute_tool` directly. This ensures the same validation, error formatting, and telemetry as external clients.

See `references/mcp-to-openai-agent-bridge.md` for a complete worked example (MyApp Copilot agent).

## ReAct engine contract pitfalls (learned the hard way)

When internal agents call MCP tools through an in-app ReAct engine, three contract mismatches bite repeatedly:

1. **`summarize_result` key-type contract.** If the engine does `case summary` with **atom keys** (`%{data: ...}`, `%{status: "error"}`), every agent module's `summarize_result/1` MUST return atom-keyed maps. An agent returning string keys (`%{"type" => "text"}`) crashes at runtime with `%CaseClauseError{term: %{"type" => ...}}` — but only when a tool returns that shape (binary results are common: MCP tools return text). The engine's `default_summarize_result` needs a `{:ok, binary}` clause too, and its result formatter needs an `is_binary(data)` branch. Fix the class, not the site: check EVERY agent module's `summarize_result` for key-type consistency, not just the one that crashed.
2. **Caller timeout must exceed the agent loop timeout.** A GenServer exposing `send_message` that runs a 120s agent loop needs `GenServer.call(pid, msg, 180_000)`, not the default 5s or a guessed 60s — otherwise the caller times out while the agent is still working, the user sees an error, and the agent's successful result is orphaned. Rule: caller timeout ≥ agent timeout + processing margin.
3. **Test the REAL end-to-end path, not just the module.** An agent engine can pass all unit tests yet fail live because (a) the model behind it doesn't support `tool_calls` (returns prose — verify with a curl probe, see `local-omlx-inference-api` for the probe recipe), or (b) a fallback path silently masks the failure (user gets a degraded answer and reports "doesn't work" — grep the logs for the fallback warning). And before debugging code, check the running server actually runs the new code: `mix phx.server` does NOT reload newly added modules — if a module was created after the server booted, restart the server first.

## References & support files

- `templates/mcp_smoke.sh` — ready-to-adapt smoke script (initialize +
  tools/list + enum/prefix/description checks) for any MCP server.
  Verifies the **schema** served, not tool execution.
- `references/mcp-tool-execution-smoke.md` — complementary pattern: call
  every tool via HTTP with valid params and assert on the response text.
  Catches runtime crashes (pattern-match errors, dead supervisors, wrong
  return shapes) that schema-only checks miss. Includes pitfalls: SSE vs
  JSON response format, session_id parsing, cleanup between runs, async
  agent tools that won't finish during the test. Also covers **plugin-side
  shim bugs** — when a plugin client generates inline eval code (extools
  pattern), the eval itself can crash even though the MCP server is fine.
  Classify results by return shape (`success:false` + `Eval raised:` =
  plugin bug; `requires the 'X' dep` = expected dep-gate; `missing required
  argument` = operator error) before blaming the server or the user's app.
- `references/mcp-to-openai-agent-bridge.md` — converting MCP tool schemas to
  OpenAI function-calling format for internal agents, with context injection
  and the `done` tool pattern.
- `references/mcp-per-user-context-auth.md` — full worked example of per-user
  context scoping on a Streamable HTTP endpoint: controller `with`/401/403
  gate, legacy-admin-then-user-token auth, the admin-map-`:all` vs
  loaded-`has_many`-list union, `process_message(msg, opts \\ [])` extension,
  and the `params["arguments"]["context"]` (not `params["context"]`) injection
  path.
- `references/auth-identity-to-ownership.md` — extending per-user auth to
  resolve `owner` and `created_by` fields from the API key name or user email.
  Covers the 3 auth paths, the `key_name` field that was being lost, wiring
  MCP/REST/web creation surfaces, and the 4 docs surfaces to keep in sync.
- For description-only disambiguation passes (no schema/handler changes), see
  the `second-brain` skill's `references/mcp-description-tuning.md` — its
  "Do NOT change inputSchemas except for enum values" rule applies to that
  narrower class only; the "Evolving schemas when the domain model changes"
  section above covers the broader class where schema + handler must move too.
- For MCP servers built with the **`hermes_mcp` Elixir SDK** (Hermes.Server
  behaviour, component tools, Streamable HTTP transport), the server-side
  contract pitfalls live in the `elixir-dev-bridge` skill (pitfalls 16–20 +
  `references/hermes-mcp-server-gotchas.md`): atom-keyed params after schema
  validation, mandatory `%Frame{}` passthrough in `{:reply, resp, frame}`,
  the `Hermes.Server.Registry` supervision requirement, the initialize /
  mcp-session-id handshake, and JSON-encoding sanitization. Those crashed a
  real server repeatedly despite passing direct `execute/2` unit tests —
  always integration-test over real HTTP.
