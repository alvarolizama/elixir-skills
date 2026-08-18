---
name: mcp-proxy-gateway
description: "Use when building an MCP gateway/proxy over upstreams."
version: 1.0.0
author: Álvaro Lizama
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [mcp, model-context-protocol, gateway, proxy, multiplexing, elixir, phoenix]
    related_skills: [llm-proxy-gateway, mcp-server-development, plan]
---

# MCP Proxy Gateway

Use when designing or building a gateway/multiplexer in front of multiple MCP
servers: one client-facing endpoint that fans out to N third-party upstreams,
with central auth, per-tenant tool visibility, and credential vaulting.

Sibling of `llm-proxy-gateway` (same hot-path discipline, grants, breakers —
for LLM traffic). This skill covers the MCP-specific deltas. Protocol
mechanics live in `references/streamable-http-protocol.md`.

## When to use

- User wants one MCP endpoint aggregating several MCP servers (a.k.a. MCP
  router, multiplexer, hub)
- User wants the same API key to unlock different MCP servers/tools per team
  or person ("asignación igual que los modelos")
- User wants third-party MCP credentials centralized and never exposed to
  clients
- User asks about MCP proxy performance (tools/list fan-out, sessions)

## Core architecture

```
MCP client ──Streamable HTTP──> Gateway ──Streamable HTTP──> Upstream MCP ×N
(one config, one key)            │
                                 ├─ auth (bearer → tenant, ETS-cached)
                                 ├─ grants (team ∪ member extras ∪ service)
                                 ├─ namespace ({slug}__{tool})
                                 ├─ upstream session registry (lazy, ETS)
                                 ├─ tools/list cache (TTL + serve-stale)
                                 └─ audit log (async, off hot path)
```

Two endpoint shapes pay for themselves:

- `POST /mcp` — **aggregated**: one `initialize`, merged `tools/list`,
  prefix-routed `tools/call`. This is what clients configure.
- `POST /mcp/:slug` — **passthrough** to one upstream (debugging, pinning,
  per-server client entries with the same central key).

## Design decisions (each one learned the hard way)

### 1. Namespace tools as `{slug}__{tool}`

- MCP tool names cap at **64 chars** — skip+log any `slug__tool` that exceeds it.
- Decode by splitting on the **FIRST** `__` only — upstream tool names may
  contain `__` themselves.
- The prefix is routing semantics for the model (origin is explicit), not just
  collision avoidance. Also prefix each tool's `description` with the server
  display name in the aggregated list.

### 2. Upstream sessions are lazy, registered, reaped

Streamable HTTP is stateful: `initialize` → upstream returns `Mcp-Session-Id`;
subsequent requests must carry it or the upstream errors (typically 400/404 —
treat as `:session_expired`).

- Registry keyed `{api_key_id, server_id} → {session_id, protocol_version,
  last_used_at}` in ETS.
- **Lazy init**: handshake only when that key actually calls that server —
  never at client-connect time (session explosion otherwise).
- On `:session_expired`: delete, re-initialize, retry the call **once**.
- Idle reaper (e.g. 30 min TTL) — upstreams hold state per session.
- Send `notifications/initialized` right after each handshake (spec).

### 3. Client-facing session is ceremonial

The spec requires issuing an `Mcp-Session-Id` at `initialize`. Store
`{session_id → api_key_id}` for validation, but keep real authorization on the
per-request bearer — the gateway stays stateless-friendly and clients that
re-initialize per call don't trigger upstream re-handshakes.

### 4. tools/list never fans out on the hot path

Fan-out = N upstream RTTs on agent startup. Instead: per-server ETS cache
`{server_id → {tools, fetched_at}}`, TTL ~5 min:

1. Fresh → serve (~1 ms).
2. Stale → serve-stale + supervised async refresh (dedup per server).
3. Miss (cold) → sync fetch once; parallelize multi-server cold fetches with
   `Task.async_stream` + per-server timeout (~5 s).

A periodic health job (every ~2 min: `initialize`+`tools/list` per active
server) pre-warms the cache, updates status fields, and feeds the breaker —
kills the post-restart thundering herd too.

### 5. SSE can answer ANY POST

