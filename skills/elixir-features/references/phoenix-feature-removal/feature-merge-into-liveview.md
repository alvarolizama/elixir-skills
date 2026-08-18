# Feature Merge into Existing LiveView

Relocating a whole feature page (e.g. `/dashboard/alerts`) into an existing
LiveView (e.g. `/dashboard/logs`) as sections, rather than building a new
dedicated page. Same discipline as full feature removal, but the destination
LiveView absorbs the moved sections.

## When to Use

- User says "merge X into Y", "move alerts into logs", "consolidate X and Y"
  in a Phoenix app.
- The old page has standalone sections (KPI cards, tables, forms) that fit
  naturally as blocks inside the destination page.

## Merge Checklist

### 1. Map the source page's blast radius

Same as `phoenix-feature-removal` — find every piece:
- LiveView module + route + router entry
- Sidebar link + badge/count logic
- Tests (often a dedicated `*_live_test.exs`)
- Helpers that only serve the source page

### 2. Absorb into the destination LiveView

| Source piece | Where it goes in destination |
|-------------|------------------------------|
| KPI summary cards | New row in the existing KPI strip (or above it), gated by `:if` on admin + non-empty data |
| Data tables | New `<div :if={...} class="space-y-2">` sections below KPIs, above the main table |
| `handle_event` clauses (reactivate, reset, etc.) | Copy as-is into destination's `handle_event` block |
| Data-loading helpers (`load_alerts`, etc.) | Copy as private functions, rename if collision |
| `handle_info` clauses (PubSub subscriptions) | Add new `handle_info` clauses for the source's topics |
| `mount` assigns | Add source's assigns to destination's `mount` |

### 3. Add new capabilities (if requested)

The merge is a natural time to add features that only make sense in the
combined page:

- **New filter**: add to `default_filters/0`, `build_filters/2`,
  `log_matches_filters?/3`, and the template's `<.form>` as a new `<.input>`
- **CSV export**: add a clause to the existing export controller
  (`StatsExportController`) with `build_csv(user, "errors", ...)`
- **Sidebar badge**: pass an `alert_count` attr to the sidebar component;
  compute it in `dashboard_sidebar/1` with the same queries the old page used

### 4. Real-time notifications

If the merged feature has events that should toast/flash (breaker opened,
credential error), the cleanest path is PubSub:

1. **Broadcast** from the event source (e.g. `circuit_breaker.ex` on trip,
   `proxy_controller.ex` on credential disable):
   ```elixir
   Phoenix.PubSub.broadcast(MyApp.PubSub, "alerts", {:breaker_opened, cred_id, reason})
   ```
2. **Subscribe** in destination's `mount` when `connected?(socket)`:
   ```elixir
   Phoenix.PubSub.subscribe(@pubsub, "alerts")
   ```
3. **Handle** in destination:
   ```elixir
   def handle_info({:breaker_opened, _cred_id, reason}, socket) do
     {:noreply, socket |> put_flash(:error, "Circuit breaker abierto") |> load_alert_data()}
   end
   ```

### 5. Delete the source page

After the destination is verified working:
- `rm` the source LiveView file
- Remove the route from `router.ex`
- Remove the sidebar link
- Migrate tests: copy relevant test cases to the destination's test file,
  adapting paths (`~p"/dashboard/alerts"` → `~p"/dashboard/logs"`) and
  adding any new fixture helpers (`broke_member_fixture`, `log_spend`, etc.)
- Delete the source test file

## Grouped Pagination Pattern ("ver más")

