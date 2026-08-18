# my_app LiveView / UI Patterns

Reference for building new LiveView pages and UI features in the my_app Phoenix
app. my_app is a single-app Phoenix project (not umbrella), so all modules live
under `lib/my_app/` and `lib/dran_web/`.

## Directory structure (UI layer)

| Layer | Path | Example |
| --- | --- | --- |
| LiveView | `lib/dran_web/live/<name>_live.ex` | `DranWeb.NoteLive`, `DranWeb.TagLive` |
| Shared component | `lib/dran_web/components/<name>_components.ex` | `DranWeb.PageComponents`, `DranWeb.PageListComponents` |
| Router | `lib/dran_web/router.ex` | `scope "/", DranWeb do ... end` |
| Page types helper | `lib/dran_web/page_types.ex` | `DranWeb.PageTypes` — path/icon/label/plural maps |
| Auth plug | `lib/dran_web/plugs/auth.ex` | `DranWeb.Plugs.Auth` — `assign_to_socket/2` |
| Page edit helper | `lib/dran_web/page_edit.ex` | `DranWeb.PageEdit` — shared edit event handlers |

## Adding a new LiveView page (checklist)

1. **Read an existing LiveView** for the pattern. `note_live.ex` and
   `concept_live.ex` are the canonical examples — they show index list +
   detail view with inline editing. `search_live.ex` is a simpler read-only
   example closer to what a tag/filter page needs.

2. **mount/3**: Always use `Auth.assign_to_socket/2` to get the context:

   ```elixir
   def mount(_params, session, socket) do
     {socket, context} = Auth.assign_to_socket(socket, session)
     {:ok, assign(socket, context: context, ...)}
   end
   ```

   `context` may be `nil` — always guard with `if socket.assigns.context do`
   before calling `Brain.list_pages/1` etc.

   **Initialize every assign that `handle_params` reads.** If
   `handle_params` references `socket.assigns.all_todos` (or any assign
   computed inside the `if context do` block) and `context` is `nil`, the
   `else` branch returns without setting it — the next access crashes with
   `KeyError`. Set defaults for all such assigns in `mount/3`:

   ```elixir
   {:ok,
    assign(socket,
      context: context,
      all_todos: [],          # ← default; handle_params may skip setting it
      filtered_todos: [],
      filtered_count: 0,
      ...
    )}
   ```

   This is especially important for LiveViews with filter/recompute
   pipelines (`recompute_filtered_todos/1`) that read multiple assigns.

3. **handle_params/3**: Fetch data based on URL params. For a param-driven
   page (e.g. `/tags/:tag`), pattern-match on `%{"tag" => tag}`:

   ```elixir
   def handle_params(%{"tag" => tag}, _url, socket) do
     pages =
       if socket.assigns.context do
         Brain.list_pages(context_id: socket.assigns.context.id, tag: tag, limit: 200)
       else
         []
       end
     {:noreply, assign(socket, tag: tag, pages: pages, page_title: "##{tag}")}
   end
   ```

4. **render/1**: Wrap in `<Layouts.app>` with the standard assigns
   (`flash`, `current_scope`, `current_user`, `context_slug`, `contexts`).
   Add `active_nav` if the page has a sidebar entry.

5. **Route**: Add inside the authenticated scope:

   ```elixir
   scope "/", DranWeb do
     pipe_through [:browser, :auth]
     live "/tags/:tag", TagLive, :index
   end
   ```

6. **Compile + test + commit**:

   ```bash
   mix compile
   mix test
   git add lib/dran_web/live/tag_live.ex lib/dran_web/router.ex ...
   git commit -m "feat: add tag pages showing all pages with a given tag"
   ```

## Shared components

### `DranWeb.PageListComponents.page_list/1`

Reusable list of pages with icon, title, summary, and tag links. Uses
LiveView streams for efficient DOM updates (add/remove without re-rendering
the whole list).

```elixir
<.page_list page_type={@page_type} context_slug={@context_slug} />
```

- **No `pages` attr** — the component reads `@streams.pages` directly (the
  LiveView must set up the stream in `handle_params`).
- Each row has `phx-click="show_page"` and `phx-value-slug={page.slug}`.
- Each row gets a unique DOM `id` from the stream tuple `{id, page}`.
- Tag links use `<.link navigate={"/tags/#{URI.encode_www_form(tag)}"}>` —
  they navigate away (full page transition), not LiveView events.
- The `page_type` attr controls the "New" button URL and the header label.
- Pass `page_type: nil` for cross-type lists (e.g. tag pages, search results).

## Converting page lists to LiveView streams

my_app's page-type LiveViews (note, concept, entity, reference, goal, plan,
artifact, comparison, query) use a shared `page_list/1` component for their
index view. All 9 were converted from `assign(socket, :pages, ...)` to
`stream(socket, :pages, ...)` for better performance (DOM diffing only
adds/removes changed rows, no full list re-render).

### What changes in each LiveView

**1. `handle_params` for `:index`** — replace `assign` with `stream`:

```elixir
# Before
{:noreply, assign(socket, pages: pages, page_title: "Notes")}

# After
{:noreply, stream(socket, :pages, pages, reset: true) |> assign(page_title: "Notes")}
```

The `reset: true` option clears the stream before inserting, so navigating
between LiveViews doesn't accumulate stale rows. The `page_title` (and any
other assigns) chain after via `|> assign(...)` since `stream/4` returns a
socket.

**2. `render/1`** — remove `pages={@pages}` from the component call:

```heex
<!-- Before -->
<.page_list pages={@pages} page_type={@page_type} context_slug={@context_slug} />

<!-- After -->
<.page_list page_type={@page_type} context_slug={@context_slug} />
```

The component reads `@streams.pages` directly — you cannot pass a stream as a
regular attr because streams are special LiveView state.

### What changes in `page_list_components.ex`

```heex
<!-- Before -->
<div class="space-y-2">
  <div :for={page <- @pages} ...>
    ...
  </div>
</div>

<!-- After -->
<div id="pages-list" phx-update="stream" class="space-y-2">
  <div :for={{id, page} <- @streams.pages} id={id} ...>
    ...
  </div>
</div>
```

- Add `id="pages-list"` (or any unique id) and `phx-update="stream"` on the
  parent container.
- Change `:for={page <- @pages}` to `:for={{id, page} <- @streams.pages}`.
- Add `id={id}` on each row — the stream tuple's `id` is the DOM id
  (`"pages-" <> page.id` by default for `%Page{}` structs).
