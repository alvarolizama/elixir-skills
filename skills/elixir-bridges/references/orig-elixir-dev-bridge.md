---
name: elixir-dev-bridge
description: "Build runtime bridges between AI agents and Elixir apps."
version: 1.1.0
author: Álvaro Lizama
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [elixir, mcp, runtime, bridge, hermes-plugin, phoenix, beam, debugging]
    related_skills: [tidewave-mcp-development, mcp-server-development]
---

# Elixir Dev Bridge

Build runtime development bridges between AI agents (Hermes, Claude Code,
Cursor, etc.) and Elixir applications. Covers the architecture of a system
that gives an agent access to a running Elixir app's runtime — evaluating
code, querying the database, reading logs, inspecting processes, running
tests, and more.

## When to Use

- Planning or building a tool that gives an AI agent access to an Elixir app's runtime
- Designing an MCP server for Elixir development (like Tidewave but framework-agnostic)
- Building a Hermes plugin that wraps Elixir dev tools
- Deciding how an agent should connect to a running BEAM (static vs remsh vs MCP HTTP)

## The Core Insight: Same BEAM = Same State

The fundamental principle (learned from analyzing Tidewave): an MCP server
that lives as a Plug **inside the same BEAM** as your app has access to
everything — GenServers, ETS, Ecto Repo, Logger, processes, in-memory state.
It's not an external process talking by API; it's code running in the same
runtime.

This is why Tidewave works: the `Tidewave` plug in `endpoint.ex` handles
MCP requests by calling `Code.eval_string/1` in the same BEAM that's serving
HTTP requests. The agent's `project_eval` call runs in the same process space
as your app.

## 3-Layer Tool Architecture

Unlike Tidewave (which only has runtime tools), a complete dev bridge has
**3 layers** of tools:

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 3: Filesystem + Git (only the plugin can do this)    │
│  The MCP server inside the BEAM can't see the filesystem.   │
│  git blame, git diff, module graph, changed modules...     │
├─────────────────────────────────────────────────────────────┤
│  Layer 2: BEAM Runtime (what Tidewave does)                 │
│  project_eval, get_logs, execute_sql, process_info...      │
├─────────────────────────────────────────────────────────────┤
│  Layer 1: Mix / Project (build, test, deps, lint)          │
│  Tidewave doesn't have these — no mix tasks at all.        │
│  compile, test, format, credo, dialyzer, coverage...      │
└─────────────────────────────────────────────────────────────┘
```

- **Layer 1** (Mix/Build): Always available via `mix` CLI. Doesn't need the
  app running. The agent can compile, run tests, check deps, lint — all
  from the project directory.
- **Layer 2** (Runtime): Needs a connection to the running BEAM (remsh or
  MCP HTTP). The agent sees live state: GenServers, ETS, DB, logs.
- **Layer 3** (FS/Git): Only the Hermes plugin can do this — it lives in
  the filesystem, not inside the BEAM. Git history, module dependency
  graphs, changed-files tracking.

See `references/tool-catalog.md` for the full 67-tool catalog organized
by layer and category.

## 3 Connection Modes

### Mode 1: Static (`mix run -e`) — always available

Works without the app running. Arrancas un BEAM nuevo, evalúa, muere.

```bash
mix run --no-start -e '
try do
  result = (fn ->
    # agent code here — multi-statement OK, last expression wins
    MyApp.User.count()
  end).()
  IO.puts("~RESULT_START~")
  IO.puts(inspect(result, limit: :infinity, pretty: true))
  IO.puts("~RESULT_END~")
rescue
  e -> IO.puts("~RESULT_START~\nerror: " <> Exception.message(e) <> "\n~RESULT_END~")
end
'
```

- **Speed**: ~0.5s per call with `--no-start` (deps already compiled);
  several seconds if the full app boots
- **State**: empty — no GenServers, no ETS, no live data
- **When to use**: introspection (docs, source location, schemas), one-shot
  queries that don't need runtime state
- **Marker parsing**: use unique start/end markers (`~RESULT_START~` /
  `~RESULT_END~`) to separate the result from compile warnings/boot output,
  and parse them BEFORE truncating output (big results push the end marker
  past the cap)
- **`--no-start` by default, `start_app` for Repo queries**: plain `mix run`
  boots the endpoint, Oban, etc. on EVERY eval — slow and side-effectful.
  `--no-start` still lets you load app modules via `Application.load/1` +
  `Code.ensure_loaded!/1`. Only start the app when the code needs the
  running supervision tree (e.g. `Repo.query`).

### Mode 2: remsh (Erlang distribution) — fast, needs `--sname`

Connects to the running BEAM via Erlang distribution.

```bash
# App must be started with --sname:
iex --sname MyApp -S mix phx.server