When a merged table has many rows and the user asks to group + paginate
(e.g. "agrupalos por equipo y muestra de 10 en 10 y luego abajo link de ver
más"), the pattern is:

1. **Group in `load_*`**: `Enum.group_by(rows, & &1.group_id)` → assign as
   `@rows_by_group`
2. **Track per-group page counts**: assign `shown_counts: %{}` (map of
   `group_id → N shown`) and `per_page: 10`
3. **Handle "show more"**: increment the count for that group:
   ```elixir
   def handle_event("show_more", %{"group-id" => id}, socket) do
     shown = Map.get(socket.assigns.shown_counts, id, @per_page)
     {:noreply, assign(socket, :shown_counts, Map.put(socket.assigns.shown_counts, id, shown + @per_page))}
   end
   ```
4. **Render**: iterate groups with `:for={{group_id, rows} <- @rows_by_group}`,
   `Enum.take(rows, Map.get(@shown_counts, group_id, @per_page))`, and a
   `:if={length(rows) > Map.get(@shown_counts, group_id, @per_page)}` button
   showing remaining count.

Key detail: module attributes (`@per_page`) are NOT available in templates —
they must be assigned to the socket (`assign(:per_page, @per_page)`) or the
template crashes with `KeyError: key :per_page not found`.

## Layout Fix After Element Removal

When removing a UI element from a flex container (e.g. a `<select>` next to
a CSV button), the container's `justify-between` no longer makes sense —
the remaining element hugs the left edge. Change to `justify-end` to keep
it right-aligned, or `justify-center` if it should be centered. Grep for
`justify-between` in the file after any removal to catch these.

## Verification

1. `mix compile --warnings-as-errors` clean
2. `mix test test/my_app_web/live/destination_live_test.exs` green
3. `mix test test/my_app_web` full suite green
4. `mix precommit` green
5. Manual smoke: visit destination page, verify merged sections render,
   old route 404s

## Pitfalls

- **Assign collisions**: if both source and destination have `@teams`,
  `@models`, etc., rename one set or scope them (`@alert_teams` vs
  `@filter_teams`).
- **Unused alias warnings**: merging code often orphans `alias` lines that
  `--warnings-as-errors` catches. Remove them immediately after the merge.
- **handle_info topic overlap**: if both pages subscribed to the same topic
  (e.g. `"logs:new"`), keep only ONE `handle_info` clause in the destination
  and merge the logic (e.g. prepend log AND check for errors).
- **Sidebar badge needs the attr**: adding `badge={@alert_count}` to
  `sidebar_link` without passing `alert_count` from `dashboard_sidebar` or
  the `Layouts.dashboard` component silently renders nothing.
- **Test fixture helpers**: when migrating tests, also migrate private
  fixture helpers (`broke_member_fixture`, `log_spend`) and any `setup`
  blocks that start required processes (`Budgets.Manager`).
- **Route removal breaks `~p` sigils**: if any remaining template or
  controller uses `~p"/dashboard/alerts"`, compile fails with
  "undefined route". Grep for the path string before deleting the route.
- **Module attributes in templates**: `@per_page` inside a module attribute
  works in Elixir code but NOT in HEEx templates — assign it to the socket
  or use a literal. The compiler won't catch this; it's a runtime `KeyError`.
- **`defp` helpers are invisible in external `.html.heex`**: when the source
  LiveView uses an inline `~H"""` template, private helpers (`defp`) are
  callable from the template because the sigil compiles inside the module.
  But if the **destination** LiveView uses an external `.html.heex` file
  (no `~H` sigil — the template lives in a separate file), only **public**
  functions (`def`) are callable from the template. Symptom: `UndefinedFunctionError`
  at render time, not compile time. Fix: change all `defp` helpers that the
  template calls to `def`. MyApp 2026-08-08: moving alert helpers
  (`api_key_prefix`, `fmt_money`, `reason_label`, `fmt_duration`, `budget_periods`,
  `errors_for_credential`) from LogsLive (inline `~H`) to MonitorLive (external
  `.html.heex`) — all had to be promoted from `defp` to `def`.
- **Clause ordering when moving `handle_info` + `handle_event`**: two Elixir
  compiler warnings that bite when you paste handlers into the destination:
  1. **`handle_info` catch-all shadows specific clauses** — the catch-all
     `def handle_info(_msg, socket), do: {:noreply, socket}` must come LAST.
     If you paste new specific clauses (e.g. `{:breaker_opened, ...}`) AFTER
     the catch-all, they're dead code — the compiler warns "this clause for
     handle_info/2 cannot match because a previous clause always matches".
  2. **`handle_event` clauses split by `defp`** — all `handle_event/3` clauses
     must be contiguous. If you paste new event handlers, then have `defp`
     data-loading helpers, then the destination's existing event handlers,
     the compiler warns "clauses with the same name and arity should be
     grouped together". Fix: move all `handle_event` clauses together (after
     the `defp` helpers), or remove redundant `@impl true` annotations that
     split the group. A single `@impl true` before the first `handle_event`
     clause covers all subsequent ones — extra `@impl true` between split
     clauses is what triggers the "should be grouped" warning.
  MyApp 2026-08-08: both warnings appeared when moving 2 `handle_event`
  + 2 `handle_info` alert handlers from LogsLive to MonitorLive.
