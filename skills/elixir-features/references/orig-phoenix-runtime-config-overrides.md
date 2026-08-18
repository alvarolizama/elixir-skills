---
name: phoenix-runtime-config-overrides
author: Álvaro Lizama
description: Make Phoenix/Elixir application configuration web-editable at runtime — DB-backed settings override env-var defaults, with nil-as-fallback semantics, try/rescue for DB-not-up contexts, and LiveView form sections per config group. Covers the Config helper pattern, the nil-as-delete trick, select-with-fallback rendering, and testing with SQL sandbox.
---

# Phoenix Runtime Config Overrides

When a Phoenix app loads configuration from environment variables at boot
(`config/runtime.exs`) but operators need to tune some of those values at
runtime without redeploying, the pattern is: DB-backed settings table
overrides env defaults, with the Config module checking the DB first and
falling back to the env value.

## When to use

- User asks to "make X web-configurable" or "add a settings page for Y"
- A config value (model name, threshold, limit, toggle) is loaded from an
  env var but should be editable at runtime
- The app already has a key-value settings table (JSONB `settings` table
  accessed via `Repo.one`/`Repo.insert_all` with `on_conflict: :key`)
- User wants per-purpose overrides (e.g. different chat model vs embedding
  model) with env vars as defaults

## DB-only variant (Álvaro's MyApp direction, 2026-08) — NO env defaults

The env-default-override pattern above is the general shape, but Álvaro
progressively moved MyApp's model config to **DB-only** over three iterations.
Respect the final state unless he asks otherwise:

1. **Phase 1 (2026-07):** DB overrides env vars; env vars have hardcoded module
   defaults (e.g. `Ornith-1.0-9B`).
2. **Phase 2 (2026-08):** hardcoded `@default_models` removed → env vars were
   the only fallback.