# Plugin connects:
iex --sname bridge --remsh MyApp@hostname
```

- **Speed**: ~100ms per call
- **State**: full — sees GenServers, ETS, processes, everything
- **Requirement**: app MUST start with `--sname` (or `--name`). Plain
  `mix phx.server` starts as `nonode@nohost` — remsh CANNOT connect.
- **Node discovery**: `epmd -names` lists BEAMs with distribution active

### Mode 3: MCP HTTP (hex package) — best, like Tidewave

A hex package mounts an MCP endpoint inside the running BEAM. Agent
connects via HTTP streamable transport.

```
Agent → POST http://localhost:4000/extools/mcp → Plug in BEAM → Code.eval_string
```

- **Speed**: ~50ms per call
- **State**: full — same BEAM as the app
- **No `--sname` needed** — works with plain `mix phx.server`
- **Requirement**: hex package installed as dev dependency

See `references/connection-modes.md` for the full auto-detection logic,
`--sname` setup guide, and mode selection matrix. See
`references/elixir-120-runtime-gotchas.md` for verified Elixir 1.20 / Ecto
3.14 transcripts (eval wrapper syntax, ExUnit format, `__schema__` changes).
See `references/hermes-mcp-server-gotchas.md` for the hermes_mcp server-side
contract (atom-keyed params, Frame passthrough, handshake flow, supervision
safety) with verified crash transcripts. See
`references/mcp-streamable-http-client.md` for the CLIENT side of that same
protocol (Python stdlib MCP Streamable HTTP client: Accept headers, the
initialize/mcp-session-id handshake, stale-session re-handshake, content
unwrapping) — required reading before writing any Python code that talks to
a hermes_mcp server; a bare-ping client misdetects the endpoint as down.

## Monorepo Structure

Follows the **existing Hermes plugin repo convention** used by
hermes-dev-browser, and other Hermes plugins: `python/` + `desktop/` +
`SKILL.md` in the repo root (NOT `plugin/` or `skill/` subdirectories).

```
~/Workspace/Repos/hermes-extools/
├── README.md
├── LICENSE (MIT)
├── .gitignore
├── SKILL.md                      # Skill in ROOT (same as dev-browser/kanban)
├── references/                    # Skill references in root
│
├── python/                        # Hermes AGENT plugin (Python)
│                                   # Install: ~/.hermes/plugins/hermes-extools
│   ├── plugin.yaml
│   ├── __init__.py                # ctx.register_tool() × N
│   ├── tools.py                   # Tool functions + JSON schemas
│   ├── bridge/
│   │   ├── connection.py          # auto-detect: static / remsh / mcp
│   │   ├── static_eval.py         # mix run -e (one-shot BEAM)
│   │   ├── remsh_eval.py          # iex --remsh (attached session)
│   │   ├── mcp_client.py          # HTTP client to hex package
│   │   ├── project_detector.py    # find mix.exs, umbrella, ecto, phoenix
│   │   └── output_parser.py       # parse IEx/ExUnit → structured
│   └── dashboard/                  # Optional: REST API for desktop plugin
│       ├── manifest.json
│       └── plugin_api.py
│
├── hex/                           # Hex package (Elixir)
│                                   # Install: dep in mix.exs
│   ├── mix.exs                    # {:hermes_mcp, "~> 0.14"}, {:bandit, optional}
│   ├── lib/extools/
│   │   ├── plug.ex                # Plug module (Phoenix/Plug apps)
│   │   ├── application.ex         # Standalone Bandit server (non-Phoenix)
│   │   ├── mcp_server.ex          # use Hermes.Server
│   │   ├── log_handler.ex         # :logger.add_handler for log capture
│   │   └── tools/                 # one module per tool
│   └── test/
│
└── desktop/                       # Hermes DESKTOP plugin (JS)
                                    # Install: ~/.hermes/desktop-plugins/hermes-extools
    └── plugin.js
```

### Directory naming convention (IMPORTANT)

The existing Hermes plugin repos use `python/` and `desktop/` — NOT
`plugin/` or `skill/`. This was confirmed by inspecting hermes-dev-browser,
and other Hermes plugins in `~/Workspace/Repos/`. Follow this
convention exactly for consistency.

### Installation pattern (symlinks)

```bash
# Agent plugin (Python tools)
ln -s ~/Workspace/Repos/hermes-extools/python ~/.hermes/plugins/hermes-extools

# Desktop plugin (JS UI)
ln -s ~/Workspace/Repos/hermes-extools/desktop ~/.hermes/desktop-plugins/hermes-extools

