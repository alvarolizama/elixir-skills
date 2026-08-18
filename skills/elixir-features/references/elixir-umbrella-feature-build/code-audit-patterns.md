# Code Audit Patterns — Money Bot Umbrella

Concrete findings from static reviews of a 3-app Elixir/Phoenix umbrella
(`:core` data, `:harness` business logic, `:admin` LiveView UI). These patterns
recur in Phoenix umbrella projects — use as a checklist when auditing similar
codebases.

## 1. Silent JS Hook Failure (CRITICAL)

**Symptom:** A modal or interactive element doesn't work, but there's no error
in the console, no compile warning, no test failure.

**Root cause:** `phx-hook="Modal"` in HEEx, but the hook is never registered
in `app.js`:

```javascript
// app.js
import {hooks as colocatedHooks} from "phoenix-colocated/admin"
// phoenix-colocated exports: { hooks: {} }  ← EMPTY

const hooks = {
  ...colocatedHooks,
  Scroll: { /* ... */ }
  // Modal: { ... }  ← MISSING
}
```

**Fix:** Define the hook and add it to the `hooks` map:

```javascript
const Modal = {
  mounted() {
    this.el.addEventListener("data-close", () => this.el.close())
    this.handleOpen()
  },
  updated() {
    this.handleOpen()
  },
  destroyed() {
    if (this.el.open) {
      this.el.close()
    }
  },
  handleOpen() {
    if (this.el.dataset.open === "true") {
      this.el.showModal()
    } else {
      this.el.close()
    }
  }
}

const hooks = {
  ...colocatedHooks,
  Scroll: { /* ... */ },
  Modal
}
```

**Detection:** Search for all `phx-hook="X"` in HEEx, then verify each `X`
exists in the `hooks` object. `phoenix-colocated` exports `{}` by default —
do not assume it is already populated.

## 2. LiveView JS: `JS.exec` vs `JS.dispatch` for Custom Events (CRITICAL)

**Symptom:** A button that should trigger a JS hook action (e.g., close a
modal) does nothing; no error, no console trace.

**Root cause:** `JS.exec("data-close", to: "#modal")` executes a `phx-*`
binding named `data-close` on the target. If the hook listens via
`addEventListener("data-close", ...)`, the event never arrives.

```elixir
# ❌ Wrong — tries to execute a phx- binding that doesn't exist
<button phx-click={JS.exec("data-close", to: "##{@id}")}>Close</button>

# ✅ Correct — dispatches a custom DOM event the hook listens for
<button phx-click={JS.dispatch("data-close", to: "##{@id}")}>Close</button>
```

**Rule of thumb:** Use `JS.exec` only when the target has a `phx-*` attribute
you want to trigger (e.g. `phx-click`, `phx-submit`). Use `JS.dispatch` for
custom DOM events consumed by JS hooks or external scripts.

## 3. Router Route Ordering With `:id` Segments (CRITICAL)

**Symptom:** A specific route like `/agents/:id/chat` never matches — the
request is captured by a broader `/agents/:id` route defined earlier.

**Root cause:** Phoenix matches routes in definition order. A bare `:id` route
will grab any path with one more segment, including `/agents/123/chat`.

```elixir
# ❌ Broken — /agents/:id/chat never reached
live "/agents/:id/edit", AgentLive.Edit
live "/agents/:id", AgentLive.Show
live "/agents/:id/chat", AgentLive.Chat
```

**Fix:** Order from most specific to least specific:

```elixir
# ✅ Correct
live "/agents/:id/chat", AgentLive.Chat, :chat
live "/agents/:id/edit", AgentLive.Edit, :edit
live "/agents/:id", AgentLive.Show, :show
```

**Detection:** `grep -n 'live.*:id' lib/admin/router.ex` and verify that any
route with segments after `:id` appears before the bare `:id` route.

## 4. Alias Shadowing in Umbrella Apps (CRITICAL)

**Symptom:** Code works by accident — a function call resolves to the wrong
module but happens to have a compatible signature. Refactors later blow up
silently.

**Root cause:** Two umbrella apps define modules with the same name. Sequential
`alias` calls silently overwrite each other.

```elixir
# ❌ Dangerous — second Message overwrites first
alias Core.Agents.{Agent, Session, Message}
alias Harness.{Message, SystemPrompt, Vectorizer}

# Harness.Message is now the binding for `Message`, while Core.Agents.Message
# was shadowed the moment the second alias evaluated.
```

**Fix:** Remove the unused alias, or alias to distinct names:

```elixir
# ✅ Option A: remove unused Core.Agents.Message
alias Core.Agents.{Agent, Session}
alias Harness.{Message, SystemPrompt, Vectorizer}

# ✅ Option B: explicit alias
alias Core.Agents.Message, as: CoreMessage
alias Harness.Message
```

**Detection:** Read alias blocks top-to-bottom. If a bare module name appears
in multiple `alias` lines, one of them is shadowing the others.

## 5. OpenAI API Content Shape Mismatch (CRITICAL)

**Symptom:** Chat completions fail or produce empty responses when hitting a
real OpenAI-compatible endpoint, but unit tests pass because they don't
validate the shape sent to the API.

