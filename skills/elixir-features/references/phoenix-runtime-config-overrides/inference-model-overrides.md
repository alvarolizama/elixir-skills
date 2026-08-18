# my_app Inference Model Overrides — Worked Example

## CURRENT STATE (2026-08) — DB-only, provider-driven

The original plan below (env vars as defaults + "(env)" annotation) was
implemented, then Álvaro moved my_app to DB-only across two follow-up sessions.
**Do NOT revert to env-var model config.** Final code shape:

### `lib/my_app/inference/config.ex`

- `@default_models` map — DELETED (was Ornith-1.0-9B / Qwen3-Embedding /
  Qwen3-Reranker).
- `env_chat_model/0`, `env_embedding_model/0`, `env_rerank_model/0` — DELETED.
- `load_from_env/0` reads ONLY: `DRAN_INFERENCE_API_URL`, `_API_KEY`,
  `_TIMEOUT`, `_USE_RERANK`, `DRAN_EMBEDDING_BODY_LIMIT`. Model env vars are
  ignored (dead).
- Getters are DB-only with a config fallback that exists purely so tests
  (which inject models via `Application.put_env`) keep passing:

```elixir
def chat_model, do: model_or_setting("chat")
def embedding_model, do: model_or_setting("embedding")
def rerank_model, do: model_or_setting("rerank")

defp model_or_setting(key) do
  case my_app.Settings.get("model_#{key}") do
    nil -> get(:"#{key}_model")
    "" -> get(:"#{key}_model")
    model -> model
  end
rescue
  _ -> get(:"#{key}_model")
end
```

### `lib/dran_web/live/settings_live.ex` "Modelos" tab

- `model_purposes/0` returns 3-tuples `{key, label_fn, desc_fn}` — no env
  getter in the tuple anymore.
- `model_options(models_result, current)` = provider ids + current value
  appended if missing (provider dropped it). NO "(env)" suffix.
- Select `prompt` = `gettext("Selecciona un modelo")`.
- Per-purpose "Probar" button: colocated hook `.ModelTest` reads the sibling
  select (`data-model-select="models_<key>"`) at click time and
  `pushEventTo` → `handle_event("test_model", %{"key" => key, "model" => model})`.
  Runs in a `Task`, replies `{:model_test_done, key, result}` to
  `handle_info`, status lives in the `model_test_status` map assign.
  `run_model_test/2` does a real call per purpose: chat → `Client.chat(%{
  "model" => m, "messages" => [%{"role" => "user", "content" => "Say OK"}],
  "max_tokens" => 5})`; embedding → `Client.embeddings(m, ["test"])`; rerank →
  `Client.rerank(m, "test", ["test doc"])`. Returns `{:ok, latency_ms}` or
  `{:error, reason}`; `format_model_error/1` compacts reasons for the UI.
- **KeyError pitfall:** `model_test_status` must be declared as
  `attr :model_test_status, :map, required: true` on `models_section` AND
  passed at the call site (`<.models_section model_test_status={@model_test_status} />`)
  or rendering `/settings/models` crashes with KeyError. Add a render test
  that hits `/settings/models` — that's what caught it in prod.

### Tests

- `test/my_app/inference_test.exs` → `load_from_env` test asserts model keys
  are ABSENT even when the env vars are set ("ignores model env vars").
- `test/dran_web/live/settings_live_test.exs` → regression test renders
  `/settings/models` and asserts each `models_<purpose>` select + each
  `test_model_<purpose>` button + `data-model-key` attrs exist.

---

## ORIGINAL PLAN (2026-07-19) — historical, superseded

Session: 2026-07-19. Task: make my_app's 6 inference models
(chat/embedding/rerank/markitdown/asr/vision) web-configurable per purpose,
with env vars as defaults. Investigation complete; implementation not yet
landed (iteration budget consumed by a pathological tool-call loop — see
"Session failure mode" at the bottom).

## The 6 model getters

`lib/my_app/inference/config.ex` defines these getters, all delegating to
`get/1` (reads `Application.get_env(:my_app, :inference)`):

