# DashScope regions & region-scoped API keys

DashScope (Alibaba Cloud Model Studio) has two API regions with **different hosts**
and **region-specific keys**. A key minted in one region returns `401 InvalidApiKey`
against the other region's host — this surfaces in a gateway as `all_providers_down`
even when the request body and dialect are correct.

| Region | Host | Keys |
|---|---|---|
| International | `https://dashscope-intl.aliyuncs.com` | `sk-ws-...` |
| China (Beijing) | `https://dashscope.aliyuncs.com` | China-scoped key |

Fix: make the provider's `base_url` / `embedding_base_url` / `rerank_base_url` host
match the key's region (use `-intl` for intl keys).

## Native endpoints (both region-scoped, NOT the compatible-mode path)

- **Embedding** — `.../api/v1/services/embeddings/text-embedding/text-embedding`
  - request: `{"model": "text-embedding-v4", "input": {"texts": ["..."]}}`
  - response: `{"output": {"embeddings": [{"text_index": 0, "embedding": [...]}]}, "usage": {"total_tokens": N}}`
  - `text_index` → OpenAI `index`; `output.embeddings` → `data`. `usage.total_tokens` → `prompt_tokens`.
- **Rerank** — `.../api/v1/services/rerank/text-rerank/text-rerank`
  - request: nested `{"model": "qwen3-rerank", "input": {"query": "...", "documents": [...]}, "parameters": {"top_n": N, "return_documents": true}}`
  - response: `{"output": {"results": [{"index": 0, "relevance_score": 0.9}]}, "usage": {"total_tokens": N}}`
  - `output.results` → `results`; `usage.total_tokens` → `prompt_tokens`.

## Verified (2026-08-16, live intl endpoint)

- Flat rerank request (`query`/`documents` at top level) → **400** `Field required: input.query & input.documents`.
- Nested rerank request → **200**.
- `dashscope.aliyuncs.com` (China) with an intl key → **401** `InvalidApiKey`.
- `dashscope-intl.aliyuncs.com` with the same intl key → **200**.

Symptom mapping in my_app_gateway: a region mismatch shows up as `all_providers_down`
(upstream rejected every candidate), NOT as a dialect/format error. Check the host
vs. key region before debugging the encode/decode.