**Root cause:** Message content stored as a map `%{"text" => "..."}` in the
DB, then passed directly to the API without unwrapping:

```elixir
# harness/message.ex — BUG: sends map as content
def to_api_format(%Message{} = msg) do
  %{"role" => msg.role, "content" => msg.content}  # map, not string!
end

# harness/agent.ex — BUG: passes map to Message.user
Message.user(user_message.content)  # %{"text" => "..."} not a string
```

**Fix:** Unwrap in both places:

```elixir
# harness/message.ex
def to_api_format(%Message{} = msg) do
  %{"role" => msg.role, "content" => Message.text(msg)}
end

# harness/agent.ex
] ++ [Message.user(Harness.Message.text(user_message))]
```

**Lesson:** When a schema field is `:map` but an external API expects a string,
the boundary conversion must happen explicitly. Tests that mock the API with
`Req.Test` won't catch this because they match on the URL, not the body shape.

## 6. Ignored Opts in Business Logic (CRITICAL)

**Symptom:** Agent `steps` and `retries` config fields exist in the DB and UI,
but the inference runner never uses them.

**Root cause:** Function accepts `opts` keyword list but pattern-matches
nothing from it:

```elixir
# harness/inference/chat.ex
def call(client, model, messages, opts \\ []) do
  # opts[:steps] and opts[:retries] are NEVER read
  body = %{model: model, messages: messages}
  # ...
end
```

**Fix:** Implement the behavior or explicitly mark future-use options to avoid
warnings and silent feature gaps:

```elixir
def call(client, model, messages, opts \\ []) do
  retries = Keyword.get(opts, :retries, 0)
  _steps = Keyword.get(opts, :steps, 1)  # reserved for future tool-calling loop
  do_call(client, model, messages, retries)
end
```

**Detection:** Grep for function heads that accept `opts \\ []` and trace
whether each option is consumed in the body.

## 7. Task.async Without Supervision (ROBUSTNESS)

**Symptom:** A LiveView process dies when an async task raises, disconnecting
the WebSocket.

```elixir
# chat_live.ex
task = Task.async(fn -> AgentRunner.chat(session, agent, text) end)
```

If `AgentRunner.chat` raises (e.g. DB constraint, timeout), the linked task
kills the LiveView. `handle_info({ref, {:error, reason}}, ...)` only handles
`{:error, _}` returns, not actual exceptions.

**Fix:** Use `Task.Supervisor.async_nolink/3`:

```elixir
# In application.ex children:
{Task.Supervisor, name: Admin.TaskSupervisor}

# In LiveView:
Task.Supervisor.async_nolink(Admin.TaskSupervisor, fn ->
  AgentRunner.chat(session, agent, text)
end)
```

The `handle_info({ref, result}, ...)` clause still works for normal `{:ok, _}` /
`{:error, _}` returns. Add a `handle_info({:DOWN, ref, :process, _pid, reason}, socket)`
clause to catch crashes — `async_nolink` sends `{:DOWN, ...}` (a monitor message),
not `{:EXIT, ...}` (a link message). Clean up `:loading` and `:task` in the DOWN handler.

## 8. Req.Test Plug URL Warnings (NOISE)

**Symptom:** Test output has warnings like:
`"the URI path used in plug tests must start with /, got: models"`

**Root cause:** Production client uses relative URLs without leading slash:

```elixir
Req.get(client, url: "models")         # should be "/models"
Req.post(client, url: "chat/completions")  # should be "/chat/completions"
```

**Fix:** Prepend `/` in production code:

```elixir
Req.get(client, url: "/models")
Req.post(client, url: "/chat/completions")
Req.post(client, url: "/embeddings")
```

## 9. String Operations on Potentially Empty Strings (ROBUSTNESS)

**Symptom:** `FunctionClauseError` on `String.upcase(nil)` when a role or
title is an empty string.

```elixir
# ❌ Crashes on empty string
defp avatar_letter(role) when is_binary(role) do
  role |> String.first() |> String.upcase()
end
# String.first("") == nil → String.upcase(nil) → ** FunctionClauseError
```

**Fix:** Handle the `nil` return explicitly:

```elixir
# ✅ Safe
defp avatar_letter("user"), do: "U"
defp avatar_letter("assistant"), do: "A"

defp avatar_letter(role) when is_binary(role) do
  case String.first(role) do
    nil -> "?"
    char -> String.upcase(char)
  end
end

defp avatar_letter(_), do: "?"
```

## 10. Fragile URL-Decoded Params Parsing (CODE SMELL)

**Symptom:** Wizard step 2 tries to parse step 1 params from URL query strings
by decoding keys that contain `=`.

```elixir
# new_models_live.ex — FRAGILE
Enum.find_value(%{}, fn key ->
  with true <- is_binary(key) and String.contains?(key, "="),
       decoded when is_map(decoded) <- URI.decode_query(key) do
    Map.take(decoded, ["title", "api_inference_url", "api_inference_token"])
  end
end)
```

**Fix:** Phoenix's verified routes pass query params as a flat map. Read them
directly:

