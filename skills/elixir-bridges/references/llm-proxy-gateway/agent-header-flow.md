# Agent Header Flow — Hermes → MyApp → Provider

Complete header lifecycle for LLM proxy requests. Traced from source code
(2026-07-27) against Hermes Agent's OpenAI SDK client and MyApp's
`ApiAuth` plug + `OpenAIAdapter`.

## Layer 1: Hermes → MyApp (inbound)

Hermes uses the **OpenAI Python SDK** (`AsyncOpenAI`) to talk to custom
providers. For `local-MyApp` (`http://localhost:4000/v1`), no special
header branch matches — it's not OpenRouter, Codex, Copilot, Kimi, or
Nvidia NIM. The SDK's default headers pass through untouched.

### Headers the OpenAI SDK sends by default

| Header | Example value | Source |
|-------|---------------|--------|
| `Authorization` | `Bearer tg-...` | `auth_headers/0` in `_client.py` |
| `Content-Type` | `application/json` | `default_headers` in `_base_client.py` |
| `Accept` | `application/json` | same |
| `User-Agent` | `AsyncOpenAI/Python 1.54.0` | `user_agent` property |
| `X-Stainless-Lang` | `python` | `platform_headers/2` |
| `X-Stainless-Package-Version` | `1.54.0` | same |
| `X-Stainless-OS` | `MacOS` | `get_platform()` |
| `X-Stainless-Arch` | `arm64` | `get_architecture()` |
| `X-Stainless-Runtime` | `CPython` | `get_python_runtime()` |
| `X-Stainless-Runtime-Version` | `3.12.0` | `get_python_version()` |
| `X-Stainless-Async` | `async:asyncio` | `auth_headers` (AsyncOpenAI subclass) |
| `X-Stainless-Retry-Count` | `0` | added per-retry in `_base_client.py` |
| `X-Stainless-Read-Timeout` | (if set) | same |

**Total: 13 headers** (12 constant + 1-2 per-request).

### Headers Hermes ONLY sends for OpenRouter

When the provider IS OpenRouter (hostname match), Hermes adds these via
`build_or_headers()` in `agent/auxiliary_client.py`:

```python
_OR_HEADERS_BASE = {
    "HTTP-Referer": "https://hermes-agent.nousresearch.com",
    "X-Title": "Hermes Agent",
    "X-OpenRouter-Categories": "productivity,cli-agent",
}
```

For MyApp (custom provider), these are **NOT sent**. Hermes sends no
attribution headers.

### Does Hermes send `X-Agent-Type`?

**No.** MyApp's `ApiAuth` plug reads this header (`api_auth.ex:57-61`),
but Hermes never sets it. All requests from Hermes log as `agent_type: "unknown"`
in `request_logs`. To populate it, either:
- Configure `extra_headers` in Hermes config for the `local-MyApp` provider
- Have the OpenAI SDK client set it via `default_headers`

### Does Hermes send `X-Title` or `HTTP-Referer`?

**Yes — but only when the provider is OpenRouter.** Hermes sets these via
`build_or_headers()` (`agent/auxiliary_client.py:616`). For custom providers
like `local-MyApp`, they are NOT sent unless the user configures them
via `model.default_headers`.

The OpenAI SDK **does** send `User-Agent: AsyncOpenAI/Python 1.54.0` to
custom providers — this is what `client_agent/1` resolves when no X-Title
is present.

## Layer 2: MyApp capture (what persists)

### What `ApiAuth` plug extracts

MyApp captures two distinct agent values:

```elixir
# api_auth.ex — legacy agent_type (X-Agent-Type only)
defp agent_type(conn) do
  case get_req_header(conn, "x-agent-type") do
    [type | _] when byte_size(type) > 0 -> type
    _ -> "unknown"
  end
end

# api_auth.ex — client_agent (X-Title > User-Agent > X-Agent-Type > "unknown")
def client_agent(conn) do
  with :error <- first_header(conn, "x-title"),
       :error <- first_header(conn, "user-agent"),
       :error <- first_header(conn, "x-agent-type") do
    "unknown"
  end
end
```

**`client_agent`** is the human-readable identity shown in the logs "Agente"
column. Priority: `X-Title` → `User-Agent` → `X-Agent-Type` → `"unknown"`.
Resolves to things like `"Hermes Agent"` (from X-Title) or
`"AsyncOpenAI/Python 1.54.0"` (from the SDK User-Agent).

**`agent_type`** is the programmatic type used for metrics/rollup via
`MyApp.Metrics.Collector`. Still sourced from `X-Agent-Type` only.