- Change the empty-state check from `@pages == []` to `@streams.pages == []`.
- Remove `attr :pages, :list, required: true` from the component's attrs.

### What changes in `page_edit.ex` (create/delete)

For `stream_insert` (on page create) and `stream_delete` (on page delete),
add to the imports:

```elixir
import Phoenix.LiveView, only: [..., stream_insert: 3, stream_delete: 3]
```

**`stream_insert` in `create_page/2`:**

```elixir
case Brain.create_page(page_params) do
  {:ok, page} ->
    {:noreply,
     socket
     |> stream_insert(:pages, page)        # ← add this
     |> put_flash(:info, "Page created.")
     |> push_navigate(to: page_path(type, page.slug) <> "?edit=true")}
  ...
end
```

**`stream_delete` in `delete_page` handler:**

```elixir
case Brain.delete_page(page) do
  {:ok, _} ->
    {:noreply,
     socket
     |> stream_delete(:pages, page)        # ← add this
     |> put_flash(:info, "Page deleted.")
     |> push_navigate(to: ~p"/")}
  ...
end
```

### LiveViews not converted

`todo_live.ex` does NOT use `page_list` — it renders a Kanban board with
`@items` (not `@pages`). `tag_live.ex` uses `@pages` with its own inline
rendering (not the shared component). Neither was converted.

### `stream_delete` arity

`stream_delete` is `/3` (socket, name, item), NOT `/2`. Importing it as
`stream_delete: 2` fails with a compile warning: `cannot import
Phoenix.LiveView.stream_delete/2 because it is undefined or private`. The
correct import is `stream_delete: 3`.

### `DranWeb.PageComponents.page_detail/1`

Full page detail view with sidebar (metadata, relations, versions, activity).

```elixir
<.page_detail
  page={@page}
  relations={@relations}
  versions={@versions}
  compare_version={@compare_version}
  logs={@logs}
  context_slug={@context_slug}
>
  <:actions> ... </:actions>
  <:tabs> ... </:tabs>
</.page_detail>
```

- `actions` slot: buttons shown top-right (Back, Edit, Save, Cancel, Delete).
- `tabs` slot: content area with a tab bar (`tabs_bar/1` component).
- Tags in `page_detail` link to `/tags/{tag}` (tag pages).

### `DranWeb.PageComponents.tabs_bar/1`

```elixir
<.tabs_bar tabs={@tabs} active_tab={@active_tab} />
```

- `tabs` is a list of `{key, label}` tuples.
- Fires `phx-click="switch_tab"` with `phx-value-tab={key}`.

## DranWeb.PageTypes module

Central registry for the 10 page types. Use for URLs, icons, labels:

```elixir
PageTypes.path("note")        # "notes"
PageTypes.label("note")       # "Note"
PageTypes.plural("note")      # "Notes"
PageTypes.icon("note")        # "hero-document-text"
PageTypes.page_show_path(page) # "/notes/my-note"
```

`page_show_path/1` accepts a `%Page{}` struct or a map with `:page_type` and
`:slug` keys. Returns `"#"` for invalid input.

## Tag link patterns

Tags in my_app are stored as `tags: [string]` on the `Page` schema. Two contexts
render tags:

1. **`page_detail`** (sidebar): Tags link to `/tags/{tag}`. Previously linked
   to the page if the tag matched a slug (via `tag_link_path/3`), or to search
   if no matching page existed. Now uniformly links to `/tags/{tag}`.

2. **`page_list`** (list rows): Tags link to `/tags/{tag}` via
   `<.link navigate=...>`.

Always URL-encode the tag: `URI.encode_www_form(tag)`.

## Brain.list_pages/1 tag filtering

```elixir
Brain.list_pages(context_id: context.id, tag: "elixir", limit: 200)
```

The `:tag` opt filters via `maybe_filter_tag/2` which uses
`where(query, [p], ^tag in p.tags)` — a PostgreSQL array containment query.
No index needed for small datasets; add a GIN index on `tags` if performance
becomes an issue.

## Layouts.app required assigns

Every my_app LiveView render must pass these to `<Layouts.app>`:

| Assign | Purpose | Source |
| --- | --- | --- |
| `flash` | Flash messages | Phoenix auto-assigned |
| `current_scope` | Auth scope | `Auth.assign_to_socket/2` |
| `current_user` | User struct | `Auth.assign_to_socket/2` |
| `context_slug` | Current context slug | `Auth.assign_to_socket/2` |
| `contexts` | All contexts (for switcher) | `Auth.assign_to_socket/2` |
| `active_nav` | Active sidebar item | Optional, set in mount |

If any are missing, the layout will crash with a missing assign error.

## Pre-computed `rendered_body` pattern (fragment caching)

`render_markdown/2` is expensive (parses markdown, resolves wikilinks, fetches
embeds). Calling it inline in the template re-parses on *every* LiveView render
(every `handle_event`, every `handle_params`, every PubSub message). The fix:
pre-compute once in `handle_params` and pass the result as an assign.

### Where to compute

In the **slug-loading `handle_params` clause** (the one that calls
`Brain.get_page_by_slug/2`), not in `mount/3`. my_app loads pages by slug in
`handle_params`, so that's where the page struct and its `context_id` / `meta`
are first available.

```elixir
def handle_params(%{"slug" => slug} = params, _url, socket) do
  context = socket.assigns.context

  if context do
    case Brain.get_page_by_slug(slug, context.id) do
      nil ->
        {:noreply, push_navigate(socket, to: ~p"/notes")}

      page ->
        # ... load relations, versions, logs, graph ...

        rendered_body =
          render_markdown(page.body,
            context_id: page.context_id,
            inline_links: Map.get(page.meta || %{}, "inline_links", [])
          )

        {:noreply,
         assign(socket,
           page: page,
           # ... other assigns ...
           rendered_body: rendered_body
         )}
    end
  end
end
```

### Template usage

Replace inline `render_markdown(@page.body, ...)` calls with `{@rendered_body}`:

```heex
<!-- Before (re-parses on every render) -->
{render_markdown(@page.body,
  context_id: @page.context_id,
  inline_links: Map.get(@page.meta || %{}, "inline_links", [])
)}

<!-- After (uses pre-computed assign) -->
{@rendered_body}
```

### Passing to `<.page_detail>`

