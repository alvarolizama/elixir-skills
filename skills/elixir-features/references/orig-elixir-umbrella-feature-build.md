---
name: elixir-umbrella-feature-build
description: "Build a feature end-to-end across an Elixir Phoenix umbrella project: domain schemas/context in one app, business logic in another, LiveView UI in a web app. Execute phase-by-phase with verification gates."
version: 1.0.0
author: Álvaro Lizama
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [elixir, phoenix, umbrella, liveview, implementation, planning]
    related_skills: [plan, phoenix-umbrella-project-setup, phoenix-wizard-forms, systematic-debugging]
---

# Elixir Umbrella Feature Build

Use this skill when Álvaro asks to implement a feature that touches multiple apps inside an Elixir umbrella (e.g. `:core` for data, `:harness` for business logic, `:admin` for UI).

## Persisting computed graph signals into `Page.meta` + curation_agent enrichment

When the task involves writing derived/computed data (pagerank, community_id,
future centrality/embedding stats) into MyApp's `Page.meta` JSONB, or enriching
an existing agent tool result (e.g. `find_duplicates`) with a derived field
from both pages' meta, read `references/MyApp-graph-signals-and-meta-persistence.md`
FIRST. It captures: the `Repo.update_all` + `COALESCE(meta,'{}'::jsonb) ||
?::jsonb` pattern that bypasses `Brain.update_page/2` to avoid triggering the
augmenter/embeddings/broadcasts; the `community_pages/2` query shape
(`(meta->>'community_id')::int = ?`); the curation_agent pair-enrichment pattern
(select meta, derive boolean, strip meta before LLM sees it); and pure-Elixir
Label Propagation implementation notes (undirected adjacency via nested
`Access.key`, `reduce_while` early-stop with min-iter threshold, label
compression to `1..k`, `:seed` opt for deterministic tests).

## Adding a tool to a MyApp agent module

When the task is specifically "add a new tool to an existing `MyApp.Agent.*`
module" (QA, LinkGardenerAgent, CurationAgent, Research, Ingest, WeeklyReview), read
`references/MyApp-agent-add-tool.md` FIRST. It captures the recurring
workflow: read `tools/0` + an existing `execute_tool/3` clause before
writing, **verify** the real `context_id` field (`state.session.context_id`,
not `state.context_id` — the user flags this every time), check whether
`summarize_result/1` needs a new clause (often it doesn't — structural
clauses cover `{:ok, list}` and `{:ok, %{slug:, title:}}`), update the
`tools/0` assertion test, and report `mix compile --warnings-as-errors` +
`PORT=4099 mix test test/MyApp/agent/` output.

Related references for the testing side:
- `references/MyApp-agent-guard-unit-testing.md` — guard-only tests, no DB.
- `references/MyApp-agent-e2e-testing.md` — full tool-call sequence with
  `Req.Test` stub.

## Core workflow

1. **Read or refresh the plan.** If the plan is missing, create one with the `plan` skill before writing code.
4. **Expose UI.** Add LiveViews, routes, and shared components in the web app. Use `assign()` before `~H` in Phoenix 1.8.
5. **Verify at each phase.** Run the narrow test scope for the changed app, then run the full umbrella gate after integration.

## Execution style

- When Álvaro says "implementa", "completa todo", "sigue", or similar, keep executing phase by phase. Do not stop at every boundary to ask "shall I continue?"
- Surface blockers immediately (compilation error, failing test, missing config) and propose a fix in the same turn.
- Keep commits frequent and atomic, one per logical phase if possible.

## When you ARE the subagent executing a single phase

When the parent dispatches you to implement one phase of a plan (file-scoped, with explicit out-of-scope constraints like "ONLY `lib/MyApp/brain.ex`"), the plan's code is idealized and may not match the codebase's actual API surface. This is the most common source of silent breakage in phase-by-phase execution.

Key discipline: **verify every function the plan's code calls actually exists** with `search_files` before using it. Plans frequently reference helpers by names that are *close but wrong* (`fetch_page_by_slug` vs the actual `get_page_by_slug`; `PageMeta.meta_get/2` that was never written). Adapt to the real name; if no equivalent exists, create a minimal local fallback and report it. Five seconds of `search_files` before writing prevents the recurring failure mode: a subagent blindly copies the plan's code, creates a shadow helper, and the build breaks for the parent to debug.

Full six-step procedure with concrete examples: see `references/subagent-orchestration-pitfalls.md` §7.

## Pre-flight: clean tree before dispatching subagents

Before launching any subagent wave, the working tree MUST be clean. If there are pending changes, commit them yourself in atomic groups FIRST — do not let subagents inherit a dirty tree.

Pattern from the MyApp 2026-07-17 session:

```bash
# 1. Inspect what's pending
git status --short
git diff --stat | tail -30

# 2. Group into logical commits (example: 24 modified files → 5 commits)
git add <files-for-feature-A> && git commit -m "feat: ..."
git add <files-for-chore-B>   && git commit -m "chore: ..."
git add <files-for-docs>      && git commit -m "docs: ..."

# 3. Verify clean baseline
git status --short
mix compile --warnings-as-errors
mix test
```

**Why:** a dirty tree means subagents race on the same git index, bundle unrelated changes into single commits, and misattribute pre-existing failures to their own work. The 5-commit pre-flight above prevented all of that.

## Baseline verification gate

Never dispatch subagents against an unverified baseline. After cleaning the tree:

```bash
mix compile --warnings-as-errors   # must be clean
mix test                           # must be 100% green
```

If the baseline is red, fix it BEFORE dispatching — otherwise subagents will chase pre-existing failures and report them as their own blockers.

## Plan-to-code gap: verify the plan against the actual codebase

Plans written in prior sessions or by other agents are often stale. Before dispatching any task, verify:

- **Function signatures** — the plan may say `slugify(text) → "untitled"` but the real code returns `""` for empty input.
- **Module existence** — the plan may assume a module doesn't exist, but it already does with different semantics.
- **Line numbers** — drift between sessions is common; always read the file before patching.
- **Already-implemented features** — grep before proposing. The MyApp plan assumed `resolve_embeds` was never called; verification showed it was only missing from `create_page`/`update_page`, not everywhere.

**Rule:** if the plan's code block doesn't match the actual file, adjust the plan or the task before dispatching. Do not let subagents discover the mismatch mid-flight.

## Shared config rules

- All config lives under `config/` at the umbrella root. Do not duplicate endpoint or repo config per app.
- Web apps created with `phx.new.web` have no Ecto repo of their own; set `config :admin, ecto_repos: []` and route test sandboxes to `Core.DataCase`.
- `import_config "#{config_env()}.exs"` must be at the very bottom of `config/config.exs`.
- macOS dev port convention: starting at 3000, increment per app. Admin usually gets 3001. Bind with `http: [ip: {0,0,0,0}, port: 3001]` and `url: [host: nil]`.

## PGVector specifics

See `references/pgvector-setup.md` for the custom Postgrex types dance. Short version:

1. Add `{:pgvector, "~> 0.4"}` to the repo app.
2. Create a `PostgrexTypes` module with `Pgvector.extensions() ++ Ecto.Adapters.Postgres.extensions()`.
3. Set `types: MyApp.PostgrexTypes` on the repo in `config/config.exs`.
4. Migration uses `add :embedding, :vector, size: 1536`.
5. Schema uses `field :embedding, Pgvector.Ecto.Vector`.

For testing functions that select records by embedding distance, see
`references/pgvector-semantic-selection-testing.md` — covers synthetic vector
construction, the 51-noise-page discriminator pattern, and testing both
the semantic and fallback branches.

## Prompt injection defence

When building LLM-facing features, add a policy-based scanner before any text
reaches the system prompt. See `references/prompt-injection-defence.md` for a
port of Hermes Agent's `threat_patterns.py` to Elixir, including the curly-brace
regex trap and the `String.graphemes/1` invisible-unicode gotcha.

**Placement rule for this umbrella:** agent/inference-facing code (runners,
LLM clients, system prompt builders, and prompt security) belongs to `:harness`;
`:core` is for domain schemas and contexts.

## Verification gates

After each phase run:

```bash
mix compile --warnings-as-errors
mix test --umbrella  # or cd apps/<app> && mix test
```

Before declaring a task done:

```bash
mix format --check-formatted
mix compile --warnings-as-errors
MIX_ENV=test mix compile --warnings-as-errors
mix test
```

### `--warnings-as-errors` fails on unrelated dirty working-tree changes

When the working tree has concurrent/unrelated modifications (another session, a prior commit that left a file dirty, a tool that auto-edited a file), `mix compile --warnings-as-errors` will fail on THOSE warnings — even though YOUR changes are clean. Don't waste time fixing someone else's warning.

**Diagnose whether the warning is yours or pre-existing:**

```bash
# 1. Grep the output for YOUR files only
mix compile --warnings-as-errors 2>&1 | grep -E "(todo_live|todo_helpers|TodoHelpers)" || echo "NO WARNINGS IN OUR FILES"

# 2. If unsure, stash and re-run to see what was already broken
git stash
mix compile --warnings-as-errors 2>&1    # if the same warning appears, it's pre-existing
git stash pop

# 3. Verify YOUR changes compile cleanly without the strict flag
mix compile    # exit 0 = your code is clean
```

**Rule:** `--warnings-as-errors` is a gate for the WHOLE project, not just your diff. When the tree is dirty from concurrent work, fall back to `mix compile` (no flag) to verify your changes, then grep the `--warnings-as-errors` output for your specific files/modules to confirm zero warnings from your work.

## Common pitfalls