```elixir
defp step1_params(params) do
  Map.take(params, ["title", "api_inference_url", "api_inference_token"])
end
```

If params arrive garbled, the issue is in how they were encoded — not in
needing a decoder in the receiver.

## 11. JSONB Config Partial-Map Data Loss (CRITICAL)

**Symptom:** A LiveView form with `phx-change="auto_save"` contains inputs for
nested JSONB config fields (e.g. `agent[memory_config][message_window]`). When
any field changes, the entire config map is replaced with only the fields
present in the form submission — losing `enabled`, `summary_model`, and every
other key that wasn't in that specific form payload.

**Root cause:** Ecto's `cast/3` replaces the entire `:map` field value. If the
incoming params contain `%{"memory_config" => %{"message_window" => "30"}}`,
the stored map becomes just that — `enabled` and `summary_model` vanish.

**Fix:** Deep-merge incoming partial config maps with the existing config before
passing to `update_agent`:

```elixir
def handle_event("auto_save", %{"agent" => params}, socket) do
  params = merge_tool_configs(socket.assigns.agent, params)
  # ... proceed with update
end

defp merge_tool_configs(agent, params) do
  ~w(memory_config brain_config mcp_config)a
  |> Enum.reduce(params, fn field, acc ->
    incoming = Map.get(params, to_string(field))

    case incoming do
      incoming when is_map(incoming) ->
        existing = Map.get(agent, field) || %{}
        merged = deep_merge_maps(existing, incoming)
        Map.put(acc, to_string(field), merged)

      _ ->
        acc
    end
  end)
end

defp deep_merge_maps(existing, incoming) when is_map(existing) and is_map(incoming) do
  Map.merge(existing, incoming, fn _k, v1, v2 ->
    if is_map(v1) and is_map(v2), do: deep_merge_maps(v1, v2), else: v2
  end)
end

defp deep_merge_maps(_existing, incoming), do: incoming
```

**Detection:** Any LiveView form that binds `phx-change` to inputs for nested
JSONB config fields. Toggle switches that use dedicated `phx-click` handlers
(see `references/jsonb-config-and-prompt-extension.md`) bypass this problem
because they construct the full map in the handler.

## 12. MCP Tool Name Parsing Crash (CRITICAL)

**Symptom:** Clicking a tool toggle checkbox in the MCP panel crashes the
LiveView with `MatchError` — `String.split(name, "/", parts: 2)` returns a
list of length 1 because the tool name doesn't contain `/`.

**Root cause:** The handler assumed tool names from MCP discovery include a
`server/tool` format. They don't — `Harness.MCP.Client.list_tools/1` returns
tools with a simple `name` field (e.g. `"search_repos"`), not a composite key.

**Fix:** Pass the server name separately via `phx-value-server` and use
`params["name"]` directly as the tool name:

```elixir
# In the HEEx template:
phx-value-name={tool.name}
phx-value-server={@discovering_server || @discovered_tools_server}

# In the handler:
def handle_event("toggle_mcp_tool", params, socket) do
  tool_name = params["name"]
  server_name = params["server"]
  # ... use tool_name and server_name directly, no String.split
end
```

**Gotcha:** `@discovering_server` is set to `nil` after discovery completes.
Store the server name in a separate `discovered_tools_server` assign that
persists so toggles after discovery still have the correct server name.

## 13. Unsafe Runtime Side-Effects in Chat Pipeline (MODERATE)

**Symptom:** A chat call fails after the assistant message has already been
stored, because an optional post-processing step (memory summarization, brain
retrieval, vectorization) raised an exception.

**Root cause:** `Memory.summarize_session/2` or `Brain.retrieve/2` can raise
on network/DB failures. If called directly inside `chat/3`, the exception
propagates even though the primary work (storing user + assistant messages) is
complete.

**Fix:** Wrap optional side-effects in `try/rescue` so failures are logged but
never break the primary flow:

```elixir
# Memory summarization — fire and forget
if Memory.enabled?(agent) do
  try do
    Memory.summarize_session(session, agent)
  rescue
    _ -> :ok
  end
end

# Brain retrieval — degrade gracefully to no context
defp safe_brain_retrieve(agent, query) do
  try do
    Harness.Agent.Brain.retrieve(agent, query)
  rescue
    _ -> {:ok, nil}
  catch
    _, _ -> {:ok, nil}
  end
end
```

## 14. MCP SSE Parsing Robustness (MODERATE)

**Symptom:** `extract_tools_from_sse/1` crashes on malformed SSE payloads or
when `Jason.decode!/1` encounters invalid JSON.

**Root cause:** Using `Jason.decode!` (bang) on untrusted SSE data, and fragile
`chunk_every(2, 1)` pattern matching that assumes specific line pairing.

**Fix:** Use safe `Jason.decode/1`, filter by `String.starts_with?/2`, and use
`get_in/2` for nil-safe nested access:

```elixir
defp extract_tools_from_sse(body) do
  payloads =
    body
    |> String.split("\n")
    |> Enum.filter(&String.starts_with?(&1, "data: "))
    |> Enum.map(&String.trim_leading(&1, "data: "))
    |> Enum.flat_map(fn payload ->
      case Jason.decode(payload) do
        {:ok, decoded} -> [decoded]
        _ -> []
      end
    end)

  case Enum.find(payloads, &(get_in(&1, ["result", "tools"]) != nil)) do
    nil -> :not_found
    rpc -> {:ok, get_in(rpc, ["result", "tools"])}
  end
end
```

