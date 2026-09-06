# Architecture Specs & Audit

Two sibling tasks over an existing codebase: **producing architecture
specs** (for reimplementation/porting) and **auditing** (bug-finding,
improvement planning). Same systematic reading; different output shape.

## Specs: analyze → spec documents

### When to use

- "Analyze this repo and create specs for a clone in X stack"
- "Create specs for porting this to Elixir/Phoenix"
- "Design the architecture for a version of this that also does Y"
- "Spec out a reimplementation with agent/MCP support"

### Core workflow

```
scope → read systematically → map concepts → write specs progressively
```

1. **Scope** — project manifest (`mix.exs` / `package.json` / etc.),
   README, file inventory. Identify: public API surface, entry points,
   layout, dependencies.
2. **Read systematically** — batch 5-8 independent reads per turn, NEVER
   one at a time, in layers:
   - Layer 1 — types & contracts (schemas, config types, public API)
   - Layer 2 — core logic (context modules, domain logic, mutations, storage)
   - Layer 3 — UI / rendering (app shell, router, pages, components)
   - Layer 4 — server / API (routes, WebSocket/realtime, serialization)
   - Layer 5 — design / theming (design system, presets, CSS variables)
3. **Map concepts source → target** — build a mapping table (e.g. React
   Page component → HEEx function component; filesystem → DB records;
   BroadcastChannel → Phoenix PubSub). This table goes in the overview
   spec — the single most useful artifact for the reader; it bridges
   mental models.
4. **Write specs progressively** in a `specs/` directory, in dependency
   order: overview → data model → rendering → components → integration →
   routes → roadmap. Each file builds on the previous (data model informs
   rendering, rendering informs components, components inform the tool
   catalog). Adapt the list to the codebase (5-6 files for a simple
   project, 15+ for a complex one).

### Spec file quality bar

- **Concrete code examples** in the target language (real Elixir/HEEx/SQL,
  not pseudocode).
- **ASCII mockups** for UI components.
- **Tables** for structured comparisons (props, fields, tools).
- **Props/attrs listed explicitly** for each component.
- **Event names** for LiveView/real-time interactions.
- **SQL DDL** for the data model (actual `CREATE TABLE`, not "a table for
  users").

Bad: "The system has a canvas component that scales to fit."
Good: `attr`/`slot` declarations + a `~H"""` template.

### Key architectural patterns

- **Content as declarative data, not code strings** — when porting from a
  filesystem-embedded content system (JSX/TSX) to a DB-backed one, store
  content as structured JSONB. A renderer pattern-matches on `type`; edit
  operations become JSONB mutations, not AST surgery.
- **Umbrella for separable concerns** — prefer an umbrella over a single
  app when concerns separate: a `core` app (pure logic, Ecto + no Phoenix)
  that all web apps depend on; separate web apps that never know about
  each other. Tool **implementations** live in core; the **endpoint**
  lives in the app that needs it. Short, clean app names.
- **Agent/MCP integration as first-class** — every CRUD operation gets a
  tool; include a tool catalog table, usage sequences, PubSub
  integration, an auth model. Design it as a full API surface, not an
  afterthought.
- **Real-time via PubSub** — replacing client-only sync
  (BroadcastChannel) with server-rendered: mutation → broadcast →
  LiveView `handle_info` → re-render.
- **DESIGN.md as the design-system format** — YAML frontmatter tokens +
  markdown body over ad-hoc palette/fonts/radius columns. Token references
  (`{colors.primary}`) keep the palette single-source; WCAG-checkable;
  exportable to Tailwind theme JSON or W3C DTCG. Rendering pipeline: parse
  frontmatter → cache as tokens JSONB → generate one CSS var per token →
  resolve references.
- **Widget-first architecture** — with configurable widgets, define a
  `props_schema` per widget type; the inspector reads it and
  auto-generates editing fields. The schema doubles as validation for tool
  inputs and as documentation.
- **Concept pivots — rewrite, don't patch**:
  - Replacement pivot (changing the fundamental unit of construction,
    removing a document type, changing the rendering model) → delete the
    old specs and start clean; leftover references contaminate.
  - Additive pivot (keep the widget catalog; layer on layouts/styles) →
    rewrite data model + rendering specs, keep the catalog.
  - Field addition or size correction is NOT a pivot → patch in place.
  - Pivots can happen more than once in a session; recognize which kind
    each one is.

### Pitfalls

- Reading files one at a time — batch 5-8 per turn.
- Skipping the concept mapping table.
- Writing pseudocode instead of real code.
- Forgetting the phased roadmap.
- Over-specifying trivial parts — focus on architectural decisions, data
  model, rendering pipeline, integration surfaces.
- Ignoring the "why" — explain each decision briefly.
- Assuming all document types share one canvas — if multiple types with
  different aspect ratios or orientations can exist, add a size field from
  the start; canvas, thumbnails, overview, defaults, and export all branch
  on it.
- Patching when you should rewrite (concept pivot).

## Audit: read → baseline → findings → phased plan

For bug/improvement requests on an existing codebase (not porting):

1. **Read systematically** — same layering as specs; batch by layer
   (all domain modules in one turn, all LiveViews the next).
2. **Baseline check first**:
   ```bash
   mix compile --warnings-as-errors && mix test
   ```
   If the project doesn't compile or tests fail, the FIRST task in the
   plan is fixing that, not auditing.
3. **Scan the recurring anti-patterns** (full grep command list in
   `references/phoenix-audit-checklist.md`): dead/duplicate modules,
   `raw()` XSS, pattern-match crashes on nil assigns, N+1 in templates,
   missing pagination, no caching of expensive renders, missing debounce
   on PubSub-driven refreshes, unused parameters/dead UI controls, inline
   JS.
4. **DRY dimension is mandatory** — users expect a DRY/modularization
   phase even when they don't ask. Before reporting duplicated functions,
   check the web app's `my_app_web.ex` auto-imports: a function called in
   11 files may be defined in one place and auto-imported — that is NOT
   duplication. Only report duplication when the same `defp` is defined
   in 2+ files.
5. **Categorize findings into phases**: Bugs → Performance → DRY/Code
   Quality → Functionality → Hardening → Docs.
6. Each task in the plan: exact file, exact line number, exact fix,
   verification command.

### Audit output shape

Per finding: What · Where (file:line) · Evidence · Fix shape. Findings
become a phased improvement plan, not a wall of complaints.