- **GenServer.call timeout must exceed the inner operation's worst-case timeout (CRITICAL):** When a GenServer's `handle_call` delegates to a long-running operation (agent loop, LLM chain) with its own timeout (e.g. `@agent_timeout_ms 120_000`), the `GenServer.call(pid, msg, timeout)` at the call site must be LARGER than that inner timeout plus processing overhead — otherwise the caller dies with a timeout exit exactly when the operation would have succeeded. Rule: `call_timeout = inner_timeout * 1.5` (120s inner → 180s call). Audit both numbers whenever you change one. This bit the MyApp copilot chat: `GenServer.call(..., 60_000)` against a 120s agent timeout — every slow-but-successful reply crashed the caller.
- **LiveView PubSub refresh storms (debounce):** When a LiveView subscribes to a PubSub topic that fires rapidly (e.g. agent step progress), each message triggers a `Repo.all` refresh. Five quick events = five DB queries. **Fix:** debounce with `Process.send_after/3` + `Process.cancel_timer/1`. Store the timer ref in assigns; on each new event, cancel the old timer and schedule a new one (200ms is a good default). Add a `handle_info(:refresh, socket)` clause that does the actual DB fetch and clears the timer assign. Clean up the timer in `terminate/2` if the LiveView defines it. See the MyApp `agent_live.ex` debounce for `{:step_started, _}` and `{:step_completed, _, _}` messages.
- **`handle_info` clause ordering — specific before catch-all (CRITICAL):** When adding a new specific `handle_info` clause (e.g. `handle_info(:refresh_steps, socket)`) to a LiveView that already has a catch-all `handle_info(message, socket)`, the new clause MUST be defined BEFORE the catch-all. Elixir matches clauses top-to-bottom; a catch-all at line N makes any specific clause after it unreachable. `mix compile --warnings-as-errors` will fail with: `this clause for handle_info/2 cannot match because a previous clause at line N always matches`. **Rule:** always insert new `handle_info` clauses above any existing `def handle_info(message, socket)` or `def handle_info(_msg, socket)` catch-all.
- **Cross-app visibility:** Umbrella web app must declare `{:core, in_umbrella: true}` (and any other needed sibling) in its `mix.exs`, otherwise `Core.*` modules are not visible at compile time.
- **DataCase reuse:** If a web app uses `Core.DataCase.setup_sandbox/1`, the web app's `test/support/conn_case.ex` must point to `Core.DataCase` and the web app must depend on `:core`.
- **GPG signing from Hermes UI:** Hermes may not see `/opt/homebrew/bin/gpg` even if the shell does. Set `git config --local gpg.program /opt/homebrew/bin/gpg` and re-enable `commit.gpgsign` locally.
- **Elixirc paths:** Domain apps that define test support fixtures must add `elixirc_paths` in `mix.exs` so `test/support` compiles in `:test`.
- **Umbrella app placement:** Agent/inference-facing code (runners, LLM clients, system prompt builders, prompt security scanners) belongs in `:harness`. `:core` is for domain schemas and contexts. Do not put LLM-system-prompt logic in `:core`.
- **No circular app dependencies:** `:core` must remain dependency-free of sibling umbrella apps (e.g. `:harness`). A data context that needs to call an inference step is inverted; store/update the record in `:core`, then drive the inference call from the app that already depends on both (`:admin`, `:harness`, or a new orchestrator app).
- **N+1 in relation creation loops (CRITICAL):** `Brain.list_relations_for_page/1` runs 2 queries (outbound + inbound) with `preload: [:target]` / `preload: [:source]` each time. Calling it inside a loop over N neighbors = 2N queries. The original `PageAugmenter.maybe_create_relation/3` did exactly this — one `list_relations_for_page` call per neighbor. **Fix:** load existing outbound semantic targets ONCE in `create_relations/2` into a `MapSet` of `target_id`s, then check `MapSet.member?/2` in memory for each neighbor. With `on_conflict: :nothing` on `Brain.create_relation/1`, you can even skip the check entirely — but the MapSet prevents spurious INSERT attempts and lets you create the inverse edge only when the outbound is genuinely new. See the `create_relations/2` + `create_semantic_edge/3` refactor in `page_augmenter.ex` (Task 3.3).
- **Unique-constraint changesets POISON Ecto transactions (CRITICAL):** relying on `unique_constraint` in a changeset to make re-inserts "safe no-ops" is WRONG inside `Repo.transaction`. When Postgres raises a unique violation, the *entire transaction* enters aborted state — every subsequent query fails with `current transaction is aborted`, and the transaction function returns `{:error, :rollback}` even though your code pattern-matched `{:error, changeset}` and continued happily. Symptom: `Repo.transaction(fn -> ... end)` returns `{:error, :rollback}` with NO exception while every `IO.inspect` checkpoint inside shows `:ok`. This bit `Brain.rename_slug/2` (2026-07-17): `update_page` → `reresolve_embeds` → `resolve_embeds` → `create_relation` re-inserted a relation that already existed in the same transaction. **Fix:** pass `on_conflict: :nothing` to `Repo.insert` in any create function that can run inside a transaction or in idempotent lifecycle hooks (`create_relation`, the `resolve_embeds` path). Keep `unique_constraint` in the changeset as a safety net for non-transactional callers, but `on_conflict` is what prevents the SQL error from ever being raised. **Diagnosis recipe:** if a transaction returns `:rollback` with no crash, set `Logger.configure(level: :debug)` in the test and grep for `QUERY ERROR` — the failing INSERT is the one immediately before the final `rollback []` log line. Bisect by removing operations from the transaction until it commits; the last removed op is the poisoner.
- **Agent engine crash-guard must wrap state construction, not just the loop:** in `Engine.execute_loop/3`, a `try/rescue/catch` placed around only `loop(state)` misses crashes in `build_messages`/`init_state` (they run BEFORE `loop`) — the session stays `running` forever. **Fix:** wrap the WHOLE function body — state construction AND `loop(state)` — and in the rescue/catch call `finish_session` with a minimal synthetic state (`%{session: session, pages_created: 0}`) since the real state may never have been built. Parametrize `finish_session(state, args, status \\ "done")` so the crash path passes `"failed"`. Regression test: agent module whose `build_messages` raises; run `Engine.run/4`, poll the session row until `status == "failed"` (see `test/MyApp/agent/engine_test.exs` `CrashingAgent`).
- **Agent `summarize_result/1` atom vs string keys crash `format_tool_result` (CaseClauseError):** `Engine.format_tool_result/2` does `case summary do %{data: data} -> ... %{status: "error"} -> ... end` with **atom keys**. A new agent whose `summarize_result/1` returns **string keys** (`%{"type" => "text", "length" => n}`) compiles fine but crashes at runtime with `%CaseClauseError{term: %{"length" => 310, "type" => "text"}}` on the FIRST tool call — session dies as `Agent step failed: %CaseClauseError{...}` with 0 steps logged. This bit the Copilot agent (2026-07-17). **Fix:** agent `summarize_result/1` must return atom-keyed maps matching the Engine's case clauses: `%{status: "done"}`, `%{status: "ok", data: text, length: n}` for binaries, `%{status: "error", error: msg}`. Also: the Engine's `default_summarize_result` needs a `{:ok, binary}` clause (MCP tools return plain text) and `format_tool_result` needs a `%{data: data} when is_binary(data)` branch (`smart_truncate(data, ...)`) alongside the list/map branches. When a brand-new agent dies on step 1 with a CaseClauseError naming a summary-shaped map, this keys mismatch is the cause.
- **Conversational agents: plain-text LLM reply after tool calls = implicit `done`, not `:no_json`:** `Engine.extract_tool_call/1` falls back to `parse_response(content)` when there are no native `tool_calls`. For batch agents (research, curation_agent) that always end via an explicit `done` tool, returning `{:error, :no_json}` on unparseable text is correct. But conversational agents (copilot chat) often produce their FINAL answer as plain prose after N successful tool calls — the model synthesizes instead of calling `done`. Treating that as `:no_json` kills the session exactly when it succeeded. **Fix:** in `parse_response`, when JSON extraction fails but `content` is non-empty plain text, return `{:ok, %{tool: "done", args: %{"summary" => text}, ...}}` (implicit done); keep `:no_json` only for empty/garbage responses. Verified end-to-end 2026-07-17: copilot listed goals via `dran_list_pages`, read 3 pages via `dran_get_page`, then answered in prose — session completed with the prose as summary.
- **Model for tool-calling agents ≠ model for plain chat:** see the `local-omlx-inference-api` skill § "Tool calling" — `Qwen3.6-35B-A3B` silently ignores `tools` (returns prose), `Qwen-AgentWorld-35B-A3B` returns native `tool_calls`. Symptom in the Engine: sessions die with `Agent step failed: :no_json` on the FIRST LLM call, 0 steps, ~45k tokens burned (the model "thinks out loud" without invoking anything). **Fix:** separate env var `DRAN_INFERENCE_AGENT_MODEL` + `Inference.agent_model/0` (falls back to `chat_model`), used in `Engine.call_llm` and `create_session!`'s meta. Verify the model with the curl probe in the oMLX skill before wiring a new agent.
- **PGVector distance in Ecto — three valid approaches:** The raw operator form `e.embedding <-> ^vector` is NOT valid Elixir syntax inside `order_by`. There are three working patterns, all used in the MyApp codebase:
  1. **`fragment/1` with `<=>` (cosine)** — most common in MyApp (`brain.ex:auto_relate/2`, `brain.ex:semantic_search/2`, `summaries.ex:candidate_pages/1`): `order_by: fragment("? <=> ?", p.embedding, ^Pgvector.new(vector))`. Requires `import Ecto.Query`. The `<=>` operator is pgvector's cosine distance; `<->` is L2, `<#>` is negative inner product.
  2. **`Pgvector.Ecto.Query.cosine_distance/2`** — cleaner macro form: `import Pgvector.Ecto.Query` then `order_by([e], asc: cosine_distance(e.embedding, ^Pgvector.new(vector)))`. Used in the Money Bot brain context (`brain-semantic-search-patterns.md`).
  3. **`l2_distance/2` / `max_inner_product/2`** — same module, for L2 or inner-product distance respectively. Use when the index type or use case calls for a different metric.
  All three require wrapping the vector in `Pgvector.new/1` before passing it as a parameter. The fragment approach is more verbose but doesn't require an extra import; the macro approach is cleaner but needs `import Pgvector.Ecto.Query`. Pick one and stay consistent within a module.