| Header from Hermes | Captured as | Where persisted |
|-------------------|-------------|-----------------|
| `X-Agent-Type` | `agent_type` AND `client_agent` | `request_logs.agent_type` + `request_logs.client_agent` |
| `X-Title` | `client_agent` | `request_logs.client_agent` |
| `User-Agent` | `client_agent` | `request_logs.client_agent` |
| `X-Stainless-*` (7 headers) | nothing | `conn.req_headers` only |
| `Authorization` | nothing | consumed for auth |
| `Content-Type` / `Accept` | nothing | consumed by Plug |

### Partitioned table DDL

`request_logs` is a native Postgres RANGE-partitioned table (`inserted_at`
daily granularity). You CANNOT use Ecto's `alter table(:request_logs)` in
migrations — it fails silently or errors. Use raw SQL:

```elixir
@disable_ddl_transaction true
@disable_migration_lock true

def up do
  execute "ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS client_agent VARCHAR(255)"
end

def down do
  execute "ALTER TABLE request_logs DROP COLUMN IF EXISTS client_agent"
end
```

The `IF NOT EXISTS` / `IF EXISTS` guards make the migration safe to
re-run. The column is automatically added to all partitions.

## Layer 3: MyApp → Provider (outbound)

### What `OpenAIAdapter.headers/1` sends

```elixir
# openai_adapter.ex:283
defp headers(api_key) do
  [
    {"content-type", "application/json"},
    {"authorization", "Bearer #{api_key}"}
  ]
end
```

**Exactly 2 headers.** No `User-Agent`, no `X-Stainless-*`, no `X-Title`,
no `HTTP-Referer`, no `X-Agent-Type`, no proxy-specific headers.

### Proxy invisibility

The upstream provider (OpenRouter) sees:
- A request from the MyApp server's IP
- With the credential's own API key (not the client's)
- No SDK fingerprint (no `X-Stainless-*`)
- No agent identification (no `User-Agent` from SDK)
- No proxy markers (no `X-Proxied-By`, `Via`, etc.)
- The `User-Agent` is whatever Finch's default is (not the SDK's)

**The proxy is invisible.** The provider cannot distinguish a direct API
call from a proxied one — unless it inspects the source IP.

### Design tension: invisibility vs attribution

**Álvaro's requirement:** the provider must not know there's a proxy —
no proxy-specific headers, no SDK fingerprint leaking through. This is to
avoid provider-side bans or rate-limiting of proxy traffic.

**Counter-tension:** OpenRouter uses `X-Title` + `HTTP-Referer` for app
attribution and ranking. Without them, the OpenRouter dashboard shows no
app name. This is a cosmetic loss, not a functional one.

**Resolution (implemented 2026-07-31):** forward `X-Title`, `HTTP-Referer`,
and `User-Agent` from the original client request (if the client set them)
to the provider. This gives attribution without revealing the proxy —
the headers look like they came from the client directly. Do NOT add any
`X-Proxied-By` or similar proxy-identifying header.

Implementation: `extract_forwarded_headers/1` in `proxy_controller.ex`
pulls the 3 whitelisted headers from `conn` and passes them as
`forwarded_headers` in opts. `OpenAIAdapter.headers/2` merges them onto
the base headers. Retry paths re-extract from `conn` so headers survive
fallback. See `MyApp-cost-accounting:references/http-transport.md`
for the full code.

## Debugging recipe: inspecting headers at the proxy

To see exactly what headers arrive at MyApp:

1. Add a temporary debug endpoint or log in `ApiAuth.call/1`:
   ```elixir
   require Logger
   Logger.info("INBOUND_HEADERS #{inspect(conn.req_headers)}")
   ```
   In dev, Logger goes to the BEAM console (stdout of `mix phx.server`).

2. To see what the adapter sends upstream, add logging in
   `OpenAIAdapter.chat_completion/4` before the `Finch.request` call:
   ```elixir
   require Logger
   Logger.info("OUTBOUND_HEADERS #{inspect(headers(api_key))}")
   ```

3. Alternatively, add an env-gated debug return in the controller:
   ```elixir
   if System.get_env("TG_DEBUG_HEADERS") == "1" do
     json(conn, %{"debug_headers" => Enum.map(conn.req_headers, fn {k, v} -> %{name: k, value: v} end)})
   else
     # normal flow
   end
   ```

## Hermes config: adding `extra_headers` to a custom provider

To make Hermes send `X-Agent-Type` (or any header) to MyApp, add
`extra_headers` to the provider config in `~/.hermes/config.yaml`:

```yaml
providers:
  local-MyApp:
    name: Local MyAppGateway
    base_url: http://localhost:4000/v1
    key_env: HERMES_CUSTOM_LOCAL_MY_APP_API_KEY
    extra_headers:
      X-Agent-Type: hermes-agent
      X-Title: Hermes Agent
```

These are merged onto the OpenAI client's `default_headers` via
`apply_custom_provider_extra_headers_to_client_kwargs()` in
`hermes_cli/config.py`. They override the SDK's default headers.
