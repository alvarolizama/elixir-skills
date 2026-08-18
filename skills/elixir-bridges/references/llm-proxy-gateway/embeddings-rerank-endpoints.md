# Adding embeddings + rerank endpoints to the LLM proxy

Session-specific detail from extending MyApp (OpenAI-compatible Elixir/Phoenix proxy) beyond `/chat/completions`. Applies to any gateway built on the llm-proxy-gateway patterns.

## Provider format reality check

| Capability | oMLX (local) | OpenRouter | OpenAI |
|---|---|---|---|
| Embeddings | `POST /v1/embeddings` (OpenAI format, `dimensions` param) | `POST /embeddings` for embedding models (e.g. `qwen/qwen3-embedding-*`) | native |
| Rerank | `POST /v1/rerank` — Cohere-style: `{model, query, documents[]}` → `{results: [{index, relevance_score}]}` | **NO rerank endpoint.** Reranker models only usable via chat completions + Qwen3-Reranker prompt template (fragile) | n/a |

Client contract to expose: Cohere-style `/v1/rerank` (`query`, `documents[]`, optional `top_n`) — it's what LangChain/LlamaIndex speak.

## Implementation recipe (Elixir/Phoenix, mirrors MyApp)

1. **Adapter**: the OpenAIAdapter pattern is `base_url <> "/chat/completions"`. Add `embeddings/3` and `rerank/3` that only swap the appended path (`/embeddings`, `/rerank`) and reuse the same headers/error classification. Payloads forwarded verbatim — no translation needed for embeddings.
2. **Controller actions**: `ProxyController.embeddings` / `.rerank` mirror `chat_completions` and reuse the ENTIRE pipeline: ApiAuth plug, two-gate throttling (team limits + credential limits), `Router.route(model_alias, member, ctx)`, budget check, inflight registry, breaker outcome recording, fallback retry. Drop: streaming, guard rails injection, prompt optimizer.
3. **Routing constraint**: rerank aliases must only route to oMLX-style credentials. If a rerank alias points at OpenRouter, upstream 404s — the existing breaker/fallback handles it, but document the constraint for admins.
4. **Cost accounting**:
   - Embeddings: usage reports `prompt_tokens`/`total_tokens`; cost = input tokens only, completion = 0.
   - Rerank: oMLX reports NO token usage — estimate (query + docs) with the token estimator or bill flat per request per the model_provider's billing_mode.
5. **`GET /v1/models`**: embedding/rerank aliases appear automatically through the same alias-grant path; no changes needed.

## Working client reference

my_app's `my_app.Inference.Client` (`~/Workspace/Repos/my_app/lib/my_app/inference/client.ex`) is a verified Req-based client hitting exactly these two oMLX endpoints:

- `embeddings(model, inputs)` → POST `/embeddings` with `{model, input, dimensions}`, reads `data` sorted by `index` → `embedding`.
- `rerank(model, query, documents)` → POST `/rerank` with `{model, query, documents}`, reads `results`.

my_app.Rerank (`lib/my_app/rerank.ex`) shows the consumer-side pattern: map `results` into an `%{index => relevance_score}` map, sort candidates desc, fall back to original order on error.
