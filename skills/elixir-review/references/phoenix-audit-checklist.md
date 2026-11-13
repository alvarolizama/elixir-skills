# Phoenix Audit Checklist

Recurring anti-patterns in Phoenix/LiveView codebases and how to spot them
during an audit. Each pattern: what to grep/look for, why it's a problem,
and the fix shape.

## 1. Dead / duplicate modules

**Grep:** `grep -r "ModuleName" lib/ --include="*.ex"`

Look for modules defining functions with the same name as another module
but with incompatible signatures — common when a component is rewritten
but the old file is never deleted.

**Example:** `PageViewComponent` in `live/` defined `page_detail/1` with
`attr :page, :map` + `attr :label, :string`, while the real
`page_detail/1` in `components/page_components.ex` takes `attr :page`,
`attr :relations`, `attr :versions`, `attr :logs`, `attr :context_slug`,
and slots. Nobody imported the dead module.

**Fix:** Delete the dead file, verify with `mix compile --warnings-as-errors`.

## 2. XSS via `raw()` on user content

**Grep:** `grep -rn "raw(" lib/ --include="*.ex" --include="*.heex"`

`raw()` bypasses HEEx auto-escaping. If the input comes from user content
(even indirectly through DB functions like `ts_headline`), it's a risk.

**Example:** a search LiveView used `{raw(result.excerpt)}` where the
excerpt came from PostgreSQL `ts_headline()`. `ts_headline` escapes by
default, but `raw()` is unnecessarily dangerous — if the excerpt source
ever changes, it becomes an XSS vector.

**Fix:** Remove `raw()`, let HEEx escape. If HTML formatting is
legitimately needed (e.g. `<mark>` highlights from `ts_headline`), sanitize
explicitly rather than blindly trusting the source.

## 3. Pattern-match crash on nil context

**Look for:** `handle_event` clauses that pattern match on
`%{assigns: %{context: %{id: context_id}}}` without a fallback that
handles `context: nil`.

**Example:** a page editor matched
`%{assigns: %{page: %Page{} = page, context: %{id: context_id}}}` for a
field-change event. If `socket.assigns.context` is `nil` (user without
context), the match fails and crashes the process. The fallback clause
only caught missing `%Page{}`, not missing context.

**Fix:** Loosen the match to `%{assigns: %{page: %Page{}}}`, then extract
`context_id` with a `case` that handles nil explicitly.

## 4. N+1 queries in templates

**Look for:** function components calling context functions (e.g.
`Repo.get_by/2`, `get_page_by_slug/2`) inside `:for` comprehensions in
templates.

### 4a. Per-tag lookups

A page components module called `tag_page_exists?(tag, context_id)` and
`tag_link_path(tag, context_id)` per tag. A page with 8 tags = 8 queries.
In a list of 50 pages, that's 250+ queries.

**Fix:** Add a batch function `get_pages_by_slugs(slugs, context_id)`
doing a single `WHERE slug IN (...)` query that returns a map. Pre-load
the map before rendering and pass it to the template.

### 4b. Per-inline-link lookups

`apply_inline_links/3` called `get_page_by_slug(slug, context_id)` per
inline link inside `render_markdown/2`.

**Fix:** Same pattern — batch all slugs into one query, build a
`slug → path` map, then iterate.

## 5. Inline JavaScript (AGENTS.md violation)

**Grep:**
```bash
grep -rn "onclick=\|onchange=\|oninput=" lib/ --include="*.ex" --include="*.heex"
```

Projects with an agents file typically forbid inline `<script>` and inline
JS handlers. `onclick={"window.location.href='...'"}` violates this.

**Example:** a dashboard used
`onclick={"window.location.href='#{page_path(page)}'"}` on a div.

**Fix:** Replace with `<.link navigate={path}>` or a `phx-click` handler.

## 6. Duplicate utility code

**Grep:** `grep -rn "defp slugify" lib/` — if multiple files define the
same private function, it's duplicated.

**Patterns found:**

- `slugify/1` + `unique_slug/3` + `ensure_unique_slug/3` copied across
  three modules (3 copies, nearly identical).
- Type-mapping maps (`@type_labels`, `@type_icons`, `@type_paths`,
  `@type_routes`) duplicated across several LiveViews/components.
- Layout helpers and `@type_colors`/`@edge_colors` duplicated between a
  graph LiveView and its helpers module.

**Fix:** Extract to a shared module (`MyApp.Slug`,
`MyAppWeb.TypeLabels`). Single source of truth; all consumers call the
shared module.