## 15. LiveView handle_event Assigns Over-Matching (CRITICAL)

**Symptom:** A `handle_event` clause crashes with `CaseClauseError` when an
assign that was assumed present is actually `nil`. The catch-all fallback
clause never fires, so the user sees a LiveView crash/reconnect instead of
graceful degradation.

**Root cause:** Matching on a nested assign key in the *specific* clause head
requires that key to be present and match. If `context` is `nil`, the entire
clause head fails to match, and Elixir moves to the next clause — but the
catch-all (`handle_event("field_change", _params, socket)`) matches *any*
params, so it handles the event. Wait — no. The trap is subtler: the specific
clause matches on the *event name and params shape* first, then the assigns
guard. When params match but assigns don't, the clause fails. If there's a
*less specific* clause below it that *does* match the params shape with looser
assigns, that's the one that should catch it. But if the catch-all uses
`_params` (no params destructuring), it still matches. The real problem arises
when the specific clause is the *only* one that matches the event+params shape,
so the fallback `_params` clause catches it — but by then the developer's
intent (slug rename logic) is silently skipped. Worse: if the match is on a
*struct pattern* like `%Page{}` that also fails, you get a crash, not a
fallback.

The concrete crash from the my_app codebase:

```elixir
# ❌ Crashes when socket.assigns.context is nil
def handle_event(
      "field_change",
      %{"page" => %{"slug" => new_slug}},
      %{assigns: %{page: %Page{} = page, context: %{id: context_id}}} = socket
    ) do
  # ... uses context_id ...
end

def handle_event("field_change", _params, socket) do
  {:noreply, socket}
end
```

When `context` is `nil`, the first clause head fails to match on
`context: %{id: context_id}`. The fallback fires, silently dropping the slug
rename — or if the assign struct pattern itself fails, the LiveView crashes.

**Fix:** Match only the *minimum required* assigns in the clause head. Fetch
optional/nullable assigns inside the body via a nil-safe helper:

```elixir
# ✅ Safe — clause head matches only what's strictly required
def handle_event(
      "field_change",
      %{"page" => %{"slug" => new_slug}},
      %{assigns: %{page: %Page{} = page}} = socket
    ) do
  context_id = context_id(socket)

  if is_nil(context_id) do
    {:noreply, put_flash(socket, :error, "No context available for slug rename.")}
  else
    new_slug = String.trim(new_slug)
    # ... existing body logic unchanged ...
  end
end

# Nil-safe helper (already present in the module)
defp context_id(socket) do
  case socket.assigns[:context] do
    %{id: id} -> id
    _ -> nil
  end
end
```

**Why not just add `context: nil` to the match?** You could add a second
specific clause with `context: nil`, but that duplicates the body logic or
requires extracting a shared private function. The nil-safe-helper approach is
cleaner: one clause, one body, one guard.

**Rule:** In LiveView `handle_event` clause heads, match only assigns that are
*structurally required* for the event to make sense (e.g. `page: %Page{} = page`
for an edit handler). Any assign that can legitimately be `nil` at runtime
should be fetched in the body via `socket.assigns[:key]` or a helper, never
matched in the head.

**Detection:** Search for assigns patterns that include a nested map/struct
match on an assign documented as nullable (e.g. `:context` in my_app's
`@moduledoc` says `"the %my_app.Brain.Context{} (or nil)"`). Any such match in a
`handle_event` head is a latent crash.

## 16. `raw/1` with Untrusted DB-Generated HTML — XSS via `ts_headline` (CRITICAL)

**Symptom:** Search results render correctly, but if a page body contains HTML
like `<script>alert(1)</script>`, that HTML is injected into the page as live
markup — a stored XSS vulnerability with no error, no warning, no test failure.

**Root cause:** PostgreSQL's `ts_headline()` wraps matched search terms in `<b>`
tags but does **not** HTML-escape the source text. If the underlying body
contains `<script>`, `<img onerror=...>`, or any other HTML, it passes through
`ts_headline` raw. The LiveView then renders the excerpt with `{raw(result.excerpt)}`,
bypassing Phoenix's automatic HTML escaping:

```elixir
# brain.ex — ts_headline produces HTML with unescaped user content
fragment(
  "ts_headline('spanish', immutable_unaccent(coalesce(body, '')), plainto_tsquery('spanish', ?), 'MaxWords=35, MinWords=15')",
  ^tsquery
)

# search_live.ex — ❌ XSS: raw/1 renders the excerpt as live HTML
{raw(result.excerpt)}
```

**Fix:** Create an HTML sanitizer that allows only the expected highlight tags
(`<b>`, `<strong>`, `<em>`, `<i>`, `<mark>`) and HTML-escapes everything else.
Then replace `raw/1` with the sanitized output:

```elixir
# lib/dran_web/html_sanitizer.ex
defmodule DranWeb.HTMLSanitizer do
  @allowed_tags MapSet.new(~w(b strong em i mark))

  def sanitize(nil), do: {:safe, ""}
  def sanitize(excerpt) when is_binary(excerpt) do
    {:safe, do_sanitize(excerpt)}
  end

  def sanitize_to_string(excerpt) when is_binary(excerpt) or is_nil(excerpt) do
    {:safe, iodata} = sanitize(excerpt)
    IO.iodata_to_binary(iodata)
  end

  # Recursively walk the binary, emitting allowed tags as-is and escaping
  # everything else. Uses :binary.match/2 to find tag boundaries.
  # Key: allowed tags with attributes (e.g. <b onclick=...>) are REJECTED —
  # only bare tag names like <b> or </b> pass through.
  defp do_sanitize(<<>>), do: ""
  defp do_sanitize(<<"</", rest::binary>>), do: ...
  defp do_sanitize(<<"<", rest::binary>>), do: ...
  defp do_sanitize(<<char, rest::binary>>), do: ...
end

# search_live.ex — ✅ Safe
{raw(HTMLSanitizer.sanitize_to_string(result.excerpt))}
```

**Implementation notes:**
- The sanitizer uses binary pattern matching (`<<"<", rest::binary>>`) and
  `:binary.match/2` to find tag boundaries — no regex, no external deps.
- Allowed tags with attributes (e.g. `<b onclick=alert(1)>`) are escaped, not
  stripped — the tag name AND attributes are rendered as visible text.
- `Phoenix.HTML.html_escape/1` returns `{:safe, iodata}`, NOT a plain string.
  Do NOT embed `{:safe, ...}` tuples inside iodata lists — `IO.iodata_to_binary/1`
  will crash with `ArgumentError: not an iodata term`. Write your own
  `escape_char/1` that returns plain binaries (`"&lt;"`, `"&gt;"`, etc.).
- Return `{:safe, iodata}` from `sanitize/1` for direct use with `raw/1`, and
  a `sanitize_to_string/1` helper that calls `IO.iodata_to_binary/1` for
  callers that need a plain string (e.g. for `{raw(...)}` in HEEx).

**Detection:** Search for all `{raw(` in HEEx templates and trace whether the
input originates from user-controlled content or a DB function that produces
HTML. `ts_headline` is the most common offender; also check `ts_rewrite`,
custom SQL functions returning text with markup, and any third-party API
response rendered with `raw/1`.

```bash
grep -rn '{raw(' lib/*/live/ lib/*/components/
```

Every `raw/1` call must have a sanitization boundary or a provably-safe source
(e.g. internally-generated markdown already rendered through a sanitizer).

## 17. Strict Form Params Match with Conditionally-Rendered Fields (CRITICAL)

**Symptom:** A LiveView form submits successfully for one agent type but crashes
with `FunctionClauseError` (no clause matching in `handle_event`) for another
type — even though the form renders and the submit button works.

**Root cause:** A HEEx template conditionally renders a form field:

```elixir
# agent_live.ex — language selector only shown for research agents
<%= if @type == "research" do %>
  <select name="agent[lang]">
    <option value="es" selected>Español</option>
    ...
  </select>
<% end %>
```

But the `handle_event` clause head strictly pattern-matches on that field being
present in the submitted params:

```elixir
# ❌ Crashes for ingest agents — "lang" key absent from form submission
def handle_event("start", %{"agent" => %{"input" => input, "lang" => lang}}, socket) do
  lang = lang || "es"
  ...
end
```

When `@type == "ingest"`, the `<select>` is not rendered, so the browser does
not send `agent[lang]` in the form data. The params map is
`%{"agent" => %{"input" => "..."}}` — no `"lang"` key. The strict pattern match
fails, and since there's no fallback clause, the LiveView crashes.

**Fix:** Loosen the params match to capture the whole inner map, then extract
fields conditionally in the body:

```elixir
# ✅ Safe — works for both research and ingest
def handle_event("start", %{"agent" => agent_params}, socket) do
  context = socket.assigns.context
  type = socket.assigns.type
  input = agent_params["input"]
  lang = if type == "research", do: agent_params["lang"] || "es", else: nil

  if context && String.trim(input) != "" do
    case start_agent(type, input, context.id, lang: lang) do
      ...
    end
  end
end
```

**Rule:** When a HEEx template conditionally renders a named form input
(`name="entity[field]"`) inside an `if` block, the corresponding
`handle_event` must NOT strictly pattern-match on that field in the params.
Browsers only submit fields that are present in the DOM — a conditionally
hidden field is absent from the form data, not sent as `nil`.

**Detection:** Search for `if @` guards wrapping form inputs (`<select>`,
`<input>`, `<textarea>`) in HEEx templates, then check whether the matching
`handle_event` destructures those fields directly in the clause head.

```bash
# Find conditionally-rendered form fields
grep -B2 -A2 'name="agent\[' lib/*/live/*.ex | grep -E '(if @|name=)'
```

This is the form-params counterpart to pattern #15 (which covers over-matching
on *socket assigns*). Both are "over-matching in `handle_event` clause heads"
but one crashes on missing assigns, the other on missing form fields.