# Skill is loaded from the repo root SKILL.md via skill_view
```

Why monorepo: the tool definitions must stay synchronized across both
sides. Adding a tool to the hex package means the plugin needs to know
about it. One repo = one source of truth.

## Phoenix Plug vs Bandit Standalone

The hex package works in **both** app types with the same MCP server:

### With Phoenix/Plug (mounts in endpoint)

```elixir
# lib/my_app_web/endpoint.ex
if Mix.env() == :dev do
  plug Extools    # mounts /extools/mcp in the existing endpoint
end
```

**CRITICAL — the plug MUST halt the conn after the delegated MCP call.**
`hermes_mcp`'s `Hermes.Server.Transport.StreamableHTTP.Plug` sends the
HTTP response (`send_resp`) but never calls `Plug.Conn.halt/1`. In a
Phoenix endpoint, the plug pipeline continues after Extools — the Router
receives the already-responded conn, doesn't find a route for `/extools/mcp`,
and raises `Phoenix.Router.NoRouteError`. The log shows a confusing
`[info] Sent 200 in 3ms` (Extools responded fine) immediately followed by
the NoRouteError traceback.

The fix (shipped in extools 0.2.1) is one line in the plug's `call/2`:

```elixir
def call(%Plug.Conn{request_path: path} = conn, mcp_opts) do
  if path == @mcp_path or String.starts_with?(path, @mcp_path <> "/") do
    conn
    |> MCPPlug.call(mcp_opts)
    |> Plug.Conn.halt()   # ← stops the pipeline, Router never sees it
  else
    conn
  end
end
```

If you're using an older extools (≤0.2.0) and can't upgrade, a workaround
in the endpoint is a `halt_if_sent` plug after Extools:

```elixir
if Mix.env() == :dev do
  plug Extools
  plug :halt_if_sent
end

plug MyAppWeb.Router

defp halt_if_sent(%Plug.Conn{state: state} = conn, _opts)
     when state in [:sent, :chunked, :file] do
  Plug.Conn.halt(conn)
end
defp halt_if_sent(conn, _opts), do: conn
```

### Without Phoenix (starts own Bandit server)

```elixir
# config/dev.exs
config :extools, port: 4040
# Extools detects no Phoenix endpoint → starts Bandit on port 4040
```

The key: `Extools` module is both a `Plug` (for Phoenix apps) and a
supervisor child (for standalone). Same MCP server module, same tools,
different HTTP server. The hex package uses `hermes_mcp` as the MCP
protocol library and `bandit` as an optional dependency.

### Auto-detection logic

```elixir
# In Extools.start_link/1
if phoenix_endpoint_running?() do
  :ignore  # Plug is mounted, no need for standalone server
else
  Bandit.start_link(plug: __MODULE__, port: port)
end
```

## Comparison with Tidewave

| Aspect | Tidewave | Elixir Dev Bridge |
|--------|----------|-------------------|
| Frameworks | Phoenix only | Any Elixir app (Phoenix, Plug, CLI, Nerves, umbrella) |
| Requires code changes | Yes (add plug + dep) | No (Phase 1 works with just `mix`) |
| Without app running | Doesn't work | Yes — static mode (`mix run -e`) |
| Mix/build tools | None | compile, test, format, credo, dialyzer, coverage, deps |
| Filesystem/git | No | git blame, git diff, module graph, changed modules |
| Tool count | ~10 | 67 (across 6 categories) |
| Agent integration | External MCP (manual config) | Hermes plugin native (auto-registered tools) |

## Elixir MCP Libraries

When building the hex package, use one of these Elixir MCP SDKs:

| Library | Hex | Notes |
|---------|-----|-------|
| **hermes_mcp** | `~> 0.14.1` | Best choice — client+server, Phoenix integration, streamable HTTP, most downloads (181K) |
| phantom_mcp | `~> 0.4.5` | Plug-based, auth/authz, session management |
| anubis_mcp | `~> 1.6.2` | Component-based DSL, compile-time registration |
| ex_mcp | — | DSL with `deftool`/`defresource` macros |

Prefer `hermes_mcp` — it's the most maintained and has both client and
server implementations.

## Naming & Docs Conventions

When naming new projects/tools for the user: prefer **functional, descriptive
names** over clever/cultural/mythological references. "hermes-elixir-tools"
beats "balam" or "chaac". The name should explain what it does, not require
a Wikipedia lookup.

**Public READMEs: no third-party comparisons or borrowed branding.** When a
project's README shipped with a "How it differs from Tidewave" comparison
table and "Tidewave-inspired" tagline, the user had it removed (*"quita lo de
tidewave"*). Public docs for his projects stand on their own: what it is,
how to install, how to use. Don't anchor his projects to other people's
projects in the main README pitch — comparisons belong at most in deep-dive
reference docs, not in the public-facing intro.

**Hex package names**: check hex.pm availability BEFORE proposing. Use
`web_extract` on `https://hex.pm/packages/<name>` — a 404 page means it's
available. The hex package for this project is `extools` (confirmed available).
For the actual publish flow (owner/org prompt trap, key permissions), see the
`hex-package-publishing` skill.

