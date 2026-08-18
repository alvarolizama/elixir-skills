---
name: architecture-specs
description: "Analyze an existing codebase or system and produce comprehensive architectural specs for reimplementation or porting to a different tech stack. Covers the analysis-to-spec workflow: systematic source reading, concept mapping across stacks, progressive spec document writing."
version: 1.0.0
author: Álvaro Lizama
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [architecture, specs, analysis, porting, reimplementation, documentation, design]
    related_skills: [plan, spike]
---

# Architecture Specs

Use this skill when the user wants to **analyze an existing codebase/system and produce architectural specification documents** for reimplementation — typically porting to a different tech stack, adding a major new dimension (e.g., MCP integration), or building a clone with modifications.

This is NOT the same as `plan` (which produces bite-sized TDD implementation tasks) or `spike` (which produces throwaway feasibility experiments). Architecture specs describe WHAT to build and HOW the pieces fit together — the data model, rendering pipeline, component inventory, API surface — not step-by-step implementation tasks.

## When to use

- "Analyze this repo and create specs for a clone in X stack"
- "Create specs for porting this to Elixir/Phoenix"
- "Design the architecture for a version of this that also does Y"
- "Spec out a reimplementation with MCP/agent support"
- User wants to understand a codebase deeply before deciding how to rebuild it

## Audit mode

When the user asks to **audit** an existing codebase for bugs, performance issues, and improvement opportunities (not reimplement or port it), use the audit workflow described in `references/phoenix-audit-checklist.md`. This is a sibling to the spec workflow — same systematic reading, different output shape.

The audit workflow is: **read systematically → run compile+tests → categorize findings → write plan**. See the reference file for the reading order, the recurring anti-patterns to scan for in Phoenix apps, and how to structure the output as a phased improvement plan.

**Critical audit dimension — DRY/modularization:** Always include a DRY/modularization phase in the audit output. Users expect this covered even if they don't ask explicitly. Missing it forces a second-pass audit. Before reporting duplicated functions, check `my_app_web.ex` for hidden auto-imports — a function called in 11 files may be defined in only one and auto-imported. See pitfall 6a in the reference file.

## When NOT to use

- User wants an implementation plan with tasks → use `plan`
- User wants to validate if something is feasible → use `spike`
- User just wants to understand how a codebase works (no reimplementation goal) → just analyze and explain
- The answer is knowable from docs without reading source → just research

## Core workflow

```
scope → read systematically → map concepts → write specs progressively
```

### 1. Scope: understand what exists

Start by reading the project manifest and structure to understand the shape:

```
read_file("package.json")           # or mix.exs, Cargo.toml, go.mod
read_file("README.md")
search_files("*.ts", target="files") # or appropriate glob
```

Identify:
- **Public API surface** — what the library/framework exports (read `index.ts` / `__init__.py` / etc.)
- **Entry points** — CLI, server, main app
- **Layout** — packages, apps, modules
- **Dependencies** — what it relies on

### 2. Read systematically (batch independent reads)

Read in this order, batching independent reads in a single turn:

**Layer 1 — Types & contracts:**
- Type definitions / interfaces / schemas
- Config types
- Public API exports

**Layer 2 — Core logic:**
- Context modules / domain logic
- Editing / mutation operations
- File / storage operations

**Layer 3 — UI / rendering:**
- App shell / router
- Main routes / pages
- Key components (canvas, editor, inspector, player)
- Sub-components (thumbnail rail, sidebar, panels)

**Layer 4 — Server / API:**
- API routes / endpoints
- WebSocket / real-time handlers
- Export / serialization logic

**Layer 5 — Design / theming:**
- Design system types
- Presets / themes
- CSS variable mapping

**Pitfall:** Don't read files sequentially one at a time. Batch 5-8 independent reads per turn. The runtime executes them concurrently, saving round-trips.

### 6. Umbrella structure for Phoenix targets

When the target stack is Elixir/Phoenix, prefer an **umbrella app** over a single app when the system has separable concerns. The pattern that works:

```
project/
├── apps/
│   ├── core/      # logic pura (sin Phoenix): schemas, context, registry, export, MCP tool impl
│   ├── studio/    # crear + editar (LiveView): editor, inspector, pickers, present, MCP endpoint
│   ├── public/    # ver publicado (LiveView): gallery + viewer, sin edición
│   └── admin/     # admin (LiveView): users, moderation, config
├── config/
└── mix.exs
```