## 18. ETS Cache Key Missing Dependencies — Stale HTML (CRITICAL)

**Symptom:** A proposed performance optimization caches rendered markdown in ETS,
but the cache key doesn't include all inputs that affect the output. The result
is stale HTML served to users with no error, no warning, and no test failure.

**Root cause:** A plan proposed caching `render_markdown(body, context_id)` in ETS
with cache key `{body, context_id}`. But `render_markdown` also depends on
`inline_links` (from page meta) and `embeds` (resolved via DB queries). If a
linked page changes its slug, the cached HTML still points to the old path.

```elixir
# ❌ Dangerous — cache key doesn't include inline_links or embeds
def render_markdown(body, opts) when is_binary(body) do
  context_id = Keyword.get(opts, :context_id)
  cache_key = {body, context_id}  # MISSING: inline_links, embeds

  case :ets.lookup(@markdown_cache, cache_key) do
    [{^cache_key, html}] -> raw(html)  # STALE if links changed
    [] -> ...
  end
end
```

**Fix:** Either (a) include ALL inputs in the cache key, or (b) avoid global
caches for content with external dependencies. The safer alternative is
pre-computation in the LiveView:

```elixir
# ✅ Safe — pre-compute in mount, no global cache
def mount(_params, _session, socket) do
  page = Brain.get_page!(id)
  rendered = render_markdown(page.body, context_id: page.context_id, inline_links: page.inline_links)
  {:ok, assign(socket, page: page, rendered_body: rendered)}
end

# Template uses {@rendered_body} instead of calling render_markdown
```

**Why not just add more keys to the cache?** You'd need `{body, context_id,
inline_links, embeds_hash}`. But `embeds` are resolved from the DB — any page
update invalidates the cache transitively. The invalidation logic becomes more
complex than the optimization. Pre-computation in mount is simpler and always
correct.

**Rule:** Never cache rendered content whose dependencies (links, embeds,
relations) can change independently of the primary content. If the cache key
doesn't capture all inputs, the cache is a bug, not an optimization.

**Detection:** Any ETS/Cachex/Redis cache for rendered content. Check if the
cache key includes: (1) the primary content, (2) all IDs/slugs of linked
entities, (3) a hash of any resolved embeds, (4) any user-specific or
context-specific modifiers. If any of these are missing, the cache serves
stale data.

## 19. `Map.get` on Struct for Non-Existent Field (COMPILE WARNING → ERROR)

**Symptom:** `mix compile --warnings-as-errors` fails with "incompatible types
given to Map.get/2 — the map does not have all required keys — therefore this
function will always return nil."

**Root cause:** Elixir's type checker knows the keys of a struct at compile
time. Calling `Map.get(%MyStruct{}, :field_that_doesnt_exist)` produces this
warning because the struct definition guarantees the key is absent. This
commonly happens when building JSON export/serialization maps that include
keys not yet present on the schema (e.g. `description` on `Context`).

```elixir
# ❌ Compile error with --warnings-as-errors
def export_context(context) do
  %{
    name: context.name,
    description: Map.get(context, :description),  # Context has no :description
    slug: context.slug
  }
end
```

**Fix:** Don't use `Map.get` on a struct for a field the schema doesn't
define. Set the value directly:

```elixir
# ✅ Safe
def export_context(context) do
  %{
    name: context.name,
    description: nil,  # or a default, or omit the key
    slug: context.slug
  }
