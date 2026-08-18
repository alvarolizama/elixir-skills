# Embeddings & Rerank API formats across providers

Verified against provider docs and the my_app oMLX client (`~/Workspace/Repos/my_app/lib/my_app/inference/client.ex`), 2026-08. Use when adding `/embeddings` or `/rerank` to a proxy/gateway.

## Embeddings — universal OpenAI format

All three backends accept `POST <base_url>/embeddings` and return the OpenAI shape:

```json
// request
{"model": "qwen3-embedding-8b", "input": ["a", "b"], "dimensions": 1024}
// response
{"object": "list",
 "data": [{"index": 0, "embedding": [0.0023, ...], "object": "embedding"}],
 "model": "...",
 "usage": {"prompt_tokens": 8, "total_tokens": 8}}
```

| Provider | Base URL | Usage reported | Extras (passthrough-free) |
|---|---|---|---|
| oMLX (local) | server base | sometimes absent → estimate | — |
| OpenRouter | `https://openrouter.ai/api/v1` | yes | multimodal input (`image_url` content blocks), `provider` routing prefs, `GET /embeddings/models` |
| Fireworks | `https://api.fireworks.ai/inference/v1` | yes | `dimensions`, `encoding_format`, `return_logits` + `normalize` (rerank-via-embeddings hack) |

Notes:
- No streaming — always buffered responses.
- Errors follow OpenAI envelope `{"error": {"code", "message"}}`; OpenRouter adds 402 (insufficient credits) and 529 (provider overloaded).
- Passthrough works 1:1 as long as the adapter never mutates the payload.

## Rerank — stable request, DIVERGENT response list key

Request is identical everywhere:

```json
{"model": "qwen3-reranker-8b", "query": "...", "documents": ["d1", "d2"],
 "top_n": 5, "return_documents": true, "task": "optional task hint (Fireworks)"}
```

Response diverges only in the list wrapper — items are identical (`index`, `relevance_score`, optional `document`):

```json
// oMLX / Cohere style
{"results": [{"index": 0, "relevance_score": 0.95}]}

// Fireworks / Jina style
{"object": "list",
 "data": [{"index": 0, "relevance_score": 0.5, "document": "..."}],
 "usage": {"prompt_tokens": 123, "total_tokens": 123}}
```

| Provider | Endpoint | Response key | Usage |
|---|---|---|---|
| oMLX | `/rerank` | `results` | none → estimate (query + Σ docs) |
| Fireworks | `/inference/v1/rerank` | `data` (+`object: "list"`) | real `prompt_tokens` |
| OpenRouter | **does not exist** | — | — |
| DashScope | native services API | `output.results` (wrapped) | `total_tokens` (not `prompt_tokens`) |

**⚠️ DashScope is NOT Cohere-compatible for rerank.** The compatible-mode `/v1/rerank` returns **404**. The native endpoint uses a different format entirely — see `references/provider-rerank-dialects.md` for the full encode/decode pattern, `rerank_base_url` override, and the `RerankDialect` registry. DashScope chat and embeddings DO work via compatible-mode (`/compatible-mode/v1`); only rerank diverges.

**Gateway rule: normalize to Cohere shape (`results`) before responding.** my_app and most Cohere-style clients consume `results`; normalizing lets the same client hit any backend:

```elixir
defp normalize_rerank_body(%{"results" => _} = body), do: body
defp normalize_rerank_body(%{"data" => data} = body) when is_list(data) do
  body |> Map.delete("data") |> Map.delete("object") |> Map.put("results", data)
end
defp normalize_rerank_body(body), do: body
```

Fireworks rerank usage feeds cost accounting exactly; oMLX needs a token estimator fallback (chars/4 over query + documents, completion_tokens = 0).

Fireworks escape hatch: rerank via `/embeddings` with `return_logits: [no_token_id, yes_token_id]` and `normalize: true` — the "yes" probability is the relevance score. Supports more models/parallelism than `/rerank`. Qwen3 token IDs: no = 2753, yes = 9454.

## Gateway implementation checklist (MyApp-proven)

1. `model_type` field on the model alias: `llm | embedding | rerank`, default `llm` → zero breaking change. Router filters by capability; mismatch → distinct 400 (never route chat to an embedding model).
2. Skip chat-only per-alias transforms (guard rails, prompt optimizers, reasoning flags) for non-llm types.
3. Generalize the chat adapter POST into a shared `post_json(path)` — the three endpoints differ only in path.
4. Reuse the full gate pipeline unchanged: auth → team limits → route → budget → credential limits → inflight log → execute with fallback → usage normalize → cost inject → async log write.
5. Add `request_type` (`chat | embedding | rerank`) to request logs/inflight for observability; embeddings responses can carry injected cost inside `usage`, rerank (Cohere shape) has no `usage` key → cost goes to headers + log only.
6. `/v1/models` may include `model_type` per entry — OpenAI clients ignore unknown fields.