The `page_detail/1` component accepts an optional `rendered_body` attr (default
`nil`). When provided, it uses the pre-computed value; when `nil`, it falls back
to calling `render_markdown` inline (backward-compatible). Always pass it from
every LiveView that renders `page_detail`:

```heex
<.page_detail
  page={@page}
  relations={@relations}
  versions={@versions}
  compare_version={@compare_version}
  logs={@logs}
  context_slug={@context_slug}
  rendered_body={@rendered_body}
>
```

### Recomputing on `body_change` (CRITICAL)

The `body_change` event (autosave) in `PageEdit` updates the page body in the
DB. If you don't recompute `rendered_body` here, the rendered HTML will be stale
after every autosave until the next full page load (`handle_params`).

`PageEdit` is a shared handler module, not a LiveView — it doesn't import
`PageComponents`. Call `render_markdown` via the fully-qualified module name:

```elixir
# lib/dran_web/page_edit.ex
def handle_event("body_change", %{"body" => body}, %{assigns: %{page: %Page{} = page}} = socket) do
  if body == page.body do
    {:noreply, assign(socket, save_status: "saved")}
  else
    case Brain.update_page(page, %{body: body}) do
      {:ok, updated_page} ->
        rendered_body =
          DranWeb.PageComponents.render_markdown(updated_page.body,
            context_id: updated_page.context_id,
            inline_links: Map.get(updated_page.meta || %{}, "inline_links", [])
          )

        {:noreply,
         socket
         |> assign(page: updated_page, save_status: "saved", rendered_body: rendered_body)}

      {:error, _changeset} ->
        {:noreply, assign(socket, save_status: "idle")}
    end
  end
end
```

### Files touched when adding this pattern to a new LiveView

1. **`lib/dran_web/live/<type>_live.ex`** — add `rendered_body` computation in
   `handle_params` slug clause, add `rendered_body: rendered_body` to the
   `assign` call, pass `rendered_body={@rendered_body}` to `<.page_detail>`,
   replace `render_markdown(@page.body, ...)` with `{@rendered_body}` in the
   template.
2. **`lib/dran_web/page_edit.ex`** — already handles `body_change` recomputation
   for all page types (shared handler). No per-LiveView change needed here.

### Why not ETS cache?

See `references/code-audit-patterns.md` §18. Short version: `render_markdown`
depends on `body`, `context_id`, `inline_links`, and `embeds` (resolved via DB
queries). A cache key that misses any of these serves stale HTML. Pre-computation
in `handle_params` is simpler and always correct — it runs once per navigation,
not once per render.

## my_app design system (CSS utility classes)

my_app defines custom semantic CSS utility classes in `assets/css/app.css`.
**Always prefer these over raw Tailwind equivalents** for consistency across
components. The design system encodes Álvaro's typographic hierarchy and
surface elevation conventions.

### Typography scale

| Class | Size | Weight | Use for |
| --- | --- | --- | --- |
| `.text-display` | 2.25rem (36px) | 800 | Hero / page landing titles (rare) |
| `.text-title` | 1.5rem (24px) | 700 | Document / detail page titles |
| `.text-caption` | 0.75rem (12px) | 500 | Metadata, labels, timestamps, empty states |

Use `.text-title` (not `text-3xl font-bold`) for page detail titles — it
maintains visual hierarchy with the rest of the page without overpowering
the metadata bar and sidebar.

### Surface elevation

| Class | Background | Border | Shadow | Use for |
| --- | --- | --- | --- | --- |
| `.surface-1` | `--color-base-200` | 8% content | none | Flat container backgrounds |
| `.surface-2` | `--color-base-100` | 8% content | `--shadow-surface-2` | Elevated cards, list items with depth |

`.surface-2` is the workhorse for relation items, version history rows, and
any list item that should feel like a card. Pair with `transition` and
`hover:bg-base-200/50` for subtle interactivity.

### Chip / badge pattern

For type badges, tags, and status indicators:

```heex
<span class="text-[11px] font-medium px-2 py-0.5 rounded-full bg-primary/10 text-primary">
  {label}
</span>
```

This is the established chip style — `text-[11px]` (slightly smaller than
`.text-caption`), pill-shaped (`rounded-full`), with a translucent primary
background. Use it for page type badges in metadata bars.

### Segmented control tabs

`tabs_bar/1` uses a segmented control pattern (not underline tabs):

```heex
<div class="inline-flex rounded-lg bg-base-200 p-1">
  <button
    phx-click="switch_tab"
    phx-value-tab={tab}
    data-testid={"tab-#{tab}"}
    class={[
      "px-3 py-1.5 rounded-md text-sm transition",
      active && "bg-base-100 shadow-sm font-medium",
      inactive && "text-base-content/60 hover:text-base-content"
    ]}
  >
    {label}
  </button>
</div>
```

Key points:
- Container: `inline-flex rounded-lg bg-base-200 p-1` (not full-width, not
  border-bottom).
- Active tab: `bg-base-100 shadow-sm font-medium` (elevated pill).
- Inactive tab: `text-base-content/60 hover:text-base-content`.
- **Always add `data-testid={"tab-#{tab}"}`** — enables robust test selectors
  that survive class changes.

### Separator pattern

For joining metadata items in a horizontal bar:

```heex
<span class="text-base-content/30">·</span>
```

Use between metadata items (type · slug · created · updated) for subtle
visual separation without adding visual weight.

## Page detail layout: reading width vs. full width

The `page_detail/1` component serves both a **content tab** (prose, needs
reading width) and a **graph tab** (SVG, needs full width). Since both live
inside the `<:tabs>` slot, you cannot apply `max-w-3xl` to the slot
container — it would constrain the graph.

### Solution

- **Outer container**: `max-w-5xl mx-auto p-6 space-y-6` — gives a generous
  max width that accommodates the graph.
- **Default (no-tabs) content path**: wrap prose, changelog, and diff in
  `max-w-3xl mx-auto` individually — each gets reading width independently.
- **Tabs slot**: `{render_slot(@tabs)}` is left unconstrained. LiveViews
  control their own content widths inside the slot.

```heex
<div class="max-w-5xl mx-auto p-6 space-y-6">
  <%!-- header, metadata bar, title --%>
  {render_slot(@tabs)}
  <div :if={@tabs == []} class="max-w-3xl mx-auto prose ...">
    {@rendered_body}
  </div>
</div>
```

### Pitfall: `max-w-none` cancels `max-w-3xl`

