# OTLP GenAI Semantic Conventions — OpenRouter-Compatible Webhook Format

OpenRouter's observability webhooks send **OTLP JSON traces** (OpenTelemetry Protocol JSON format), not custom event payloads. This file documents the exact format for building compatible webhooks.

## Payload structure

```json
{
  "resourceSpans": [
    {
      "resource": {
        "attributes": [
          { "key": "service.name", "value": { "stringValue": "MyApp" } }
        ]
      },
      "scopeSpans": [
        {
          "spans": [
            {
              "traceId": "abc123def456...",
              "spanId": "def456ab...",
              "name": "chat",
              "kind": "SPAN_KIND_INTERNAL",
              "startTimeUnixNano": "1705312800000000000",
              "endTimeUnixNano": "1705312801000000000",
              "attributes": [
                { "key": "gen_ai.operation.name", "value": { "stringValue": "chat" } },
                { "key": "gen_ai.request.model", "value": { "stringValue": "openai/gpt-4o" } },
                { "key": "gen_ai.response.model", "value": { "stringValue": "gpt-4o-2024-08-06" } },
                { "key": "gen_ai.usage.input_tokens", "value": { "intValue": "1250" } },
                { "key": "gen_ai.usage.output_tokens", "value": { "intValue": "380" } }
              ],
              "status": { "code": "STATUS_CODE_OK" }
            }
          ]
        }
      ]
    }
  ]
}
```

## Attribute value types

OTLP attributes use typed value wrappers:
- `{ "stringValue": "..." }` — strings
- `{ "intValue": "100" }` — integers (as strings in JSON)
- `{ "doubleValue": 0.7 }` — floats
- `{ "boolValue": true }` — booleans
- `{ "arrayValue": { "values": [ { "stringValue": "stop" } ] } }` — arrays

## GenAI semantic convention attributes

### Request attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `gen_ai.operation.name` | string | `chat`, `text_completion`, `embeddings` |
| `gen_ai.request.model` | string | Model requested by client |
| `gen_ai.request.temperature` | double | Temperature setting |
| `gen_ai.request.top_p` | double | Top-p sampling |
| `gen_ai.request.max_tokens` | int | Max tokens to generate |
| `gen_ai.request.stream` | bool | Whether streaming was requested |
| `gen_ai.request.seed` | int | Seed for reproducibility |
| `gen_ai.request.frequency_penalty` | double | Frequency penalty |
| `gen_ai.request.presence_penalty` | double | Presence penalty |
| `gen_ai.request.stop_sequences` | string[] | Stop sequences |
| `gen_ai.request.choice.count` | int | Number of choices (n) |
| `gen_ai.system_instructions` | any | System message content |
| `gen_ai.input.messages` | any | Input messages (multimodal stripped) |
| `gen_ai.tool.definitions` | any | Tool/function definitions |

### Response attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `gen_ai.response.model` | string | Actual model that responded |
| `gen_ai.response.id` | string | Completion ID from provider |
| `gen_ai.response.finish_reasons` | string[] | `["stop"]`, `["length"]`, `["tool_calls"]` |
| `gen_ai.response.time_to_first_chunk` | double | TTFT in seconds (streaming only) |
| `gen_ai.output.messages` | any | Output messages |
| `gen_ai.output.type` | string | `text`, `json`, `image` |

### Usage attributes

**IMPORTANT — OpenRouter does NOT use the OTel standard names.** The OTel
semantic convention registry defines `gen_ai.usage.input_tokens` and
`gen_ai.usage.output_tokens`, but OpenRouter's actual webhook payloads
use `prompt_tokens` / `completion_tokens` / `total_tokens` / `total_cost`.
MyApp already sends the OpenRouter names (correct).

| Attribute | Type | Description | OpenRouter sends? | MyApp sends? |
|-----------|------|-------------|--------------------|------------------|
| `gen_ai.usage.prompt_tokens` | int | Prompt tokens (includes cached) | ✅ | ✅ |
| `gen_ai.usage.completion_tokens` | int | Completion tokens (includes reasoning) | ✅ | ✅ |
| `gen_ai.usage.total_tokens` | int | prompt + completion | ✅ | ✅ (prompt + completion) |
| `gen_ai.usage.total_cost` | double | Total cost of the request (real paid) | ✅ | ✅ (= `provider_cost_usd`) |
| `gen_ai.usage.cache_read.input_tokens` | int | Tokens served from provider cache | (if applicable) | ❌ |
| `gen_ai.usage.cache_creation.input_tokens` | int | Tokens written to provider cache | (if applicable) | ❌ |
| `gen_ai.usage.reasoning.output_tokens` | int | Reasoning/thinking tokens (o1, Claude) | (if applicable) | ❌ |