Per spec a server may respond `application/json` **or** `text/event-stream` to
any request. Parse SSE incrementally (`Finch.stream`), stop at the JSON-RPC
message with the expected `id`, tolerate `:keepalive` comment lines and events
split across chunks. Passthrough mode streams chunks to the client without
buffering. `GET` (server→client notification stream) can be `405` in v1 —
document the limitation.

### 6. No JSON-RPC batching

Batching was removed from the MCP spec (2025-06-18). Single messages only;
reject arrays with `-32600`.

### 7. Auth-swap, never forward

The client's bearer NEVER travels upstream. The gateway injects the server's
stored credential (`bearer` / custom header). Validate `base_url` scheme
(http/https) at config time — defense-in-depth SSRF even if admins configure.

### 8. Mirror the host app's existing RBAC

Don't invent a new grant model: copy the one already proven (e.g. team grants
∪ member extras ∪ service grants, fixed small query count, ETS-cached). Same
invalidation paths, same UI patterns, same tests. Wu Wei — act without forcing.

### 9. Tool surface area is a model-side cost, manage it explicitly

Aggregating N servers is free for the client (one config) but expensive for
the **model**: each tool schema costs ~200–800 tokens injected every turn, and
tool-selection accuracy degrades noticeably past ~40–50 visible tools.
Defense ladder (cheapest first):

1. **Grants as curation** — tenants only see assigned servers; nobody gets the
   full catalog by default.
2. **Per-grant `allowed_tools`** (nullable array; NULL = all) — expose 5 of a
   server's 40 tools. Filter in `tools/list`, enforce in `tools/call`
   (`-32602`). Combination rule: member extras can only *reduce* the team's
   allowlist, never widen it.
3. **Client narrowing** — `X-MCP-Servers: slug1,slug2` (or `?servers=`)
   intersects with grants (never widens). Same endpoint/key, each agent pins
   its subset.
4. **Meta-tools (future)** — `search_tools` / `describe_tool` / `call_tool`
   deferred-loading pattern (à la Hermes `tool_search`) for tenants with
   100+ tools. Don't build in v1.

### 10. Protocol limitations to state up front

- No upstream→client notifications (`tools/list_changed`, progress) without a
  GET SSE fan-in — v1: unsupported.
- `resources/*`, `prompts/*`: return empty lists or `-32601` in v1; namespaced
  passthrough later if clients demand them.
- No stdio or legacy-SSE upstreams — streamable HTTP only (stdio needs a
  wrapper like `mcp-remote` on the upstream side).
- No sampling/elicitation (requires persistent server→client channel).
- Slug rename = renames every visible tool prefix (breaking for agents) — warn
  loudly in the UI.

## Performance pitfalls checklist

| Problem | Mitigation |
|---------|-----------|
| tools/list fan-out latency | §4 cache + parallel cold fetch |
| Session explosion {key}×{server} | §2 lazy init + idle reaper |
| One slow upstream poisons the aggregate | independent timeouts + per-server breaker + exclude-from-merge |
| SSE CPU/latency | incremental parse, cut at matching id; raw passthrough streaming |
| Agent JSON-RPC bursts | hot path ETS-only (auth, grants, tools); DB writes async |
| Shared upstream exhaustion | per-server `max_concurrent`/`max_rpm` gate (+ optional per-user) |
| Giant tool results (base64) | body size cap; passthrough avoids decode |
| Post-restart stampede | health job pre-warms cache with jitter |
| Hot code reload (BEAM) | `:ets.whereis` guard on every cache — degrade to DB/direct, cache is never a hard dependency |

## Smoke probe (verify against one real upstream first)

Before building, run the curl handshake in
`references/streamable-http-protocol.md` against a real server and record:
content-type of each response (JSON vs SSE), session-id header presence, and
the exact error shape for an expired/missing session. Those three answers
decide how much of §5 and §2 you need on day one.

## Verification checklist

- Aggregated `tools/list` shows `{slug}__{tool}` for 2+ upstreams with correct
  per-tool routing on `tools/call`
- Tool without grant / outside allowlist rejected with `-32602`
- Expired upstream session → transparent re-init + single retry
- Upstream down → `tools/list` still serves (stale cache), `tools/call` fails
  with a clean JSON-RPC error, breaker marks degraded
- No DB queries on the hot path; logs enqueued asynchronously
- Client bearer never appears in upstream requests (assert in tests)