If you write `class="max-w-3xl mx-auto prose max-w-none"`, Tailwind's
`max-w-none` wins (later in source order = higher specificity in the same
layer). Remove `max-w-none` when constraining prose to reading width.

## Metadata bar pattern

The page detail header uses a horizontal metadata bar above the title,
replacing the old icon+label row:

```heex
<div class="flex flex-wrap items-center gap-2 mb-2 text-caption">
  <span class="inline-flex items-center gap-1 text-[11px] font-medium px-2 py-0.5 rounded-full bg-primary/10 text-primary">
    <.icon name={PageTypes.icon(@page.page_type)} class="size-3" />
    {PageTypes.label(@page.page_type)}
  </span>
  <span class="text-base-content/30">·</span>
  <code class="font-mono text-caption text-base-content/60">{@page.slug}</code>
  <span class="text-base-content/30">·</span>
  <span class="inline-flex items-center gap-1 text-caption text-base-content/50">
    <.icon name="hero-calendar" class="size-3" />
    {gettext("Created")} {format_date(@page.inserted_at)}
  </span>
  <span class="text-base-content/30">·</span>
  <span class="inline-flex items-center gap-1 text-caption text-base-content/50">
    <.icon name="hero-clock" class="size-3" />
    {gettext("Updated")} {format_date(@page.updated_at)}
  </span>
</div>
```

Key points:
- Type badge uses the chip pattern (above).
- Slug uses `font-mono` + `.text-caption`.
- Dates use `hero-calendar` (created) / `hero-clock` (updated) icons at
  `size-3` — smaller than the default `w-5 h-5` to match caption scale.
- All items are `.text-caption` with `·` separators.
- `flex-wrap` ensures it degrades gracefully on narrow screens.

When this metadata bar is present, the sidebar metadata section no longer
needs Created/Updated rows (they're in the bar). Keep Type, Version, Owner,
Created by, Updated by in the sidebar.

## Relations panel pattern

Each relation item uses `.surface-2` with directional icons:

```heex
<div class="space-y-1">
  <div class="text-caption text-base-content/40 mb-1 inline-flex items-center gap-1">
    <.icon name="hero-arrow-right" class="size-3" />
    {gettext("Outbound")}
  </div>
  <div :for={rel <- @relations.outbound} class="surface-2 px-3 py-2 transition">
    <.link navigate={...} class="text-sm hover:text-primary transition">
      {rel.target.title}
    </.link>
    <div class="text-caption text-base-content/40 mt-0.5">{rel.relation_type}</div>
  </div>
</div>
```

- Outbound: `hero-arrow-right`, Inbound: `hero-arrow-left`.
- Title link: `hover:text-primary` (not `hover:underline` — cleaner).
- Relation type in `.text-caption` below the title (not inline).
- Empty state: `.text-caption` "No relations yet".

### Relation type badge colors

For color-coding relation types (in both the sidebar panel and the main
content backlinks section), use `relation_type_badge_class/1`:

```elixir
def relation_type_badge_class(type) when is_binary(type) do
  case type do
    "semantic" -> "bg-primary/10 text-primary"
    "embeds" -> "bg-accent/10 text-accent"
    "related" -> "bg-base-content/10 text-base-content/60"
    "part_of" -> "bg-success/10 text-success"
    "supersedes" -> "bg-warning/10 text-warning"
    "contradicts" -> "bg-error/10 text-error"
    _ -> "bg-base-content/10 text-base-content/60"
  end
end
```

Render as a chip:

```heex
<span class={"text-[11px] font-medium px-1.5 py-0.5 rounded-full #{relation_type_badge_class(rel.relation_type)}"}>
  {rel.relation_type}
</span>
```

This replaces the plain `.text-caption` text for relation types and gives
each type a distinct color for quick visual scanning.

## Collapsible backlinks section in main content

The sidebar "Relations" panel is compact, but backlinks (inbound relations)
are important enough to also surface in the main content area below the page
body. Use a collapsible `<details>` section with a count in the header.

### Pattern

```heex
<div class="max-w-3xl mx-auto border-t border-base-300 pt-4">
  <.backlinks_section relations={@relations} />
</div>
```

The `backlinks_section/1` component renders two collapsible `<details>` blocks:

1. **"Linked from (N)"** — inbound relations (backlinks). Auto-open when
   `inbound_count > 0`, collapsed when empty. Empty state: "No backlinks yet".
2. **"Links to (N)"** — outbound relations. Only rendered when
   `outbound_count > 0` (no empty state needed — the section is absent).

Each item shows the source/target page title as a link (via
`PageTypes.page_show_path/1`) and a relation-type badge chip.

### Collapsible `<details>` pattern (consistent with sidebar nav)

my_app uses native HTML `<details>`/`<summary>` for collapsible sections
(also in `layouts.ex` sidebar nav groups). The established class pattern:

```heex
<details class="group" open={@count > 0}>
  <summary class="flex items-center gap-2 cursor-pointer select-none mb-3">
    <.icon
      name="hero-chevron-right"
      class="size-4 shrink-0 text-base-content/40 transition-transform duration-150 group-open:rotate-90"
    />
    <h3 class="text-caption font-semibold text-base-content/60 uppercase tracking-wider">
      {gettext("Linked from")}
      <span class="ml-1 text-base-content/40">({@count})</span>
    </h3>
  </summary>
  <!-- content -->
</details>
```

Key points:
- `class="group"` on `<details>` + `group-open:rotate-90` on the chevron
  icon — Tailwind's `group-open:` variant targets the open state.
- `open={@count > 0}` — auto-expand when there's content, collapse when empty.
- `cursor-pointer select-none` on `<summary>` — removes the default arrow
  and makes the whole header clickable.
- Count in parentheses: `({@count})` — gives immediate visibility without
  needing to expand.

### CRITICAL: `:if={@tabs == []}` guard hides content from tabbed LiveViews

The `page_detail/1` component has several content blocks guarded with
`:if={@tabs == []}` — these only render when NO `:tabs` slot is passed.
**All 10 page-type LiveViews** (note, concept, entity, reference, goal,
plan, todo, artifact, comparison, query) pass a `<:tabs>` slot, so
content inside `:if={@tabs == []}` is **invisible** for every page detail
view in the app.

**Symptom:** you add a new section to `page_detail` inside the
`:if={@tabs == []}` block, compile cleanly, but tests that mount a
LiveView and assert on the rendered HTML fail — the section's text is
nowhere in the output.

**Fix:** if the new section should appear for all page types (including
those with tabs), place it **outside** the `:if={@tabs == []}` guard.
The backlinks section goes after `{render_slot(@tabs)}` and the
no-tabs prose block, unconditionally:

```heex
{render_slot(@tabs)}

<div :if={@tabs == []} class="max-w-3xl mx-auto prose prose-base dark:prose-invert">
  {@rendered_body}
</div>

<!-- This renders for ALL page types, with or without tabs -->
<div class="max-w-3xl mx-auto border-t border-base-300 pt-4">
  <.backlinks_section relations={@relations} />
</div>

<div :if={@tabs == []} class="max-w-3xl mx-auto border-t border-base-300 pt-4">
  <!-- Changelog (no-tabs only) -->
</div>
```

**Rule:** the `:if={@tabs == []}` guard is for fallback content that only
makes sense when a LiveView doesn't provide its own tabbed UI (the
no-tabs path renders prose + changelog directly). Anything that should
appear on every page detail view must be outside this guard.