### Cost attribute alignment — DECIDED (2026-07)

MyApp sends 4 custom cost attributes (`MyApp.cost.*`) AND the
OpenRouter standard `gen_ai.usage.total_cost`. Both are kept — the
custom attrs give more detail, the standard attr ensures consumer
compatibility.

| Attribute | Value | OpenRouter sends? | MyApp sends? |
|-----------|-------|--------------------|------------------|
| `gen_ai.usage.total_cost` | real paid cost | ✅ | ✅ = `provider_cost_usd` |
| `MyApp.cost.estimated_usd` | market price (model_alias) | ❌ | ✅ (kept) |
| `MyApp.cost.usd` | provider pricing calc | ❌ | ✅ (kept) |
| `MyApp.cost.provider_usd` | real paid (reported or calc) | ❌ | ✅ (kept) |
| `MyApp.cost.savings_usd` | estimated - provider_cost | ❌ | ✅ (kept) |

**Key**: `gen_ai.usage.total_cost` = `provider_cost_usd` (the real paid
cost), NOT `cost_usd` (which is the provider pricing-table calculation).
The user confirmed: "nunca mandamos el costo estimado que definimos en
los modelos de MyApp hay que enviar el real de los proveedores".

The `trace.metadata` namespace is `openrouter` (NOT `MyApp`) —
match OpenRouter's real format exactly.

### Real observed OpenRouter payload

Captured from an actual OpenRouter webhook delivery (2026-07):

```json
{
  "resourceSpans": [
    {
      "resource": {
        "attributes": [
          { "key": "service.name", "value": { "stringValue": "user@example.com" } }
        ]
      },
      "scopeSpans": [
        {
          "spans": [
            {
              "traceId": "a1b2c3d4e5f6789012345678abcdef00",
              "startTimeUnixNano": "1753526400000000000",
              "attributes": [
                { "key": "trace.metadata.openrouter.api_key_name", "value": { "stringValue": "user@example.com" } },
                { "key": "gen_ai.request.model", "value": { "stringValue": "anthropic/claude-sonnet-4" } },
                { "key": "gen_ai.usage.prompt_tokens", "value": { "intValue": "1250" } },
                { "key": "gen_ai.usage.completion_tokens", "value": { "intValue": "830" } },
                { "key": "gen_ai.usage.total_tokens", "value": { "intValue": "2080" } },
                { "key": "gen_ai.usage.total_cost", "value": { "doubleValue": 0.0156 } }
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

Key observations from the real payload:
- **service.name = user account identifier** (email), NOT a static
  "openrouter" or "MyApp" string. MyApp uses
  "$Team.name - $User.email" (e.g. "Engineering - user@example.com").
- **trace.metadata.openrouter.api_key_name** — custom metadata is
  namespaced under trace.metadata.<system>.<field>. The namespace is
  "openrouter" (NOT "MyApp") — match OpenRouter's real format
  exactly. MyApp sends the same "$Team - $email" value here.
- **spanId, name, kind, endTimeUnixNano, status may be omitted** in
  minimal payloads — OpenRouter's real delivery can be sparser than the
  docs example. MyApp includes them all.
- **gen_ai.system is NOT present** in the real payload, despite being
  in the docs example. MyApp sends it ("MyApp"); it's harmless
  but not required.
- **intValue is a string** in JSON ("1250" not 1250).

### Provider attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `gen_ai.provider.name` | string | `openai`, `anthropic`, `aws.bedrock`, `groq`, `x_ai`, etc. |
| `server.address` | string | Provider host |

### Known provider name values

`openai`, `anthropic`, `aws.bedrock`, `azure.ai.openai`, `azure.ai.inference`, `cohere`, `deepseek`, `gcp.gemini`, `gcp.gen_ai`, `gcp.vertex_ai`, `groq`, `ibm.watsonx.ai`, `mistral_ai`, `perplexity`, `x_ai`

## Custom metadata (trace field)

Clients can pass metadata via the `trace` field in the API request:

```json
{
  "model": "openai/gpt-4o",
  "messages": [...],
  "trace": {
    "trace_id": "order_processing_001",
    "trace_name": "Order Processing Pipeline",
    "generation_name": "Extract Order Details",
    "order_id": "ORD-12345",
    "priority": "high"
  }
}
```

### Metadata key mapping

| Request key | OTLP mapping | Notes |
|-------------|---------------|-------|
| `trace.trace_id` | `traceId` (span top-level) | Groups multiple requests into one trace |
| `trace.trace_name` | `name` (span) | Root span name |
| `trace.span_name` | `name` (span) | Parent span name |
| `trace.generation_name` | `name` (span) | Generation span name |
| `trace.parent_span_id` | `parentSpanId` | Link to external span |
| `trace.*` (any other) | `trace.metadata.*` attributes | Custom span attributes |
| `user` (request field) | `user.id` span attribute | End-user identifier |
| `session_id` (request field) | `session.id` span attribute | Session/conversation ID |

## Webhook configuration

### Headers

Custom headers configured per destination:

```json
{
  "Authorization": "Bearer your-token",
  "X-Webhook-Signature": "your-webhook-secret"
}
```

### Test connection

OpenRouter sends an empty OTLP payload with `X-Test-Connection: true` header. Endpoint should return 2xx (or 400, accepted for empty payloads).

### Privacy mode

When enabled, prompt and completion content is excluded from traces. All other data (tokens, costs, timing, model info, custom metadata) is still sent.

### API key filtering

Each destination can be configured to only receive traces from specific API keys.

### Delivery semantics

- **Async** — traces sent after request completes, never block the API response
- **Batching** — multiple spans can be sent in one `resourceSpans` array
- **Retry** — webhook endpoint may be down; retry with backoff
- **Timeout** — short timeout (5s); drop if endpoint doesn't respond

## Fallback trace modeling

When the proxy does fallback (provider 1 fails, provider 2 succeeds), model as multiple spans sharing a traceId:

```
Trace: req_abc123
├── Span 1: "chat" (provider: openai) — status: ERROR
│   └── gen_ai.provider.name=openai, error.type=timeout
└── Span 2: "chat" (provider: anthropic) — status: OK
    └── gen_ai.provider.name=anthropic, gen_ai.usage.*
