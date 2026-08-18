# Provider rerank dialect abstraction

Session-learned pattern: when a provider's rerank endpoint does NOT speak the Cohere lingua franca, add a data-driven dialect translation layer — NOT a new adapter module per provider. Captured during DashScope rerank integration (2026-08).

> **✅ CONFIRMED (2026-08-16):** DashScope's native rerank endpoint
> (`text-rerank/text-rerank`) requires the NESTED request (`input.query` /
> `input.documents` / `parameters.*`) — a FLAT request returns 400
> "Field required: input.query & input.documents". So `DashScopeRerank.encode/1`
> MUST nest the request (as documented below); `decode/1` unwraps
> `output.results`. DashScope native embedding also needs a real encode
> (`input` string/list → `input.texts[]`) + decode (`output.embeddings` → `data`),
> see `DashScopeEmbedding` in the my_app_gateway repo.

## Problem

The proxy's lingua franca for rerank is Cohere format:
- Request: `{model, query, documents[], top_n?, return_documents?}`
- Response: `{results: [{index, relevance_score, document?}]}`

Some providers (DashScope) expose rerank only through a **completely different format** AND at a **different base URL** than chat/embeddings. DashScope's compatible-mode (`/compatible-mode/v1/rerank`) returns **404** — rerank only lives at the native services path.

## DashScope native rerank format

**Request** — nested `input`/`parameters`:
```json
{
  "model": "qwen3-rerank",
  "input": {
    "query": "What is a text rerank model",
    "documents": ["doc1", "doc2"]
  },
  "parameters": {
    "top_n": 5,
    "return_documents": true
  }
}
```

**Response** — wrapped in `output`:
```json
{
  "output": {
    "results": [
      {"index": 0, "relevance_score": 0.93, "document": {"text": "..."}},
      {"index": 1, "relevance_score": 0.72, "document": {"text": "..."}}
    ]
  },
  "usage": {"total_tokens": 117}
}
```

**Key differences from Cohere:**
| Aspect | Cohere | DashScope |
|--------|--------|-----------|
| Request shape | Flat top-level fields | `input.query`, `input.documents`, `parameters.*` |
| Response wrapper | Top-level `results` | `output.results` |
| Usage field | `prompt_tokens` | `total_tokens` only |
| Endpoint URL | `base_url/rerank` | Different base (`/api/v1/services/rerank/text-rerank/text-rerank`) |

## Solution: data-driven dialect registry

Instead of a new adapter module per provider, resolve the dialect from provider metadata in the DB:

```elixir
defmodule MyApp.Proxy.RerankDialect do
  alias MyApp.Proxy.DashScopeRerank

  def dialect_for(provider) when is_map(provider) do
    case Map.get(provider, :rerank_dialect) || Map.get(provider, "rerank_dialect") do
      "dashscope" -> {&DashScopeRerank.encode/1, &DashScopeRerank.decode/1}
      _ -> :passthrough
    end
  end

  def dialect_for(_), do: :passthrough
end
```

The adapter's `rerank/4` function becomes:
```elixir
def rerank(provider, credential, payload, opts) do
  url = rerank_url(provider)  # uses rerank_base_url override when present

  case RerankDialect.dialect_for(provider) do
    :passthrough ->
      post_json(provider, credential, url, payload, opts)
    {encode, decode} ->
      provider
      |> post_json(credential, url, encode.(payload), opts)
      |> decode_response(decode)
  end
end
```

### Why not a new adapter module?

- The transport (Finch POST, error classification, header handling) is identical.
- Only the **payload shape** and **response shape** differ.
- A dialect registry is data-driven: adding a new dialect means one new entry + one encode/decode module. No changes to controller, adapter dispatch, or routing.

## Database changes

Provider schema gains two nullable fields:

```elixir
field :rerank_base_url, :string       # Full URL override for rerank endpoint
field :rerank_dialect, :string         # "cohere" (passthrough) or "dashscope"
```

`rerank_base_url` is needed because DashScope's rerank lives at a completely different path than chat/embeddings. When nil, the adapter appends `/rerank` to `base_url` (standard Cohere surface).

## `build_url` helper for absolute vs relative paths

When `rerank_base_url` is a full URL (`https://dashscope...`), `post_json` must NOT concatenate it with `base_url`. Add a `build_url/2` helper:

```elixir
defp build_url(_provider, "http://" <> _ = url), do: url
defp build_url(_provider, "https://" <> _ = url), do: url
defp build_url(provider, path), do: base_url(provider) <> path
```

## Ecto changeset pitfall: get_change vs get_field with schema defaults

**Bug:** When a changeset field has the same value as the struct default, `Ecto.Changeset.cast/3` does NOT generate a change. `get_change(changeset, :field)` returns `nil` even though the user explicitly set it.

**Example:** Schema has `field :rerank_dialect, :string, default: "cohere"`. User passes `rerank_dialect: "cohere"`. After cast, `get_change` returns `nil` — indistinguishable from "user didn't set it at all".

**Fix:** Remove the schema default and use `nil` as the sentinel for "not set by user":

```elixir
# Before (broken — can't detect explicit user input)
field :rerank_dialect, :string, default: "cohere"

# After (works — nil means "not set", "cohere" means explicit)
field :rerank_dialect, :string
```

Then normalize in the changeset:
```elixir
defp normalize_rerank_dialect(changeset) do
  dialect_changed? = Ecto.Changeset.get_change(changeset, :rerank_dialect) != nil
  rerank_url = normalize_blank(Ecto.Changeset.get_field(changeset, :rerank_base_url))

  cond do
    is_nil(rerank_url) ->  # No rerank URL → force cohere
      put_change(changeset, :rerank_dialect, "cohere")
    not dialect_changed? ->  # URL set but no dialect → default to dashscope
      put_change(changeset, :rerank_dialect, "dashscope")
    true -> changeset  # User explicitly set dialect → respect it
  end
end
```

This pattern applies to ANY Ecto changeset where you need to distinguish "user explicitly set X" from "default value of X".

## Response normalization in decoder

DashScope's `usage.total_tokens` must be mapped to `prompt_tokens` for the proxy's cost estimator:

```elixir
defp normalize_usage(%{"usage" => usage} = body) do
  case Map.get(usage, "total_tokens") do
    nil -> body
    total -> put_in(body, ["usage", "prompt_tokens"], total)
  end
end
```

## Provider config for operators

| Field | DashScope value | oMLX/Fireworks |
|-------|----------------|----------------|
| Base URL | `compatible-mode/v1` (for chat/embeddings) | `http://localhost:1234/v1` |
| Rerank Base URL | `api/v1/services/rerank/text-rerank` | (leave empty) |
| Rerank Dialect | (auto-inferred: "dashscope") | (auto-inferred: "cohere") |

When `rerank_base_url` is empty string from the form, treat it as nil: normalize `""` to `nil` in the changeset.