| Getter | Env var | Module default |
|---------|---------|----------------|
| `chat_model/0` | `DRAN_INFERENCE_CHAT_MODEL` | `Ornith-1.0-9B` |
| `embedding_model/0` | `DRAN_INFERENCE_EMBEDDING_MODEL` | `Qwen3-Embedding` |
| `rerank_model/0` | `DRAN_INFERENCE_RERANK_MODEL` | `Qwen3-Reranker` |
| `markitdown_model/0` | `DRAN_INFERENCE_MARKITDOWN_MODEL` | `MarkItDown` |
| `asr_model/0` | `DRAN_INFERENCE_ASR_MODEL` | `Qwen3-ASR` |
| `vision_model/0` | `DRAN_INFERENCE_VISION_MODEL` | `Ornith-1.0-9B` |

`asr_model` and `vision_model` have `|| @default_models.*` fallbacks in the
getter itself; the other 4 rely on `load_from_env/0` always supplying a
value (env var with module default as the env default).

## The Config helper pattern (to implement)

```elixir
@spec chat_model :: String.t() | nil
def chat_model, do: settings_model("model_chat") || get(:chat_model)

@spec embedding_model :: String.t()
def embedding_model, do: settings_model("model_embedding") || get(:embedding_model)

@spec rerank_model :: String.t()
def rerank_model, do: settings_model("model_rerank") || get(:rerank_model)

@spec markitdown_model :: String.t()
def markitdown_model, do: settings_model("model_markitdown") || get(:markitdown_model)

@spec asr_model :: String.t()
def asr_model, do: settings_model("model_asr") || get(:asr_model) || @default_models.asr

@spec vision_model :: String.t()
def vision_model, do: settings_model("model_vision") || get(:vision_model) || @default_models.vision

defp settings_model(key) do
  case settings_get(key) do
    nil -> nil
    "" -> nil
    value -> value
  end
end

defp settings_get(key) do
  try do
    my_app.Settings.get(key)
  rescue
    _ -> nil
  end
end
```

## The nil-as-delete verification (the key finding)

`my_app.Settings` (`lib/my_app/settings.ex`):

```elixir
def get(key) do
  case Repo.one(from s in "settings", where: s.key == ^key, select: s.value) do
    nil -> Map.get(@defaults, key)
    %{"value" => value} -> value    # matches with value = nil ✓
    value -> value
  end
end

def put(key, value) do
  # ... upserts %{"value" => value}
end
```

- `Settings.put("model_chat", nil)` stores `%{"value" => nil}`.
- `Settings.get("model_chat")` matches `%{"value" => value}` with `value = nil`,
  returns `nil`.
- Config helper's `settings_model("model_chat")` returns `nil` (via the
  `nil -> nil` clause), so `|| get(:chat_model)` falls back to env.
- **No `delete/1` function needed.** The `is_map` guard in `Settings.all/0`
  only affects `all/0`, not `get/1`.

## The LiveView "Modelos" section (to implement)

`lib/dran_web/live/settings_live.ex` currently has:
- `brain_tuning_section/1` — editable, `phx-submit="save"`.
- Read-only "Entorno" sections (Inference API, Agents, Firecrawl, Uploads).

Add `models_section/1` between them, with its own `<.form phx-submit="save_models">`.

### mount: fetch available models once

```elixir
def mount(_params, session, socket) do
  {socket, _} = Auth.assign_to_socket(socket, session)

  available_models =
    case my_app.Inference.Client.models() do
      {:ok, models} -> Enum.map(models, & &1["id"])
      {:error, _} -> []
    end

  socket =
    socket
    |> assign(active_nav: "settings", page_title: gettext("Settings"))
    |> assign(available_models: available_models)
    |> assign_brain_form()

  {:ok, socket}
end
```

### save_models handler

```elixir
@model_keys ~w(model_chat model_embedding model_rerank model_markitdown model_asr model_vision)

@impl true
def handle_event("save_models", %{"models" => params}, socket) do
  for key <- @model_keys do
    value = Map.get(params, key, "")
    normalized = if value == "", do: nil, else: value
    Settings.put(key, normalized)
  end

  {:noreply, put_flash(socket, :info, gettext("Models saved"))}
end
```

### Section rendering

- Header: `gettext("Modelos")` with caption explaining these override env
  defaults per purpose.