Rules:
- `core` **no sabe nada de Phoenix** — solo Ecto + lógica pura. Todas las apps web dependen de `core`.
- Las apps web **no se conocen entre sí** — studio no sabe que public existe, y viceversa.
- El MCP endpoint vive en la app que lo necesita (típicamente `studio`), pero las tool **implementations** (business logic) viven en `core`.
- Namespace convention: `SlideforgeryCore.*` (core), `SlideforgeryStudioWeb.*` (studio), `SlideforgeryPublicWeb.*` (public), `SlideforgeryAdminWeb.*` (admin).
- Config usa `config :slideforgery_core`, `config :slideforgery_studio`, etc. — no namespace umbrella.

**User preference (Álvaro):** short, clean app names (`core`, `studio`, `public`, `admin` — not `slideforgery_core_app`/`slideforgery_editor_app`). Expects correction if naming drifts.

### 3. Map concepts source → target

Create a mapping table in your head (or in the overview spec) showing how each concept translates:

```
| Source (React/TS)        | Target (Elixir/Phoenix)           |
|--------------------------|------------------------------------|
| Page component (React)  | Function component (HEEx)          |
| Filesystem slides       | PostgreSQL records                 |
| Babel AST editing        | JSONB mutation + DB persist         |
| Vite HMR                 | LiveView diffs                      |
| BroadcastChannel         | Phoenix PubSub/Channels             |
```

This table goes in the overview spec. It's the single most useful artifact for the reader — it bridges mental models.

### 4. Write specs progressively

Create a `specs/` directory in the project root. Write files in this order:

| # | File | Content |
|---|------|---------|
| 00 | `overview.md` | Vision, principles, differences table, stack, repo structure |
| 01 | `data-model.md` | Tables/schemas, relationships, JSONB structures, indexes |
| 02 | `rendering.md` | Core rendering pipeline, canvas, element renderer, design→CSS (from DESIGN.md tokens) |
| 03 | `components.md` | Full component inventory with props, behavior, ASCII mockups |
| 04 | `inspector-edit-ops.md` | Edit operations, selection model, element snapshots |
| 05 | `mcp-server.md` | MCP architecture, tool catalog, PubSub, auth |
| 06 | `present-ebook.md` | Presentation mode, reader modes, keyboard shortcuts |
| 07 | `design-themes.md` | Design system structure, presets, themes |
| 08 | `assets-export.md` | Asset storage, upload flows, export formats |
| 09 | `liveviews-routes.md` | Router, LiveViews, events, PubSub handlers |
| 10 | `roadmap.md` | Phases with dependencies, deliverables per phase |
| -- | `README.md` | Index + executive summary |

**Not all projects need all files.** Adapt the list to the codebase. A simpler project might need 5-6 files. A complex one might need 15+.

### 5. Spec file quality bar

Each spec file should include:

- **Concrete code examples** in the target language (not pseudocode). If spec is for Phoenix, write actual Elixir/HEEx snippets.
- **ASCII mockups** for UI components — they communicate layout faster than prose.
- **Tables** for structured comparisons (props, fields, tools, shortcuts).
- **Props/attrs** listed explicitly for each component.
- **Event names** for LiveView/real-time interactions.
- **SQL DDL** for data model (not "a table for users" — actual `CREATE TABLE`).

**Bad spec:**
```
The system has a canvas component that scales to fit.
```

**Good spec:**
```elixir
attr :design, :map, default: nil
attr :scale, :float, default: nil
slot :inner_block, required: true

def slide_canvas(assigns) do
  ~H"""
  <div class="relative h-full w-full overflow-hidden" phx-hook="CanvasScaler">
    <div style={"width: #{@canvas_width}px; height: #{@canvas_height}px; transform: scale(#{@scale || 1});"}>
      {render_inner_block(assigns)}
    </div>
  </div>
  """
end
```

## Key patterns

### Content as declarative data, not code strings

When porting from a system where content is embedded in source code (e.g., JSX/TSX files), convert to **declarative JSONB structures** stored in a database. This is the single most important architectural decision when porting from a filesystem-based system to a DB-based one.

```elixir
# Instead of slides/<id>/index.tsx with JSX:
# Store content as structured data:
[
  %{type: "text", text: "Hello", style: %{"fontSize" => "120px"}},
  %{type: "steps", children: [%{type: "text", text: "Step 1"}]}
]
```

A renderer function pattern-matches on `type` and produces HEEx. Edit operations become JSONB mutations, not AST surgery.

