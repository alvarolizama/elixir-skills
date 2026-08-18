# MCP Tool Execution Smoke Test

Schema verification (`templates/mcp_smoke.sh`) confirms the server advertises
the right tools with the right descriptions. It does NOT confirm the tools
actually work when called. A tool can have a perfect schema and crash at
runtime — the `dran_delete_relation` pattern-match crash (handler didn't
match `{:error, atom}` from the backend) passed schema checks for months.

## When to run

- After adding a new tool to the dispatcher.
- After changing a tool's handler logic or the backend function it calls.
- After a domain model change that touches meta fields or return shapes.
- Before declaring "all tools work" to the user.

## Pattern

Write a Python (or bash) script that calls each tool via the HTTP MCP endpoint
with valid params and asserts on the response text. Key structure:

```python
import json, requests, re, time

BASE = "http://localhost:4000/api/mcp"
TOKEN = "<token>"
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}

_id = 0

def call_tool(name, args):
    """Call a tool and return (success, result_text, error)."""
    global _id
    _id += 1
    resp = requests.post(BASE, headers=HEADERS, json={
        "jsonrpc": "2.0", "id": _id, "method": "tools/call",
        "params": {"name": name, "arguments": args}
    }, timeout=30)
    text = resp.text.strip()
    # Server may return SSE (data: {...}) or plain JSON
    if text.startswith("data: "):
        for line in text.split("\n"):
            if line.startswith("data: "):
                data = json.loads(line[6:])
                break
    else:
        data = json.loads(text)
    if data.get("error"):
        return False, None, data["error"]
    if data.get("result", {}).get("content"):
        txt = "\n".join(c["text"] for c in data["result"]["content"] if c.get("type") == "text")
        return True, txt, None
    return True, str(data.get("result")), None
```

Then call each tool in workflow order (capture → read → organize → maintain →
automate), asserting on the returned text:

```python
# Capture
ok, txt, err = call_tool("prefix_create_page", {"context": "test", ...})
assert ok and "created" in txt.lower()

# Read
ok, txt, err = call_tool("prefix_search", {"context": "test", "query": "..."})
assert ok and "expected-slug" in txt

# Organize
ok, txt, err = call_tool("prefix_update_page", {"context": "test", "slug": "...", ...})
assert ok and "updated" in txt.lower()

# Maintain
ok, txt, err = call_tool("prefix_get_stats", {"context": "test"})
assert ok and "pages" in txt.lower()

# Automate (async — start, then poll)
ok, txt, err = call_tool("prefix_start_agent", {"agent_type": "ask", ...})
session_id = re.search(r"session_id:\s*([a-f0-9-]+)", txt).group(1)
time.sleep(2)
ok, txt, err = call_tool("prefix_get_agent_session", {"session_id": session_id})
assert ok and session_id in txt
```

## Pitfalls

### 1. Cleanup between runs

Tools that create pages/records will fail on the second run if the script
doesn't clean up. Either:
- Delete all test slugs at the end of the script, OR
- Prefix test slugs with `mcp-smoke-test-` and bulk-delete them before running.

If a create tool fails with "already taken" on a second run, it's a dirty
state problem, not a tool bug.

### 2. Response format: SSE vs plain JSON

The MCP Streamable HTTP transport can return either `text/event-stream`
(lines starting with `data: `) or plain `application/json`. The same server
may return different formats for different methods. Handle both:

```python
if text.startswith("data: "):
    for line in text.split("\n"):
        if line.startswith("data: "):
            data = json.loads(line[6:])
else:
    data = json.loads(text)
```

### 3. `session_id` is in plain text, not JSON

Async tools (like `start_agent`) return the session_id as plain text in the
tool result content (`session_id: <uuid>`), not as a JSON field. Parse with
regex:

```python
m = re.search(r"session_id:\s*([a-f0-9-]+)", txt)
```

Don't try `json.loads` on the result text or search for `"session_id":` with
quotes — it's formatted text, not JSON.

### 4. Async agent tools won't reach terminal status during the test

An `ask` or `research` agent takes seconds to minutes (LLM calls). The
`get_agent_session` tool will return `status: running` — that's a valid
response, not a failure. Assert that the tool returns the session info
(status, steps, type), not that the agent finished:

```python
assert ok and session_id in txt  # correct: tool works
# NOT: assert "done" in txt     # wrong: agent hasn't finished
```

### 5. `dran_delete_page` needs the server running, not `mix run`

Cleanup via `mix run -e '...'` fails with `:eaddrinuse` if the dev server
is already running on port 4000. Use the MCP tools themselves for cleanup
(call `dran_delete_page` via the same HTTP endpoint), not `mix run`.

### 6. Token from `.env`, not hardcoded

The auth module may read `DRAN_API_TOKEN` at compile time. A server started
with `mise` (which loads `.env`) serves the `.env` token, not the default.
Read it with `grep DRAN_API_TOKEN .env` and pass to the script.

## Plugin-side shim bugs (extools pattern)

The HTTP execution smoke catches **MCP server** bugs. It does NOT catch
bugs in **plugin clients that generate inline code** to evaluate in the
target process. The Hermes plugin for the `extools` hex package is the
canonical example: each of its 42 tools is a thin Python wrapper that
builds a string of Elixir code and calls `project_eval` over MCP. The
MCP server is fine. The Elixir eval can crash. The error trace you see
in the agent looks like `(FunctionClauseError) no function clause
matching in Access.get/3` — it looks like a test problem, not a plugin
bug.

