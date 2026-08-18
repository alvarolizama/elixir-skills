# Concept Mapping: open-slide (React/TS) → SlideForge (Elixir/Phoenix)

Reference example from the session that produced the architecture-specs skill. Shows the source→target concept mapping table, spec file inventory, and key architectural decisions.

## Session history — concept evolution

This session went through three phases:

1. **Phase 1 (discarded):** "slides + ebooks" with dual canvas (1920×1080 for slides, A4/Letter for ebooks). User corrected the ebook canvas size, specs were updated. Then the user **reformulated the entire concept**: "Quita lo de los ebooks y slide decks" — the system is not about slides vs ebooks, it's about **mini apps** with **interactive widgets** presenting data visually. All specs were deleted and rewritten.

2. **Phase 2 (additive pivot):** The user pointed to the `baoyu-infographic` skill and asked to adopt its model: "Los widgets deben ser tambien tipo infografia... revisa el skill baoyu para entender como las arma y hacer lo mismo pero con componentes de liveview." This added a **layout × style** dimension on top of the widget model. Pages became infographics with 21 layout types (bento-grid, hub-spoke, funnel, venn-diagram, etc.) and 21 visual styles (craft-handmade, cyberpunk-neon, corporate-memphis, etc.). Layouts define **named slots** (hero, cell_1, spoke_1, step_1, stage_1...) where widgets are assigned. The widget model stayed; the layout system was layered on top.

3. **Phase 3 (final):** "mini apps" with 21 layouts × 21 styles × 37 widgets. Canvas is always 1920×1080. The unit of construction is the **widget** assigned to a **named slot** in a **layout**. Each widget has a `props_schema`. The InspectorPanel auto-generates fields from the schema. Layouts and styles are combinatorial (441 layout×style combinations).

**Lesson 1:** When the user reformulates the core concept (replacement pivot), delete the old specs and rewrite. Don't patch a concept pivot.

**Lesson 2:** When the user references an external skill as the model, load it (`skill_view`), study its structure, and translate its dimensions into the architecture. Baoyu has layout × style; SlideForge gets `layout_type` (page structure) × `style` (visual aesthetic) as DB fields. Image-generation concepts become component concepts: baoyu layouts → layout modules with named slots; baoyu styles → CSS class sets applied to widgets. Keep the combinatorial power (21 × 21 = 441 combinations).

## Source→Target Concept Mapping

| open-slide (React/TS/Vite) | SlideForge (Elixir/Phoenix/LiveView) |
|---|---|
| Slides as `.tsx` files on disk | Apps as DB records (apps + pages + widgets tables) |
| `Page` = React component type | Page = layout config + ordered widgets (JSONB) |
| `SlideModule` = { default: Page[], meta, design, notes } | `Page` struct = { layout: JSONB, widgets: [Widget], notes, transition } |
| Content = JSX elements in a Page component | Content = widgets with `widget_type` + `props` (JSONB) |
| Babel AST editing for inspector | EditOps on JSONB (set_prop, set_layout_slot, etc.) |
| Filesystem as source of truth | PostgreSQL as source of truth |
| Vite dev server API routes (`/__slides`, `/__edit`) | Phoenix LiveView events + context modules |
| React Router routes | Phoenix LiveView routes |
| `useState` / `useEffect` / `useMemo` | LiveView assigns + handle_event/handle_info |
| BroadcastChannel (presenter sync) | Phoenix PubSub + Channels |
| `useAgentSocketConnected` (Vite WS) | MCP server endpoint + PubSub broadcast |
| shadcn/ui React components | Phoenix.Component function components |
| `SlideCanvas` with ResizeObserver | `canvas` component + CanvasScaler JS hook (1920×1080) |
| `<Steps>` / `<Step>` reveal | `step_group` prop on widgets + step_revealed assign |
| `DesignSystem` → CSS vars | Same, injected via HEEx style attribute |
| `export-pdf.ts` (client-side) | Server-side Chromium headless |
| No MCP | MCP server with 40+ tools as Phoenix endpoint |
| Inspector hardcoded per element type | **Inspector auto-generated from widget `props_schema`** |
| No datasources | Datasources (static, CSV, JSON URL, API) for dynamic widget data |
| No widget catalog | **37 widget types** in a registry with props_schema per type |
| No layout system (pages = array of Page components) | **21 layout types** (bento-grid, hub-spoke, funnel, venn-diagram...) with named slots |
| No style system | **21 styles** (craft-handmade, cyberpunk-neon...) as CSS class sets on the design system |
| No slot concept | **Named slots** (hero, cell_1, spoke_1, step_1, stage_1) — widgets assigned to slots, not x/y coords |
| baoyu-infographic: layout × style → image | SlideForge: layout × style → CSS classes + LiveView components (not image generation) |

