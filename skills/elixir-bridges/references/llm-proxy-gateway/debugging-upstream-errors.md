# Debugging upstream provider errors

MyApp proxy errors that look like client errors but originate from the upstream provider. Use this when a chat completion returns 404/400 but the API key authenticates fine.

## Symptom: `upstream_client_error` (404)

```
{"error":{"code":"upstream_client_error","message":"Provider rejected the request (404)","type":"invalid_request_error"}}
```

This means MyApp authenticated the Bearer key, routed to a provider, but the provider returned 404. The most common cause is a URL construction mismatch.

## Diagnostic recipe

### 1. Confirm the API key is valid

```bash
curl -s http://localhost:4000/v1/models \
  -H "Authorization: Bearer tg-XXXX"
```

If this returns `{"data": [...]}`, the key is fine — the problem is upstream.

### 2. Check what model aliases are available

The `/v1/models` response shows only the aliases the API key's team can access. Note the `id` field — that's the value to pass as `model` in `/v1/chat/completions`.

### 3. Inspect the DB for provider + base_url + provider_model

```sql
SELECT ma.name AS alias, ap.provider_model, p.name AS provider,
       p.base_url, p.status, ap.enabled
FROM model_aliases ma
JOIN alias_providers ap ON ap.model_alias_id = ma.id
JOIN providers p ON p.id = ap.provider_id
ORDER BY ma.name;
```

The `provider_model` is what gets sent to the upstream (e.g. `deepseek/deepseek-v4-flash` for OpenRouter). The `base_url` must include the full API base path (e.g. `https://openrouter.ai/api/v1`), and the adapter appends only `/chat/completions` to it.

### 4. Test the upstream directly

Extract the credential key from `provider_credentials` and curl the upstream:

```bash
FULL_KEY=$(PGPASSWORD=postgres psql -h localhost -U postgres -d my_app_dev -t -A -c \
  "SELECT api_key_encrypted FROM provider_credentials
   WHERE provider_id = (SELECT id FROM providers WHERE name='OpenRouter') LIMIT 1;")

curl -s -w "\nHTTP_STATUS:%{http_code}\n" \
  https://openrouter.ai/api/v1/chat/completions \
  -H "Authorization: Bearer $FULL_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek/deepseek-v4-flash","messages":[{"role":"user","content":"hi"}],"max_tokens":10}'
```

If this works (200) but MyApp returns 404, the issue is URL construction — the `base_url` in the DB is likely missing the API base path, or the adapter was concatenating an extra path segment.

### 5. Check the adapter's URL builder

`OpenAIAdapter` builds URLs as:

```elixir
defp chat_completions_url(provider) do
  base_url(provider) <> "/chat/completions"
end

defp models_url(provider) do
  base_url(provider) <> "/models"
end
```

The `base_url` must include the provider's API base path. Correct examples:

| Provider | Correct `base_url` | Final URL |
|----------|-------------------|-----------|
| OpenRouter | `https://openrouter.ai/api/v1` | `https://openrouter.ai/api/v1/chat/completions` |
| OpenAI | `https://api.openai.com/v1` | `https://api.openai.com/v1/chat/completions` |
| Self-hosted (vLLM) | `http://localhost:8000/v1` | `http://localhost:8000/v1/chat/completions` |
| Custom endpoint | `http://my-api.example.com/api/v2` | `http://my-api.example.com/api/v2/chat/completions` |

**Previous bug (now fixed):** The adapter used to append `/v1/chat/completions` to `base_url`. If the DB had `https://openrouter.ai/api/v1`, the final URL was `https://openrouter.ai/api/v1/v1/chat/completions` — doubled `/v1`, upstream returned 404. The fix was to change the adapter to append only `/chat/completions` (no `/v1` prefix) and require `base_url` to include the full API base path. This lets each provider declare its own path convention.

## Fix: update base_url in DB

If the provider's `base_url` is missing the API base path, update it:

```sql
UPDATE providers SET base_url = 'https://openrouter.ai/api/v1'
WHERE name = 'OpenRouter';
```

The provider form has a hint: "URL base de la API del proveedor, incluyendo el API base path (ej. /v1, /api/v1). Sin slash final." and placeholder `https://api.openai.com/v1`.

## Key tables

| Table | Purpose |
|-------|---------|
| `providers` | Provider config: name, base_url, status |
| `provider_credentials` | API keys per provider (api_key_encrypted, status) |
| `model_aliases` | Logical model names (name, display_name, market prices, context_window) |
| `alias_providers` | Alias ↔ provider mapping (provider_model, priority, weight, enabled) |
| `model_pricing` | Per-provider pricing for an alias_provider |
