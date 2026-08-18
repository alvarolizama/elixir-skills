# Provider native formats per service (embedding + rerank)

my_app_gateway speaks ONE standard format to its clients (OpenAI for chat+embeddings, Cohere for rerank) and translates to each provider's native format per service. Captured 2026-08-16 while adding per-service provider formats.

## The architecture

```
Client (my_app) ── standard (OpenAI/Cohere) ──> my_app_gateway ── translate ──> Provider (native)
```

- `model_type` on the ALIAS decides the endpoint (`/chat/completions`, `/embeddings`, `/rerank`).
- The FORMAT (dialect) is a PROVIDER property (`embedding_format`, `rerank_format`), NOT an alias property — one rerank alias routes to multiple providers with different dialects.
- The `Format` registry resolves per service: `embedding_dialect_for/1` and `rerank_dialect_for/1`, returning `:passthrough` or `{encode_fn, decode_fn}`.
- The client (my_app) is pure standard — it sends `input:[...]` and reads `data`/`results`; it never sees the native formats. All translation lives in the proxy.

## Rerank: request is FLAT everywhere, only the RESPONSE differs

The request is identical across Cohere, Fireworks, and DashScope:

```json
{"model": "...", "query": "...", "documents": ["..."], "top_n": 5, "return_documents": true}
```

| Provider | Response list key | Usage |
|---|---|---|
| Cohere / oMLX | `results` | `prompt_tokens` (or absent) |
| Fireworks | `data` (+ `object: "list"`) | `prompt_tokens` |
| DashScope / Qwen Cloud | `output.results` (wrapped) | `total_tokens` |

**⚠️ DashScope rerank `encode` is IDENTITY** — do NOT nest into `input`/`parameters`. The original nested encode broke the native endpoint (the API expects a flat Cohere-shaped request). Only `decode` (unwrap `output.results` + `total_tokens`→`prompt_tokens`) is needed. Fireworks needs only the `data`→`results` normalization (already in the controller), no dialect.

## Embedding: DashScope native diverges (Fireworks/OpenAI passthrough)

OpenAI / Fireworks accept `POST /embeddings` with `{model, input: string|list}` → `{data: [{index, embedding}]}` (passthrough).

DashScope native (`/api/v1/services/embeddings/text-embedding/text-embedding`) differs:
- Request: `{model, input: {texts: [...]}}` (nested `texts`, not bare `input`)
- `dimensions` → `dimension`
- Response: `{output: {embeddings: [{text_index, embedding}]}}` (wrapped, `text_index` not `index`)
- `usage.total_tokens` only (no `prompt_tokens`)

Translation (`DashScopeEmbedding`):
- encode: `input` (string→[string], list→list) → `input.texts`; `dimensions` → `dimension`
- decode: `output.embeddings` → `data` with `text_index` → `index` (sorted); `total_tokens` → `prompt_tokens`

## Provider form (per-service URLs + formats)

| Field | Type | Values |
|---|---|---|
| `base_url` | LLM base (up to /v1) | — |
| `embedding_base_url` | full URL (nullable) | nil = base_url + /embeddings |
| `embedding_format` | select | `openai` · `dashscope` |
| `rerank_base_url` | full URL (nullable) | nil = base_url + /rerank |
| `rerank_format` | select | `cohere` · `dashscope` |

URLs: LLM is base-only (adapter appends `/chat/completions`); embedding and rerank are FULL URLs pasted by hand (the native endpoints live at a different path than the compatible-mode base, e.g. DashScope).