## Widget-first architecture — key pattern

The defining architectural decision: the unit of construction is a **widget**, not a content element. Each widget:

1. Has a `widget_type` string (e.g., "metric_card", "bar_chart")
2. Has a `props_schema` function that defines its configurable fields
3. Has a `render/1` function component
4. Is registered in a central `Registry` module

```elixir
defmodule SlideForge.Widgets.Registry do
  @widgets %{
    "metric_card" => SlideForge.Widgets.MetricCard,
    "bar_chart"   => SlideForge.Widgets.BarChart,
    # ... 28 more
  }
  def module_for(type), do: Map.get(@widgets, type)
  def types, do: Map.keys(@widgets)
end
```

The InspectorPanel is **dynamic** — it reads `props_schema` from the widget module and renders the appropriate field types:

```elixir
def inspector_panel(assigns) do
  schema = assigns.widget_module.props_schema()
  # Render fields based on schema types: :string, :number, :boolean, :enum, :color, :list
end
```

This means adding a new widget type = defining a module with `props_schema` + `render`, registering it. No inspector changes needed.

## Widget categories (37 total)

| Category | Widgets |
|---|---|
| Métricas | metric_card, stat_grid, counter, progress_bar, gauge, kpi_highlight, sparkline |
| Gráficas | bar_chart, line_chart, pie_chart, donut_chart, funnel_chart, heatmap |
| Data | data_table, comparison, checklist, badge_row, icon_list |
| Estructura | tabs, accordion, step_flow, timeline, process_step, node_card, category_cell |
| Texto | heading, text_block, quote, code_block, callout, warning_box |
| Visual | image, diagram, map, avatar_group, divider, spacer |

## Layout × Style × Widget architecture (final model)

The final architecture has three combinatorial dimensions:

### 21 Layouts (page structure — defines named slots)

Inspired by the baoyu-infographic skill's layout gallery. Each layout is a module that defines named regions (slots) where widgets are assigned:

| Layout | Key slots | Best for |
|---|---|---|
| `bento-grid` | hero, cell_1..4, wide_1..2 | Overview, multiple topics |
| `dashboard` | kpi_1..4, chart_1..2, summary | KPIs, metrics, analytics |
| `hub-spoke` | center, spoke_1..6 | Ecosystems, features around core |
| `linear-progression` | step_1..5 | Timelines, processes |
| `binary-comparison` | left_title, left_1..3, right_title, right_1..3, center_label | A vs B, before/after |
| `comparison-matrix` | header_row, row_1..4, col_headers | Multi-factor comparison |
| `hierarchical-layers` | level_1..5 | Priorities, pyramid |
| `tree-branching` | root, branch_1..3, leaf_1..6 | Taxonomies, decision trees |
| `structural-breakdown` | subject, callout_1..5 | Anatomy, teardown |
| `iceberg` | surface_1..3, depth_1..5 | Surface vs hidden |
| `funnel` | stage_1..5 | Conversion, filtering |
| `circular-flow` | center, node_1..5 | Cycles, recurring processes |
| `winding-roadmap` | start, milestone_1..4, end | Journeys, roadmaps |
| `venn-diagram` | circle_a, circle_b, overlap, circle_c | Overlapping concepts |
| `bridge` | problem_1..3, bridge, solution_1..3 | Problem→solution |
| `periodic-table` | element_1..12, legend | Categorized collections |
| `comic-strip` | panel_1..5 | Narratives, sequences |
| `story-mountain` | rising_1..2, climax, falling_1..2 | Plot structure |
| `jigsaw` | piece_1..6 | Interconnected parts |
| `isometric-map` | zone_1..5, connector_1..3 | Spatial relationships |
| `dense-modules` | mod_1..7 | High-density guides |

### 21 Styles (visual aesthetic — CSS class sets)

Inspired by baoyu-infographic's style gallery. Each style is a set of CSS classes applied to the canvas and all widgets:

| Style | Aesthetic |
|---|---|
| `craft-handmade` | Hand-drawn, paper craft (default) |
| `corporate-memphis` | Flat vector, vibrant |
| `cyberpunk-neon` | Neon glow, futuristic |
| `chalkboard` | Chalk on black board |
| `technical-schematic` | Blueprint, engineering |
| `kawaii` | Japanese cute, pastels |
| ... (15 more) |

### 37 Widgets (content units — assigned to slots)

Widgets are assigned to named slots in the layout. Each widget has `props_schema` for the dynamic inspector:

| Category | Widgets |
|---|---|
| Métricas | metric_card, stat_grid, counter, progress_bar, gauge, kpi_highlight, sparkline |
| Gráficas | bar_chart, line_chart, pie_chart, donut_chart, funnel_chart, heatmap |
| Data | data_table, comparison, checklist, badge_row, icon_list |
| Estructura | tabs, accordion, step_flow, timeline, process_step, node_card, category_cell |
| Texto | heading, text_block, quote, code_block, callout, warning_box |
| Visual | image, diagram, map, avatar_group, divider, spacer |

### Layout compatibility

Not all widgets fit all slots. The editor and MCP validate widget-slot compatibility:

| Layout | Slot types | Recommended widgets |
|---|---|---|
| bento-grid | hero, cells, wide | hero=chart/stat_grid, cells=metric_card/heading |
| dashboard | kpi, chart, summary | kpi=metric_card/counter, chart=bar/line/pie |
| hub-spoke | center, spokes | center=kpi_highlight/heading, spokes=node_card/icon_list |
| linear-progression | steps | process_step, timeline |
| funnel | stages | metric_card, heading, progress_bar |
| dense-modules | mods | data_table, comparison, warning_box, checklist |

### How layouts render

```elixir
# PageRenderer groups widgets by slot, then calls the layout module
def render_page(assigns) do
  layout_module = Registry.module_for(page.layout_type)
  widgets_by_slot = Enum.group_by(page.widgets, & &1.slot)
  layout_module.render(%{widgets_by_slot: widgets_by_slot, design: design, ...})
end

# Each layout module defines slot positions (grid, absolute, flex, SVG)
defmodule SlideForgeWeb.Layouts.BentoGrid do
  def render(assigns) do
    ~H"""
    <div style="display: grid; grid-template-columns: repeat(4, 1fr); ...">
      <div style="grid-column: 1/3; grid-row: 1/3;">
        <.render_slot_widgets slot_name="hero" {@widgets_by_slot} ... />
      </div>
      ...
    </div>
    """
  end
end
```

## Spec File Inventory (final)

11 files, ~2,923 lines total:

| File | Focus |
|---|---|
| README.md | Index + executive summary |
| 00-overview.md | Vision: infographics with 21 layouts × 21 styles, comparison with baoyu, umbrella structure |
| 01-data-model.md | SQL tables + 21 layouts with named slots + 21 styles + datasources |
| 02-rendering.md | Canvas 1920×1080, Layout Registry (21), PageRenderer, WidgetRenderer, style→CSS |
| 03-widgets.md | 37 widgets with props_schema, layout compatibility table |
| 04-components.md | 11 components incl. LayoutPicker + StylePicker |
| 05-inspector-edit-ops.md | EditOps on JSONB, dynamic InspectorPanel, slot selector |
| 06-mcp-server.md | 45+ tools incl. list_layouts, get_layout_slots, list_styles, example with 3 layouts |
| 07-present-export.md | PresentLive, steps, presenter view, export HTML/PDF/PPTX |
| 08-liveviews-routes.md | Router per app (studio/public/admin), EditorLive, GalleryLive, ViewerLive, comparison table |
| 09-roadmap.md | 11 phases incl. umbrella scaffolding + public viewer + admin, widget/layout priority |

## Umbrella structure (phase 3 addition)

After the specs were complete, the user asked: "Should this be an umbrella or a normal Phoenix app?" Then specified four apps: one for create/edit, one for public viewing, one for admin, plus core.

Final structure:

```
slideforgery/
├── apps/
│   ├── core/      # SlideforgeryCore.* — lógica pura (sin Phoenix)
│   ├── studio/    # SlideforgeryStudioWeb.* — editor + present + MCP endpoint
│   ├── public/    # SlideforgeryPublicWeb.* — gallery + viewer (sin auth)
│   └── admin/     # SlideforgeryAdminWeb.* — users, moderation, config
├── config/
└── mix.exs
```