## Version history pattern

Each version item uses `.surface-2` with `font-mono` version number:

```heex
<div class="surface-2 px-3 py-2 flex items-center justify-between gap-2 transition hover:bg-base-200/50">
  <span class="text-sm text-base-content/60">
    <span class="font-mono">v{version.version}</span>
    <span class="text-base-content/30 mx-1">·</span>
    {format_date(version.inserted_at)}
  </span>
  <button phx-click="compare_version" phx-value-version={version.version} class="btn btn-ghost btn-xs">
    {gettext("Compare")}
  </button>
</div>
```

- Version number in `font-mono`.
- `·` separator between version and date.
- `.surface-2` + `hover:bg-base-200/50` for subtle card hover.
- Empty state: `.text-caption` "No version history yet."

## Component redesign workflow

When redesigning a shared my_app component (like `page_components.ex`):

1. **Read the full file first** to map all components, attrs, and slots.
2. **Check how LiveViews call it** — `search_files` for `page_detail`,
   `tabs_bar`, `<:tabs>` across `lib/dran_web/live/`.
3. **Understand slot structure** — if a slot contains both a bar and content
   divs, layout constraints (like `max-w`) must go inside, not on the slot.
4. **Preserve component signatures** — never change `attr` declarations or
   slot names. Add attrs with defaults if needed (`attr :new_thing, :string,
   default: nil`).
5. **Verify**: `mix compile --warnings-as-errors` then `mix test test/dran_web/`.
6. **Check for markup-asserting tests** — `search_files` in `test/` for old
   class names or text. If found, update to robust selectors (`data-testid`,
   semantic text) rather than fragile class assertions.

### Pitfall: `w-4 h-4` vs `size-4`

my_app's codebase is migrating from `w-N h-N` to `size-N` (Tailwind v4 shorthand).
When touching icon classes, prefer `size-N` for new code, but don't
mass-replace existing `w-N h-N` in the same patch — it creates noise.

## Selective git staging in multi-agent environments

When parallel subagents or sibling processes modify the same working tree,
`git add -A` stages everyone's changes. To commit only your files:

```bash
git reset HEAD          # unstage all (keeps working tree changes)
git add lib/dran_web/live/tag_live.ex lib/dran_web/router.ex ...
git commit -m "feat: ..."
```

This is lighter than `git reset --soft origin/main` (which unwinds commits)
and sufficient when you just need to isolate uncommitted changes from
sibling agents that haven't committed yet. Verify with
`git diff --cached --stat` before committing.

## Colocated JS Hooks (`Phoenix.LiveView.ColocatedHook`)

my_app uses inline colocated JS hooks for component-scoped client behavior
(drag-drop, copy buttons, phone formatting). This is the preferred form over
adding hooks to `assets/js/app.js` — the hook lives next to the LiveView
that uses it, and AGENTS.md:301-319 mandates this pattern.

### Naming convention: leading dot is REQUIRED

Every colocated hook in the my_app codebase uses a **leading dot** in the
`name` attribute. This is not optional — it's the established convention
across all existing hooks:

```heex
<!-- Correct — leading dot -->
<div phx-hook=".KanbanDragDrop" id="kanban-board">
  ...
</div>

<script :type={Phoenix.LiveView.ColocatedHook} name=".KanbanDragDrop">
  export default { mounted() { ... } }
</script>
```

Existing hooks in the repo (verify with `search_files` for `ColocatedHook`):
`.KanbanBoard` (todo_live.ex), `.GoalKanban` (goal_live.ex), `.CopyCode`
(docs_live.ex), `.PhoneNumber` (AGENTS.md example). All use the dot.

**Pitfall:** plan specs (e.g. `.hermes/plans/*.md` §4.2) sometimes write
`name="KanbanDragDrop"` without the dot. When a plan disagrees with the
repo convention, **verify against the repo first** — read an existing
LiveView that uses the same mechanism (`goal_live.ex`, `todo_live.ex`)
and match its form. The plan is a guide; the repo is the source of truth
for conventions.

### The `phx-hook` value must match the `name` (including the dot)

The `phx-hook="X"` attribute on the element must equal the `name="X"` on
the `<script>` tag. If the script declares `name=".KanbanDragDrop"` but
the element has `phx-hook="KanbanDragDrop"` (no dot), the hook never
attaches. Keep them identical.

### Drag-and-drop kanban pattern (reusable)

The drag-drop board is implemented identically in `goal_live.ex`,
`todo_live.ex`, and `kanban_live.ex`. The pattern:

1. **Board container** has `phx-hook=".XxxKanban"`, a unique `id`, and
   contains column divs each marked `data-kanban-status={status}`.
2. **Cards** have `data-kanban-slug={todo.slug}`, `draggable="true"`,
   `phx-click="show_page"`, `phx-value-slug={todo.slug}`.
3. **JS hook** listens for `dragstart` (capture slug), `dragover`
   (`preventDefault` to allow drop), `drop` (`pushEvent("move_todo", {slug,
   target_status})`), and `dragend` (clear slug).
4. **LiveView** handles `"move_todo"` by updating `meta.kanban_status` via
   `Brain.update_page/2` and recomputing the filtered list.

For the richer variant with visual drop-target feedback (ring + dashed
border classes toggled on `dragenter`/`dragleave`/`drop`/`dragend`), see
`todo_live.ex` — it adds `dropClasses = ["ring-2", "ring-primary/30",
"border-dashed"]` and a `dragend` cleanup that removes classes from all
columns (in case the drop happened outside any column).