```

Span 2 has `parentSpanId` = Span 1's `spanId`. This gives full visibility into the fallback chain.

## Proxy-specific custom attributes

Attributes the proxy can add beyond standard GenAI conventions:

| Attribute | Type | Description |
|-----------|------|-------------|
| `proxy.provider.selected` | string | Provider chosen for this request |
| `proxy.fallback.triggered` | bool | Whether fallback was activated |
| `proxy.fallback.attempts` | int | Number of providers tried |
| `proxy.circuit_breaker.state` | string | `closed`, `open`, `half-open` |
| `proxy.routing.strategy` | string | `round_robin`, `weighted`, `sticky` |
| `proxy.cost.usd` | double | Billed cost to user (what we charge) |
| `proxy.provider_cost.usd` | double | Real cost to us (0 if subscription) |
| `proxy.estimated_cost.usd` | double | What it would cost at standard pay-per-token rates |
| `proxy.savings.usd` | double | Savings amount (estimated - provider_cost) |
| `proxy.subscription.id` | string | Subscription used (if any) |
| `proxy.client.id` | string | Client API key identifier (hashed) |

## Sources

- OpenRouter Broadcast docs: https://openrouter.ai/docs/guides/features/broadcast
- OpenRouter Webhook docs: https://openrouter.ai/docs/guides/features/broadcast/webhook
- OpenTelemetry GenAI semantic conventions: https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/
- GenAI semantic conventions repo: https://github.com/open-telemetry/semantic-conventions-genai

## OpenRouter vs OTel standard — naming discrepancy

The OTel semantic convention registry and the GenAI spec define
`gen_ai.usage.input_tokens` / `gen_ai.usage.output_tokens`. However,
**OpenRouter's actual webhook delivery uses different names**:

| OTel standard | OpenRouter actually sends |
|---------------|--------------------------|
| `gen_ai.usage.input_tokens` | `gen_ai.usage.prompt_tokens` |
| `gen_ai.usage.output_tokens` | `gen_ai.usage.completion_tokens` |
| `gen_ai.usage.total_tokens` | `gen_ai.usage.total_tokens` |
| `gen_ai.cost.*` | `gen_ai.usage.total_cost` |

**Decision:** match OpenRouter's actual names (what consumers like
Datadog, Grafana, Langfuse expect from OpenRouter-format traces), NOT
the OTel spec names. MyApp already uses `prompt_tokens` /
`completion_tokens` (correct). Missing: `total_tokens` and
`total_cost` — see TODO items above.