### MCP integration as first-class

When the user mentions MCP/agents, design the MCP server spec as a full API surface — every CRUD operation gets a tool. Don't treat it as an afterthought. Include:
- Tool catalog table (name, description, parameters)
- Example agent usage sequences (JSON-RPC request/response)
- PubSub integration (MCP changes reflect in UI in real-time)
- Auth model

### Progressive file writing

Don't write all specs at once. Write them in dependency order:
1. Overview → 2. Data model → 3. Rendering → 4. Components → 5. Inspector → 6. MCP → 7. Present/Reader → 8. Design → 9. Assets/Export → 10. Routes → 11. Roadmap

Each file builds on the previous. The data model informs rendering, rendering informs components, components inform the MCP tool catalog.

### Real-time via PubSub

When porting from a client-only system (e.g., React with BroadcastChannel) to a server-rendered system (e.g., Phoenix LiveView), replace client-side sync with server-side PubSub:

```
# Source: BroadcastChannel (client-to-client)
# Target: Phoenix.PubSub (server-mediated)
# MCP mutation → PubSub broadcast → LiveView handle_info → re-render
```

### DESIGN.md as the design system format

When the target system has a design system (themes, palettes, typography, components), use **DESIGN.md** — Google's open spec (`google-labs-code/design.md`) — as the storage format, not ad-hoc `palette`/`fonts`/`type_scale`/`radius` columns. A DESIGN.md file combines YAML frontmatter (machine-readable tokens) with markdown body (human-readable rationale).

**Database schema:**
```sql
CREATE TABLE design_systems (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name        TEXT NOT NULL,
  style       TEXT NOT NULL DEFAULT 'craft-handmade',  -- generates the template initial
  design_md   TEXT NOT NULL,                           -- full DESIGN.md (frontmatter + body)
  tokens      JSONB NOT NULL DEFAULT '{}',              -- parsed frontmatter cache
  inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**Why DESIGN.md over ad-hoc fields:**
- Tokens are structured and validated (not loose JSONB blobs)
- Token references (`{colors.primary}`) keep the palette single-source
- WCAG contrast validation via `npx @google/design.md lint`
- Exportable to Tailwind theme JSON or W3C DTCG
- Human-readable rationale lives next to the tokens
- An agent can generate/modify the DESIGN.md via MCP without understanding a custom format

**Rendering pipeline:** parse frontmatter → cache as `tokens` JSONB → generate CSS vars per token → resolve `{colors.primary}` references in components.

**Style → DESIGN.md relationship:** when the system has visual "styles" (like baoyu-infographic's 21 styles), each style generates a DESIGN.md template with tokens that reflect its aesthetic (craft-handmade → warm palette + rounded corners; cyberpunk-neon → dark palette + small radius + glow shadows). The style is the starting point; the user can edit the DESIGN.md freely afterward.

**MCP tools:** `update_design_md` (raw DESIGN.md), `update_design_tokens` (specific tokens), `validate_design` (lint + WCAG), `get_style_design_md` (template per style).

### Widget-first architecture (props_schema drives inspector)

When the target system uses configurable visual components (widgets) instead of raw content elements (text, image, heading), define a `props_schema` per widget type. The InspectorPanel reads this schema and auto-generates the editing fields dynamically. This avoids hardcoding inspector UI per widget type.

```elixir
# Each widget module defines its props schema
defmodule SlideForge.Widgets.MetricCard do
  def props_schema do
    %{
      label: %{type: :string, required: true, label: "Label"},
      value: %{type: :number, required: true, label: "Value"},
      format: %{type: :enum, values: ["raw", "currency", "percent"], default: "raw"},
      delta: %{type: :number, required: false, label: "Delta %"},
      animated: %{type: :boolean, default: true}
    }
  end

  def render(assigns), do: ~H"<div>...</div>"
end

# InspectorPanel renders fields dynamically from schema
<%= for {key, field} <- @schema do %>
  <.prop_field field_key={key} field_def={field} value={Map.get(@props, key)} />