Do NOT change the `phx-hook` name, `phx-value-*` attributes, or the
`pushEvent` call when extending a hook — only add behavior around the
existing event logic.

## Global Command Palette (Cmd+K / Ctrl+K) via LiveComponent + JS Hook

my_app implements a global command palette using a stateful LiveComponent
rendered in `Layouts.app` and a JS hook with a `window` keydown listener.
This pattern is reusable for any global keyboard-driven UI.

### Architecture

1. **LiveComponent** (`lib/dran_web/components/command_palette.ex`) — holds
   state: `open` (boolean), `query` (string), `results` (list), `selected`
   (integer index), `context_slug`. Handles `toggle`/`open`/`close`/`search`
   /`key`/`navigate`/`navigate_action` events.
2. **JS Hook** (`assets/js/app.js`) — `CommandPalette` hook with a `window`
   keydown listener. Detects Cmd/Ctrl+K (toggle), Escape (close), and
   ArrowUp/ArrowDown/Enter (navigation) when the modal is open. Uses
   `this.pushEventTo(this.el, "event_name", payload)` to target the
   LiveComponent specifically.
3. **Layout integration** — `<.live_component>` in `Layouts.app/1` before
   `<.flash_group>`, passing `context_slug` so the component can scope
   `Brain.search/2` results.

### Component root structure

```heex
<div id={@id} phx-hook="CommandPalette" phx-target={@myself}>
  <div :if={@open} class="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm"
       phx-click="close" phx-target={@myself}>
    <div class="mx-auto max-w-lg w-full rounded-xl border ..."
         role="dialog" aria-modal="true" ...>
      <input name="query" phx-keyup="search" phx-debounce="200"
            phx-target={@myself} ... />
      <!-- results / quick actions / empty state -->
    </div>
  </div>
</div>
```

**Key design decisions:**
- The root `<div>` is **always rendered** (even when closed) so the JS hook
  stays attached. Only the inner overlay is conditional via `:if={@open}`.
- `phx-target={@myself}` on the root div routes all events to the
  LiveComponent's `handle_event/3`, not the parent LiveView.
- `push_navigate/2` works in LiveComponents for navigation on Enter/click —
  return `{:noreply, push_navigate(socket, to: path)}`.
- Module attributes (e.g. `@quick_actions`) must be assigned in `mount/1`
  (`assign(socket, :quick_actions, @quick_actions)`) before they're
  available in the `~H` template.

### JS Hook pattern

```javascript
const CommandPalette = {
  mounted() {
    this._keyHandler = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault()
        this.pushEventTo(this.el, "toggle", {})
        return
      }
      const isOpen = this.el.querySelector('[role="dialog"]') !== null
      if (!isOpen) return
      if (e.key === "Escape") {
        this.pushEventTo(this.el, "close", {})
      } else if (["ArrowDown", "ArrowUp", "Enter"].includes(e.key)) {
        e.preventDefault()
        this.pushEventTo(this.el, "key", {key: e.key})
      }
    }
    window.addEventListener("keydown", this._keyHandler)
  },
  destroyed() {
    if (this._keyHandler) {
      window.removeEventListener("keydown", this._keyHandler)
    }
  }
}
```

**Key points:**
- Register in the `hooks` object: `hooks: {...colocatedHooks, ..., CommandPalette}`.
- The hook checks `this.el.querySelector('[role="dialog"]')` to detect if
  the modal is open — this is simpler than tracking state in JS.
- `destroyed()` must remove the listener to avoid leaks on LiveView
  disconnect/reconnect.
- `pushEventTo(this.el, event, payload)` targets the LiveComponent, not the
  parent LiveView.

## HEEx pitfalls

### Em-dash before `%>` breaks the tokenizer

HEEx comments use `<%!-- ... --%>` (ASCII double-dash). If a comment ends
with an em-dash or any sequence that looks like `--%>` to the parser, it
fails with a misleading error:

```
** (MatchError) no match of right hand side value:
    {:error, "expected closing '--%>' for EEx expression\n   |\n42 | ..."}
```

The error points at a line *inside* the comment, not at the comment itself,
which makes it hard to locate. The trigger is any `──%>` (em-dash + `%>`)
or similar sequence at the end of a `<%!-- --%>` block.

**Wrong (breaks):**
```heex
<%!-- Filtros combinables ──%>
<%!-- Board ──%>
```

**Right (ASCII dashes):**
```heex
<%!-- Filtros combinables --%>
<%!-- Board --%>
```

**Rule:** in HEEx comments, always close with ASCII `--%>`. Never let an
em-dash (`─`, U+2015) or en-dash (`–`, U+2013) sit immediately before `%>`.
This is a tokenizer limitation, not a style preference — the file will not
compile.

### Plan specs can carry this bug

Plan files in `.hermes/plans/*.md` sometimes contain HEEx snippets with
em-dash comment closers (copy-pasted from editors that auto-convert `--`
to `─`). When you transcribe a plan's HEEx into a `.ex` file, **re-check
all `<%!-- --%>` closers** before compiling. The plan renders fine as
markdown; the `.ex` file will not.

## Adding a new page type (end-to-end gatekeeper: `PageNewLive.type_to_page/1`)

When adding a new page type (e.g. `project`) with the standard
`/<plural>/new` route pointing at `PageNewLive`, you MUST extend the
`type_to_page/1` mapping in `lib/dran_web/live/page_new_live.ex` or the
`/new` form silently creates the wrong type.

### The pitfall

`PageNewLive` infers the page type from the request path via
`type_from_path/1` → `type_to_page/1` (around line 234-255). The mapping
is a hand-maintained clause list:

```elixir
defp type_to_page("notes"), do: "note"
defp type_to_page("concepts"), do: "concept"
# ... 9 entries ...
defp type_to_page(_), do: "note"   # ← fallback
```

If you add `live "/projects/new", PageNewLive, :new` to the router but
forget to add `defp type_to_page("projects"), do: "project"`, the
fallback clause fires and `/projects/new` creates a **note** instead of a
**project**. No compile error, no warning — the form just persists the
wrong `page_type`. The bug surfaces only at runtime when the saved page
shows up under `/notes` instead of `/projects`.

### Checklist when adding a page type

1. **`lib/my_app/brain/page_meta.ex`** — add the type to `@types`-style
   validation (`validate_meta_for_type/2`) and `meta_fields_for/1` so the
   form renders the right meta fields.