Key decisions:
- `core` has NO Phoenix dependency — only Ecto + pure logic. Widget registry, layout registry, style definitions, export functions, MCP tool implementations all live here.
- `studio` has the MCP endpoint (`/api/mcp`) because it's the editor's API surface. The tool implementations call `SlideforgeryCore.*` functions.
- `public` is a separate Phoenix app with its own router — no auth required, no editing controls, just canvas + navigation.
- `admin` is a separate Phoenix app with admin auth — user management, app moderation, feature flags.
- The three web apps depend on `core` but not on each other.
- Namespace cleanup: all `SlideforgeryWeb.*` references in specs were replaced with the correct app-specific namespace (`SlideforgeryStudioWeb.*`, `SlideforgeryPublicWeb.*`, etc.) via `sed`.
- Router per app: studio has `/a/:slug` (editor), public has `/v/:slug` (viewer), admin has its own admin routes.
- ViewerLive vs EditorLive comparison table was added to spec 08: canvas interactive in both, but only editor has inspector, palette, pickers, edit ops, PubSub listener.

**Lesson 3:** When the user asks "umbrella or normal app?", the answer is umbrella when there are separable concerns (editor vs viewer vs admin). The user already had a preference for umbrella apps from prior projects (my_app). Always propose the structure before writing specs — the umbrella decision affects the repo structure section of the overview spec, the router section, and the roadmap.

### Elixir naming convention

The project was initially named "SlideForge" (two words concatenated). The user corrected it to "SlideForgery" — in Elixir/Phoenix, `slide_forgery` (snake_case) converts to `SlideForgery` (CamelCase), preserving the internal capital F. The initial `SlideForge` was wrong because it dropped the "y" and didn't preserve the word boundary. A `sed` pass replaced all occurrences across 11 spec files, including module namespaces (`SlideforgeryCore` → `SlideForgeryCore`), directory paths (`slideforgery/` → `slide_forgery/`), and config keys (`:slideforgery` → `:slide_forgery`).

**Lesson 3b:** In Elixir, the module name is derived from the snake_case app name by capitalizing each word boundary. `slide_forgery` → `SlideForgery` (not `SlideForge` or `Slideforgeery`). Always derive the module namespace from the snake_case app name, not the other way around. If the user corrects a name, `sed` across all spec files is the fastest fix — don't manually edit each file.

## DESIGN.md as design system format (phase 4 addition)