## Repo Structure Convention (Hermes Plugins)

All Hermes plugin repos in `~/Workspace/Repos/` follow the same pattern:

```
hermes-<name>/
├── README.md          # Full docs with installation, features, repo structure
├── LICENSE            # MIT
├── .gitignore         # OS, editor, Python __pycache__, .env
├── SKILL.md           # Agent skill in ROOT (not in a skill/ subdir)
├── python/            # Agent plugin (tools, bridge logic, plugin.yaml, __init__.py)
├── desktop/           # Desktop plugin UI (plugin.js)
└── (optional extras)  # hex/, docs/, etc.
```

Confirmed by inspecting hermes-dev-browser, hermes-kanban, hermes-my-plugin.
When creating a new Hermes plugin repo, follow this exact layout. The skill
references go in `references/` at the root, not under a `skill/` directory.

## Key Pitfalls

1. **`mix phx.server` starts without distribution** — `nonode@nohost`. remsh
   cannot connect. User must start with `iex --sname MyApp -S mix phx.server`
   for remsh mode to work. The skill/README must document this clearly.

2. **Static mode has no runtime state** — `mix run -e` starts a fresh BEAM.
   GenServers aren't running, ETS is empty, no in-memory data. Only use it
   for introspection (docs, source, schemas) or DB queries (if Repo can
   connect without the full app booted).

3. **Side effects in `project_eval`/`elixir_eval` affect the real app** —
   when connected via remsh or MCP HTTP, code runs in the production BEAM.
   Creating/deleting records, modifying ETS, killing processes — all real.
   Static mode is safe (isolated BEAM).

4. **Bandit as optional dep** — when the hex package is used in a non-Phoenix
   app, `bandit` must be in deps but marked `optional: true`. Phoenix apps
   already have a web server (Cowboy/Bandit via Phoenix.Endpoint) and don't
   need a standalone one.

5. **Umbrella projects** — the hex package goes in the app that defines the
   Phoenix endpoint (typically `apps/your_app_web`), not in the umbrella root.
   For standalone mode in umbrella, put it in the main application app.

6. **Tool descriptions must match across plugin and hex package** — if the
   hex package exposes `project_eval` via MCP, the plugin's tool description
   for the same tool must be identical. Keep a shared constants file or
   generate descriptions from the hex package's schema.

7. **Project naming: functional over clever.** the user explicitly rejected
   mythological/cultural names (balam, chaac, ixchel, kuub) for this project.
   He prefers **functional, descriptive names** like `hermes-elixir-tools`.
   The name should explain what it does. Don't propose clever names unless
   he asks for them.

8. **MyApp plan/todo granularity: features, not micro-tasks.** When creating
   project plans with todos in MyApp, the user wants **complete, verifiable
   features** as todos — not micro-tasks broken down to individual files or
   functions. A todo should deliver something functional end-to-end with a
   clear "what it delivers" and "how to verify" section. For example:
   - **Correct**: "Feature 1: Plugin Core — static eval, remsh, 12 tools, skill"
   - **Too atomic**: "T2: project_detector.py" and "T3: static_eval.py" as
     separate todos.
   Consolidate into feature-level units. A 4-todo plan (one per feature) is
   better than an 11-todo plan (one per file/function).

