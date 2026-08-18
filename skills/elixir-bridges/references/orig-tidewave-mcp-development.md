---
name: tidewave-mcp-development
description: "Use Tidewave MCP tools for Phoenix/Elixir development: browser_eval for UI navigation and interaction, execute_sql_query for database inspection, project_eval for runtime evaluation, get_logs/get_docs/get_source_location for code introspection. Covers the browser object API, snapshot-based element location, and parallel subagent patterns."
version: 1.0.0
author: Álvaro Lizama
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [tidewave, mcp, phoenix, elixir, browser, debugging, development]
    related_skills: [phoenix-liveview-debugging, phoenix-umbrella-project-setup]
---

# Tidewave MCP Development

Use this skill when Tidewave MCP tools are available (browser_eval, execute_sql_query, project_eval, get_logs, get_docs, get_source_location, get_ecto_schemas, restart_app_server) and you need to interact with a running Phoenix/Elixir application — navigate pages, inspect the DOM, query the database, evaluate runtime code, or read logs.

## When to Use

- You need to navigate a Phoenix LiveView app and interact with elements (click buttons, fill forms, read page state)
- You need to query the database directly without leaving the agent conversation
- You need to evaluate Elixir code in the running application context
- You need to inspect logs, read module docs, or find source locations
- You want to parallelize: browser navigation in the main thread + code/DB analysis via subagents

## The Tidewave MCP Tool Ecosystem

| Tool | Purpose |
|------|---------|
| `browser_eval` | Execute JS in the browser, take snapshots, click elements, fill inputs, navigate |
| `execute_sql_query` | Run raw SQL against the app's Ecto repo (PostgreSQL by default) |
| `project_eval` | Evaluate Elixir code in the project's runtime context |
| `get_logs` | Read application log output, filter by level or grep pattern |
| `get_docs` | Get module/function documentation from the runtime |
| `get_source_location` | Find the source file and line for a module or function |
| `get_ecto_schemas` | List all Ecto schema modules and their file paths |
| `restart_app_server` | Restart the web server (rarely needed — code reloads on the fly) |

## The `browser` Object API (inside `browser_eval`)

The `browser_eval` tool executes JavaScript that MUST use the global `browser` object. All methods are async — always `await` them.

### Navigation

```javascript
// Navigate to a path — THIS is how you navigate, not window.location
await browser.reload("/some/path");

// Reload the current page
await browser.reload();
```

**CRITICAL: `window.location` is NOT available** in the top-level `browser_eval` code scope. It only exists inside `browser.eval()` callbacks that execute on the page. Use `browser.reload(path)` for navigation, never `window.location.href = ...`.

### Snapshots — the primary way to understand the page

```javascript
// Full page snapshot — returns accessibility tree with ref IDs (e1, e2, ...)
console.log('Snapshot: ', await browser.snapshot());

// Snapshot a specific element by ref
console.log('Snapshot: ', await browser.snapshot(browser.getBySnapshotRef('e42')));

// Snapshot with a locator — CAUTION: complex CSS selectors can fail silently
// This works for simple selectors:
console.log('Snapshot: ', await browser.snapshot(browser.locator('#sidebar')));

// This may fail with empty error {} — use getBySnapshotRef instead:
// browser.snapshot(browser.locator('h3:has-text("Modo de vista")'))  // AVOID
```

**Pitfall: Complex CSS selectors in `browser.snapshot(locator)` fail with empty error `{}`.** Pseudo-selectors like `:has-text()`, compound selectors, and nested selectors are unreliable. Instead, take a full `browser.snapshot()`, find the ref ID you need, then use `browser.getBySnapshotRef(ref)`.

### Locating elements

Two reliable methods:

1. **By snapshot ref (preferred)**: Take a snapshot, find the ref ID (e.g., `e507`), then:
   ```javascript
   const btn = browser.getBySnapshotRef('e507');
   ```

2. **By simple CSS selector or hasText**:
   ```javascript
   // Simple selector — works
   browser.locator('input[name="user_email"]')
   
   // hasText — works for buttons/links
   browser.locator('button', { hasText: 'Save' })
   ```

### Clicking and filling

```javascript
// Click — PREFER this over element.click() inside browser.eval
const btn = browser.getBySnapshotRef('e507');
await browser.click(btn);

// Fill an input
const input = browser.getBySnapshotRef('e42');
await browser.fill(input, "some value");
```

**Never** call `element.click()` or `form.submit()` directly inside `browser.eval`. Always use `browser.click(locator)` and dispatch events for form submission:
```javascript
form.dispatchEvent(new Event('submit', { bubbles: true }));
```

### Waiting

```javascript
await browser.wait(1000);  // Wait 1 second for page transitions/animations
```

### Snapshot output format

The snapshot returns an accessibility tree as YAML-like text. Key elements:
- `[ref=eNNN]` — the reference ID for locating via `getBySnapshotRef`
- `[cursor=pointer]` — clickable element
- `link "Text" [ref=eNNN]` — anchor links with href
- `button "Text" [ref=eNNN]` — buttons
- `textbox "Label" [ref=eNNN]` — input fields
- `combobox "Label" [ref=eNNN]` — select dropdowns
- `heading "Text" [level=N]` — headings
- `group "Label"` — fieldset/role groups

Large snapshots are truncated. Use `offset` and `limit` options to page through:
```javascript
console.log('Snapshot: ', await browser.snapshot(null, { offset: 200, limit: 200 }));
```