- If `Config.enabled?() == false`: render a note instead of the form.
- If `@available_models == []`: render text inputs (API unreachable).
- Else: 6 selects, each with:
  - First option `value=""` labeled `gettext("Por defecto (%{model})", model: Config.<purpose>_model())`
  - Other options: model ids from `@available_models`.
  - Selected value: `Settings.get(key) || ""`.
- Plain-language caption under each select.

## New gettext msgids (exact strings)

- `"Modelos"`
- `"Override the environment-default inference models per purpose."` (caption)
- `"Chat / Agentes"`
- `"Embeddings"`
- `"Re-ranking"`
- `"Extracción de documentos"`
- `"Transcripción de audio"`
- `"Visión"`
- `"Por defecto (%{model})"` (with `%{model}` interpolation)
- `"No se pudo consultar el servidor de inferencia — escribe el nombre del modelo manualmente."`
- Per-purpose captions (6 strings), e.g.:
  `"Model used by agents, chat RAG, and enrichment tasks."`
- `"Inference is not configured. Set DRAN_INFERENCE_API_URL to enable model overrides."` (note when disabled)
- `"Models saved"` (flash)

## Tests (to implement)

### Config fallback + override

`test/my_app/inference/config_test.exs` (new file, `my_app.DataCase`):

```elixir
defmodule my_app.Inference.ConfigTest do
  use my_app.DataCase, async: true

  alias my_app.Inference.Config
  alias my_app.Settings

  setup do
    original = Application.get_env(:my_app, :inference)
    Application.put_env(:my_app, :inference,
      base_url: "http://localhost:8000/v1",
      chat_model: "EnvDefault-Chat",
      embedding_model: "EnvDefault-Embed"
    )
    on_exit(fn ->
      if original, do: Application.put_env(:my_app, :inference, original),
        else: Application.delete_env(:my_app, :inference)
    end)
    :ok
  end

  test "falls back to env default when no Settings override" do
    assert Config.chat_model() == "EnvDefault-Chat"
  end

  test "returns the override when Settings has one" do
    Settings.put("model_chat", "Override-Chat")
    assert Config.chat_model() == "Override-Chat"
  end

  test "nil override falls back to env default" do
    Settings.put("model_chat", "Override-Chat")
    Settings.put("model_chat", nil)
    assert Config.chat_model() == "EnvDefault-Chat"
  end
end
```

### Settings page renders the section

Extend `test/dran_web/live/settings_live_test.exs`:

```elixir
test "renders the Modelos section", %{conn: conn} do
  {:ok, _view, html} = live(conn, ~p"/settings")
  assert html =~ t("Modelos")
end
```

## Existing patterns referenced

- `my_app.Settings` (`lib/my_app/settings.ex`) — key-value JSONB settings table,
  `get/1`/`put/2`/`all/0`. No `delete/1`.
- `my_app.Inference.Client.models/0` — returns `{:ok, [map]}` (each map has
  `"id"`) or `{:error, term}`.
- `DranWeb.SettingsLive` — existing `brain_tuning_section/1` is the template
  for adding a new editable section (own `<.form>`, own `phx-submit`).
- `my_app.DataCase` — SQL sandbox, `async: true` for DB tests.
- `DranWeb.ConnCase` — `async: false`, session setup via `Plug.Test`.
- `t/1` helper in LiveView tests: `Gettext.gettext(DranWeb.Gettext, msgid)`
  because default locale is `es`.

## Session failure mode (process lesson)

The session hit the tool-call iteration limit because of a pathological loop:
the same `grep` command was re-issued ~30 times with identical output. Root
cause: the agent kept re-running a search that had already returned its
answer, never advancing to the next step (writing the code). The
investigation was complete after ~10 tool calls; the remaining ~30 were
wasted on duplicate greps.

**Lesson for future sessions:** after a `search_files` or `grep` returns
results, either (a) act on those results (read_file, patch, write_file) or
(b) move to the next investigation step. Never re-issue the same query
expecting different output. If you find yourself re-running a command, stop
and state what you've found — a summary with a plan is more useful than
another identical tool call. The iteration budget is finite; treat each tool
call as consuming it.
