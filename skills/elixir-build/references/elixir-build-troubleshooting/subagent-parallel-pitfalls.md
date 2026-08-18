# Subagent Parallel Execution Pitfalls — my_app Session 2026-07-16

Real issues from a 21-commit subagent-driven improvement session on the my_app Phoenix 1.8 app.

## 1. Commit message bundling across parallel subagents

**What happened:** 5 subagents ran in parallel. Each was told to commit with a specific message. The first subagent to finish committed ALL working-tree changes under its message ("refactor: remove dead PageDetailComponent"), sweeping up the other 4 subagents' changes.

**Fix:** The orchestrator (parent agent) must:
1. After each batch, run `git status --short` and `git log --oneline -3` to see what actually got committed
2. Use `git reset --soft origin/main` to unbundle mixed commits
3. Re-commit each logical change with its correct message
4. Never let subagents commit directly in parallel batches — either sequence the commits or have the orchestrator do them

## 2. Subagent timeout ≠ work not done

**What happened:** Task 1/5 (delete dead component) timed out at 600s, but the file was already deleted and committed. Task 2/5 (XSS sanitizer) also timed out but left 15 passing tests and a working sanitizer.

**Rule:** A timeout means the *report* exceeded the limit, not that the work failed. Always check:
- `git log --oneline -5` — is there a commit with the task message?
- `git status --short` — are the expected files modified?
- `mix compile --warnings-as-errors` — does it compile?
- `mix test` — do tests pass?

If yes to all: the work is done, don't re-dispatch.

## 3. Parallel subagents + same file = broken syntax

**What happened:** Multiple subagents edited `page_components.ex`, `page_list_components.ex`, and `search_live.ex` in parallel. Result: `TokenMissingError` from unescaped quotes in `~p` sigils, missing `Phoenix.VerifiedRoutes` import, and `gettext(dynamic_var)` compile errors.

**Rule:** Batch subagents by **file dependency**, not by task count. If two tasks touch the same file, run them sequentially or merge them. After every batch, the orchestrator must compile and fix syntax errors before dispatching the next batch.

## 4. Test files that trigger external HTTP calls hang the suite

**What happened:** Subagent created `smart_collection_test.exs` with `async: false` and `schedule_async: false`, but left `base_url` pointing to `http://localhost:8000`. Every `Brain.create_page` call triggered `PageAugmenter.schedule/1` → HTTP request → 3 retries × 7s timeout = 21s per page. 25 tests × multiple creates = suite hangs.

**Fix:** In test setup, set `base_url: nil` to make `Inference.enabled?()` return `false`, short-circuiting the augmenter:

```elixir
Application.put_env(:my_app, :inference,
  base_url: nil,  # ← this is the key
  timeout: 100,
  schedule_async: false
)
```

## 5. Gettext in subagent-generated code

**What happened:** Subagent wrapped UI strings in `gettext()` calls but used dynamic variables: `gettext(label)` where `label` comes from a for-loop. Gettext requires compile-time strings.

**Fix:** For dynamic labels, don't use `gettext()` — render the variable directly. If translation is needed, use `Gettext.gettext(DranWeb.Gettext, dynamic_string)` (function form, not macro).

## 6. `~p` sigil in components without VerifiedRoutes

**What happened:** Subagent used `~p"/collections/new"` in `page_list_components.ex`, but the component doesn't `use Phoenix.VerifiedRoutes`.

**Fix:** In function components, use plain strings `"/collections/new"` or add `use Phoenix.VerifiedRoutes, endpoint: DranWeb.Endpoint, router: DranWeb.Router, statics: DranWeb.static_paths()` to the component.

## 7. LiveView streams vs. assigns mismatch

**What happened:** Subagent A converted `page_list_components.ex` to use `@streams.pages`. Subagent B didn't update the LiveViews to use `stream(socket, :pages, pages)` — they still used `assign(socket, pages: pages)`.

**Fix:** Streams and assigns are not interchangeable. Either:
- Use `stream/3` in the LiveView AND `phx-update="stream"` + `@streams.pages` in the component, OR
- Use `assign/3` in the LiveView AND `@pages` in the component.

Never mix them. The orchestrator must verify both sides match after subagent batches.

## 8. i18n locale routes must exist before the switcher works

**What happened:** Subagent added a locale switcher in the layout with `href={~p"/locale/en"}` but didn't create the route or controller.

**Fix:** Always verify routes exist before referencing them. For locale switching, you need:
1. A route: `get "/locale/:locale", LocaleController, :set`
2. A controller that sets `Plug.Conn.put_session(:locale, locale)` and redirects back
3. The `Gettext` backend configured to read the locale from session

## 9. Health check endpoint must be outside auth pipelines

**What happened:** Subagent added `/health` but inside the `:auth` pipeline, making it useless for monitoring (returns 401).

**Fix:** Health checks must be in a public scope with only `:api` pipeline (or no pipeline):

```elixir
scope "/", DranWeb do
  pipe_through :api
  get "/health", HealthController, :show
end
```

## 10. PageVersion diff viewer needs `list_page_versions/1` to exist

**What happened:** Subagent created a diff component but didn't verify `Brain.list_page_versions/1` existed. It did (brain.ex:1004), but the subagent didn't check before writing the component.

**Fix:** Always verify the data layer supports the feature before building UI. A quick `grep -n "list_page_versions" lib/my_app/brain.ex` would have confirmed it exists.

## 11. Subagent stuck in a search/read loop writes NOTHING — the inverse of "timeout ≠ work not done"