After the specs were complete, the user said "los themes deben usar design.md soportarlo." This meant adopting **DESIGN.md** (Google's open spec, `google-labs-code/design.md`) as the storage format for design systems, replacing the ad-hoc `palette`/`fonts`/`type_scale`/`radius` columns.

### What changed in the data model

Before:
```sql
CREATE TABLE design_systems (
  palette     JSONB NOT NULL,
  fonts       JSONB NOT NULL,
  type_scale  JSONB NOT NULL,
  radius      INT NOT NULL DEFAULT 12,
  style       TEXT NOT NULL DEFAULT 'craft-handmade'
);
```

After:
```sql
CREATE TABLE design_systems (
  style       TEXT NOT NULL DEFAULT 'craft-handmade',  -- generates template initial
  design_md   TEXT NOT NULL,                           -- full DESIGN.md (frontmatter + body)
  tokens      JSONB NOT NULL DEFAULT '{}',              -- parsed frontmatter cache
);
```

### Why DESIGN.md over ad-hoc fields

- **Structured tokens** with validation (not loose JSONB blobs)
- **Token references** (`{colors.primary}`) keep palette single-source
- **WCAG contrast validation** via `npx @google/design.md lint`
- **Exportable** to Tailwind theme JSON or W3C DTCG
- **Human-readable rationale** lives next to the tokens (markdown body)
- **Agent-friendly** — an MCP agent can generate/modify the DESIGN.md without understanding a custom format

### Rendering pipeline change

Before: `design.palette.bg` → `--osd-bg: #f7f5f0`
After: `design.tokens[:colors][:primary]` → `--osd-color-primary: #3A2A1A` (one CSS var per token)

```elixir
def to_css_vars(design) do
  tokens = design.tokens  # JSONB cache of parsed frontmatter
  # colors → --osd-color-{name}
  # typography → --osd-font-{name}-family/size/weight/line-height
  # rounded → --osd-rounded-{name}
  # spacing → --osd-spacing-{name}
end
```

### Style → DESIGN.md relationship

The 21 styles (craft-handmade, cyberpunk-neon, etc.) each generate a DESIGN.md template with tokens that reflect their aesthetic. The style is the starting point; the user can edit the DESIGN.md freely afterward. This replaces the old approach where `style` was a field that mapped to hardcoded CSS class sets.

### MCP tools change

Before: `update_design` with `palette`, `fonts`, `type_scale`, `radius`, `style`
After: `update_design_md` (raw DESIGN.md), `update_design_tokens` (specific tokens), `validate_design` (lint + WCAG), `get_style_design_md` (template per style)

### DesignPanel component change

The DesignPanel now edits DESIGN.md: form fields for colors/typography/rounded/spacing/components + a raw textarea editor for the full DESIGN.md + Validate and Lint WCAG buttons.

**Lesson 4:** When the user references an existing spec format (like DESIGN.md), adopt it as the source of truth rather than inventing a custom schema. The format brings validation, tooling, and agent-friendliness for free. Load the relevant skill (`skill_view(name='design-md')`) to understand the format before integrating it.

## Key architectural decisions

1. **Widget as atomic unit** — encapsulates data + presentation + interactivity. Assigned to named slots in layouts.
2. **props_schema drives inspector** — each widget defines its fields; inspector auto-generates. Adding widgets doesn't require inspector changes.
3. **21 layouts × 21 styles combinatorial model** — inspired by baoyu-infographic. Layouts define named slots; styles are CSS class sets. 441 combinations.
4. **Named slots** — widgets go into named regions (hero, cell_1, spoke_1, step_1...) defined by the layout, not free x/y coordinates.
5. **JSONB props** — widget configuration stored as JSONB, editable via EditOps (set_prop, set_props).
6. **PostgreSQL as source of truth** — replaces filesystem. Apps, pages, widgets — all in DB.
7. **Canvas 1920×1080 always** — single canvas size, no dual canvas (unlike the discarded phase 1).
8. **MCP as first-class** — 45+ tools covering every CRUD + layout/style tools + `update_widget_prop` for granular edits. PubSub reflects changes in LiveViews.
9. **Datasources** — widgets can consume data from static props or dynamic datasources (CSV, JSON URL, API).
10. **Phoenix PubSub replaces BroadcastChannel** — presenter sync via channels.
11. **37 widget types** — metric_card, bar_chart, line_chart, timeline, data_table, tabs, accordion, heatmap, map, diagram, counter, sparkline, process_step, node_card, category_cell, warning_box, gauge, kpi_highlight, funnel_chart, etc.
12. **Layout compatibility** — not all widgets fit all slots. The editor and MCP validate widget-slot pairs.
13. **Umbrella with 4 apps** — `core` (pure logic, no Phoenix), `studio` (editor + MCP endpoint), `public` (gallery + viewer, no auth), `admin` (moderation). Web apps depend on `core` but not each other.

## Reading order for systematic analysis

The source codebase (open-slide) was read in this order (batched reads):

1. `package.json` + `README.md` + file listing (scope)
2. `index.ts` + `config.ts` + `sdk.ts` + `slides.ts` (types & contracts)
3. `design.ts` + `transition.ts` + `themes.ts` + `folders.ts` + `assets.ts` + `step-context.tsx` + `page-context.tsx` (core types)
4. `app.tsx` + `home.tsx` + `slide.tsx` + `presenter.tsx` + `slide-canvas.tsx` + `thumbnail-rail.tsx` + `overview-grid.tsx` (UI shell + routes)
5. `slide-ops.ts` + `edit-ops.ts` + `comments.ts` + `player.tsx` + `inspector-panel.tsx` + `style-panel.tsx` + `notes-drawer.tsx` + `sidebar.tsx` (editing + panels)
6. `export-html.ts` + `use-agent-socket.ts` + `home-shell.tsx` + `edit.ts` (routes) + `slides.ts` (routes) + `design-presets.ts` (exports + API + presets)

This order: types → core logic → UI shell → UI components → editing → API/exports. Each layer informs the next.