### Why schema + HTTP smoke don't catch it

- Schema check: `tools/list` confirms the tool exists with the right
  params. Pass.
- HTTP smoke: `tools/call` returns a 200 with the eval error text in
  the result content. The MCP layer is working perfectly. The bug is
  one layer deeper — the inline code the plugin generated.

### What catches it

You must **look at the response text**, not just the HTTP status. Classify
the failure:

| Return shape | What it means |
| --- | --- |
| `{"success": true, "result": "..."}` | Tool works end-to-end. |
| `{"success": false, "processes": "Eval raised:\n** (FunctionClauseError) ..."}` | **Plugin-side shim bug** — the inline Elixir code is wrong. |
| `{"error": "elixir_X requires the 'Y' dep — not found in mix.lock."}` | Expected dep-gating failure. Not a bug. |
| `{"error": "missing required argument(s): foo"}` | Tool needs a required param the script forgot. Not a bug. |
| `{"error": "tool_call to 'X' is missing required argument(s): ..."}` | Same as above. |

### Concrete case: `elixir_process_info` (Aug 2026 MyApp audit)

The plugin's `tools.py:925` generated:

```python
f"  {{pid, Process.info(pid, :memory)[:memory], Process.info(pid, :registered_name)[:registered_name]}}\n"
```

`Process.info(pid, key)` returns either `{key, value}` (a 2-tuple) or
`nil` — never a map. The plugin treats the return as a map and uses
`Access.get` (the `tuple[:key]` syntax). When the process has the key,
`Process.info(pid, :memory)` returns `{:memory, 34376}`; `Access.get`
on a tuple is `(FunctionClauseError)`. The tool crashes on **every
process**, regardless of the filter argument.

Fix in the plugin:

```python
# OLD (crashes)
{ {pid, Process.info(pid, :memory)[:memory], Process.info(pid, :registered_name)[:registered_name]} }

# NEW (passes bulk info to BEAM, then indexes)
{ info = Process.info(pid, [:memory, :registered_name]) || %{}
  {pid, info[:memory], info[:registered_name]} }
```

The fix is in the plugin, not the MCP server and not the user's project.

### Reproduction recipe for any plugin that generates inline code

```python
# In the smoke script, after every tool call, also classify the result:
def classify(name, data):
    if data.get("error"):
        if "missing required argument" in str(data["error"]):
            return "PLUGIN_OK_NEEDS_ARGS"  # OK — operator forgot a param
        if "requires the '" in str(data["error"]):
            return "PLUGIN_OK_DEP_GATED"  # OK — dep not installed
        return "PLUGIN_BUG"  # real plugin bug
    if data.get("success"):
        return "TOOL_OK"
    if data.get("success") is False:
        # Probably a runtime eval error
        return "PLUGIN_BUG_EVAL_CRASH"
    return "UNKNOWN"

# Then assert: only PLUGIN_OK_NEEDS_ARGS, PLUGIN_OK_DEP_GATED, TOOL_OK
# are acceptable. PLUGIN_BUG and PLUGIN_BUG_EVAL_CRASH need a fix.
```

### Pitfall: the eval error trace is in the result, not stderr

The plugin embeds the eval error inside the `result` field as a
formatted string. Real-world trace from the reproduction:

```
Eval raised:
** (FunctionClauseError) no function clause matching in Access.get/3
    (elixir 1.20.1) lib/access.ex:324: Access.get({:memory, 34376}, :memory, nil)
    nofile:3: (file)
    nofile:2: (file)
    (elixir 1.20.1) src/elixir.erl:382: :elixir.eval_external_handler/3
```

The `nofile` is suspicious — it means the eval is a string, not a `.exs`
file. Read the file/line carefully: `Access.get/3` is in
`elixir/lib/access.ex`, but the `nofile:3` / `nofile:2` lines are the
plugin's string template. The bug is in the template, not the runtime.

### Other corners where this class of bug hides

- **String interpolation assumptions**: enums, atom names, or paths
  built into the eval that the project's domain doesn't have.
- **Tuple vs map destructuring**: `:foo` returns different shapes from
  `:foo => :bar` pattern matches depending on the BIF.
- **Default nil in dict access**: `some_func()[:key]` returns `nil` on
  shape mismatch instead of raising; only `Access.get` raises. If the
  plugin uses `[:key]` blindly, the silent `nil` cascades into a
  later TypeError, three frames deep, looking unrelated.

### Reporting back to the user

When you find a plugin-side shim bug, the report should say:

- **The plugin generated buggy code** (cite the file:line in the
  plugin), not "the tool is broken".
- **The MCP server is fine** — `tools/list` returns the schema correctly.
- **The user's project doesn't need fixing** — the inline code is built
  per-call inside the plugin.
- **Exact fix and verification**: the corrected inline code, and the
  smoke test that proves it works.

This avoids the user trying to "fix" their Elixir project when the bug
is in the Python wrapper two layers up.

## Reference implementation

The my_app repo has a full-coverage Python script at `/tmp/dran_mcp_smoke.py`
(written Jul 2026) that tests all 18 tools in workflow order. It's not
committed to the repo because it's disposable — rewrite it per session as
tools change. The pattern above is the reusable part.

For the plugin-side shim bug class, the canonical reproduction is the
extools `elixir_process_info` crash against MyApp (Aug 2026, see
"Concrete case" above). The bug location (`tools.py:925`) is in the
client plugin, not in the user's Elixir code.