**What happened (my_app session 2026-07-19):** Two parallel UI-polish subagents (layouts.ex modernization, global kanban restyle) burned their full 600s and 100 API calls repeatedly re-searching the same CSS class patterns (`grep btn-primary|btn-ghost...` returning zero matches over and over) and re-reading the same files. Final report: "task NOT completed — file was not modified". A third subagent on the same wave finished normally in 223s.

**Rule:** §2 says "timeout usually means work IS done — check disk". This is the inverse: a subagent that enters a read/grep discovery loop produces nothing, and the report itself confesses ("Outcome: Task NOT completed"). Before re-dispatching, check file mtimes (`stat -f "%Sm %N" <files>`) — if the target file was never touched, the work does not exist.

**Recovery — do it yourself, don't re-dispatch the same prompt:** when the task is small and well-specified (a restyle of one file/section), the parent should just make the edit directly. Re-dispatching the identical prompt to the same model that just looped for 600s usually loops again. If you do re-dispatch, strip the exploratory steps from the prompt — the stuck agent already "discovered" the design tokens, so tell the next one the answer instead of letting it re-search.

**Prevention in prompt design:** for UI polish tasks, include the needed design tokens/classes IN the prompt (e.g. "available classes: .surface-2, .lift, .text-title, btn-primary...") so the subagent never needs a discovery phase. Discovery loops are where leaf agents die.

## 12. Subagent sweeps parent's uncommitted work into its own commit (2026-07-19)

**What happened:** The parent dispatched a subagent to fill empty Spanish `msgstr` entries in `priv/gettext/es/LC_MESSAGES/default.po`. While the subagent ran, the parent made its own edits (kanban duplicate button removal, `page_new_live` gender-aware labels). The subagent finished, ran `git add -A && git commit`, and its commit bundled **both** the .po translations AND the parent's uncommitted edits under a single "fix: complete Spanish translations" message. The parent then ran `git status --short` → clean, `git log --oneline -1` → one commit — and initially couldn't tell whether its own edits were inside that commit or lost.

**Rule:** §1 covered parallel subagents racing each other on the git index. This is the sequential variant: a *single* subagent with `git add -A` sweeps up whatever the parent left uncommitted. After ANY subagent batch completes, the parent must:

1. `git log --oneline -3` — does the latest commit message cover MORE than the subagent's scope?
2. `git show <sha> --stat` — are the parent's files in the diff?
3. If yes: the work is integrated (fine), but the commit message is now a lie — consider `git commit --amend` to fix the message, or accept it and move on.
4. If the parent's edits are NOT in the commit and `git status` is clean: they were lost (reset or overwritten) — re-apply from memory or `git reflog`.

**Prevention:** before dispatching a subagent that will commit, either (a) commit your own pending work first, or (b) tell the subagent explicitly: "do NOT run `git add -A`; stage ONLY these files: `<list>`". Option (a) is safer — subagents don't always follow staging instructions.

## 13. Gettext merge corrupts existing msgstr via fuzzy matching (2026-07-19)

**What happened:** After a wave of subagent edits introduced new `gettext()` calls, the parent ran `mix gettext.extract --merge`. The merge silently changed `msgid "None"` (used as the prompt for ALL `<select>` elements — "None", "Sin objetivo", "Sin proyecto") from `msgstr ""` to `msgstr "Hecho"`. The UI then showed "Hecho" as the first option in every Project/Goal/Plan/Status/Priority select. No error, no warning — the fuzzy matcher decided "None" was close enough to "Done" (which had `msgstr "Hecho"`).

**Rule:** `mix gettext.extract --merge` is NOT safe to run blindly. The fuzzy matcher fills empty msgstrs with the nearest existing translation — and "nearest" is a string-distance heuristic, not a semantic one. After every merge:

1. `git diff priv/gettext/es/LC_MESSAGES/default.po | grep "^+msgstr"` — scan every added/changed msgstr
2. Look for msgstrs that don't match their msgid (e.g. `msgid "None"` → `msgstr "Hecho"`)
3. Fix the msgstr manually AND remove the `#, fuzzy` flag (fuzzy entries get re-matched on the next merge)
4. If the same msgid is used in multiple UI contexts, split it: `gettext("Sin objetivo")` for Goal selects, `gettext("Sin proyecto")` for Project selects — context-specific msgids can't be cross-contaminated

**Diagnosis shortcut:** if the UI shows a translated string that makes no sense in context ("Hecho" as a select prompt), grep the .po for that msgstr value to find which msgid it belongs to:

```bash
grep -B2 'msgstr "Hecho"' priv/gettext/es/LC_MESSAGES/default.po
```

## 14. Dynamic gettext msgids vanish on every extract — extraction markers (2026-07-19)

**What happened:** Page type labels ("Note", "Concept", "Todo", etc.) are stored as plain strings in a map (`%{"note" => %{label: "Note"}}`) and translated at runtime via `Gettext.gettext(DranWeb.Gettext, label)`. The parent added correct Spanish msgstrs to the .po, but every `mix gettext.extract --merge` deleted them — because the extractor only scans for `gettext("literal")` calls in source, and these msgids only exist as map values.

**Fix:** add a dead-code extraction block at the end of the module:

```elixir
# page_types.ex — at the bottom, after all real functions
if false do
  gettext("Note")
  gettext("Concept")
  gettext("Entity")
  # ... all labels and plurals
end
```

The `if false` guard means the code never executes, but the extractor sees the msgids and preserves them through merges. Without this, translations for dynamic lookups are deleted on every merge and the UI falls back to English.

**Requires:** `use Gettext, backend: DranWeb.Gettext` at the top of the module (imports the `gettext/1` macro). Do NOT use `import DranWeb.Gettext, only: [gettext: 1]` — Gettext is a backend, not a module with importable macros.