<% end %>
```

The schema doubles as: (1) the inspector field generator, (2) validation for MCP tool inputs, (3) documentation of what each widget accepts.

### Concept reformulation — be ready to throw away and rewrite

The user may pivot the entire concept mid-spec. Example from the open-slide session: specs were initially written for "slide decks + ebooks" with dual canvas sizes. The user then said "Quita lo de los ebooks y slide decks" and reframed the system as "mini apps" with interactive "widgets" presenting data visually. This required deleting all specs and rewriting from scratch with a fundamentally different data model, widget catalog, and component set.

**When the user reformulates:** delete the old specs, don't patch them. A concept pivot isn't an edit — it's a rewrite. The old specs will contaminate the new concept if you try to salvage pieces. Start clean, keep only what's structurally reusable (the analysis of the source codebase, the reading order, the spec file structure).

A concept pivot can happen more than once in the same session. The open-slide session pivoted twice: (1) slides+ebooks → mini apps with widgets, then (2) the user pointed to an external skill (baoyu-infographic) and asked to adopt its 21-layout × 21-style model. The second pivot added the infographic layout system on top of the widget model — pages became infographics with structured layouts (bento-grid, hub-spoke, funnel, venn-diagram...) and named slots where widgets are assigned. This was an **additive** reformulation (the widget model stayed, the layout system was layered on top) rather than a **replacement**. Recognize the difference: a replacement pivot requires a full rewrite; an additive pivot requires rewriting the data model + rendering specs while keeping the widget catalog.

### Adopting external skill models as architecture patterns

When the user references an external skill or tool as the model for a system ("make it like baoyu-infographic but with LiveView components"), load that skill, study its structure, and translate its concepts into the target architecture:

1. **Load the referenced skill** (`skill_view`) and read its full content + references
2. **Map its dimensions to your architecture** — baoyu has layout × style; your system gets `layout_type` (page structure) × `style` (visual aesthetic)
3. **Translate image-generation concepts to component concepts** — baoyu's layouts become layout modules with named slots; baoyu's styles become CSS class sets applied to widgets
4. **Keep the combinatorial model** — 21 layouts × 21 styles = 441 combinations. The power is in the matrix. Don't reduce it to "pick one layout."
5. **Add the new dimensions to the data model** — `pages.layout_type`, `design_systems.style`, `widgets.slot` (named region in the layout)

This pattern — adopting an external skill's conceptual model as an architecture dimension — is distinct from porting a codebase. The source of inspiration is a skill, not a repo. The translation is concept→architecture, not code→code.

## Pitfalls

- **Reading files one at a time** — batch 5-8 independent reads per turn. A 50-file analysis takes 6-8 turns batched vs 50 turns sequential.
- **Skipping the concept mapping table** — without the source→target mapping, the reader has to do the translation themselves. Always include it in the overview.
- **Writing pseudocode instead of real code** — specs with `// do something here` are useless. Write actual Elixir/HEEx/SQL.
- **Forgetting the roadmap** — specs without a phased roadmap leave the reader wondering where to start. Always include phases with dependencies.
- **Over-specifying trivial parts** — don't spec every UI button. Focus on the architectural decisions, the data model, the rendering pipeline, and the integration surfaces (MCP, export, real-time).
- **Ignoring the "why"** — for each architectural decision, briefly explain WHY (e.g., "JSONB instead of JSX strings because edit ops become data mutations, not AST surgery").
- **Assuming all document types share one canvas** — when the target system supports multiple document types (e.g., slide decks AND ebooks), don't assume they share the same canvas dimensions. Slides are 16:9 landscape (1920×1080); ebooks are portrait paper formats (A4 794×1123px or Letter 816×1056px at 96dpi). Add a `canvas_size` field to the document table from the start. The canvas component, thumbnails, overview grid, design defaults, and export pipeline all need to branch on canvas size. This was a user correction during the open-slide→SlideForge spec session — the first pass put ebooks in the 1920×1080 canvas and the user caught it immediately.
- **Patching when you should rewrite** — if the user reformulates the core concept (not just a field addition), delete the old specs and start over. Trying to patch a concept pivot produces Frankenstein specs with leftover references to the old model. A concept pivot is: changing the fundamental unit of construction (elements → widgets), removing a document type entirely, or changing the rendering model. A field addition or canvas size correction is NOT a concept pivot — patch that in place.

## References

- `references/open-slide-to-slideforge-mapping.md` — worked example: full concept mapping table (React/TS → Elixir/Phoenix), spec file inventory, key architectural decisions, and the systematic reading order used to analyze the source codebase.
- `references/phoenix-audit-checklist.md` — recurring anti-patterns in Phoenix/LiveView codebases (N+1 in templates, `raw()` XSS, pattern match crashes on nil context, duplicate utility code, missing pagination/caching, inline JS violations) with grep commands, examples, and fix shapes. Use when auditing a Phoenix app for bugs and improvements.