- **`distinct(query, [p], p.id)` conflicts with `order_by` — use `distinct(query, true)` (CRITICAL):** `DISTINCT ON (column)` in Postgres requires the `DISTINCT ON` expression to match the leading `ORDER BY` expression. So `distinct(query, [p], p.id)` followed by `order_by([p], desc: p.updated_at)` raises `ERROR: SELECT DISTINCT ON expressions must match initial ORDER BY expressions`. This surfaces when you add a `LEFT JOIN` for filtering (e.g. joining the `plan` page to filter todos by their plan's goal) and the join duplicates rows. **Fix:** use `distinct(query, true)` — full-row `DISTINCT` with no column list. It has no `ORDER BY` coupling and works with any subsequent `order_by`. Duplicated rows from a join are byte-identical (same `%Page{}` struct), so full-row dedup is safe and correct. Only reach for `DISTINCT ON (col)` when you genuinely need first-per-group semantics with a matching `order_by`; for plain join-dedup, `distinct: true` is the right tool.
- **Gettext in tests — `gettext/1` is undefined, use `Gettext.gettext/2` (CRITICAL):** MyApp's default locale is `"es"`, so all rendered LiveView HTML comes back in Spanish. Tests that assert `assert html =~ "Activity"` will FAIL — the rendered text is `"Actividad"`. But you can't call `gettext("Activity")` in a test module either: `DranWeb.ConnCase` does not import the `gettext` macro, so it fails at compile time with `undefined function gettext/1`. **Fix:** define `defp t(msgid), do: Gettext.gettext(DranWeb.Gettext, msgid)` in the test module and assert with `assert html =~ t("Activity")`. Note: `DranWeb.Gettext.gettext(msgid)` does NOT work (not a public function) — the correct call is `Gettext.gettext(DranWeb.Gettext, msgid)`. For untranslated strings (new msgids not yet in `.po` files), `Gettext.gettext/2` returns the English msgid unchanged. See `references/MyApp-liveview-testing-patterns.md` § "Asserting on localized (gettext) strings in tests".
- **Testing PubSub `handle_info` live updates:** To verify a LiveView's `handle_info({:page_changed, _action, _page}, socket)` actually updates the rendered output, mount the LiveView, trigger the broadcasting action (e.g. `Brain.create_page/1`), `Process.sleep(50)` to let the async PubSub message propagate, then `render(view)` and assert. See `references/MyApp-liveview-testing-patterns.md` § "Testing PubSub `handle_info` live updates".
- **LiveView route ordering:** Static-segment routes must precede param catch-alls when they share a prefix. Put `/brain/graph` before `/brain/:slug`, `/agents/new` before `/agents/:id`, etc. Otherwise the generic live view mounts and raises `Ecto.NoResultsError`.
- **Async sandbox operations:** `Task.start` launched from a context function that tries to query inside the test process will fail with `DBConnection.ConnectionError` once the test exits. Keep async side effects (embedding calls, notifications, search indexing) out of the data context; trigger them from the caller or a supervised job after the DB transaction commits.
- **PageAugmenter.schedule spawns a task that loses sandbox ownership (CRITICAL):** `Brain.create_page/1` and `Brain.update_page/2` call `MyApp.Brain.PageAugmenter.schedule/1`, which checks `Inference.enabled?()`. If inference is enabled in a test (e.g. you set `base_url` to use a `Req.Test` stub for the chat endpoint), `PageAugmenter.schedule` spawns an async `Task.Supervisor.start_child` that tries to access the DB from a process that doesn't own the sandbox → `DBConnection.OwnershipError` (`cannot find ownership process ... using mode :manual`). The error may appear as a background log line, not in the test that triggered it. **Fix:** create/update all test pages BEFORE enabling inference. With inference disabled (the default in tests — `Application.get_env(:MyApp, :inference)` is `nil`), `PageAugmenter.schedule` returns `:ignored` immediately without spawning a task. Then enable inference with the stub right before the tool-call sequence under test. This is distinct from the "set `base_url: nil` to disable inference entirely" pattern — here you WANT inference enabled for the test, just not during page creation. See `references/MyApp-agent-e2e-testing.md` for the full sequence.
- **Smart quotes corruption in write_file:** When writing large Elixir files via `write_file` or `patch`, Unicode smart/curly quotes (`"` `"`) can replace straight ASCII quotes (`"`). The code looks correct in the diff but won't compile — Elixir requires ASCII quotes. Always re-read the file after writing large blocks and rewrites with `write_file`; if compilation fails with mysterious syntax errors, check for `"` vs `"` with `grep -P '[\x{201C}\x{201D}]' file.ex`. Fix by rewriting the file clean.
- **`<.input field={nil}>` in Phoenix 1.8:** The `CoreComponents.input/1` component requires a `Phoenix.HTML.FormField` struct for the `field` attribute — passing `nil` produces a compile warning and runtime error. For standalone inputs that use `phx-click` handlers instead of form binding (e.g. toggle switches for JSONB config), use raw HTML `<input>` / `<label>` tags with DaisyUI classes instead of `<.input>`.
- **Form `id` attribute for phx-change forms:** LiveView forms with `phx-change` must have an `id` attribute, or Phoenix warns about missing form recovery. Add `id="my-form"` to every `<.form>` tag that has `phx-change` or `phx-submit`.
- **`to_form(map)` without `as:` produces flat field names — `handle_event` params never match (CRITICAL):** When building a LiveView form from a plain map (not an Ecto changeset), `to_form(%{"key" => value})` generates field names like `name="key"` (flat, no namespace). But if your `handle_event` pattern-matches `%{"settings" => params}` (expecting namespaced params), the clause never fires — the params arrive as `%{"key" => value}` at the top level. **Symptom:** `LiveViewTest.form/3` raises `could not find non-disabled input with name "settings[key]"` because the rendered `<input name="key">` doesn't match. **Fix:** pass the `as:` option: `to_form(values, as: :settings)` — this makes field names `settings[key]`, params arrive nested as `%{"settings" => %{"key" => value}}`, and the `handle_event("save", %{"settings" => params}, socket)` clause matches. This mirrors how `to_form(changeset, as: :page)` works for Ecto changesets (see `ingest_live.ex` using `to_form(%{...}, as: :ingest)`). The `as:` option is REQUIRED whenever your `handle_event` expects namespaced params — plain `to_form(map)` is only safe when your handler reads top-level params.
- **Narrow `import Phoenix.Component, only: [to_form: 1]` shadows already-imported macros (COMPILE ERROR):** `use DranWeb, :live_view` (via `html_helpers()`) already imports `Phoenix.Component` macros — `attr/3`, `slot/2`, `assign/2`, `assign_new/2`, etc. Adding `import Phoenix.Component, only: [to_form: 1]` to get `to_form/1` RE-IMPORTS the module with an `only:` list that excludes those macros, shadowing them. `mix compile` fails with `undefined function attr/3 (there is no such import)` on any `attr` declaration in the same module. **Fix:** do NOT add a narrow `import Phoenix.Component` — `to_form` is already available via `use DranWeb, :live_view`. If you need only a specific function, check whether it's already imported by the web macro before adding an explicit import. The general rule: `use MyAppWeb, :live_view` already brings in everything from `html_helpers()`; adding competing narrow imports for the same module breaks the macros that were already in scope.
- **Plan-to-code gap verification:** Before implementing from a plan, verify every assumption against the actual codebase. Plans often have: (1) wrong function signatures (e.g. `list_messages_for_session(session)` when the real function takes `session_id`), (2) references to env vars or modules that don't exist, (3) duplicate function definitions copy-pasted in the plan, (4) functions used in later tasks but defined in earlier ones with different names. Read the actual files with `read_file` before patching, never trust the plan's code blocks blindly.
- **Batch regex-refactor across N "similar" files: diff ALL N, not 2 (CRITICAL):** When consolidating a repeated pattern with a transformation script (e.g. N page-type LiveViews sharing mount/handle_params), proving files A and B match with `diff` does NOT prove the other N−2 match. Same-shape files often carry extra per-file clauses (extra assigns loaded in the detail, a different default tab, an extra query, a `*_tabs` assign computed from context). A script keyed on the shared block silently DELETES those extras. Safe workflow: (1) transform ONE file, compile, run its tests; (2) for EACH remaining file, `git show HEAD:<file> | sed -n '<range>p'` the original block and compare against the generic replacement BEFORE applying — any line outside the known-shared block is a custom clause that must survive (skip the file, or extend the shared helper with a callback / `extra_assigns` option); (3) if a script already ate custom code, `git checkout <file>` to revert and re-apply manually. This cost a revert of 3 LiveViews in the MyApp PageDetail refactor (2026-08): `project_live`/`goal_live`/`plan_live` load extra linked data (project_todos/goal_plans/tabs, active_tab "overview") that note/entity/concept don't — the naive script wiped those assigns and only a compiler warning about an orphaned private helper revealed the loss.
- **Chat pipeline resilience:** Optional side-effects in the chat pipeline (memory summarization, brain retrieval, vectorization) must be wrapped in `try/rescue` so a failure in one optional step never breaks the primary flow (storing user + assistant messages + returning the response). Use `safe_brain_retrieve/2` wrappers that degrade to `{:ok, nil}` on exception, and `try do Memory.summarize_session/2 rescue _ -> :ok end` for fire-and-forget post-processing.
- **JSONB config partial-map data loss in `phx-change` forms:** When a LiveView form with `phx-change` contains raw HTML inputs for nested JSONB config fields (`agent[memory_config][message_window]`), the browser sends only the fields that have values. Ecto's `cast/3` replaces the entire map, losing `enabled`, `summary_model`, etc. Deep-merge the incoming partial map with the existing config before calling `update_agent`. See `references/jsonb-config-and-prompt-extension.md` §2 for the `merge_tool_configs/2` pattern.
- **MCP tool toggle server name passing:** MCP discovery returns tools with a simple `name` field, not a composite `server/tool` key. Pass the server name via a separate `phx-value-server` attribute. Store the server name in a `discovered_tools_server` assign that persists after discovery completes, because `discovering_server` is set to `nil` when the loading spinner stops. Never use `String.split(name, "/", parts: 2)` on tool names.
- **UUID primary keys are the default:** Álvaro wants all schemas to use `:binary_id` (UUID), not `:bigserial`. Every schema gets `@primary_key {:id, :binary_id, autogenerate: true}` + `@foreign_key_type :binary_id`. See `references/uuid-primary-keys.md` in the `phoenix-umbrella-project-setup` skill for the full pattern.
- **Test DB schema mismatch after PK type change:** After changing primary key types (e.g. integer → UUID), `mix test` fails with `DBConnection.EncodeError: Postgrex expected an integer ... got <<binary>>`. The dev DB was reset but the **test DB** wasn't. Always run both `mix ecto.reset` AND `MIX_ENV=test mix ecto.reset` after schema type changes.
- **LiveView `handle_event` assigns over-matching (CRITICAL):** Pattern-matching `%{assigns: %{page: %Page{} = page, context: %{id: context_id}}}` in a *specific* `handle_event` clause head crashes with `CaseClauseError` when `context` is `nil`. The catch-all fallback clause (`handle_event("field_change", _params, socket)`) never catches this because Elixir tries the specific clause first and the match failure happens there. **Fix:** match only the minimum required assigns in the clause head (`%{assigns: %{page: %Page{} = page}}`), then fetch optional assigns via a nil-safe helper (`context_id(socket)` that returns `nil` for missing/`nil` context). Guard with `if is_nil(context_id) do {:noreply, put_flash(socket, :error, "...")} else ... end`. See `references/code-audit-patterns.md` §15 for the full pattern with before/after code.
- **Subagent batch-finish summaries can misattribute their own WIP as pre-existing failures (CRITICAL):** A timed-out subagent's batch summary may report "12 pre-existing test failures" or "the premise no longer exists" when in fact the failures come from its own uncommitted WIP files in the working tree (e.g. an untracked test file from a sibling subagent that raced the same tree). **Verification rule:** never accept a subagent's claim of "pre-existing failure" without running `git stash` + the test command yourself to see the true baseline. Also: subagent summaries saying "nothing to commit, already applied" often mean a sibling committed first — verify with `git log -1 --stat`, not the summary text.
- **Propose new features only after grep-checking they don't already exist:** Before proposing or building a feature, search the codebase for the hook/component/handler names that would implement it. In a MyApp feature brainstorm, the agent proposed "kanban drag-and-drop" and "backlinks" as new features — both already existed (`phx-hook=".KanbanBoard"` in `todo_live.ex`, inbound relations section in `page_components.ex`). A 30-second grep (`grep -rn "phx-hook\|KanbanBoard\|inbound" lib/ assets/js/`) prevents proposing redundant work. Check `assets/js/app.js` for hook registrations and `lib/**/*_live.ex` for existing UI before writing any proposal.
- **`Config` deep-merge silently ignores `jobs: []` overrides (CRITICAL):** Elixir's `Config` module deep-merges keyword lists across `config.exs` → `#{env}.exs`. If `config/config.exs` defines `config :app, App.Scheduler, jobs: [curation_agent_daily: [...], weekly_review: [...]]` and `config/test.exs` tries to disable it with `config :app, App.Scheduler, jobs: []`, the empty list contributes NO keys to override the nested `curation_agent_daily:` / `weekly_review:` entries — the production jobs survive into the test env. `Application.get_env(:app, App.Scheduler)` in `MIX_ENV=test` returns the full production job list, and Quantum/Oban will try to start those jobs. **Symptom:** scheduler logs `Job with name :X not started: invalid task function` in test, and tests asserting `jobs == []` fail. **Fix:** guard the definition in `config.exs` with `if config_env() != :test do ... end` so the jobs are never compiled into the test env in the first place. Then `test.exs`'s `jobs: []` is belt-and-suspenders (or can be omitted). This applies to ANY nested keyword-list config that needs to be fully replaced per-env (not just schedulers) — `Config`'s deep merge means an empty/shorter list cannot shadow a longer one. See the Quantum scheduler Task 6.5 in MyApp (2026-07-17) for the full reproduction.
- **`page_detail` `:if={@tabs == []}` guard hides content from all page-type LiveViews (CRITICAL):** The shared `page_detail/1` component in `page_components.ex` has several content blocks (prose body, changelog, backlinks) guarded with `:if={@tabs == []}`. These only render when NO `:tabs` slot is passed. **All 10 page-type LiveViews** (note, concept, entity, reference, goal, plan, todo, artifact, comparison, query) pass a `<:tabs>` slot, so content inside `:if={@tabs == []}` is **invisible** for every page detail view. **Symptom:** you add a section inside the guard, compile cleanly, but tests that mount a LiveView and assert on the rendered HTML fail — the text is absent. **Fix:** if the section should appear for all page types, place it **outside** the `:if={@tabs == []}` guard, after `{render_slot(@tabs)}`. The guard is only for fallback content (prose + changelog) that makes sense when a LiveView doesn't provide its own tabbed UI. See `references/MyApp-liveview-ui-patterns.md` § "Collapsible backlinks section" for the full placement pattern.
- **`gettext.merge` silently drops new strings when compile fails elsewhere:** `mix gettext.extract` compiles the project to find `gettext()` calls. If there's a compile error in any other file (e.g. another agent's in-progress work), the extractor may still write the `.pot` with new msgids, but `mix gettext.merge` will NOT pick them up into `.po` files — it reports `0 new` even though the `.pot` contains the entries. **Fix:** manually add the new entries to the `.po` files, or ensure `mix compile` is clean before running extract+merge. See `references/MyApp-i18n-gettext-patterns.md` § "gettext.merge silently drops new strings".
- **LiveView streams: convert LiveView + component in the same commit, or revert entirely (CRITICAL):** Converting a list to streams touches both the LiveView (`stream/4` in `handle_params`) and the shared component (`@streams.pages` + `phx-update="stream"`). A subagent that converts only one side leaves the build broken with `undefined attribute "pages"` or `undefined assign @streams`. If you inherit a half-done streams conversion (component uses `@streams.pages` but LiveViews still `assign(socket, :pages, ...)`), the safest fix is to **revert the component back to plain `@pages` list** and abandon the streams conversion — a working non-stream list beats a broken stream. Only re-attempt streams when you can touch all page LiveViews and the component atomically. Also: `@streams.pages` is NOT enumerable — you cannot `Enum.map(@streams.pages, ...)` in a template; consume it only via `:for={{id, page} <- @streams.pages}` inside a `phx-update="stream"` container.
- **`raw/1` with `ts_headline` output — stored XSS (CRITICAL):** PostgreSQL's `ts_headline()` wraps search matches in `<b>` tags but does NOT HTML-escape the source body. If the body contains `<script>`, `<img onerror=...>`, or any HTML, it passes through raw. Rendering with `{raw(result.excerpt)}` creates a stored XSS with no compile warning or test failure. **Fix:** create an `HTMLSanitizer` that allows only `<b>`, `<strong>`, `<em>`, `<i>`, `<mark>` (no attributes) and escapes everything else; replace `{raw(result.excerpt)}` with `{raw(HTMLSanitizer.sanitize_to_string(result.excerpt))}`. **Gotcha:** `Phoenix.HTML.html_escape/1` returns `{:safe, iodata}` — do NOT embed those tuples in iodata lists or `IO.iodata_to_binary/1` crashes; write your own `escape_char/1` returning plain binaries. See `references/code-audit-patterns.md` §16 for the full pattern with detection steps. A ready-to-use implementation is in `templates/html_sanitizer.ex`.
- **Strict form params match with conditionally-rendered fields (CRITICAL):** When a HEEx template conditionally renders a named form input (`<%= if @type == "research" do %> <select name="agent[lang]"> ... <% end %>`), browsers omit that field from form submissions when the condition is false — the key is absent from the params map, not `nil`. A `handle_event` clause that strict-matches `%{"agent" => %{"input" => input, "lang" => lang}}` crashes with `FunctionClauseError` for the type that doesn't render the field. **Fix:** loosen the match to `%{"agent" => agent_params}` and extract fields conditionally in the body: `lang = if type == "research", do: agent_params["lang"] || "es", else: nil`. See `references/code-audit-patterns.md` §17.
- **ETS cache key missing dependencies (CRITICAL):** A proposed ETS cache for rendered markdown used cache key `{body, context_id}` but `render_markdown` also depends on `inline_links` and `embeds`. If a linked page changes slug, the cache serves stale HTML. **Fix:** either include ALL inputs in the cache key, or avoid global caches for content with external dependencies — pre-compute in LiveView mount instead. See `references/code-audit-patterns.md` §18.
- **Gettext `gettext(dynamic_var)` in HEEx templates (COMPILE ERROR):** The `gettext()` macro requires literal string arguments at compile time. You cannot store untranslated strings in a module-attribute map and call `gettext()` on them in the template — `gettext(empty_state(@page_type).title)` fails with `Gettext macros expect message keys to expand to strings`. **Fix:** use a `case` with literal `gettext("...")` calls per branch inside a private function, return the translated strings, and use them directly in the template without a `gettext()` wrapper. See `references/MyApp-i18n-gettext-patterns.md` § "Per-type translation lookups".
- **Interpolating a nullable Ecto field into a binary (RUNTIME CRASH, hits prompt builders):** `"summary: #{page.summary}"` raises `(ArgumentError) construction of binary failed: segment 2 of type 'binary': expected a binary but got: nil` when the field is NULL. This is especially insidious for columns that are NULL in tests but populated in prod (embeddings, summaries, any async-filled field) — the crash only surfaces when a query path that skips a default returns a struct with `nil`. **Defense in depth:** (a) coalesce at the query — `select: %{..., summary: coalesce(p.summary, "")}` so no consumer ever sees nil; (b) guard at the interpolation site — `summary = summary || ""` before building the string. Do BOTH. The query guard protects the known call sites; the interpolation guard protects the next consumer you add. Real case: `Summaries.augment_prompt` crashed the curation_agent agent because `candidate_pages` selected `p.summary` raw (2026-07-17).
- **Truthiness in `and`/`or` chains is a `BadBooleanError` (RUNTIME CRASH):** Elixir's `and`/`or`/`&&` are NOT truthy operators like in Ruby/JS — `if connected?(socket) and assigns[:context_slug] and ...` raises `(BadBooleanError) expected a boolean on left-side of "and", got: "personal"` when the assign is a string. Any value used in a boolean chain must be a real boolean. **Fix:** `not is_nil(assigns[:context_slug])`. This bit the chat widget's `maybe_start_chat` guard (2026-07-17) and broke every LiveView test that mounted the layout (because the widget mounts on every page). If a guard crashes with `BadBooleanError` and names a string/assign, this is the cause.
- **`Map.get` on a struct for a non-existent field (COMPILE WARNING → ERROR with `--warnings-as-errors`):** Elixir's type checker knows the keys of a struct at compile time. Calling `Map.get(%MyStruct{}, :field_that_doesnt_exist)` produces a warning: "incompatible types given to Map.get/2 — the map does not have all required keys — therefore this function will always return nil." With `--warnings-as-errors` this fails compilation. This commonly happens when building JSON export/serialization maps that include keys (e.g. `description`) not yet present on the schema. **Fix:** don't use `Map.get` on a struct for a field the schema doesn't define — just set the value directly (`description: nil` or a default). If the field might be added later, use a helper that accepts a plain map, not the struct itself.
- **Pre-compute `rendered_body` in LiveView `handle_params`, not inline in template (PERFORMANCE):** `render_markdown/2` is expensive (parses markdown, resolves wikilinks, fetches embeds). Calling it inline in the HEEx template re-parses on *every* render — every `handle_event`, every PubSub message, every `handle_params` patch. Pre-compute `rendered_body` in the slug-loading `handle_params` clause, store it as an assign, pass it as a `rendered_body` attr to `<.page_detail>` (which already accepts it with a `nil` fallback), and use `{@rendered_body}` in the template instead of `render_markdown(@page.body, ...)`. **CRITICAL:** also recompute in `PageEdit.handle_event("body_change", ...)` after `Brain.update_page` succeeds — otherwise the rendered HTML is stale after every autosave until the next full navigation. `PageEdit` is a shared handler, not a LiveView; call `DranWeb.PageComponents.render_markdown/2` fully-qualified since `PageComponents` isn't imported there. See `references/MyApp-liveview-ui-patterns.md` § "Pre-computed `rendered_body` pattern" for full code. This is the concrete implementation of the §18 anti-pattern (don't use ETS cache with incomplete keys — pre-compute in the LiveView instead).
- **`~p` sigil in shared handler modules (COMPILE ERROR):** The `~p"/path"` verified-route sigil requires `use Phoenix.VerifiedRoutes` (or the project's `use MyAppWeb, :live_view` macro, which includes it via the `verified_routes/0` macro in `lib/my_app_web.ex`). Modules that only `use Phoenix.LiveView` directly — common in shared handler modules like `PageEdit`, `GraphEvents`, or `EnrichHandler` that aren't full LiveViews but define `handle_event/3` clauses — do NOT get the sigil. `mix compile` fails with `undefined function sigil_p/2 (expected MyModule to define such a function or for it to be imported, but none are available)`. **Fix:** add `use Phoenix.VerifiedRoutes, endpoint: MyAppWeb.Endpoint, router: MyAppWeb.Router, statics: MyAppWeb.static_paths()` alongside the existing `use Phoenix.LiveView`. Check `lib/my_app_web.ex`'s `verified_routes/0` function for the exact `endpoint`/`router`/`statics` values — copy them verbatim to stay consistent. Alternatively, use a plain string `"/"` instead of `~p"/"` if route verification isn't needed, but `~p` is preferred for compile-time route checking.
- **Standalone `Phoenix.Component` modules need explicit `use Gettext` (COMPILE ERROR):** Shared component modules that use `use Phoenix.Component` directly — not via `use MyAppWeb, :html` — do NOT inherit the Gettext macros. Calling `gettext("...")` in their templates fails at compile time with `undefined function gettext/1`. This affects modules like `PageComponents` and `PageListComponents` in MyApp. **Fix:** add `use Gettext, backend: MyAppWeb.Gettext` alongside `use Phoenix.Component`. LiveView modules (`*_live.ex`) do NOT need this — they get `gettext` via the `use MyAppWeb, :live_view` -> `html_helpers()` -> `use Gettext, backend: MyAppWeb.Gettext` macro chain. See `references/MyApp-i18n-gettext-patterns.md`.
- **`stream_delete` is arity `/3`, not `/2` (COMPILE ERROR):** When importing LiveView stream functions in a shared handler module like `PageEdit`, `stream_delete` takes `(socket, name, item)` — arity 3. Importing it as `stream_delete: 2` fails with: `cannot import Phoenix.LiveView.stream_delete/2 because it is undefined or private`. The correct import is `stream_delete: 3`. `stream_insert` is also `/3`. See `references/MyApp-liveview-ui-patterns.md` section "Converting page lists to LiveView streams" for the full pattern.
- **Converting `assign` lists to LiveView streams (PERFORMANCE):** When a LiveView index page renders a list via `assign(socket, :items, items)`, every `handle_event` re-sends the entire list to the client. For page-type LiveViews in MyApp (note, concept, entity, reference, goal, plan, artifact, comparison, query), convert to `stream(socket, :pages, pages, reset: true) |> assign(...)` in `handle_params`, update the shared component to use `phx-update="stream"` with `:for={{id, page} <- @streams.pages}`, and add `stream_insert`/`stream_delete` in `PageEdit` for create/delete. See `references/MyApp-liveview-ui-patterns.md` section "Converting page lists to LiveView streams" for the complete before/after.
- **Dirty working tree containing reverts of committed changes (CRITICAL):** More dangerous than the selective-staging scenario above — sometimes the working tree contains modifications that *revert* a prior commit (e.g. `@streams.pages` reverted to `@pages`, `stream/4` reverted to `assign/3`). These look like normal uncommitted changes but would undo someone else's work if committed. After `git add -A`, always run `git diff --cached --stat` and inspect any unexpected files. If you see files you didn't touch, `git diff --cached <file>` to check if they revert committed work, then `git reset HEAD -- <file>` and `git checkout -- <file>` to discard the unrelated changes. Only stage files you actually modified.
- **Verify-before-implement — the codebase may already have the feature:** Before implementing a multi-step feature plan, read every file the plan mentions. The plan may describe work that is already 95% done (only missing a wire, an import, a registration). Reading 3-4 key files up front prevents redundant implementation work and identifies the precise missing piece. In the MyApp 3D graph integration, the hook file, LiveView template, event handler, and assign were all already implemented — the only missing piece was a single `import` and `hooks` registration in `app.js`.
- **LiveComponent module attributes not available in `~H` render (CRITICAL):** In a `Phoenix.LiveComponent`, module attributes (e.g. `@quick_actions [...]`) are NOT available inside the `render/1` template's `~H` sigil — the template accesses `socket.assigns`, not compile-time module attributes. Referencing `@quick_actions` in the template produces a crash at render time (e.g. when `handle_event("toggle")` flips `@open` to `true` and re-renders). **Fix:** assign the module attribute to the socket in `mount/1`: `assign(socket, :quick_actions, @quick_actions)`. This does not affect regular function components (stateless `Phoenix.Component`) where module attributes work normally in templates — only `LiveComponent` has this constraint because its render goes through the diff engine with assigns.
- **`push_navigate` inside a LiveComponent (CRITICAL):** `push_navigate/2` works in LiveComponents — return `{:noreply, push_navigate(socket, to: path)}` from `handle_event/3`. The navigation is forwarded to the parent LiveView. Do NOT try to use `JS.navigate` or `redirect` from a component event handler; `push_navigate` is the correct API for LiveComponent-initiated navigation.
- **LiveComponent hook targets via `pushEventTo`:** When a JS hook needs to send events to a specific LiveComponent (not the parent LiveView), use `this.pushEventTo(this.el, "event_name", payload)`. The component's root element must have `phx-target={@myself}` so Phoenix routes the event to the component's `handle_event/3`. This is how the Command Palette hook sends `toggle`, `close`, and `key` events to the `CommandPalette` LiveComponent from a global `window` keydown listener.
- **Partial unique indexes block same-transaction UPDATE→INSERT (CRITICAL):** A partial unique index like `unique_index(:api_keys, [:team_member_id], where: "status = 'active'")` will block an INSERT of a new active row even after an `update_all` revokes the old active row in the same `Ecto.Multi` transaction. PostgreSQL doesn't free the partial index entry until COMMIT + HOT pruning. This reproduces in all sandbox modes AND in `iex -S mix` outside tests — it's NOT a sandbox artifact. **Fix:** if the spec says "one key per X" (not "one *active* key"), use a non-partial unique index and implement `replace_api_key` as an in-place UPDATE of the existing row's hash/prefix. See `references/ecto-migration-and-schema-pitfalls.md` §1 for three fix options.
- **`references/2` does not accept `:null` (migration-time crash):** `add :org_id, references(:orgs, type: :binary_id, null: false)` raises `Map.update(:null, false, ...)` at migration time. The `null: false` goes on the `add/3` call, not inside `references/2`.
- **`assoc_constraint` error key is the association name, not the FK column:** `assoc_constraint(:organization)` adds errors to `:organization`, not `:organization_id`. Tests must assert `errors_on(changeset).organization`, not `.organization_id` (which raises `KeyError`).
- **Pin operator `^` in `assert_receive` requires a variable, not an expression (COMPILE ERROR):** `assert_receive {:event, ^provider.id, _}` fails to compile with `invalid argument for unary operator ^, expected an existing variable, got: ^provider.id`. The pin operator pins a *variable*, not a field access or expression. **Fix:** bind to a variable first: `provider_id = provider.id` then `assert_receive {:event, ^provider_id, _}`. This catches you in PubSub broadcast tests where you naturally write `^sub.id` or `^struct.field` inline.
- **Second-precision `timestamps(type: :utc_datetime)` breaks deterministic ordering tests:** Ecto's `:utc_datetime` type truncates to whole seconds — back-to-back inserts in the same test share the same `inserted_at`. Sorting by `inserted_at` becomes non-deterministic, and round-robin / priority tests that depend on insertion order will flake. **Fix:** don't use `Process.sleep(10)` (unreliable and the AGENTS.md forbids it). Instead, explicitly set distinct timestamps via `Ecto.Changeset.change/2` after insert:
  ```elixir
  defp timed_fixture(factory_fn, name, offset_seconds) do
    record = factory_fn.(%{name: name})
    time = DateTime.utc_now() |> DateTime.add(offset_seconds) |> DateTime.truncate(:second)
    {:ok, _} = record |> Ecto.Changeset.change(%{inserted_at: time}) |> Repo.update()
    %{record | inserted_at: time}
  end
  ```
  Use `DateTime.add/2` with distinct offsets (-20, -10, 0) to guarantee a strict ordering that `Enum.sort_by/3` will respect. This pattern works for any timestamp-dependent ordering test, not just subscriptions.
- **Postgres aggregates via Ecto `fragment/1` decode as float OR Decimal depending on the column type (RUNTIME CRASH):** `AVG(int_col)` and `percentile_cont(...) WITHIN GROUP (...)` come back from Postgrex as plain floats for some column types and `%Decimal{}` for others — you cannot assume one. Calling `Decimal.to_float/1` on a value that is already a float raises `(FunctionClauseError) no function clause matching in Decimal.to_float/1` at runtime, and it only shows up when the query actually returns rows (a RED test with empty results won't catch it). **Fix:** normalize every aggregate value with a polymorphic helper before arithmetic:
  ```elixir
  defp to_float!(%Decimal{} = d), do: Decimal.to_float(d)
  defp to_float!(n) when is_integer(n), do: n / 1
  defp to_float!(n) when is_float(n), do: n
  ```
  Also handle `nil` first (`value && to_float!(value)`) — aggregates over nullable columns (e.g. `ttft_ms`, `latency_ms`) return NULL. This bit the my_app_gateway `Rollup.provider_ranking/2` analytics query (2026-07-27): `SUM` fragments elsewhere in the module used `Decimal.new(to_string(...))` safely, but `AVG`/`percentile_cont` needed the float branch.
- **`mix precommit` (or `mix format`) reformats files AFTER you committed them — format before committing:** projects with a `precommit` alias run `mix format` as part of the gate, and the formatter can rewrite the exact files your feature commit just landed (HEEx line wraps, default-arg removal in test fixtures). Result: `git status` shows your committed files as modified again, forcing a follow-up `style:` commit. **Rule:** run `mix format` (or `mix precommit`) BEFORE the feature commit when the project has the alias, or accept that the precommit run at the end needs its own formatting commit. Verify with `git status --short` after `mix precommit` — don't assume the tree is clean just because tests passed.
- **Ecto `fragment` requires literal strings AND Postgres rejects parameterized `date_trunc` in GROUP BY (COMPILE + RUNTIME, analytics queries):** two walls hit back-to-back when writing bucketed time-series rollups (my_app_gateway `busiest_hours`/`busiest_minutes`, 2026-07-27): (1) `fragment("date_trunc(?, ?)", ^unit, rl.inserted_at)` with the unit as a *parameter* fails at runtime with `ERROR 42803 column must appear in the GROUP BY clause` — Postgres cannot prove `$1 == $3` is the same expression across SELECT/GROUP BY/ORDER BY. (2) The obvious fix, `fragment(^"date_trunc('#{unit}', ?)", ...)` with an interpolated string, fails at COMPILE time: `to prevent SQL injection attacks, fragment(...) does not allow strings to be interpolated as the first argument`. **Fix:** duplicate the query pipeline per unit with literal fragment strings (`fragment("date_trunc('hour', ?)", ...)` and a separate body for `'minute'`) behind a multi-clause private function (`defp busiest_buckets(id, "hour", opts)` / `defp busiest_buckets(id, "minute", opts)`). The duplication is the price of injection safety; whitelist-guard with function heads, never user input.
- **`Enum.sort_by(keys, DateTime)` does not work on tuple keys — write the comparator yourself:** `Enum.sort_by(events, fn {ts, delta} -> {ts, delta} end, DateTime)` looks right but `DateTime.compare/2` receives the whole `{ts, delta}` tuple, not the DateTime, and raises. **Fix:** `Enum.sort(events, fn {ts_a, d_a}, {ts_b, d_b} -> case DateTime.compare(ts_a, ts_b) do :lt -> true; :gt -> false; :eq -> d_a <= d_b end end)` — explicit comparator with tie-breaking (for sweep lines: ends (−1) before starts (+1) on ties so back-to-back requests don't count as concurrent).
- **Estimating historical max concurrency from request logs (sweep line):** when the runtime in-flight counter lives in ETS (not persisted), reconstruct it from durable logs: each completed request occupied `[inserted_at − latency_ms, inserted_at]`. Build +1/−1 events per request, sort with the comparator above, fold tracking `current` and `max` (+ first timestamp where max was hit). Requests with `nil` latency count as instantaneous (start == end). Document in the moduledoc that it loads `(inserted_at, latency_ms)` pairs into memory — fine for dashboards, never for hot paths. Label the UI value "Estimado" — it IS an estimate.
- **Time-relative test fixtures flake by wall-clock — truncate to a boundary:** a test that builds `busy = DateTime.add(now, -3600) |> Map.put(:minute, 10)` passes at :15 past the hour and fails at :05 (both timestamps land in the same hour bucket → `assert [first, second]` matches one row). **Fix:** anchor fixtures to a truncated boundary first: `hour_now = DateTime.utc_now() |> DateTime.truncate(:second) |> Map.put(:minute, 0) |> Map.put(:second, 0)`, then `DateTime.add(hour_now, -3600 * n)` per bucket. Deterministic regardless of when the suite runs. Also: a "excludes NULL" test is impossible when the column is `NOT NULL` in the DB (e.g. `agent_type`) — don't fight the constraint with raw SQL inserts; test something real instead (e.g. `:limit` behavior).
- **`git add -A` / `git add lib test` sweeps the USER's pre-existing uncommitted changes into YOUR feature commit (happens repeatedly in long sessions):** when the session starts with a dirty tree (`M lib/my_app_gateway/budgets.ex` that isn't yours), any broad-stage command bundles those hunks into your commit. Symptom: `git show --stat HEAD` lists files you never touched. **Prevention:** `git status --short` BEFORE every stage; stage only explicit paths you edited. **Recovery (local, unpushed):** `git reset --soft HEAD~1 && git restore --staged <not-your-file> && git commit -m "..."` — the user's hunks go back to dirty-working-tree, your commit keeps only your files. If their file IS one you legitimately edited too, disclose the mix to the user instead of trying to surgically separate.
- **"Un top 5 más" — offer the dimension menu before building:** when Álvaro asks for one more top-N dashboard card, the candidate dimensions (agent_type, credentials, error codes, days, model_requested) are a product choice, not a technical one. Building your own pick (Top 5 Agentes, 2026-07-27) got rejected with "agentes no, ¿qué otra opción tenemos?" — one `clarify` round with the available dimensions + what's already covered would have skipped a full build/revert cycle. Ask first, listing which dimensions are already on the page so the choice is informed.

## MyApp agent guard unit-testing (no DB sandbox)

When TDD'ing a pure limit/validation guard inside an agent's `execute_tool/3`
(page limits, query caps, scrape caps), test it WITHOUT `MyApp.DataCase` by
building an in-memory `%Research.State{}` + `%Session{}` with `struct/2` and
using `assert_raise DBConnection.OwnershipError` to prove the non-guard branch
was reached. See `references/MyApp-agent-guard-unit-testing.md` for the full
pattern: in-memory state construction, the OwnershipError trick, polymorphic
`opts` (keyword vs map) reading, and guard-placement rules.

## MyApp agent E2E testing with Req.Test stubs

When testing a full agent tool-call sequence (`list_orphans → get_page →
propose_relation → done`) end-to-end, see
`references/MyApp-agent-e2e-testing.md` for the pattern that avoids running the
async `Engine.run` loop. Instead, call `Inference.chat` (stubbed) to get the
next scripted tool call, then feed it directly to the agent's
`execute_tool/3`, verifying DB side-effects. This tests the same code path
the engine's `single_turn/1` takes without sandbox-ownership or timing
issues.

## MyApp LiveView testing patterns

When writing LiveView tests in the MyApp Phoenix app, see
`references/MyApp-liveview-testing-patterns.md` for the established conventions:
session setup with `Plug.Test.init_test_session/1`, disabling inference in
test setup (`base_url: nil`), the HEEx HTML-escaping gotcha for data attribute
assertions, and the basic LiveView test template with `live/2` +
`element/2` + `render_click/1`.

## Phoenix proxy / streaming / HTTP-adapter testing patterns

When testing code that calls out over HTTP (provider adapters, webhook workers) or streams SSE/chunked responses through a controller, see `references/phoenix-proxy-testing-patterns.md` for: Bandit as an in-test HTTP server with marker path segments (no mock libs), `:persistent_term` request capture for passthrough assertions, the chunked-conn-test rule (thread conn through every `Plug.Conn.chunk/2` or bytes vanish from `resp_body`), `Decimal.equal?/2` vs `==/2` after `round/6`, micro-USD integer counters for ETS money, Oban manual-mode `drain_queue` in conn tests, and first-token-timeout testing without sleeping the suite.

## MyApp REST API patterns

When building new REST API endpoints on the MyApp Phoenix app (controllers, routes, tests, serialization), see `references/MyApp-rest-api-patterns.md` for the established conventions: controller structure, router scope, test auth header (`Bearer MyApp-token`), key schemas, the ID-to-slug translation pattern for exports, and **public (no-auth) endpoint patterns** for health checks with DB connectivity probes.

### MCP vs REST — when to use which

| | MCP | REST |
|---|---|---|
| **Purpose** | Agent AI interfaces (Claude, Hermes, etc.) | External integrations |
| **Format** | JSON-RPC, self-documenting tools/resources/prompts | HTTP CRUD |
| **State** | Maintains session context | Stateless |
| **Discovery** | Tools list themselves | Needs external docs |

**Rule:** MCP is the primary interface for AI agents. REST is only for integrations that can't use MCP (webhooks, health checks, simple exports). If a feature can be exposed via MCP tool, prefer that over a new REST endpoint.

**When REST makes sense:**
- `/health` — monitoring systems expect HTTP GET
- `/api/contexts/:slug/export` — simple download, no agent reasoning needed
- Webhook receivers — external services POST events

**When MCP makes sense:**
- Any CRUD on pages/contexts/relations
- Search (FTS, semantic, hybrid)
- Agent sessions (start, poll, cancel)
- Anything an AI agent would call

## MyApp i18n / Gettext patterns

When implementing internationalization (i18n) or adding Spanish translations
in the MyApp Phoenix app, see `references/MyApp-i18n-gettext-patterns.md` for
the complete workflow: the `mix gettext.extract` → `gettext.merge` cycle, what
strings to wrap, the `use Gettext` gotcha for standalone `Phoenix.Component`
modules, module-attribute compile-time translation, proper interpolation (not
`String.replace` hacks), .po file structure, and MyApp-specific translation
choices (es locale).

## MyApp floating widgets & plan conventions

When building floating/global UI (chat copilots, FABs) in MyApp, or writing
multi-phase improvement plans for Álvaro's projects, see
`references/MyApp-floating-widgets-and-plan-conventions.md` for: the
CommandPalette-style LiveComponent mount reused for FAB panels, the
async-reply `send_update/3` pattern (never block `handle_event` on LLM
calls), GenServer-backed chat sessions that survive LiveView navigation,
deictic "esta página" context detection, the plan-phase ordering rule
(features → cleanup/validation → metrics → docs/README last), and the
`retry: :transient` Req check before planning engine-level retries.

## MyApp LiveView / UI patterns

When building new LiveView pages or UI features in the MyApp Phoenix app (new
LiveViews, shared components, tag links, Layouts.app required assigns, selective
git staging in multi-agent trees), see `references/MyApp-liveview-ui-patterns.md`
for the established conventions: directory structure, the canonical LiveView
pattern (mount → handle_params → render with Layouts.app), shared component
APIs (`page_list/1`, `page_detail/1`, `tabs_bar/1`), `PageTypes` helpers, tag
link patterns, `Brain.list_pages/1` tag filtering, and selective git staging.

Also covers: **overriding delegated `handle_event` handlers** (e.g.
`archive_page`) to add index-list-specific behavior (remove card from list),
the **`update_page_meta/3` helper** for inline meta updates that refresh the
list in place, **click propagation rules** in cards with inline controls
(`phx-change` selects don't need stopPropagation; `phx-click` buttons need a
`noop` wrapper), status-aware select styling, and health dot indicators for
goal cards.

## In-app `/docs` sync (docs drift — check at every plan boundary)

A Phoenix app with a built-in docs page (`docs_live.ex`, tabbed sections like
overview / api / mcp / auth) does NOT update itself as features land. After
MyApp's 15-phase roadmap shipped (chat widget, 4 batch agents, backlinks, smart
collections, full export, runtime settings, relation weights, 3D graph), `/docs`
still documented only the original 2 agents and pre-roadmap endpoints — Álvaro
discovered it by asking "esto se actualizó?" mid-session.

**Detection:** grep the docs file for the newest feature names
(`weekly|curation_agent|gardener|chat|backlink|export|settings`). Zero matches = stale.

**Fix pattern:** the docs LiveView is usually large (~1000 lines) with
independent section functions (`overview/1`, `api_reference/1`,
`mcp_reference/1`, `auth_reference/1`). Split the update into one subagent per
section — they share the file but patch disjoint function bodies, so they don't
conflict. Verify every endpoint you document actually exists in `router.ex`
before adding it to an api table. Add a "sync /docs" phase to every multi-phase
plan, right before the README/screenshots phase.

See `references/MyApp-docs-liveview-sync.md` for MyApp's section inventory, the
HEEx component shapes (`api_group`, `mcp_tool`, env-var tables), and the
3-wave dispatch template used on 2026-07-17.

## Brain context — relation & embed lifecycle

When implementing derived/auto-created relations in MyApp's `MyApp.Brain`
context (embeds auto-resolution on `create_page`/`update_page`, stale
relation cleanup, body-derived relation types, OR meta-derived `part_of`
relations from `goal_slug`/`plan_slug`), see
`references/brain-context-relation-lifecycle.md`. It covers: the two-phase
`reresolve_embeds/1` pattern (delete-stale + resolve-new), idempotency via
`on_conflict: :nothing`, hook placement (before broadcast), the canonical
TDD test pair, AND `sync_planning_relations/2` (meta-derived relations with
prior-state diffing — contrasted with body-diff cleanup), the `meta_string/2`
jsonb helper, and the `lint/1` additive-extension rule.

## Code audit patterns

When asked to "review code" or "find bugs" in an existing umbrella, see
`references/code-audit-patterns.md` for a living checklist of real failure modes
found in this codebase (silent JS hooks, `JS.exec` vs `JS.dispatch`, route
ordering with `:id` catch-alls, alias shadowing, OpenAI content shape mismatches,
dead opts, `Task.async` crash propagation, `Req.Test` URL warnings,
`String.first/1` on empty strings, fragile URL param decoding, JSONB config
partial-map data loss, MCP tool name parsing crashes, unsafe runtime
side-effects in chat pipelines, stored XSS via `raw/1` on `ts_headline` output,
`handle_event` crashes from strict form-params matches on
conditionally-rendered fields, ETS cache key missing dependencies, `Map.get` on
struct non-existent fields, `~p` sigil in shared handler modules, docs claiming
auto-behavior that code never executes, unidirectional auto-relations, fixed
semantic thresholds ignoring content length, and slugify divergence across
modules).
### `patch` reports success but doesn't apply (CRITICAL)

The `patch` tool can return `{"success": true}` with a valid-looking diff, but
the file on disk remains unchanged. This happened with
`page_list_components.ex` — the patch showed the correct diff in its output,
but re-reading the file showed the old content. The cause is likely a fuzzy
matching edge case when the old_string spans the entire file body (attr
declaration + function definition).

**Detection:** after any `patch` that touches a large portion of a file (more
than ~20 lines changed), re-read the file with `read_file` and verify the
change actually landed before compiling. If it didn't, use `write_file` to
rewrite the entire file.

**Rule:** for whole-function or whole-module rewrites, prefer `write_file`
over `patch`. Use `patch` for targeted, small edits (1-5 lines) where the
old_string is unique and short.

- **`patch` escape-drift rejection on HEEx/sigil content with escaped quotes (CRITICAL):** When a `.ex` file contains a `~H` sigil, string interpolation inside the sigil uses `\"` for escaped quotes (e.g. `id={\"credential-#{cred.id}\"}`). The `read_file` output shows these as `\"`, but when you pass the same text back to `patch` as `old_string`, the tool's escape-drift detection rejects the call before matching: *"old_string and new_string contain the literal sequence '\\\"' but the matched region of the file does not."* This happens because JSON serialization of the tool parameters double-escapes the backslash-quote. Retrying with different quoting doesn't help — the tool's safety check fires regardless.

  **Fix:** bypass `patch` for HEEx/sigil content with escaped quotes. Use Python string replacement via `terminal`:

  ```bash
  python3 -c "
  content = open('path/to/file.ex').read()
  old = '''...content with \"...'''
  new = '''...replacement with \"...'''
  assert old in content, 'not found'
  content = content.replace(old, new, 1)
  open('path/to/file.ex', 'w').write(content)
  print('OK')
  "
  ```

  Python reads/writes raw file bytes without JSON serialization interfering, so the `\"` sequences match correctly. Use `assert old in content` as a guard so a silent no-match doesn't corrupt the file. This pattern is also faster than multiple `patch` retries when the escape-drift check is the blocker.

- **Tailwind `max-w-none` cancels `max-w-3xl` in the same class list:** When constraining prose to reading width (`max-w-3xl mx-auto prose max-w-none`), the `max-w-none` wins because it appears later in the source order within the same CSS layer. The result: the prose spans full width and `max-w-3xl` is silently ignored. Always remove `max-w-none` when adding a `max-w-*` constraint to the same element. This is especially common when refactoring existing `prose ... max-w-none` elements to add reading-width limits.
- **MyApp design system: prefer custom CSS utility classes over raw Tailwind:** MyApp defines `.text-display`, `.text-title`, `.text-caption`, `.surface-1`, `.surface-2` in `assets/css/app.css`. Use `.text-title` (not `text-3xl font-bold`) for detail page titles, `.text-caption` (not `text-xs`) for metadata/labels, `.surface-2` (not `bg-base-100 border rounded-lg shadow`) for elevated list items. See `references/MyApp-liveview-ui-patterns.md` § "MyApp design system" for the full class reference and component redesign patterns (metadata bar, segmented control tabs, relations panel, version history).
- **Prefer `write_file` over `patch` for large shared files**

When editing large umbrella files that have been read, changed by another
process, or that span several distinct sections, `patch` can produce duplicated
blocks, mangled indentation, or merged content in the wrong order. This is
especially true for files like `apps/core/lib/core/agents.ex` or long LiveView
modules that were touched earlier in the same session.

**Rule:** if a `patch` fails twice or leaves the file with duplicate/offset
content, stop patching and rewrite the whole module with `write_file`. Re-read
the file first to capture any changes made by other agents or tools, then
produce a clean, complete replacement. This is faster and safer than retrying
incremental edits.

**Batch patching silent-failure (CRITICAL):** When applying multiple `patch`
calls to the *same* file in one turn (e.g. removing duplicate module
attributes, replacing usages, and deleting a function), the patch tool may
return `"success": true` but include a `_warning: file was modified since you
last read it on disk (external edit or unrecorded writer)`. Patches carrying
this warning may **silently not apply** — the change is absent from the file
even though the tool reported success. This only surfaces later during `mix
compile` as an undefined module attribute or missing function reference.

**Prevention:** after any batch of patches to the same file, always re-read
the file (or `search_files` for the old pattern) to verify every change landed
before compiling. If any patch carried the file-modified warning, treat its
change as unverified until confirmed. For refactors touching 3+ distinct
sections of one file, prefer `write_file` for the whole module over sequential
patches — one atomic write avoids the re-read race entirely.

## JSONB config & system prompt extension

When adding per-entity configuration stored as JSONB maps (e.g. `memory_config`,
`brain_config`) or extending a layered system prompt builder to accept runtime
context (sessions, dynamic MCP servers), see
`references/jsonb-config-and-prompt-extension.md` for the patterns: default map
helpers, LiveView toggle handlers, evolving `build/1` to `build/2` without
breaking callers, and wiring MCP tool descriptors into chat completions.

## Server/tool naming for dynamic tool registries

When persisting tools discovered from external servers (MCP or similar), store
both the `server_name` and `tool_name` explicitly. Do **not** rely on a composite
`"server/tool"` key inside the tool name; discovery APIs return a plain name and
compositing it creates fragile String.split/2 parsing later. See
`references/jsonb-config-and-prompt-extension.md` §6 for the LiveView pattern
that keeps the server name in a separate assign (`discovered_tools_server`) so
toggle handlers always know which server a tool belongs to.

## Subagent commit races: `git reset --soft` recovery

When parallel subagents bundle multiple tasks into one commit (or commit under the wrong message), recover with `git reset --soft` + individual re-commits. This is faster and cleaner than interactive rebase:

```bash
# 1. Unstage everything back to origin/main (keeps working tree changes)
git reset --soft origin/main
git reset  # unstage all

# 2. Commit each task individually
git add lib/dran_web/live/page_detail_component.ex
git commit -m "refactor: remove dead PageDetailComponent module"

git add lib/dran_web/html_sanitizer.ex lib/dran_web/live/search_live.ex test/dran_web/html_sanitizer_test.exs
git commit -m "fix(security): sanitize search excerpts to prevent XSS"

# 3. Verify clean history
git log --oneline origin/main..HEAD
```

**Key:** The `--soft` flag keeps all file changes in the working tree but unstages them. Then you re-commit selectively. This only works when commits are local (not pushed).

See `references/subagent-orchestration-pitfalls.md` §2 for the full prevention strategies.

## When to use subagents

**Default to subagents for large multi-surface sweeps:** when Álvaro asks for a broad overhaul (site-wide UI/UX pass, big feature, audit across many views), plan the work as subagent-sized chunks and dispatch them — he corrected a session that was doing everything solo with "recuerda usar sub agentes para tareas pequeñas". The parent keeps the foundation layer (migrations, schema fields, shared context functions, shared components — anything every subagent depends on) plus the review gates; subagents take the disjoint per-view/per-file polish tasks. Avoid subagents only when the work genuinely doesn't split into independent, file-disjoint tasks (config files, shared components, migration ordering).

### Álvaro's preferred dispatch pattern: pairs of two (tandas de dos) — or waves of three when he says so

When subagents ARE the right call, Álvaro prefers them dispatched **two at a time in parallel** ("lanza de dos en dos los sub agentes"), with these rules:

- **Short, concrete tasks** — each subagent gets a tightly-scoped goal with an explicit file allowlist ("edita ÚNICAMENTE X"), not a broad feature brief.
- **No file overlap within a pair** — the two concurrent tasks must touch disjoint files (e.g. one on `assets/css/app.css`, one on `lib/.../page_list_components.ex`). If two tasks need the same file, split them into different tandas and run them serially.
- **Parent reviews after each tanda** — do NOT chain multiple pairs blindly. Between pairs: `git status --short` + `git diff --stat`, `mix compile --warnings-as-errors`, `mix test`. Report what landed before dispatching the next pair.
- **Subagents never commit** — instruct each task "NO hagas git commit". The parent owns all git writes, which eliminates the commit-race/bundling problem below entirely.
- **Sibling verification errors can be transient** — if subagent A reports "build fails due to an error in file X" and X belongs to sibling subagent B's allowlist, the error is usually just mid-flight overlap. Re-run the build yourself after BOTH finish before treating it as real.
- **Beware stale-content rewrites** — when subagents in the same tanda touch the same area, one may rewrite a file from its pre-read snapshot and clobber the sibling's changes (e.g. an "improve docstrings" agent restoring old phrasing). Check `git diff` for content that reverts the other task's work.

**Wave-of-three variant:** when Álvaro explicitly says "de 3 en 3" or "waves of 3", dispatch three parallel tasks instead of two. Same rules apply: disjoint files, no commits, parent verifies after the wave. The only difference is batch size — everything else (short tasks, explicit allowlists, parent gate) stays identical.

**Hard cap on parallel subagents (CRITICAL):** `delegate_task` rejects batches larger than `delegation.max_concurrent_children` (currently **3** for Álvaro's config). If Álvaro says "usa sub agentes 4" (or any N > 3), do NOT try a 4-task batch — the call fails with `Too many tasks`. Instead: dispatch 3 immediately, then either do the 4th task yourself in the meantime or dispatch it when a slot frees. Tell him you're doing it that way. Nested delegation is also OFF (`max_spawn_depth=1`) — orchestrator children can't fan out further.

## Removing a feature end-to-end (teardown workflow)

When Álvaro says "borra X" (borra el chat, quita el copilot, elimina Y feature), do NOT just delete the main module. A Phoenix feature has ~8 surfaces — use this checklist, verified on the MyApp chat-widget teardown (2026-07-18):

1. **Map every surface BEFORE deleting anything** (batch the greps in one turn):
   - `search_files` for the module/component names (`Chat.Server|ChatWidget|chat_widget`)
   - `grep` the **layout** for the component mount (`<.live_component module={...}`)
   - `grep` `application.ex` for supervision children + Registries
   - `grep` the **router** for routes/controllers (may find dead doc entries too)
   - `grep` the **in-app docs LiveView** (`docs_live.ex`) for TOC entries + section text
   - `grep` README (feature bullets, screenshot cells) and check `docs/screenshots/`
   - `grep` gettext catalogs for feature msgids
   - Check migrations dir for the feature's table(s)
   - Check assigns that exist ONLY for the feature (e.g. `page_slug`/`page_type` attrs in `layouts.ex` forwarded only to the deleted component — verify no other template uses them before removing the attrs)
2. **Fan out with disjoint scopes** (fits the wave-of-3 rule): backend modules + supervision / frontend component + layout / README + gettext + migration. Scopes must not overlap; gettext regeneration via `mix gettext.extract && mix gettext.merge` must run AFTER lib deletions land (it compiles the project), so that subagent may need a retry — or remove msgids manually.
3. **Drop the table:** `mix ecto.gen.migration drop_<table>` with `def change, do: drop_if_exists(table(:<table>))`. Run `mix ecto.migrate` on **dev AND test** (`MIX_ENV=test mix ecto.migrate`) and verify with `psql \dt`. If the test DB still has the table but `schema_migrations` shows the version as run, drop it manually — stale test-DB state lies.
4. **Verify zero leftovers:** `grep -rn "ModuleName\|component_name" lib/ --include='*.ex' --include='*.heex'` must print NOTHING. Then `mix compile --warnings-as-errors`, full `mix test`, `mix precommit`.
5. **Commit as one `feat!:` (breaking) commit** listing every surface removed.

### Byte-identical revert to a known commit (subagent-safe)

When reverting files to a prior commit via subagents (e.g. undoing a feature without touching newer work):

```bash
# Revert one file to commit <sha>
git show <sha>:path/to/file > path/to/file

# Verify EVERY reverted file is byte-identical to the target commit
for f in <file1> <file2> ...; do
  git show "<sha>:$f" | diff -q - "$f" > /dev/null 2>&1 \
    && echo "OK (reverted): $f" || echo "DIFFERS: $f"
done
```

**Parent must run the verification loop after the wave** — subagent self-reports of "reverted" are not proof. Files that DIFFER get re-applied by the parent before compiling. For the "revert + delete" combo, `git rm -f` the new files the feature added (their absence is also part of the revert).

If you do use subagents for code-audit / cleanup tasks (multiple independent fixes across the codebase), see `references/subagent-orchestration-pitfalls.md` first — it covers plan validation before dispatch, commit races in parallel batches, timeout recovery, untracked files, post-batch parent fix-up, and the "audit done but big file never written" iteration-limit trap with its re-dispatch-with-pre-digested-analysis recovery (§8). Then follow these rules learned from a 24-task MyApp platform audit:

### Validate the plan against the codebase BEFORE dispatching

Plans written from prior session context or by another agent are often stale. Before executing, verify every claim:

- Run the grep/search commands the plan assumes will return specific results. If the plan says "only 3 copies of slugify exist," verify — the real count might be 7.
- Read the files the plan says to modify. Line numbers and function signatures drift between sessions.
- Check whether the plan proposes adding something that already exists. The MyApp plan said "add pagination to list_pages" but `list_pages` already had `limit: 50` as a default.
- Check for incorrect technical assumptions. The MyApp plan said "ts_headline escapes HTML" — it does NOT (see code-audit-patterns §16).
- Check for functionality that would break if the plan's change is applied. The plan proposed an ETS cache for markdown rendering, but the cache key didn't include `inline_links` or `embeds`, which would serve stale HTML.
- Check for over-engineering. The plan proposed adding Oban for queue persistence, but the queue is a permit serializer, not a job queue — no jobs to persist.

This validation step catches plan errors before you waste subagent cycles on them. A plan that hasn't been validated against the current codebase is a liability, not an asset.

**Write a corrected plan file** (e.g. `plan-v2.md`) with the fixes, then dispatch from that. Don't dispatch from the original unvalidated plan.

### Subagent LiveView tests: `render_hook` vs `render_click`/`render_submit` (CRITICAL)

Subagents writing LiveView tests habitually misuse `Phoenix.LiveViewTest.render_hook/3` for components that use `phx-click`/`phx-submit` bindings. `render_hook` is ONLY for `phx-hook` JS hooks — using it on a `phx-click` element fails with: `(ArgumentError) element selected by "#my-widget" does not have phx-hook attribute`.

**Fix pattern (applied to the MyApp chat widget tests, 2026-07-17):**

| Widget binding | Wrong (subagent default) | Correct |
|---|---|---|
| `<button phx-click="toggle">` | `render_hook("toggle", %{})` | `element("#widget-fab") |> render_click()` |
| `<form phx-submit="send">` | `render_hook("send", %{"text" => "x"})` | `element("#widget-form") |> render_submit(%{"text" => "x"})` |
| `<button phx-click="clear">` | `render_hook("clear", %{})` | `element("#widget-clear") |> render_click()` |

**Also:** give every test-targeted element a unique DOM id (`id={"#{@id}-fab"}`, `id={"#{@id}-form"}`, `id={"#{@id}-clear"}`) — subagents default to selecting the component's container div (`#chat-widget`), which has `phx-target` but no event binding, so clicks/submits can't attach. Add the ids to the component template yourself before fixing the test file.

**For the full MyApp LiveView test conventions** (session setup, inference disabling, gettext assertions), see `references/MyApp-liveview-testing-patterns.md`.

### Subagent leaves debug artifacts behind

A subagent that hits a failing test it can't explain often creates a temporary `*_debug_test.exs` file with `IO.inspect` dumps and non-existent helpers (e.g. `String.find/2`) to investigate, then forgets to delete it. The debug file fails suite-wide (`UndefinedFunctionError`) even though all real tests pass.

**Post-wave check:** `git status --short` for unexpected `*debug*` files, and if a single test fails with a bizarre error (`String.find`, `IO.inspect` in output) right after a subagent wave, look for a stray debug test file before debugging the app code. Delete it and re-run.

### `:eaddrinuse` when running `mix test` after a subagent wave

Subagents validating UI changes often leave `mix phx.server` running on port 4000/4002, which makes the next `mix test` fail with `DranWeb.Endpoint ... :eaddrinuse` (the test env endpoint tries to bind the same port). This is expected multi-agent noise, not a real failure.

**Fix:** `lsof -ti :4000 | xargs kill -9` (and :4002) before `mix test`, or run tests on a different port: `PORT=4199 mix test`. Don't let the parent agent kill a dev server Álvaro may be using — prefer the `PORT=` override when in doubt.

### Counters in agent engine tests: `Process.get` doesn't survive Tasks

Subagents testing agent session side-effects (token usage accumulation, step counts) often write a counting helper with `Process.get(:count, 0)` / `Process.put(:count, n+1)` and assert on it after `Engine.run/4`. This ALWAYS returns 0 because the engine's `single_turn` runs in a `Task` — a different process with its own dictionary.

**Fix:** use `:counters` (`:counters.new(1, [])` + `:counters.add(ref, 1, 1)`) or an `Agent` for cross-process counting in engine tests. See the MyApp `engine_test.exs` token-accumulation test for the `:counters` pattern.

### UI screenshot capture for README via Hermes browser tools

When the final plan task asks for README screenshots of a Phoenix app, a subagent with Playwright can stall for 10+ minutes on `npx playwright install chromium` (large download) and produce nothing. The faster path is the parent's own browser tools against the already-running dev server:

1. `browser_navigate("http://localhost:4000/login")` — read the auth plug for default creds (`auth.ex` module attributes, e.g. `System.get_env("DRAN_USERNAME", "admin")`)
2. `browser_type` + `browser_click` to log in
3. For each view: `browser_navigate(url)` → `browser_vision(question)` — the vision call returns a `screenshot_path`
4. `cp <screenshot_path> docs/screenshots/<view>.png`
5. For content below the fold, `browser_console(expression: "...scrollIntoView...")` before `browser_vision` — `browser_scroll(direction: "down")` alone often doesn't reach far enough on long settings pages

Then update the README `## Screenshots` section to reference only the files that actually exist (drop placeholders for views you didn't capture — a broken image link in a README is worse than a missing section). Clean up any `node_modules`/`package.json`/`capture.js` the stalled subagent left in `docs/screenshots/` before committing.

A `status=timeout` does NOT mean "nothing happened" — the subagent may have edited or created files but never committed. After a timeout:

1. `git status --short` — look for modified files that should have been committed
2. `mix compile --warnings-as-errors` — check if the tree is in a working state
3. If the work looks complete, verify + commit it yourself instead of re-dispatching
4. Re-dispatch only when the files are absent or half-written

### Frozen subagents that never write (mtime watchdog)

The inverse failure also happens: a subagent stays "running" for 1+ hour and writes NOTHING — distinct from the usual timeout-leaves-finished-work pattern. Seen on 2026-07-19: 2 of 3 UI-polish subagents (kanban_live.ex, layouts.ex) never touched their target files while their sibling finished fine, and the consolidated batch result never arrived either.

**Detection — don't wait for the batch result, poll target-file mtimes:**

```python
import os, time
watch = ["/abs/path/to/file_a.ex", "/abs/path/to/file_b.ex"]
for i in range(8):
    changed = [os.path.basename(f) for f in watch if os.path.getmtime(f) > time.time() - 1800]
    if len(changed) == len(watch): break
    time.sleep(30)
```

**Rule:** if a subagent's target file shows no mtime change after ~30-45 min (UI-polish tasks should write within 10-15 min), declare it frozen, do the task yourself (it's usually small — that's why you delegated it), and move on. When the frozen subagent's result eventually arrives, treat its diff as suspect: it may rewrite the file from a stale pre-read snapshot and clobber your fix — review with `git diff` before keeping anything.

### Inter-phase commits: commit after every wave, not just at the end

Álvaro wants commits **between tasks**, not a single mega-commit at the end of a phase. After each subagent wave (or after completing a serial task yourself), run the verification gate and commit immediately:

```bash
# After wave N finishes and passes verification
git add <files-from-wave-N>
git commit -m "feat: <wave-N-scope>"

# Then dispatch wave N+1
```

**Why:** if a later wave breaks something, you can `git reset --hard HEAD~1` to the last known-good state without losing the earlier waves' work. It also makes `git log` a readable audit trail of what each wave accomplished.

**Commit message convention for waves:**
- `feat: <what the wave built>` — for new functionality
- `fix: <what the wave fixed>` — for bug fixes
- `refactor: <what the wave cleaned>` — for deduplication/moves
- `chore: <what the wave maintained>` — for indexes, config, formatting
- `docs: <what the wave documented>` — for README/SKILL updates
- `test: <what the wave covered>` — for test-only waves

### Post-batch parent fix-up is normal

After every subagent batch, expect to do a quick cleanup pass:

- Unused imports/aliases from removed code (e.g. extracting functions to a new module leaves `import OldModule` behind)
- Files created by a timed-out subagent that another batch's compile flags as "module undefined" because the file was never added to git
- Warnings in files the subagent touched but didn't fully clean up

Budget 2-3 minutes between batches for: `mix compile --warnings-as-errors`, remove unused imports, `git add` any stray untracked files, amend or commit, then dispatch the next batch.

### Parallel subagents race on the same git working tree

Even when tasks touch disjoint files, multiple subagents can stage and commit simultaneously because they share the same git index. The result: one commit contains 3 different tasks, or a subagent's "commit" is empty because another subagent already committed the changes.

**Symptoms:**
- Subagent A says "committed as b372a47" but that commit also contains Subagent B's and C's changes.
- Subagent D says "nothing to commit — the change was already applied" because A/B/C already committed it.
- The commit message only mentions one task but the diff contains several.

**Mitigation:**
1. After every parallel batch, run `git log --oneline` and `git show --stat <hash>` yourself. Verify each commit contains exactly what the plan says it should.
2. If commits are bundled, use `git reset --soft origin/main` to unstage everything, then commit each task individually with the correct message.
3. Or: dispatch tasks that touch git sequentially, not in parallel. Tasks 1-5 of the MyApp audit (all independent file edits) could have been parallel if they didn't all commit — but the commit step makes them serial.
4. Always verify `git status --short` after a batch — if it shows files from multiple tasks staged together, you have a bundling problem.

### Subagent self-reports diverge from reality

Subagents report "completed" but the actual state differs. Common divergences:
- **Commit bundling:** Multiple subagents' changes land in a single commit because they raced on the working tree.
- **"Already done" confusion:** A subagent reports "the change was already applied" because a prior subagent in the same batch applied it. The commit hash exists but under a different message.
- **Test failures attributed to environment:** Subagent blames "port collision" or "pre-existing failure" when the actual cause is their own incomplete patch.

**Rule:** After every batch, run `mix compile --warnings-as-errors`, `mix test`, and `git log --oneline` yourself. Don't trust the summary text — verify the artifacts.

### Recovering from mixed subagent commits

When parallel subagents bundle multiple tasks into one commit (or commit under the wrong message), recover with `git reset --soft` + individual re-commits:

```bash
# 1. Unstage everything back to origin/main (keeps working tree changes)
git reset --soft origin/main
git reset  # unstage all

# 2. Commit each task individually
git add lib/dran_web/live/page_detail_component.ex
git commit -m "refactor: remove dead PageDetailComponent module"

git add lib/dran_web/html_sanitizer.ex lib/dran_web/live/search_live.ex
git commit -m "fix(security): sanitize search excerpts to prevent XSS"

# 3. Verify clean history
git log --oneline origin/main..HEAD
```

**Prevention:** If tasks must commit, dispatch them sequentially. If they're read-only analysis, parallel is fine. The commit step is what makes them serial.

### Subagent tests that trigger external HTTP calls hang the suite

Subagents writing tests often configure `base_url` to a non-existent server but forget to disable it entirely. With `async: false` and `schedule_async: false`, each `Brain.create_page` call triggers `PageAugmenter.schedule/1` → HTTP request → 3 retries × 7s timeout = 21s per page. 25 tests × multiple creates = suite hangs for minutes.

**Fix:** In test setup, set `base_url: nil` to make `Inference.enabled?()` return `false`, short-circuiting the augmenter before any HTTP call:

```elixir
setup do
  original = Application.get_env(:MyApp, :inference)

  Application.put_env(:MyApp, :inference,
    base_url: nil,  # ← this is the key
    api_key: nil,
    timeout: 100,
    schedule_async: false
  )

  on_exit(fn ->
    if original, do: Application.put_env(:MyApp, :inference, original),
      else: Application.delete_env(:MyApp, :inference)
  end)

  # ... rest of setup
end
```

The `base_url: nil` is what makes `MyApp.Inference.Config.enabled?()` return `false`, which causes `PageAugmenter.schedule/1` to return `:ignored` immediately without attempting any HTTP call.

### Subagent syntax errors in HEEx and sigils

Subagents generating HEEx templates often produce:

| Error | Fix |
|-------|-----|
| `missing terminator: " (for sigil ~p"` | Remove nested quotes: `~p"/path?key=value"` not `~p"/path?#{%{key: "value"}}"` |
| `undefined function sigil_p/2` | Component doesn't `use Phoenix.VerifiedRoutes` — use plain string `"/path"` instead |
| `Gettext macros expect message keys to expand to strings` | `gettext(dynamic_var)` is invalid — use `dynamic_var` directly, or `Gettext.gettext(DranWeb.Gettext, dynamic_var)` |
| `attribute "phx-hook" requires the "id" attribute` | Add `id="hook-name"` to the element |

**Recovery workflow after every subagent batch:**
1. `git diff --stat` to see the blast radius
2. `mix compile --warnings-as-errors 2>&1 | head -30` to find the first error
3. Read the broken file, fix the syntax yourself
4. Re-compile, fix next error, repeat
5. Only commit after compile + test pass

### Untracked files from subagents

Subagents sometimes create files but don't `git add` them (e.g. `lib/dran_web/page_types.ex` created but untracked). After every batch:

```bash
git status --short  # look for ?? entries that should be tracked
```

Add them to the correct commit with `git add <file> && git commit --amend --no-edit` (if the commit is still HEAD) or create a fixup commit.

## Ecto migration & schema pitfalls (generic)

When writing Ecto migrations, schemas, or context functions for any Elixir
project (not just umbrella apps), see
`references/ecto-migration-and-schema-pitfalls.md` for: partial unique indexes
blocking same-transaction UPDATE→INSERT (the "replace_api_key" problem with
three fix options — in-place UPDATE, DELETE+INSERT, or DEFERRABLE),
`references/2` rejecting the `:null` option, `assoc_constraint` error key
naming (association name, not FK column), sandbox+transaction visibility
diagnostics, API key generation pattern (sha256 + base64url + prefix),
Bcrypt registration/auth changeset patterns with timing-safe
`no_user_verify/1`, native PG RANGE-partitioned tables with Ecto (raw SQL
migrations, composite primary keys, `inserted_at` as partition key),
append-only tables with `timestamps(updated_at: false)`, `:map` field
atom-vs-string key behavior, DB-defaulted fields never failing
`validate_required`, and same-second insert ordering nondeterminism.
Also covers two **runtime** (non-migration) patterns: §16 `Map.put/3` on
Ecto structs for transient non-schema fields (avoids the `%{struct | field: val}`
compile warning under `--warnings-as-errors`), and §17 `Repo.preload/3` with
`force: true` to re-load associations explicitly set to `nil` (plain preload
treats `nil` as already-loaded and is a no-op even when the FK is present).