end
```

If the field might be added later, use a helper that accepts a plain map, not
the struct itself:

```elixir
defp maybe_get(map, key) when is_map(map), do: Map.get(map, key)
defp maybe_get(_struct, _key), do: nil
```

**Detection:** Search for `Map.get(%` in serialization/export code. Any struct
pattern followed by a key not in the schema's `field` definitions is a
compile-time error with `--warnings-as-errors`.

## 20. `~p` Sigil in Shared Handler Modules Without VerifiedRoutes (COMPILE ERROR)

**Symptom:** `mix compile` fails with `undefined function sigil_p/2 (expected
MyModule to define such a function or for it to be imported, but none are
available)`.

**Root cause:** The `~p"/path"` verified-route sigil requires
`use Phoenix.VerifiedRoutes` (or the project's `use MyAppWeb, :live_view`
macro, which includes it). Modules that only `use Phoenix.LiveView` directly —
common in shared handler modules like `PageEdit`, `GraphEvents`, or
`EnrichHandler` that aren't full LiveViews but define `handle_event/3` clauses —
do NOT get the sigil.

```elixir
# ❌ Compile error
defmodule DranWeb.PageEdit do
  use Phoenix.LiveView  # does NOT include ~p sigil

  def handle_event("delete_page", _params, socket) do
    {:noreply, push_navigate(socket, to: ~p"/")}  # ← undefined sigil_p/2
  end
end
```

**Fix:** Add `use Phoenix.VerifiedRoutes` alongside `use Phoenix.LiveView`:

```elixir
# ✅ Safe
defmodule DranWeb.PageEdit do
  use Phoenix.LiveView
  use Phoenix.VerifiedRoutes,
    endpoint: DranWeb.Endpoint,
    router: DranWeb.Router,
    statics: DranWeb.static_paths()

  def handle_event("delete_page", _params, socket) do
    {:noreply, push_navigate(socket, to: ~p"/")}  # ← works
  end
end
```

Check `lib/my_app_web.ex`'s `verified_routes/0` function for the exact
`endpoint`/`router`/`statics` values — copy them verbatim to stay consistent.

**Alternative:** Use a plain string `"/"` instead of `~p"/"` if route
verification isn't needed. But `~p` is preferred for compile-time route checking.

**Detection:** Search for `~p"` in modules that don't `use MyAppWeb, :live_view`
or `use Phoenix.VerifiedRoutes`. Any occurrence is a compile error.

## 21. Documentation Claims Auto-Behavior That Code Never Executes (CRITICAL)

**Symptom:** Module docs, MCP tool descriptions, or SKILL.md files declare
that something happens automatically (e.g. "embeds are auto-resolved into
relations on create/update"), but tracing the actual code path shows the
function is never called. Users build mental models around phantom behavior.

**Root cause:** A function like `resolve_embeds/1` exists and works correctly,
but the lifecycle hooks that should call it (create, update, rename) were
never wired. The docs were written aspirationally, or the wiring was lost
in a refactor. The gap is invisible because the function works when called
directly — tests pass, manual invocation works.

**Detection pattern:**

1. Read the `@moduledoc` or tool schema description for claims of automatic
   behavior ("auto-creates", "auto-resolves", "on update it rewrites").
2. Trace every public lifecycle function (create, update, delete, rename) and
   grep for the claimed function name:
   ```bash
   grep -rn 'resolve_embeds\|auto_relate\|propagate' lib/MyApp/
   ```
3. If the only callers are tests or the function itself, the claim is false.

**Real example from my_app audit:**

```elixir
# SKILL.md claimed: "embeds are auto-resolved into embeds relations"
# Brain.resolve_embeds/1 existed and worked — but was NEVER called
# by create_page/1 or update_page/2. Embeds in page bodies were dead text.
```

**Fix pattern:** Wire the missing call in the lifecycle function, then add a
test that verifies the side effect actually fires:

```elixir
# In create_page/1 and update_page/2, AFTER successful insert/update:
_ = resolve_embeds(page)  # or reresolve_embeds for updates
```

**Rule:** Every claim of automatic behavior in docs must have a corresponding
call in the lifecycle code AND a test that verifies the integration, not just
the function in isolation.

## 22. Auto-Relations Are Unidirectional — Graph Becomes Directionally Biased (MODERATE)

> **STATUS: FIXED** in the 2026-07-17 PageAugmenter refactor (Task 3.2).
> `create_semantic_edge/3` now creates both A→B and B→A. The inverse edge
> is always attempted; `on_conflict: :nothing` handles deduplication at the
> SQL level. See the `create_relations/2` + `create_semantic_edge/3`
> implementation in `page_augmenter.ex`.

**Symptom:** Semantic/auto-generated relations only exist as A→B. When viewing
page B, there's no indication it's related to A. The graph visualization shows
arrows pointing one way only, making some pages look like sinks and others
like sources with no structural reason.

**Root cause:** The augmenter/worker creates `relation(source: new_page, target: neighbor)`
but never creates the inverse `relation(source: neighbor, target: new_page)`.
Over time, older pages accumulate inbound relations but newer pages have
few or none, biasing graph metrics and making discovery asymmetric.

**Detection:** Query for asymmetric pairs:

```sql
SELECT r1.source_id, r1.target_id
FROM relations r1
LEFT JOIN relations r2
  ON r1.source_id = r2.target_id
 AND r1.target_id = r2.source_id
 AND r1.relation_type = r2.relation_type
WHERE r1.relation_type = 'semantic'
  AND r2.id IS NULL;
```

If this returns rows, your auto-relations are unidirectional.

**Fix pattern:** When creating auto-relations, create both directions:

```elixir
defp maybe_create_relation(page, target, confidence) do
  create_semantic_edge(page.id, target.id, confidence)
  create_semantic_edge(target.id, page.id, confidence)  # ← the inverse
end

defp create_semantic_edge(source_id, target_id, confidence) do
  exists =
    Repo.exists?(
      from r in Relation,
        where: r.source_id == ^source_id and r.target_id == ^target_id,
        where: r.relation_type == "semantic"
    )

  unless exists do
    Brain.create_relation(%{
      source_id: source_id,
      target_id: target_id,
      relation_type: "semantic",
      meta: %{"auto" => true, "confidence" => Atom.to_string(confidence)}
    })
  end
end
```

**Tradeoff:** Doubles the edge count for semantic relations. In dense graphs
this can make visualization noisy. Mitigate by adding a `weight` column and
letting the UI filter/prune by weight threshold.

## 23. Fixed Semantic Threshold Ignores Content-Length Variance (MODERATE)

> **STATUS: FIXED** in the 2026-07-17 PageAugmenter refactor (Task 3.1).
> The module attribute `@semantic_threshold` was replaced with a public
> `semantic_threshold/1` function that scales by body length:
> `<500` chars → `0.15`, `>4000` chars → `0.28`, else `0.22`.
> See `page_augmenter.ex` lines 166–185.

**Symptom:** Short pages (notes, todos) get semantic relations to barely-related
content; long pages (research docs) miss obvious neighbors. The same distance
threshold produces wildly different precision depending on body length.

**Root cause:** Cosine distance on embeddings is not normalized for content
length. A 50-char note and a 5000-char doc with the same cosine distance to
a candidate have very different actual relatedness. Short texts have noisier
embeddings — small distance differences are less meaningful.

**Fix pattern:** Scale threshold by content length:

```elixir
defp semantic_threshold(%Page{body: body}) do
  len = String.length(body || "")
  cond do
    len < 500 -> 0.15    # stricter for short, noisy embeddings
    len > 4000 -> 0.28   # looser for long, rich embeddings
    true -> 0.22          # default
  end
end
```

**Detection:** Sample semantic relations and check the body length distribution
of both endpoints. If short pages dominate the "false positive" relations,
your threshold is too loose for short content.

## 24. Slugify Divergence — Multiple Implementations Produce Different Slugs (MODERATE)

**Symptom:** `"Meditación"` becomes `"meditaci-n"` in one code path and
`"meditacion"` in another. Pages created via MCP have different slugs than
pages created via ingest, causing duplicate-detection failures and broken
cross-references.

**Root cause:** Multiple private `slugify/1` functions exist (e.g. one in
`Brain`, one in `Ingest.Utils`), and they handle Unicode differently. One
strips non-ASCII with a naive regex (`[^a-z0-9]+`), the other normalizes
accents first.

**Fix pattern:** Single public `Slug.slugify/1` with Unicode normalization,
delegated from all call sites:

```elixir
def slugify(text) when is_binary(text) do
  text
  |> String.normalize(:nfd)              # é → e + ́
  |> String.replace(~r/[^a-zA-Z0-9\s-]/u, "")  # strip combining marks
  |> String.downcase()
  |> String.replace(~r/[^a-z0-9]+/, "-")
  |> String.replace(~r/^-+|-+$/, "")
  |> case do
    "" -> "untitled"
    slug -> slug
  end
end
```

**Detection:** `grep -rn 'def slugify\|defp slugify' lib/` — if you get more
than one definition, they will diverge.

## Summary Checklist for Phoenix Umbrella Audits

1. [ ] All `phx-hook="X"` references exist in the `hooks` object in `app.js`
2. [ ] `JS.exec` is only used for `phx-*` bindings; custom events use `JS.dispatch`
3. [ ] Router routes with `:id/sub-path` are defined before bare `:id` routes
4. [ ] No alias shadowing across umbrella apps (same bare name aliased twice)
5. [ ] API boundary functions unwrap DB-stored maps to strings where the API expects strings
6. [ ] All `opts` parameters are actually read in the function body
7. [ ] `Task.async` in LiveViews is replaced with `Task.Supervisor.async_nolink`
8. [ ] Req URLs use leading `/`
9. [ ] `String.first/1` is guarded against empty strings
10. [ ] Query param passing uses Phoenix's `~p` properly, no manual URI decoding
11. [ ] LiveView `phx-change` forms with nested JSONB config inputs deep-merge partial maps
12. [ ] MCP tool toggle handlers use `phx-value-server` separately, not `String.split` on tool name
13. [ ] Optional chat side-effects (memory, brain, vectorization) are wrapped in `try/rescue`
14. [ ] SSE/JSON parsing uses safe `Jason.decode/1` + `get_in/2`, never `Jason.decode!/1`
15. [ ] `handle_event` clause heads match only structurally-required assigns; nullable assigns (documented as "or nil") fetched via nil-safe helpers in the body
16. [ ] Every `{raw(...)}` in HEEx templates traces to a provably-safe source or a sanitization boundary — `ts_headline` output and any DB-generated HTML containing user content is NOT safe without sanitization
17. [ ] `handle_event` params matches don't strict-pattern-match on form fields that are conditionally rendered via `<%= if @... %>` — browsers omit hidden fields from submissions entirely, causing `FunctionClauseError`
18. [ ] ETS/Cachex caches for rendered content include ALL inputs in the cache key (content, links, embeds, relations) — missing keys = stale HTML served to users
19. [ ] `Map.get(%Struct{}, :field)` is not used for fields not defined in the schema — use direct assignment or a map-based helper instead
20. [ ] `~p"/path"` sigil is only used in modules with `use Phoenix.VerifiedRoutes` or `use MyAppWeb, :live_view` — shared handler modules need the explicit import
21. [ ] Every claim of automatic behavior in docs (@moduledoc, MCP schemas, SKILL.md) has a corresponding call in the lifecycle code AND an integration test — grep for the claimed function to verify it's actually called
22. [ ] Auto-generated relations (semantic, embeds) are bidirectional — check for asymmetric pairs with the SQL query in §22
23. [ ] Semantic distance thresholds scale with content length — short pages need stricter thresholds than long pages
24. [ ] Only ONE `slugify/1` implementation exists — grep for `def slugify\|defp slugify` and consolidate to a single public module