## Common Recipes

### Navigate and interact with a page

```javascript
// 1. Navigate
await browser.reload("/graph");
await browser.wait(500);

// 2. Take snapshot to find element refs
console.log('Snapshot: ', await browser.snapshot());

// 3. Click the element using its ref
const btn2D = browser.getBySnapshotRef('e507');
await browser.click(btn2D);
await browser.wait(300);

// 4. Verify the new state
console.log('After click: ', await browser.snapshot(browser.getBySnapshotRef('e506')));
```

### Query the database while navigating

`execute_sql_query` and `browser_eval` are independent tools — call them in parallel:

```
// In the same assistant turn, call both:
// 1. browser_eval — navigate to a page
// 2. execute_sql_query — query table counts

// They execute concurrently, saving round-trips.
```

### Inspect runtime state with project_eval

```elixir
# List all registered processes
Process.list() |> Enum.take(20)

# Check a specific module's state
:sys.get_state(MyApp.Worker)

# Call a context function live
MyApp.Brain.list_pages("personal") |> length()
```

### Read application logs

Use `get_logs` with `tail` to get the last N log entries. Filter by level or grep pattern:
- `level: "error"` — only error logs
- `grep: "timeout"` — filter by regex
- `tail: 50` — last 50 entries

## Parallel Subagent + Browser Pattern

When you need both browser interaction AND code/data analysis, dispatch subagents for analysis while the main thread handles the browser:

1. **Main thread**: Use `browser_eval` to navigate, snapshot, and interact with the UI
2. **Subagent 1**: Read and analyze source code (e.g., `read_file` on the LiveView module)
3. **Subagent 2**: Query the database via `execute_sql_query` for data analysis

The subagents run in the background. Their results re-enter the conversation when they finish — you keep working in the meantime.

## Key Pitfalls

1. **`window.location` not available in top-level scope** — use `browser.reload(path)` for navigation
2. **Complex CSS selectors fail silently** in `browser.snapshot(locator)` — use `getBySnapshotRef` instead
3. **Snapshots can be large** — use `offset`/`limit` to page through truncated output
4. **`browser.eval()` runs on the page** — it's a separate execution context. Don't reference outer variables; pass them as the second argument (locators)
5. **Always await** — all `browser` methods are async. Forgetting `await` silently drops the result
6. **Console.log for output** — `browser.eval` functions should `console.log()` results, never `return` them
7. **Snapshot refs change** — after any page interaction that changes the DOM, take a fresh snapshot to get updated refs

## How Tidewave Works Internally

The key principle: **Same BEAM = Same State**. Tidewave is a Plug inside
your Phoenix endpoint that handles MCP requests by evaluating code in the
same BEAM that serves HTTP. It's not an external process talking by API —
it's code running in the same runtime as your app.

The MCP server lives at `/tidewave/mcp` and accepts streamable HTTP transport.
The tools call BEAM internals directly:
- `project_eval` → `Code.eval_string/1` in the app's runtime context
- `execute_sql_query` → the app's Ecto Repo (same connection pool as HTTP requests)
- `get_logs` → a `:logger` handler that buffers logs in ETS, queried on demand
- `get_source_location` → `:beam_lib.info/1` or `Code.fetch_docs/1`
- `get_ecto_schemas` → enumerates `:code.all_loaded()` filtering by `Ecto.Schema`

The `tidewave_app` repo (Rust/Tauri) is NOT the MCP server — it's a local
proxy + desktop app that bridges editors to MCP servers via HTTP relay.

### The `--sname` limitation

`mix phx.server` starts the BEAM as `nonode@nohost` — no Erlang distribution.
This doesn't affect Tidewave (it uses HTTP, not remsh), but if you're
building a similar tool that connects via remsh, the app must be started
with `--sname` for distribution to work. See the `elixir-dev-bridge` skill
for the full `--sname` setup guide.

### What Tidewave doesn't have

Tidewave has ~10 runtime tools only. It lacks: mix/build tools (compile,
test, lint), filesystem/git tools, and works only with Phoenix (not plain
Elixir apps). The `elixir-dev-bridge` skill covers building a more complete
bridge that addresses these gaps.

## When to Use Tidewave vs Hermes Browser Tools

| Tidewave `browser_eval` | Hermes `browser_navigate`/`browser_snapshot` |
|------------------------|----------------------------------------------|
| Paired with the user's browser (shared context) | Independent browser session |
| `browser` object API (reload, eval, snapshot, click) | Hermes snapshot/click/type/scroll API |
| Can run `execute_sql_query` and `project_eval` alongside | Can run `terminal` and `web_extract` alongside |
| Best for: Phoenix-specific debugging with DB + runtime access | Best for: independent web scraping, external sites |

**Prefer Tidewave** when working on a Phoenix/Elixir app with the dev server running — you get SQL queries, runtime evaluation, and log access in the same toolset.

## Server Lifecycle

**Do NOT restart the server for general changes.** Phoenix compiles and reloads code on the fly. Only use `restart_app_server` when:
- Config files (`config/*.exs`) are modified
- The supervision tree is changed
- Dependencies are added/removed (`mix.exs`)

Valid reasons: `"deps_changed"`, `"config_changed"`, `"supervision_tree_changed"`.

## References

- `references/browser-object-api-cheatsheet.md` — Quick reference of all `browser` object methods with examples