9. **Mermaid in MyApp pages.** When writing mermaid diagrams in MyApp page
   bodies (plans, projects, todos), use plain mermaid syntax inside the
   ` ```mermaid ` block. Common errors:
   - Do NOT wrap the diagram in `["graph LR ... "]` JSON-array syntax —
     not valid mermaid. Use `flowchart LR`, `stateDiagram-v2`,
     `sequenceDiagram` keywords directly.
   - Keep node labels short and quoted: `A["Hermes Agent"]` not `A[Hermes Agent]`.
   - Avoid `<br/>` in labels (breaks parser). Use single-line labels.
   - Avoid `&` — write `and` or omit.
   - `flowchart TB/LR` with `subgraph` works if labels are quoted.
   - `stateDiagram-v2` with `:` separators works fine.
   - After creating/updating a page with mermaid, re-read with `my_app_get_page`
     to verify the diagram wasn't silently stripped.

10. **`(begin ... end)` multiline is NOT valid Elixir.** Wrapping eval code as
    `result = (begin <code> end)` raises MismatchedDelimiterError (verified on
    Elixir 1.20 — parens can't wrap a multiline begin block). Use a zero-arg
    anonymous fn instead: `result = (fn -> <code> end).()`. Also avoid
    string-escaping user code into `Code.eval_string` — embed it directly in
    the `-e` script; no escaping layer at all.

11. **Enumerating Ecto schemas in static mode.** `:code.all_loaded()` misses
    app schemas (modules load on demand, nothing references them yet). Use
    `Application.load(app)` + `Application.spec(app, :modules)` with the app
    names from project detection. Skip modules whose `__schema__` raises
    (e.g. `Ecto.Migration.SchemaMigration` exports `__schema__/1` but doesn't
    support all queries — wrap each module in try/rescue).

12. **Ecto 3.14 removed `__schema__(:types)`.** Calling it raises
    FunctionClauseError. Use `__schema__(:type, field)` per field (with a
    per-field try/rescue fallback to nil), or `__changeset__/0` for the
    cast-type map. Verified on Ecto 3.14.1.

13. **ExUnit output format changed in Elixir 1.20.** Old: `5 tests, 0 failures`.
    New: `Result: 5 passed` / `Result: 1/2 passed` + `Failed: 1 test`. Trace
    lines are `  * test name (7.4ms) [L#4]` under a `Module [test/file.exs]`
    header, with `\r` between in-progress and completed lines (split on
    `[\r\n]+`). Failures are NOT marked on the test line — only in the
    `N) test name (Module)` detail section; cross-reference by module+name.
    Run `mix test --trace` — the plain dot formatter gives no per-test detail.
    Any ExUnit parser must handle BOTH formats. Full verified transcripts in
    `references/elixir-120-runtime-gotchas.md`.

14. **Parse output markers BEFORE truncating.** If you cap subprocess output
    (e.g. 50KB) before extracting the result between markers, a large result
    (full `Code.fetch_docs` tuple for `Enum`) pushes the END marker past the
    cap and the parse fails with "no marker found". Parse markers on the full
    output, then truncate for display. Better: make tools extract only the
    doc content (`moduledoc`, per-function doc maps), never the raw tuple.

15. **Verify the Python plugin WITHOUT restarting Hermes.** Three-step loop:
    `python3 -m py_compile` on every file; importlib-load `__init__.py` with
    `submodule_search_locations` (simulates the `hermes_plugins.<slug>`
    namespace); then call `register(mock_ctx)` where mock_ctx records each
    `register_tool(...)` — assert 12 tools, callable wrapped handlers, valid
    schemas, `check_fn()` True. Finally dispatch one real tool call through
    the captured wrapped handler as `handler(args_dict, task_id=..., session_id=...)`
    to prove the registry dispatch convention works end to end.

16. **hermes_mcp delivers tool arguments with ATOM keys.** A tool written as
    `execute(%{"code" => code}, frame)` works in direct unit tests (string
    keys) but raises FunctionClauseError on real `tools/call` — the MCP path
    validates inputSchema and produces `%{code: "..."}`. Normalize first in
    EVERY tool (`Map.new(params, fn {k, v} -> {to_string(k), v} end)`), then
    read string keys. This bug crashes the whole MCP server GenServer, and
    every subsequent request on that session then fails with
    "Server not initialized" — the visible error is far from the cause.

17. **`{:reply, response, frame}` — the third element MUST be the `%Frame{}`.**
    hermes_mcp's `server_request` case-matches `{:reply, response, %Frame{}}`;
    returning `%{}` (or anything else) as the third element raises
    CaseClauseError and kills the server. Capture the incoming `frame` arg
    (don't `_frame`-ignore it) and thread it through every return clause,
    including private helpers that build replies.

18. **NEVER probe `Supervisor.which_children/1` on an arbitrary pid.** On a
    non-supervisor GenServer the `:which_children` call has no handle_call
    clause and CRASHES THE CALLEE process (observed: it killed the MCP
    transport mid-session). When walking a supervision tree, use the child
    spec's own `type` field (`:worker` | `:supervisor`) from the parent's
    `which_children` — never call `which_children` just to test
    supervisor-ness. Same class of bug: `String.to_atom/1` on agent-supplied
    names (atom leak) — use `to_existing_atom` with the raw + `"Elixir." <>`
    prefix candidates, and strip `#PID`/ `PID` before `list_to_pid/1`.

19. **hermes_mcp wiring checklist** (all verified by crash): put
    `Hermes.Server.Registry` in YOUR app's supervision tree before the server
    child ("unknown registry" otherwise); component tool names derive from the
    last module segment underscored (`GetAppState` → `get_app_state`) — name
    modules after the tool name you want; `:dbg` requires `:runtime_tools` in
    `extra_applications`; sanitize payloads for JSON — ETS tids (Reference),
    tuples, pids, and ports all raise `Protocol.UndefinedError` in
    `JSON.Encoder` (recursively `inspect/1` them); client must send
    `Accept: application/json, text/event-stream` (406 otherwise) and complete
    `initialize` → `notifications/initialized` before any `tools/list` /
    `tools/call`, passing the `mcp-session-id` response header on every
    subsequent request. Full transcripts: `references/hermes-mcp-server-gotchas.md`.

20. **Integration-test the MCP endpoint over real HTTP, not just direct
    `execute/2` calls.** Direct calls skip param validation, the Frame
    contract, the handshake, and the JSON encoding — every one of pitfalls
    16–19 passed direct unit tests and exploded only over HTTP. The minimum
    honest test: start Bandit with `start_supervised`, run the full
    initialize handshake with Finch, then assert `tools/list` names and one
    `tools/call` round-trip.

21. **Embedding Elixir code in Python f-strings: brace conflict pitfall.**
    Elixir map/tuple syntax (`%{key => val}`, `{k, v}`) uses `{` and `}` which
    conflict with Python f-string interpolation. Writing
    `f"Map.new(behaviours, fn {k, v} -> ... end)"` raises `SyntaxError:
    f-string: invalid syntax` because Python tries to evaluate `{k, v}` as an
    f-string expression. Two fixes: (a) escape every literal brace as `{{` /
    `}}` (readable for short snippets but noisy for long Elixir code); (b)
    build the string with regular concatenation (`"apps = " + apps_elixir +
    "\nEnum.each(apps, ...)"`) or a non-f-string template. When writing long
    Elixir eval code, prefer plain string concatenation or `.format()` with
    named placeholders — f-strings become unreadable when every `%{` needs
    `%{{`. Also: write ONE correct version, not three iterations as separate
    `code =` assignments leaving dead broken code above the final one
    (py_compile catches the first broken f-string even if it's overwritten
    later — Python parses the whole file, not just the last assignment).

22. **Phoenix router detection in static mode (no app start needed).**
    `Phoenix.Router` modules expose `__routes__/0` which returns route structs.
    To find the router module without starting the app: (a) scan `lib/**/*.ex`
    for `use Phoenix.Router` and extract the `defmodule` name; (b) fall back
    to `Application.load(app)` + `Application.spec(app, :modules)` +
    `Code.ensure_loaded?(mod) and function_exported?(mod, :__routes__, 0)`.
    Both approaches work in `--no-start` static mode. Route structs have keys
    `:verb`, `:path`, `:plug`, `:plug_opts`, `:helper`, `:pipe_through`.
    For LiveView routes, filter where `plug == Phoenix.LiveView.Plug` or
    where `Map.get(route, :private) || %{}` has `:live_action`.
    Two failure modes in (a) — both hit in practice: (i) the root web module
    (`my_app_web.ex`) mentions `use Phoenix.Router` inside its `__using__`
    macro quote, so a naive first-match returns `MyAppWeb` (which has no
    `__routes__/0`) — only accept candidates whose module ends in `Router`
    or whose filename contains `router`; (ii) Phoenix 1.8 routers say
    `use MyAppWeb, :router` (no literal `use Phoenix.Router` in the file), so
    the text scan finds NOTHING — the (b) spec-scan fallback is mandatory,
    not optional.

23. **Cross-plugin dev-browser integration pattern.** Any Hermes plugin can
    drive the Dev Browser by reusing the hermes-dev-browser plugin's REST
    mailbox. The pattern (copied from `hermes-dev-browser/python/tools.py`):
    (a) emit an event via `desktop_ui.emit("hermes-dev-browser.<action>",
    {payload, request_id})`; (b) poll for the result via the in-process
    mailbox (import `_results` / `_results_lock` from the plugin module) or
    HTTP fallback (`GET http://127.0.0.1:$HERMES_DASHBOARD_PORT/api/plugins/
    hermes-dev-browser/result/{request_id}` with `X-Hermes-Session-Token`
    header). If `desktop_ui` can't be imported or `emit` returns falsy, return
    a clear error telling the user to open the Dev Browser pane. See
    [references/dev-browser-integration.md](references/dev-browser-integration.md)
    for the full reusable Python helper code and the LiveView-specific JS
    snippets (assigns extraction, phx-click, phx-submit).

24. **Module path ↔ Elixir module name conversion.** When mapping git-changed
    files to Elixir modules (`lib/foo/bar.ex` → `Foo.Bar`): strip `lib/` (or
    `apps/<name>/lib/` for umbrella), remove `.ex`/`.exs`, split on `/`, then
    convert each segment from snake_case to CamelCase (`foo_bar` → `FooBar`)
    and join with `.`. For test file mapping (`lib/foo/bar.ex` →
    `test/foo/bar_test.exs`): replace `lib/` with `test/`, append `_test`
    only if the stem doesn't already end with `_test`, change extension to
    `.exs`. These conversions are pure Python — no BEAM needed.

25. **Elixir syntax landmines when GENERATING eval code.** Three verified
    parse failures that only appear in generated code, never in hand-written
    lib code: (a) `private` is a RESERVED WORD — using it as a variable name
    (`priv = Map.get(r, :private)`) is a SyntaxError; rename to `priv` or
    `private_meta`. (b) A trailing `if` after a `?`-suffixed call does NOT
    parse — `Code.ensure_loaded?(router) if router` raises
    "syntax error before: 'if'"; write `if router, do: Code.ensure_loaded!(router)`.
    (c) One-liner `if cond, do: x, else: y` IS valid inside an `fn` body —
    don't "fix" it into a multi-line if and break indentation-based blocks.
    Details: `references/elixir-120-runtime-gotchas.md` §5.

27. **The dashboard REST backend (`python/dashboard/plugin_api.py`) cannot
    import like the agent plugin.** The dashboard loader mounts the file
    standalone via `spec_from_file_location` (no package parent), so relative
    imports fail and the gateway's `hermes_plugins.<slug>` package path is a
    guess at best (slugs with hyphens mangle). The robust pattern: insert the
    plugin's own `python/` dir (`Path(__file__).resolve().parent.parent`)
    into `sys.path` and import only the self-contained subpackage
    (`bridge` — its internal relative imports work). Do NOT import
    `tools.py` there: its absolute-under-package imports only resolve under
    the gateway's loader. Anything the dashboard needs (project detection,
    connection mode) must live in the subpackage; if it lives in `tools.py`,
    re-implement the few lines against the subpackage instead of importing
    it. Verified: with this pattern `GET /projects` + `GET /status` work when
    loaded exactly the way the dashboard loads them; the naive import chain
    degraded silently to "bridge not available".

26. **`mix test --cover` output in Elixir 1.20 is a pipe table**, not the old
    `  75.0%  Module` format:
    ```
    |     75.00% | MyApp.Module |
    |------------|----------------|
    |     35.68% | Total          |
    ```
    Parse with `^\|\s*([\d.]+)%\s*\|\s*([^|]+?)\s*\|` (keep the old-format
    regex as fallback). A coverage threshold configured in `coveralls.json` /
    mix config makes the task exit non-zero even when all tests pass —
    report `success: false` with the parsed percentages, not an error.
    Other 1.20 compile-warning trivia that fails `--warnings-as-errors`:
    ranges with implicit negative step need `3..-2//-1`; heredoc content must
    be indented to the closing heredoc delimiter; an underscored variable used after
    being set (`_lvl` then `level_to_int(_lvl)`) warns — rename without the
    underscore.

28. **Hex packages with optional deps must compile WITHOUT them installed.**
    Local `mix compile --warnings-as-errors` passes because every optional
    dep exists in your dev env; downstream users get only non-optional deps.
    Two failure modes (both shipped in extools 0.1.0 → forced 0.1.1):
    (a) struct patterns on optional-dep structs (`%Decimal{}`, `%Date{}`) —
    struct expansion needs the module at compile time; match
    `%{__struct__: mod}` and dispatch with atom comparison + `apply/3`.
    (b) unguarded module references to optional-dep modules (a
    `@behaviour Plug` module when bandit/plug is optional) — wrap the whole
    module in `if Code.ensure_loaded?(Plug.Conn) do ... else <stub> end`,
    and guard supervision children with `Code.ensure_loaded?(Bandit)` +
    clean `Logger.error` naming the dep to add (no boot crash). Verify in a
    fresh `mix new` project with ONLY the package as dep — pre-publish from
    a path dep AND post-publish from the registry. Full publish flow:
    the `hex-package-publishing` skill.

29. **No hardcoded personal paths in shipped plugin code.** A desktop
    plugin's scan root (`~/Workspace/Repos`) is one machine's layout —
    anyone else has a different one (the user called it directly: 'ese es mi
    path pero debe poder ser otro'). Make such roots configurable in layers:
    per-request override (`?root=` query param fed by a UI input persisted
    in localStorage) → env var (`EXTOOLS_REPOS_DIRS`, colon-separated) →
    documented default — and return the effective roots in the API response
    so the UI shows what was actually scanned.

31. **Simplifying the connection-mode tree when only two paths are real.** When you ship an MCP bridge to a real user base, the "auto-detect with 3+ modes" abstraction (MCP > remsh > static) gets a passive code path that "covers a case nobody exercises in practice" (remsh for projects that don't ship the hex package). The honest simplification: drop the middle mode, keep "MCP > static", update all the messages that said "remsh or MCP", delete the mode-specific test code, and bump the major version. The trade-off is real (you lose the fallback for projects that run `iex --sname` without the hex package), but for a single-developer ecosystem where the hex package is adopted across all active projects, the simpler tree wins. Pattern: 1) `rm bridge/<middle>.py`; 2) remove the mode constant + probe + dispatch branch from `connection.py`; 3) replace `remsh|remsh/MCP|remsh or MCP` strings with `MCP` everywhere (find/replace); 4) delete the obsolete references docs; 5) `git commit -m "feat(bridge): drop <middle> backend — <principal> > <fallback> only"` with explicit `Bumps version x.y.z → x.y+1.0 (removal of a backend mode)` in the body. Net effect: ~250 LOC removed, detector ~10% smaller, no functional loss for adopted projects, 0 silent behavior changes for the surviving modes.
32. **`Process.info(pid, key)` returns a 2-tuple `{key, value}` or `nil` — NOT a map.**
    NOT a map.** The idiom `Process.info(pid, :memory)[:memory]` (Access.get
    on the result) raises `FunctionClauseError: no function clause matching
    in Access.get/3` because Access only works on maps/keywords, not tuples.
    This is exactly the bug in extools `elixir_process_info` (tools.py):
    `{pid, Process.info(pid, :memory)[:memory], Process.info(pid, :registered_name)[:registered_name]}`
    crashed for any process whose `:registered_name` lookup returned nil
    (every unnamed process). Two correct forms:
    - Batch with a list: `Process.info(pid, [:memory, :registered_name])` →
      returns `nil` (process dead) or a MAP `%{memory: N, registered_name: name}`
      — map access works.
    - Single key, pattern-match the tuple: `case Process.info(pid, :memory) do
      {:memory, mem} -> mem; _ -> nil end`.
    The batch form is the clean fix: `info = Process.info(pid, [:memory, :registered_name]) || %{}; {info[:memory], info[:registered_name]}`.
    When writing generated eval code for process inspection, NEVER use
    `[...][:key]` on a per-key `Process.info/2` call.

33. **`mix phx.server` does NOT load `.env` — and "did env vars load?" is a
    runtime check, not a file check.** Phoenix/Elixir reads OS environment
    variables only; nothing auto-sources a repo `.env` unless the project has
    a dotenv dep, `bin/dev` wrapper, or direnv (check for those FIRST before
    claiming env vars are loaded). When the user asks "¿estoy cargando las env
    vars?", don't read the `.env` file and say "sí" — eval against the LIVE
    BEAM in MCP mode:
    `elixir_eval(code="System.get_env(\"MY_VAR\")")` → `nil` means not loaded,
    no matter what the file says. To start the server WITH the file:
    `set -a; source .env; set +a; mix phx.server` (zsh/bash).
    **Compile-time trap:** `@attr System.get_env("VAR", "default")` in a module
    attribute (the legacy single-user auth pattern — e.g. MyApp's `MyApp.Auth`)
    bakes the value at COMPILE time. Sourcing `.env` and restarting the server
    is NOT enough if `_build` already holds the compiled module with the
    default baked in — force a recompile (`touch lib/...` or
    `mix compile --force`) after changing env that feeds module attributes,
    or read via `Application.get_env`/runtime instead. Verify the effective
    value at runtime (`elixir_eval` calling the module's getter), not by
    re-reading the source.
    **Auth-debugging recipe that falls out of this:** for a Phoenix app whose
    login is DB-first with an env-var fallback (migrate-to-multiuser pattern),
    check IN ORDER, all via one `elixir_eval` batch in MCP mode:
    (1) does the user row exist (`Accounts.get_user_by_email(...)`),
    (2) does it have a `password_hash` (no hash → fallback path),
    (3) are the env vars even set in this BEAM (`System.get_env`),
    (4) call the real `authenticate_user(email, pass)` and inspect the tuple.
    Skipping straight to (4) tells you it fails but not WHY; the (1)-(3)
    ladder separates "user missing", "no hash set", and "env not loaded"
    which have completely different fixes (seed the user vs set password vs
    restart with env sourced).
