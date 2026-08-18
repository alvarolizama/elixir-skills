# MCP Streamable HTTP — protocol mechanics for gateway builders

Condensed notes from the MCP spec (2025-06-18) and live probing of real
servers. Only what a proxy/gateway implementer needs — not a spec mirror.

## Request/response shape

- Single HTTP endpoint per server. Client POSTs one JSON-RPC 2.0 message
  (request or notification). Batching (JSON-RPC arrays) was **removed** in
  spec 2025-06-18 — reject arrays with `-32600`.
- Required request headers:
  - `Content-Type: application/json`
  - `Accept: application/json, text/event-stream` — BOTH, always. The server
    chooses per response which one it uses.
  - `Mcp-Session-Id: <id>` — on every request after initialize.
  - `MCP-Protocol-Version: <version>` — on requests after initialize
    (negotiated value).
- The server may answer any POST with either:
  - `application/json` — the JSON-RPC response directly, or
  - `text/event-stream` — an SSE stream; the JSON-RPC response arrives as one
    `data:` event among possibly several (progress notifications first).
- Notifications (no `id`) get `202 Accepted` with an empty body.
- `GET` on the endpoint opens a long-lived SSE stream for server-initiated
  traffic (notifications, server→client requests like sampling). A v1 gateway
  can answer `405` and document it.

## Session handshake

1. Client POSTs `initialize` with `protocolVersion`, `capabilities`,
   `clientInfo`.
2. Server responds with its `protocolVersion` (possibly downgraded — persist
   the negotiated value per session), `capabilities`, `serverInfo`, and
   (usually) the `Mcp-Session-Id` **response header**.
3. Client MUST then POST `notifications/initialized` before other traffic.
4. Subsequent requests without a valid session id fail — typically `400` or
   `404` with a JSON-RPC error body. Treat as `:session_expired` → full
   re-handshake, retry the original call once.

Versions worth supporting: `2025-06-18` (current), `2025-03-26` (legacy
fallback — it predates batching removal, so keep array rejection lenient
there if you must support it).

## SSE parsing recipe (incremental)

Buffer bytes; split on `\n\n` (also tolerate `\r\n\r\n`). Per event block:

- Lines starting `:` are comments/keepalives — ignore.
- `data:` lines concatenate (joined with `\n`) → the payload; JSON-decode.
- `event:` / `id:` / `retry:` lines — safe to ignore for JSON-RPC matching.
- An event's payload may be split across arbitrary chunk boundaries — never
  assume one HTTP chunk = one event.

Gateway match loop: feed chunks until one decoded payload is a JSON-RPC
**response** (has `id` equal to the in-flight request, plus `result` or
`error`). Interim payloads with method `notifications/*` are progress —
forward or drop per mode, but keep reading.

## Error taxonomy worth normalizing

Map upstream failures to a small atom set (mirror the LLM proxy adapter):

- `:auth_error` — 401/403 from the upstream → surface config fault, mark the
  server credential unhealthy, never retry against other servers.
- `:client_error` — other 4xx → pass through, don't burn the breaker.
- `:session_expired` — 400/404 with session error → re-init + retry once.
- `:timeout` / `:unreachable` / `:server_error` — breaker food; `tools/call`
  fails clean, `tools/list` serves stale cache.

## Smoke probe (curl)

```bash
# 1) Initialize — capture session id + negotiated version + content-type
curl -i -X POST "$BASE/mcp" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{
        "protocolVersion":"2025-06-18","capabilities":{},
        "clientInfo":{"name":"gateway-probe","version":"0.1"}}}'
# Note: status, content-type, 'mcp-session-id' header, body protocolVersion.

SID=<session id from header>
VER=<protocolVersion from body>

# 2) Initialized notification (expect 202, empty body)
curl -i -X POST "$BASE/mcp" -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: $SID" -H "MCP-Protocol-Version: $VER" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'

# 3) tools/list — note whether response is JSON or SSE
curl -i -X POST "$BASE/mcp" -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: $SID" -H "MCP-Protocol-Version: $VER" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'

# 4) Missing/bogus session — note exact status + error body (re-init trigger)
curl -i -X POST "$BASE/mcp" -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: bogus" -H "MCP-Protocol-Version: $VER" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/list","params":{}}'
```

Record all four outputs in the project's spec/notes before writing the
client — content-type behavior and the session-expiry error shape vary by
server implementation and decide how much parser you need on day one.
