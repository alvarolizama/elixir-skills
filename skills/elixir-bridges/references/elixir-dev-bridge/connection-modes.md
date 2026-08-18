# Connection Modes — Elixir Dev Bridge

## The `--sname` Problem

### `mix phx.server` starts WITHOUT distribution

When you run `mix phx.server`, the BEAM starts as `nonode@nohost` — no
Erlang distribution, no epmd. This means **remsh cannot connect**.

```bash
# This is what most developers do:
mix phx.server
# BEAM node name: nonode@nohost
# epmd: NOT running
# remsh: CANNOT connect
```

### How to enable remsh

The app must start with a node name:

```bash
# Option A: iex with --sname (short names, no DNS needed)
iex --sname MyApp -S mix phx.server
# BEAM node name: MyApp@hostname
# epmd: running
# remsh: CAN connect

# Option B: elixir with --sname (no iex shell)
elixir --sname MyApp -S mix phx.server

# Option C: --name (long names, needs DNS or /etc/hosts)
iex --name MyApp@myhost.example.com -S mix phx.server
```

### How remsh connects

```bash
# Discover the running node:
epmd -names
# Output: epmd: up and running on port 4369 with data:
#         name MyApp at port 35647

# Connect:
iex --sname bridge --remsh MyApp@hostname
# Now you're in an IEx session attached to the running BEAM
# Everything you type runs in the app's runtime
```

## Mode Selection Matrix

| How app started | Node name | remsh? | MCP HTTP? | Best mode |
|-----------------|-----------|--------|-----------|-----------|
| `mix phx.server` | `nonode@nohost` | ❌ | ✅ (if hex pkg) | MCP HTTP or static |
| `iex -S mix phx.server` | `nonode@nohost` | ❌ | ✅ | MCP HTTP or static |
| `iex --sname MyApp -S mix phx.server` | `MyApp@host` | ✅ | ✅ | remsh or MCP HTTP |
| `iex --name MyApp@host -S mix phx.server` | `MyApp@host` | ✅ | ✅ | remsh or MCP HTTP |
| App not running | — | ❌ | ❌ | static (`mix run -e`) |

## Auto-Detection Logic (plugin side)

```python
# Pseudocode — bridge/connection.py

def detect_mode(project_info):
    # 1. Is the hex package installed and running?
    if extools_in_deps(project_info.mix_lock):
        # Try MCP HTTP endpoint
        port = project_info.phoenix_port or 4040
        url = f"http://localhost:{port}/extools/mcp"
        if http_probe(url):
            return MCPMode(url=url)
    
    # 2. Is there a BEAM with distribution running?
    nodes = run("epmd -names")
    if nodes and parse_node_name(nodes):
        return RemshMode(node=parse_node_name(nodes))
    
    # 3. Fallback: static mode (always works)
    return StaticMode()

def http_probe(url):
    """Quick health check — POST a ping to the MCP endpoint."""
    try:
        resp = requests.post(url, json={
            "jsonrpc": "2.0", "id": 1, "method": "ping"
        }, timeout=1)
        return resp.status_code == 200
    except:
        return False
```

## When to Use Which Mode

### Static (`mix run -e`)
- **Use for**: introspection (docs, source location, schemas), one-shot DB
  queries that don't need running GenServers
- **Speed**: ~2-5s per call
- **State**: empty (fresh BEAM)
- **Safety**: isolated — no side effects on the real app
- **Works**: always, even without app running

### remsh
- **Use for**: debugging live state, inspecting GenServers, ETS, processes
- **Speed**: ~100ms per call
- **State**: full — sees everything in the running app
- **Safety**: DANGER — code runs in the real app, side effects are real
- **Works**: only if app started with `--sname` or `--name`

### MCP HTTP (hex package)
- **Use for**: everything remsh does but without needing `--sname`
- **Speed**: ~50ms per call
- **State**: full — same BEAM as the app
- **Safety**: DANGER — same as remsh, code runs in the real app
- **Works**: if hex package installed, app running, any start method

## Speed Comparison

```
Static:   [compile 2s][boot 1s][eval 50ms][die] = ~3-5s total
remsh:    [connect 20ms][eval 50ms][disconnect 10ms] = ~100ms total
MCP HTTP: [HTTP roundtrip 30ms][eval 50ms][response 20ms] = ~50ms total
```

## Phoenix Plug vs Bandit Standalone — port detection

| App type | HTTP server | Default port | MCP path |
|----------|------------|-------------|----------|
| Phoenix | Phoenix.Endpoint (Cowboy/Bandit) | 4000 | `/extools/mcp` |
| Plug (no Phoenix) | Bandit (standalone) | 4040 | `/extools/mcp` |
| Pure Elixir (no web) | Bandit (standalone) | 4040 | `/extools/mcp` |
| Library (no app) | None | — | N/A (use static mode) |

## The `--sname` Setup Guide (for the skill/README)

When the user needs remsh mode, the skill should tell them:

```bash
# Instead of:
mix phx.server

# Use:
iex --sname MyApp -S mix phx.server

# Or add an alias to mix.exs:
#   aliases: [
#     "phx.server": "phx.server",  # keep default
#     "dev": "run --no-halt -e 'System.cmd(\"iex\", [\"--sname\", \"MyApp\", \"-S\", \"mix\", \"phx.server\"], into: IO.stream())'"
#   ]
# Then: mix dev
```

The plugin should also be able to suggest this to the user when it detects
that the app is running as `nonode@nohost` and remsh would be valuable.