2. **`lib/dran_web/page_types.ex`** — add the type to the `@types` map
   (path, label, icon, plural) so `PageTypes.path/1`,
   `page_show_path/1`, etc. work.
3. **`lib/dran_web/live/page_new_live.ex`** — add the
   `type_to_page("plural")` clause. **This is the most-missed step.**
4. **`lib/dran_web/router.ex`** — add the three routes (index, new, show).
5. **`lib/dran_web/live/<type>_live.ex`** — the LiveView itself.
6. **`lib/dran_web/components/layouts.ex`** (optional) — add a sidebar
   nav entry with `key: "<plural>"` so `active_nav` highlights.

Step 3 is the silent-failure gatekeeper. Always grep
`type_to_page` after adding a type.

## Prefer DB-level `Brain.list_pages/1` filters over in-memory `Enum.filter`

When `Brain.list_pages/1` already supports a filter as a keyword option
(`:project_slug`, `:goal_slug`, `:plan_slug`, `:tag`, `:status`, etc.),
use it directly instead of loading all pages of a type and filtering in
memory with `Enum.filter`.

### Why

- DB-level filters push the `WHERE` clause into PostgreSQL (via
  `fragment("?->>'key'", p.meta)`), so you only transfer matching rows.
- In-memory filtering loads up to `limit: 500` rows (the common pattern)
  then discards most — wasteful on large contexts.
- The `:project_slug` filter (added in Phase 2 of the projects feature)
  already handles the `"none"` orphan case and exact-match case at the
  query level.

### Pattern

```elixir
# Preferred — DB filter
project_todos =
  Brain.list_pages(
    context_id: context.id,
    type: "todo",
    project_slug: page.slug,
    include_body: false,
    limit: 500
  )

# Acceptable fallback — only when no DB filter exists for the key
project_notes =
  context.id
  |> Brain.list_pages(type: "note", include_body: false, limit: 500)
  |> Enum.filter(fn p -> meta_get(p.meta, "project_slug") == page.slug end)
```

Plan specs sometimes show the in-memory pattern as the default
(`filter_by_slug` helper). When the DB filter exists, prefer it — the
plan's helper is a lowest-common-denominator fallback, not the target.

## `meta_get/2` convention: `get_in/2`, not `Map.get/2`

When copying the `meta_get/2` helper from an existing LiveView
(`goal_live.ex:621`), use the `get_in/2` form:

```elixir
defp meta_get(meta, key), do: get_in(meta, [key])
```

Not the `Map.get/2` form that some plan specs show:

```elixir
# Avoid — fails on nil meta and doesn't handle nested access
defp meta_get(meta, key) when is_map(meta), do: Map.get(meta, key)
defp meta_get(nil, _key), do: nil
```

`get_in/2` handles `nil` meta gracefully (returns `nil`) and is the
established form across all my_app LiveViews. Match it when copying
patterns between LiveViews.

## Multi-subagent `router.ex` coordination

When multiple subagents work on different features in the same Phoenix
app and both need to add routes to `router.ex`, the parent agent (or
orchestrator) resolves the merge. Each subagent should:

1. Add its routes in the authenticated `scope "/", DranWeb do ... end`
   block, near similar page-type routes.
2. NOT touch routes owned by other subagents (e.g. if a kanban subagent
   owns `/kanban`, the projects subagent leaves it alone).
3. Report any conflict (same path, overlapping `live` clauses) to the
   parent for resolution.

The router is a single file with a single authenticated scope — parallel
edits conflict. The parent merges by taking each subagent's route
additions and placing them in the right section.

## Overriding delegated `handle_event` handlers for index-list behavior

When a LiveView delegates `handle_event("archive_page", p, s)` to
`PageEdit.handle_event/3` (the shared handler that only updates the `page`
assign), the index view needs different behavior: the archived card must
disappear from the `pages` list. The delegation pattern works for the `:show`
action (detail view), but for `:index` you need to remove the page from the
list assign.

### Pattern: override with `live_action` guard

```elixir
# Remove the blanket delegation:
# def handle_event("archive_page", p, s), do: PageEdit.handle_event("archive_page", p, s)

# Replace with a clause that branches on live_action:
def handle_event("archive_page", %{"slug" => slug} = params, socket) do
  if socket.assigns.live_action == :show do
    PageEdit.handle_event("archive_page", params, socket)
  else
    context = socket.assigns.context

    case context && Brain.get_page_by_slug(slug, context.id) do
      nil ->
        {:noreply, socket}

      page ->
        case Brain.archive_page(page) do
          {:ok, _updated} ->
            pages = Enum.reject(socket.assigns.pages, &(&1.slug == slug))
            archived_pages = [page | socket.assigns[:archived_pages] || []]
            {:noreply, assign(socket, pages: pages, archived_pages: archived_pages)}

          {:error, _} ->
            {:noreply, put_flash(socket, :error, gettext("Could not archive page."))}
        end
    end
  end
end
```

**Key points:**
- The `:show` branch delegates to `PageEdit` (which updates the `page` assign
  and shows a flash).
- The `:index` branch archives the page, removes it from the `pages` list
  via `Enum.reject/2`, and prepends it to `archived_pages` so it appears in
  the collapsible archived section.
- **Remove the old blanket delegation** (`def handle_event("archive_page",
  p, s), do: PageEdit...`) — Elixir matches clauses top-to-bottom, so the
  more specific clause must be the only one, or it must appear before the
  catch-all delegation.

### When to use this pattern

Any time a shared `PageEdit` handler needs index-list-specific side effects
(archive, delete, status change that should update the list in place).
The same override technique works for `delete_page` if you want the card
to disappear without a full page reload.

## `update_page_meta/3` helper: update meta + refresh list in place

When a LiveView index page has inline controls that change a page's `meta`
(status select, health dots), you need to: (1) update the meta in the DB,
(2) replace the stale page struct in the `pages` assign list. The
`todo_live.ex` `update_meta/3` helper (line 461) is the canonical pattern;
adapted for non-stream list LiveViews:

```elixir
defp update_page_meta(socket, slug, updater) do
  context = socket.assigns.context

  if context do
    case Brain.get_page_by_slug(slug, context.id) do
      nil ->
        {:error, put_flash(socket, :error, gettext("Page not found."))}

      page ->
        new_meta = updater.(page.meta || %{})

        case Brain.update_page(page, %{"meta" => new_meta}) do
          {:ok, updated} ->
            pages =
              Enum.map(socket.assigns.pages, fn p ->
                if p.slug == slug, do: updated, else: p
              end)

            {:ok, assign(socket, pages: pages)}

          {:error, _} ->
            {:error, put_flash(socket, :error, gettext("Could not update page."))}
        end
    end
  else
    {:error, socket}
  end
end
```

