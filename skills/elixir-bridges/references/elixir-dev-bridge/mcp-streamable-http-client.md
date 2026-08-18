# MCP Streamable HTTP client (Python stdlib)

Client-side protocol for talking to a `hermes_mcp` server (e.g. the
`extools` hex package) from Python — verified against a live server.
Stdlib only (`urllib`, `json`).

## Non-negotiables (each one fails hard if skipped)

1. **Every request** sends `Accept: application/json, text/event-stream` —
   the server 406s without both, even for plain JSON responses. You cannot
   avoid the SSE path by asking for JSON only.
2. **Handshake before anything else**: `initialize` → server responds with
   the session id in the **`mcp-session-id` response header** (not the
   body!) → send `notifications/initialized` (response 202, empty body).
3. **Send `mcp-session-id` on every subsequent request.** A bare `ping`
   without a session returns a JSON-RPC error "Server not initialized" —
   a naive client that treats errors as "endpoint down" will misdetect the
   mode and fall back (observed: connection manager stuck in static mode).
4. **Re-handshake on staleness**: if a request fails with "not
   initialized" (server restarted), drop the cached session, handshake
   once, and retry the request once.
5. **`tools/call` params shape**: `{"name": "<tool>", "arguments": {...}}`.
   Tool output comes back as content blocks:
   `result.content[i] = {"type": "text", "text": "..."}` — unwrap by
   joining the text blocks; check `result.isError` (a tool-level error is
   NOT a JSON-RPC error).
6. **Tool names are the real ones** — the component name derives from the
   last module segment underscored (`GetAppState` → `get_app_state`).
   Don't invent aliases like `eval` for `project_eval` (real bug).

## Minimal working client shape

```python
class MCPClient:
    def __init__(self, timeout_s=5.0):
        self.timeout_s = timeout_s
        self._next_id = 1
        self._sessions = {}  # url -> session_id

    def _raw_post(self, url, payload, session_id=None):
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream"}
        if session_id:
            headers["mcp-session-id"] = session_id
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            return json.loads(resp.read().decode()), resp.headers.get("mcp-session-id")

    def _handshake(self, url):
        self._next_id += 1
        data, sid = self._raw_post(url, {
            "jsonrpc": "2.0", "id": self._next_id, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                       "clientInfo": {"name": "my-client", "version": "0.1.0"}}})
        if not sid or "result" not in data:
            return False
        self._sessions[url] = sid
        self._raw_post(url, {"jsonrpc": "2.0", "method": "notifications/initialized"},
                       session_id=sid)
        return True

    def call_tool(self, url, name, arguments=None):
        if url not in self._sessions and not self._handshake(url):
            return {"error": "handshake failed"}
        self._next_id += 1
        payload = {"jsonrpc": "2.0", "id": self._next_id, "method": "tools/call",
                   "params": {"name": name, "arguments": arguments or {}}}
        data, _ = self._raw_post(url, payload, session_id=self._sessions[url])
        # stale session? re-handshake once and retry
        if "not initialized" in str(data.get("error", {}).get("data", {}).get("message", "")).lower():
            self._sessions.pop(url, None)
            self._handshake(url)
            data, _ = self._raw_post(url, payload, session_id=self._sessions[url])
        result = data.get("result", {})
        text = "\n".join(b.get("text", "") for b in result.get("content", [])
                         if isinstance(b, dict) and b.get("type") == "text")
        return {"result": text, "is_error": bool(result.get("isError"))}
```

Production-hardened version: `python/bridge/mcp_client.py` in the
hermes-extools repo (adds per-URL sessions, error taxonomy, ping/list_tools).

## curl probe (manual verification)

```bash
curl -i -X POST http://localhost:4040/extools/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"probe","version":"0.1"}}}'
# capture mcp-session-id header, then notifications/initialized, then tools/call
```