### 6a. PITFALL: Hidden auto-imports cause false duplication reports

**Before reporting a function as duplicated, check `my_app_web.ex` for
auto-imports.** The `live_view` macro auto-imports helpers into all
LiveViews:

```elixir
# lib/my_app_web.ex
def live_view do
  quote do
    use Phoenix.LiveView
    unquote(html_helpers())
    import MyAppWeb.PageComponents  # ← auto-imports format_date, type_path, etc.
    import MyAppWeb.PageListComponents
  end
end
```

A function like `format_date/1` may appear called in 11 LiveViews but is
only *defined* in one place and auto-imported. **This is NOT duplication.**

**How to verify:**

```bash
grep -n "import.*PageComponents\|import.*CoreComponents" lib/my_app_web.ex
```

If the function is in an auto-imported module, it's centralized. Only
report duplication when the same `defp` is *defined* (not just *called*)
in 2+ files.

**Real example:** an audit pass reported `format_date` as duplicated
across 11 LiveViews; it was auto-imported. Only `format_due/1` (a
different function, shorter format) was truly duplicated — defined
privately in one module and should have lived in a shared helpers module.

## 7. Missing pagination

**Look for:** `list_*` context functions that don't accept
`:page` / `:per_page` / `:limit` options.

**Example:** `list_pages(context_id: id, type: "note")` loads ALL pages of
a type with no limit. At scale (1000+ pages) this causes memory and
render-time issues.

**Fix:** Add `limit`/`offset` or `Scrivener.Ecto` pagination. Default to
50 per page. Tiebreak with a stable unique key (see
`diff-review-system-rules.md` PF-06).

## 8. No caching of expensive renders

**Look for:** `render_markdown/2` or similar functions that parse/render
on every LiveView render even when the input hasn't changed.

**Example:** `render_markdown` calls a markdown-to-HTML library + embed
resolution + inline-link insertion on every render. The DB already has a
`body_hash` column that could serve as a cache key.

**Fix:** ETS-based cache keyed by `{body, context_id}`; invalidate on body
change; use `body_hash` to skip the cache lookup when the hash matches
(see LG-02 for the mandatory expiry strategy).

## 9. Missing debounce on PubSub-driven refreshes

**Look for:** `handle_info({:step_completed, ...}, socket)` that directly
calls `Repo.all(...)`.

**Example:** an agent-status LiveView refreshed steps from DB on EVERY
PubSub message. Five quick completions = five rapid DB queries.

**Fix:** Debounce with `Process.send_after(self(), :refresh_steps, 200)`.
Coalesce rapid updates into one DB query.

## 10. Unused parameters / dead UI controls

**Look for:** `defp start_agent("ingest", input, context_id, _opts)` — the
`_opts` is discarded but the UI shows a control that feeds it.

**Example:** a LiveView showed a language `<select>` for both research and
ingest agents, but `start_agent("ingest", ...)` discarded the opts. The
user selects a language and it's silently ignored.

**Fix:** Either pass the opts through to the handler, or hide the UI
control when it isn't applicable.

## Audit reading order for Phoenix apps

```
mix.exs                    → deps, versions, aliases
config/config.exs          → static config
config/runtime.exs         → env-based config, secrets shape
lib/MyApp/application.ex  → supervision tree
lib/MyApp/*.ex            → domain modules (context, schemas, business logic)
lib/my_app_web/router.ex   → routes, pipelines, scopes
lib/my_app_web/live/*.ex   → LiveViews (mount, handle_params, handle_event, render)
lib/my_app_web/components/ → shared components, helpers
lib/my_app_web/plugs/      → auth, rate limiting, etc.
priv/repo/migrations/      → DB schema, indexes, extensions
test/                      → test coverage, test patterns
```

Batch reads by layer — all domain modules in one turn, all LiveViews the
next. 5-6 files per turn.

## Baseline check

Before writing the audit plan, establish the baseline:

```bash
mix compile --warnings-as-errors && mix test
```

If the project doesn't compile or tests fail, the first task in the plan
is fixing that, not auditing.

## Output structure

Organize findings into phases:

1. **Bugs** — correctness/security issues (crashes, XSS, dead code)
2. **Performance** — N+1 queries, missing pagination, no caching, debounce gaps
3. **DRY/Code Quality** — duplicate code, dead modules, missing shared modules
4. **Functionality** — missing features the user would expect
5. **Hardening** — rate limiting, health checks, input validation
6. **Docs** — skill/readme, missing sections

Each task in the plan: exact file, exact line number, exact fix,
verification command.