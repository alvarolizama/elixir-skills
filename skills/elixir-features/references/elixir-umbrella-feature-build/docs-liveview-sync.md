# my_app `/docs` LiveView — sync playbook

The in-app docs page (`lib/dran_web/live/docs_live.ex`, ~1000 lines) renders
tabbed documentation for my_app. It drifts silently as the roadmap ships —
after the 15-phase roadmap (2026-07-17), it still described only the original
2 agents and the pre-roadmap API surface. This file captures the file's
structure so a docs-sync wave can be dispatched quickly.

## Section inventory (as of 2026-07-17)

| Function | Tab | Content |
|---|---|---|
| `overview/1` | Overview | What is my_app, core concepts (contexts, pages, page types, relations, knowledge graph), architecture, getting started |
| `api_reference/1` | API | `<.api_group>` tables of REST endpoints grouped by domain (Contexts, Pages, Relations, Search, Goals, Todos, Ingest, Maintenance, Wiki) |
| `mcp_reference/1` | MCP | Endpoint + session management, "Agent Quick Start" ordered list, Page Types & Subtypes table, `<.mcp_tool>` definitions, resources, prompts |
| `auth_reference/1` | Auth | Env-var table (DRAN_USERNAME / DRAN_PASSWORD / DRAN_API_TOKEN), web UI auth, API auth, MCP auth, client config example, security notes |

Helper components in the same file:

- `api_group/1` — `attr :title`, slot `:endpoint` with attrs `method`, `path`, `desc`.
  `method_class/1` maps GET/POST/PUT/DELETE to badge colors.
- `mcp_tool/1` — `attr :name`, `attr :desc`, slot `:param` with attrs
  `name`, `type`, `required` ("yes"/"no"), `desc`.
- `tabs_bar/1` — tab switcher driven by `@tabs` module attribute and
  `handle_event("switch_tab", ...)`.

## Detection recipe

```bash
# Zero matches across the board = the docs are stale
grep -cE "weekly|curation_agent|gardener|chat|backlink|export|settings" lib/dran_web/live/docs_live.ex
```

Cross-check every endpoint before documenting it:

```bash
grep -n "get\|post\|put\|delete\|live" lib/dran_web/router.ex
```

## What the 2026-07-17 sync added (use as the delta checklist)

**overview/1** — new `<h3>` blocks after "Knowledge graph":
AI Chat (FAB + persisted sessions), Autonomous agents (QA, CurationAgent, Link
Gardener, Weekly Review — batch via MCP `start_agent` or Quantum), Backlinks,
Smart Collections, Full Export (`GET /api/export/:context/full`), Settings
(`/settings`, DB-backed runtime tuning). Also updated the graph paragraph to
mention 2D/3D and relation `weight`.

**api_reference/1** — new groups: Export (`GET /api/export/:context/full`),
Settings (`GET /api/settings`, `PUT /api/settings/:key`), Chat
(`POST /api/chat/sessions`, `GET .../:id`, `POST .../:id/messages`).
Additions to Pages group: `:slug/backlinks`, `:slug/diff?v1=&v2=`.
Addition to Wiki group: `GET /api/graph/3d?context=`.

**mcp_reference/1** — `start_agent` agent_type desc now lists all 6 agents
(`research, ingest, qa, curation_agent, link_gardener_agent, weekly_review`); new tools
`get_settings` and `update_setting`; new resource `settings://current`;
new prompt `weekly_review`.

**auth_reference/1** — env-var table gained DRAN_INFERENCE_URL,
DRAN_INFERENCE_API_KEY, DRAN_EMBEDDING_MODEL, DRAN_CHAT_MODEL; context
paragraph mentions the signed `dran_last_context` cookie + per-context page
counts; new "Runtime Settings" `<h3>`.

## Dispatch template (wave of 3 — disjoint function scopes, same file)

One subagent per section function. They share the file but edit disjoint
function bodies, so no conflict. Rules for the prompts:

- Give each agent the function's approximate line range AND tell it to
  re-read the file first (line numbers drift between sessions).
- Explicit allowlist: "modify ONLY the `<fn>` function body".
- "NO hagas git commit" — parent owns git.
- Each prompt must include the exact HEEx to add (component shapes above) —
  subagents guess wrong when left to invent `mcp_tool` param syntax.
- Parent gate after the wave: `mix compile --warnings-as-errors` →
  `PORT=4199 mix test` → spot-check with `browser_navigate("http://localhost:4000/docs?tab=<tab>")`
  → single `docs:` commit.

## Pitfalls specific to editing docs_live.ex

- **`<pre phx-no-curly-interpolation>` blocks** contain literal `{`/`}` —
  when patching near them, keep `old_string` anchors away from curly braces
  or the fuzzy matcher may bind to the wrong region.
- **HTML entities in code samples** — the file uses `&#123;`/`&#125;` inside
  `<code>` for literal braces outside `phx-no-curly-interpolation` blocks.
  Match that convention when adding resource URIs like `settings://current`.
- **Gettext is NOT used in docs_live.ex** — content is English prose. Don't
  wrap additions in `gettext()` (the module doesn't import it and the rest
  of the file is untranslated).
- **Tab param** — sections render via `if @active_tab == "x"`; adding a new
  tab means updating `@tabs`, `handle_params`, and `page_title` — not just
  dropping in a new function.