**Usage in `handle_event`:**

```elixir
def handle_event("change_status", %{"slug" => slug, "status" => status}, socket) do
  case update_page_meta(socket, slug, &Map.put(&1, "status", status)) do
    {:ok, socket} -> {:noreply, socket}
    {:error, socket} -> {:noreply, socket}
  end
end
```

This pattern works for any meta field: `status`, `health`, `kanban_status`,
etc. The `updater` function receives the current meta map (or `%{}` if nil)
and returns the new meta map.

**Note:** if the LiveView uses LiveView streams instead of plain list assigns,
you must use `stream_insert/3` instead of `Enum.map` to update the item
in place — see "Converting page lists to LiveView streams" above.

## Click propagation in cards with inline controls

When a page card has `phx-click="show_page"` (navigates to detail) and
contains inline controls (select dropdowns, buttons), you need to prevent
the controls from triggering the card's click handler.

### `phx-change` on `<select>` — no stopPropagation needed

A `<form phx-change="change_status">` wrapping a `<select>` fires a **form
event**, not a click event. Form events do NOT bubble to the parent's
`phx-click`. So a status select inside a clickable card works without any
propagation guard:

```heex
<div phx-click="show_page" phx-value-slug={page.slug}>
  <!-- ... card content ... -->
  <form phx-change="change_status" phx-value-slug={page.slug}>
    <select name="status" class={...}>
      <option :for={status <- status_options(@page_type)} value={status} selected={...}>
        {String.capitalize(status)}
      </option>
    </select>
  </form>
</div>
```

### `phx-click` buttons inside a card — need `noop` wrapper

Buttons with `phx-click` (like health dots or an archive button) DO
trigger the parent card's `phx-click`. To stop propagation without inline
JavaScript (which AGENTS.md forbids), wrap the buttons in a div with
`phx-click="noop"`:

```heex
<div phx-click="noop" class="flex items-center gap-1">
  <button
    :for={{color, label} <- health_options()}
    phx-click="change_health"
    phx-value-slug={page.slug}
    phx-value-health={color}
    class={...}
  />
</div>
```

Add a `noop` handler in the LiveView:

```elixir
def handle_event("noop", _params, socket), do: {:noreply, socket}
```

The `noop` handler consumes the click event so it doesn't bubble to the
card's `show_page` handler. The inner buttons' `phx-click` events fire
normally because they are more specific targets.

### Archive button — no wrapper needed

A standalone `phx-click="archive_page"` button inside the card does NOT
need a `noop` wrapper — the button's own `phx-click` takes precedence over
the parent's `phx-click` (Phoenix dispatches to the closest element with a
`phx-click` binding). The card's `show_page` is not triggered.

## Status-aware select styling in page list cards

For inline status selects in page list cards (project/plan), use
status-aware coloring that matches the badge conventions:

```elixir
defp status_select_class("done"),
  do: "text-xs rounded-md border border-base-300 px-2 py-1 bg-green-100 text-green-700 font-medium cursor-pointer"

defp status_select_class("active"),
  do: "text-xs rounded-md border border-base-300 px-2 py-1 bg-blue-100 text-blue-700 font-medium cursor-pointer"

defp status_select_class("on_hold"),
  do: "text-xs rounded-md border border-base-300 px-2 py-1 bg-yellow-100 text-yellow-700 font-medium cursor-pointer"

defp status_select_class("draft"),
  do: "text-xs rounded-md border border-base-300 px-2 py-1 bg-base-200 text-base-content/60 cursor-pointer"
```

Color mapping: done=green, active=blue, on_hold=yellow, draft=gray. This
matches the `status_button_class/3` pattern from `todo_helpers.ex` but
adapted for `<select>` elements (which can't use the active/inactive
button toggle pattern).

## Health dot indicators for goal cards

For goal pages, use clickable colored dots instead of a select:

```heex
<div phx-click="noop" class="flex items-center gap-1">
  <button
    :for={{color, label} <- health_options()}
    phx-click="change_health"
    phx-value-slug={page.slug}
    phx-value-health={color}
    class={[
      "size-3 rounded-full transition-all",
      health_dot_class(color, health_value(page))
    ]}
  />
</div>
```

```elixir
defp health_options, do: [{"green", gettext("Green")}, {"yellow", gettext("Yellow")}, {"red", gettext("Red")}]
defp health_value(page), do: Map.get(page.meta || %{}, "health") || "green"

defp health_dot_class(color, current) when color == current,
  do: health_color(color) <> " ring-2 ring-offset-1 ring-base-300"
defp health_dot_class(color, _current),
  do: health_color(color) <> " opacity-30 hover:opacity-70"

defp health_color("green"), do: "bg-green-500"
defp health_color("yellow"), do: "bg-yellow-500"
defp health_color("red"), do: "bg-red-500"
```

Current health is highlighted with a ring; others are dimmed with
`opacity-30` and brighten on hover.

## Plan-vs-repo convention conflicts

When a plan spec (`.hermes/plans/*.md`) disagrees with the actual repo
convention, **the repo wins**. Plans are guides written ahead of
implementation; they can be wrong about naming, syntax, or established
patterns. The repo is the source of truth for conventions.

### Workflow when a plan and the repo disagree

1. **Read the plan section** to understand the intent.
2. **Read the existing code** that implements the same pattern — use
   `search_files` for the mechanism (e.g. `ColocatedHook`, `assign_to_socket`,
   `phx-hook`) to find canonical examples.
3. **Match the repo's form**, not the plan's. If the plan says
   `name="KanbanDragDrop"` but every existing hook uses a leading dot
   (`.GoalKanban`, `.KanbanBoard`), use the dot.
4. **Note the deviation in your report** so the human knows the plan was
   not followed verbatim and why.

This applies to: hook naming, Auth patterns, button classes, layout
assigns, router scope placement, and any other convention the repo has
already established. When the task instructions explicitly say "copy the
pattern from X file" (e.g. "usa el MISMO mecanismo que ya funciona en
goal_live.ex"), that file is authoritative — read it first and match its
form exactly, even if the plan's code block shows something different.