3. **Phase 3 (2026-08, explicit direction: "los modelos no se carguen por .env
   solo del model list del provider"):** model env vars removed ENTIRELY from
   `load_from_env/0` (`DRAN_INFERENCE_EMBEDDING_MODEL` / `_RERANK_MODEL` /
   `_CHAT_MODEL` are dead). Models come exclusively from the provider's
   `/v1/models` list, selected in Settings, stored in the Settings DB. No env
   default, no "(env)" annotation, no "Por defecto (env)" prompt.

**Why:** Álvaro wants model config to never diverge from what the provider
actually serves. Hardcoded/env model names go stale when the provider changes
its model list.

### DB-only getter shape (Settings first, config fallback only for tests)

```elixir
def chat_model, do: model_or_setting("chat")

defp model_or_setting(key) do
  case MyApp.Settings.get("model_#{key}") do
    nil -> get(:"#{key}_model")   # config fallback: tests only
    "" -> get(:"#{key}_model")
    model -> model
  end
rescue
  _ -> get(:"#{key}_model")
end
```

- `load_from_env/0` no longer emits model keys, so in prod the config fallback
  is nil and Settings DB is the sole source.
- The `get(:"#{key}_model")` fallback exists ONLY so tests that inject models
  via `Application.put_env` keep passing. Do NOT restore env-var loading.

### UI: provider-driven select, no env prompt

- `model_options/2` = fetched provider ids + current saved value appended if
  the provider dropped it (so the effective selection stays visible). NO
  "(env)" suffix.
- Select `prompt` = `gettext("Selecciona un modelo")` — never "Por defecto
  (env)".
- Per-purpose "Probar" button (colocated hook reads the sibling select at
  click time, see `phoenix-liveview-debugging` → "Colocated hook for reading
  sibling form values") runs a real chat/embed/rerank call against the
  selected model and shows OK + latency or error inline. Server side:
  `handle_event("test_model", %{"key" => key, "model" => model})` runs in a
  `Task`, replies `{:model_test_done, key, {:ok, latency_ms} | {:error, reason}}`.

Worked example with the final MyApp code shape:
`references/MyApp-inference-model-overrides.md` (CURRENT STATE section at top).

## The Config helper pattern

For each configurable value, the getter checks the DB first, then falls back
to the env-based value:

```elixir
# lib/MyApp/inference/config.ex

@spec chat_model :: String.t() | nil
def chat_model, do: settings_model("model_chat") || get(:chat_model)

@spec embedding_model :: String.t()
def embedding_model, do: settings_model("model_embedding") || get(:embedding_model)

# ... one per purpose

defp settings_model(key) do
  case settings_get(key) do
    nil -> nil
    "" -> nil
    value -> value
  end
end

defp settings_get(key) do
  try do
    MyApp.Settings.get(key)
  rescue
    _ -> nil
  end
end
```

**Why `try/rescue`:** `MyApp.Settings` (or equivalent) is plain Ecto — no
GenServer. In test contexts where the DB isn't up, or during `mix run` without
the repo started, `Settings.get/1` raises. The rescue returns nil, which the
`|| get(env_key)` treats as "no override, use env default." This is pragmatic
and matches how other modules in the codebase handle DB-not-up (check for
existing `try/rescue` patterns in `lib/` — e.g. `firecrawl.ex`).

**Why `nil ||` and not `||` with a default in the helper:** The env-based
`get/1` already handles module defaults (e.g. `get(:asr_model) ||
@default_models.asr`). Keeping the `||` at the getter level preserves the
existing fallback chain: DB override → env value → module default.

## The nil-as-delete trick (no `delete/1` needed)

When the user selects "Por defecto" (empty value `""`) in the settings form,
the save handler should remove the override. The cleanest way:

```elixir
# In the save handler:
for key <- @model_keys do
  value = Map.get(params, key, "")
  Settings.put(key, normalize_value(value))
end
```

Where `normalize_value("")` returns `nil`. Then `Settings.put(key, nil)`
stores `%{"value" => nil}` in the JSONB column, and `Settings.get/1` returns
`nil` via the `%{"value" => value}` clause — which the Config helper treats
as "no override, fall back to env."

**Verification that this is safe:**
```elixir
# Settings.get/1 pattern match:
case Repo.one(...) do
  nil -> Map.get(@defaults, key)        # no row → default
  %{\"value\" => value} -> value        # row with nil value → returns nil ✓
  value -> value                        # bare value (legacy)
end
```

The `%{"value" => nil}` row matches the second clause with `value = nil`. The
`is_map` guard in `Settings.all/0` (if present) only affects `all/0`, not
`get/1`, so it won't break. **No `delete/1` function needs to be added.**

If the settings module's `get/1` has a stricter pattern match (e.g.
`%{"value" => value} when not is_nil(value)`), then `put(key, nil)` would
fall through to the default. In that case, add a `delete/1`:

```elixir
def delete(key) do
  Repo.delete_all(from s in "settings", where: s.key == ^key)
end
```

And use it in the save handler when value is `""`/`nil`.

## The LiveView settings section pattern

Each config group gets its own `<.form>` with its own `phx-submit` event,
separate from other sections on the same settings page:

```elixir
# lib/my_app_web/live/settings_live.ex

@model_keys ~w(model_chat model_embedding model_rerank model_markitdown model_asr model_vision)

@impl true
def mount(_params, session, socket) do
  {socket, _} = Auth.assign_to_socket(socket, session)

  available_models =
    case MyApp.Inference.Client.models() do
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

### Rendering: select when API reachable, text input when not

```heex
<.models_section
  available_models={@available_models}
  config={@config}
/>
```

```elixir
attr :available_models, :list, required: true

defp models_section(assigns) do
  ~H\"\"\"
  <section class="surface-2 rounded-2xl overflow-hidden">
    <header>...</header>

    <.form for={%{}} id="models-form" phx-submit="save_models" class="px-5 py-5 space-y-5">
      <%= if @available_models == [] do %>
        <p class="text-caption">
          {gettext("No se pudo consultar el servidor de inferencia — escribe el nombre del modelo manualmente.")}
        </p>
        <!-- render text inputs instead of selects -->
      <% else %>
        <!-- render selects with @available_models as options -->
      <% end %>
    </.form>
  </section>
  \"\"\"
end
```

**Key points:**
- Fetch `available_models` ONCE in `mount`, assign to socket. Don't re-fetch
  on every render — it's an HTTP call to the inference server.
- On `{:error, _}`, assign `[]` and render text inputs as fallback.
- First option in each select: `value=""` labeled
  `gettext("Por defecto (%{model})", model: <env default>)` where the env
  default is the current `Config.<purpose>_model()` value.
- Selected value = current override from `Settings.get(key)` (`""` when nil).
- If the feature is disabled (`Config.enabled?() == false`), render a note
  instead of the form.

## Testing

### Config fallback + override (DataCase, DB-backed)

```elixir
# test/MyApp/inference/config_test.exs
defmodule MyApp.Inference.ConfigTest do
  use MyApp.DataCase, async: true

  alias MyApp.Inference.Config
  alias MyApp.Settings

  setup do
    original = Application.get_env(:MyApp, :inference)
    Application.put_env(:MyApp, :inference,
      base_url: "http://localhost:8000/v1",
      chat_model: "EnvDefault-Chat",
      embedding_model: "EnvDefault-Embed"
    )

    on_exit(fn ->
      if original, do: Application.put_env(:MyApp, :inference, original),
        else: Application.delete_env(:MyApp, :inference)
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
    Settings.put("model_chat", nil)  # "remove" the override
    assert Config.chat_model() == "EnvDefault-Chat"
  end
end
```

### Settings page renders the section (ConnCase, LiveView)

```elixir
# test/my_app_web/live/settings_live_test.exs
test "renders the Modelos section", %{conn: conn} do
  {:ok, _view, html} = live(conn, ~p"/settings")
  assert html =~ t("Modelos")
end
```

Use the `t/1` helper (`Gettext.gettext(MyAppWeb.Gettext, msgid)`) for
assertions because the default locale may not be English.

## Pitfalls

### Don't re-fetch available models on every render
`Client.models()` is an HTTP call. Fetch once in `mount`, assign to socket.
If the list needs refreshing, add a manual "refresh" button with its own
event handler — never fetch in `render/1`.

### gettext msgids must be literal strings
`gettext("Por defecto (%{model})", model: value)` works because the msgid is
a compile-time literal. Don't build the msgid dynamically —
`gettext("Modelos" <> suffix)` won't be extracted by `mix gettext.extract`.

### The `""` vs `nil` distinction in form params
HTML forms send `""` for empty selects, not `nil`. The save handler must
normalize: `if value == "", do: nil, else: value` before calling
`Settings.put/2`. Without this, `Settings.put(key, "")` stores
`%{"value" => ""}`, and `get/1` returns `""` — which the Config helper's
`settings_model/1` must treat as nil (check for both `nil` and `""`).

### SQL sandbox and Settings in LiveView tests
`MyAppWeb.ConnCase` (or equivalent) uses `async: false` and shared sandbox.
`Settings.put/2` in a test writes to the sandbox DB; the LiveView's `mount`
reads from the same sandbox. This works because the test process owns the
sandbox. If you see "owner timed out" errors, the LiveView is trying to
query outside the owning process — use `allow/3` or keep `async: false`.

### Don't add a `delete/1` unless `get/1` rejects nil
Check the `get/1` pattern match first. If it matches
`%{"value" => value}` without a `not is_nil(value)` guard, `put(key, nil)`
is sufficient. Adding an unnecessary `delete/1` adds code surface for no
benefit.

### Per-purpose metadata tables with functions must be FUNCTIONS, not module attributes

When the settings UI needs a per-purpose spec list (settings key, env getter,
label fn, description fn), the natural shape contains anonymous functions
(`fn -> gettext("...") end`) — and **anonymous functions cannot be escaped
into module attributes**. This fails to compile:

```elixir
# ❌ CompileError: cannot inject attribute @model_purposes into function/macro
#    because cannot escape #Function<...>
@model_purposes [
  {"model_chat", &Config.env_chat_model/0,
   fn -> gettext("Chat / agentes") end,
   fn -> gettext("Model used for chat completions...") end},
  ...
]
```

Remote captures (`&Config.env_chat_model/0`) ARE escapable; anonymous fns are
NOT. Fix: define it as a private function instead:

```elixir
# ✅
defp model_purposes do
  [
    {"model_chat", &Config.env_chat_model/0,
     fn -> gettext("Chat / agentes") end,
     fn -> gettext("Model used for chat completions...") end},
    ...
  ]
end
```

Then replace every `@model_purposes` with `model_purposes()` (in mount,
handle_event, and the HEEx `for` comprehension). A subagent shipped exactly
this bug (dead before commit) — the parent's compile caught it; cost was 3
patches. Tell subagents up front: "purpose tables with gettext fns go in a
defp, never a module attribute."

### `&get(:literal_atom)` is NOT a valid capture — needs a fn wrapper

Another compile error from the same subagent: `&get(:embedding_model)` looks
like a capture but isn't (a capture can't contain a literal argument). It
fails with `invalid args for &`. The Config helper pattern must wrap env
lookups in a fn:

```elixir
# ❌ def chat_model, do: model_or_env("chat", &get(:chat_model))
# ✅
def chat_model, do: model_or_env("chat", fn -> get(:chat_model) end)
```

### Expose env-only getters for the settings UI ("(env)" annotation)

**MyApp-specific reversal (2026-08):** this pattern was built, then Álvaro
rejected it — MyApp's model config is now DB-only, env-only getters were
deleted, and the "(env)" annotation is gone. Only use this pattern when env
defaults genuinely exist AND the user wants them surfaced. If the user says
models must come from the provider list only, skip it entirely.

For apps that still have env defaults, the annotation works like this:

```elixir
@spec env_chat_model :: String.t() | nil
def env_chat_model, do: get(:chat_model)
```

The UI then renders the option label as `"#{model} (env)"` when it matches
`env_fn.()`, and the effective-value computation is
`Settings.get(key) || env_fn.()`. This keeps the "Por defecto (env)" empty
option honest — the user always sees what they'll fall back to.

## References

- (project-specific reference removed) — worked example from the
  MyApp codebase: the 6 model getters (chat/embedding/rerank/markitdown/asr/
  vision), the `settings_live.ex` "Modelos" section with 6 selects, the
  gettext msgids introduced, and the test structure. Includes the exact
  Config helper pattern and the nil-as-delete verification.
