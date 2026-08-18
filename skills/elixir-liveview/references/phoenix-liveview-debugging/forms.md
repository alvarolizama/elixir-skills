---
name: phoenix-liveview-crud-forms
description: |
  Use when making Phoenix LiveView add/edit forms consistent.
trigger: |
  Use when the user asks to make add/edit forms consistent, move any inline form (add OR edit) into a modal, audit all CRUD pages for non-modal forms, or verify that all edit fields are also available on create in a Phoenix LiveView CRUD page.
version: 1.1.0
---

# Phoenix LiveView CRUD Forms — Add/Edit Consistency

## When to use

- A user says "add should be a modal like edit", "show all fields in add and edit", or
  "make add/edit consistent".
- You are auditing LiveView CRUD pages and find one page uses an inline add card while
  others use modals.
- You need to recover from a bad patch that duplicated functions or mangled event order.

## Recipe

### 1. Audit scope first

Before editing, search the relevant `lib/my_app_web/live/*.ex` files for:

- `phx-click="new_` / `phx-click="add_` — how the add flow is triggered.
- `class="fixed inset-0` — existing modals (these are the pattern to match).
- `<.form for={@form}` / `<.form for={@*_form}` — form assigns.

Confirm with the user whether the change applies to one CRUD page or to all of them.
Do **not** blanket-rewrite every CRUD page unless explicitly told to.

### 2. Convert inline add form to modal

In the LiveView module:

- Replace the inline form assign (`@member_form`, etc.) with:
  - `@show_add_modal?` boolean, default `false`.
  - `@add_form` built by a private helper such as `add_member_form/0`.
- Add open/close events:
  - `handle_event("new_...", _params, socket)` → `show_add_modal?: true`, reset form.
  - `handle_event("cancel_...", _params, socket)` → `show_add_modal?: false`, reset form.
- Change the submit handler to expect nested params, e.g.:
  - `%{"add_member" => params}` when the form was built with `as: :add_member`.
- Reuse the same parsing helpers used by the edit form (`parse_decimal/1`,
  `parse_integer/1`, etc.).

In the HEEx template:

- Replace the inline card with a small trigger button (`phx-click="new_..."`).
- Add a modal wrapper matching the project's existing modal markup:
  - `fixed inset-0 z-50 flex items-center justify-center p-4`.
  - Overlay `div` with `phx-click="cancel_..."`.
  - Inner card with form and Cancel/Submit buttons.
- Include **the same fields** as the edit form, in the same order when possible.

### 2a. Convert inline edit form (nested in a :for loop) to global modal

A common pattern is an edit form rendered *inside* a `<:for ...>` loop using the
loop variable directly:

```heex
<%= if @editing_member_id == member.id do %>
  <div ...>
    <.form for={to_form(%{...member fields...})} id={"override-form-#{member.id}"}>
      <.input field={to_form(%{})[:field]} ... value={member.field} />
      ...
    </.form>
  </div>
<% end %>
```

To move this to a global modal that lives outside the loop:

1. **Resolve the entity from an assign.** The modal can't use the loop variable,
   so look it up by ID:
   ```heex
   <% member = Enum.find(@members, &(&1.id == @editing_member_id)) %>
   <.form :if={member} ...>
   ```
2. **Place the modal block at the same level as the add-member modal** — outside
   `@streams` / `<:for>`, directly under the main container `div`.
3. **Keep the existing form `id`** — tests reference IDs like `#override-form-#{member.id}`,
   and keeping the id format avoids breakage (just swap the source variable).
4. **Keep `phx-value-id={@editing_member_id}`** on the form so the submit handler
   still receives the correct entity ID.
5. **Remove the old inline block entirely** — leaving it as a dead branch causes a
   confusing duplicate UI when `@editing_member_id` is set.

### 2b. Remove stale visibility guards

When a form was inline, sibling elements often carried `:if` guards to hide
themselves while the form was open (e.g. hide the list while editing):

```heex
<button :if={@editing_webhook_team_id != team.id or @webhook_form == nil} ...>
<div :if={@editing_webhook_team_id != team.id or @webhook_form == nil} ...>
```

After moving the form to a modal, these guards become **harmful**: the list and
the trigger button must *always* be visible (the modal overlays them). Strip the
`:if` from both the trigger button and the list container.

### 2c. Audit pattern: find ALL inline forms across every CRUD page

When the user says "revisa todos los edit y create" (review all edit/create),
don't guess which pages have inline forms. Use two complementary searches:

1. **Find modals** — `pattern: "fixed inset-0"` on `lib/.../live/`. This gives
   the files (and line numbers) of forms already converted to modals.
2. **Find all forms** — `pattern: "<\\.form|phx-submit"` on the same directory.
   Cross-reference: any form whose surrounding markup does NOT contain
   `fixed inset-0` is inline and needs conversion.

Filter forms in `logs_live` etc. that are search/filter forms (no submit to
persist data) — those stay inline. Focus on create/edit/save forms that mutate
state.

### 3. Per-entity inline form (inside a :for loop) → global modal with assign-sourced IDs

A variant of section 2a: the form lives inside a `:for` loop and uses the loop
variable in its element IDs (e.g. `#destination-form-#{team.id}`). Moving it to
a global modal requires rewriting IDs to use a single assign instead.

Pattern (webhook form in a teams list):

1. **Delete the inline form block** from inside the `:for` loop.
2. **Add a global modal** (sibling to other modals, outside `@streams`):
   - `:if={@webhook_form}` — visible whenever a form is loaded.
   - ID format: `id={"destination-form-#{@editing_webhook_team_id}"}` — replaces
     the per-loop `#{team.id}` with the assign.
   - Form fields reference `@webhook_form` (unchanged).
3. **Remove stale visibility guards** on the list and trigger button that
   previously hid them while the form was open (same as section 2b).
4. **Preserve test-referenced IDs** — tests that assert `#destination-form-#{team.id}`
   still pass because the assign value equals `team.id` for the team being edited.

Key insight: the form's `id` doesn't need the loop variable — it just needs a
unique identifier that resolves to the entity being edited. An assign like
`@editing_webhook_team_id` serves the same purpose.

### 4. Keep add/edit field parity

If the edit form exposes extras/overrides, the add modal should expose them too so the
user can set them at creation time. Example fields:

- email / identifier
- role (select)
- extra_daily_budget_usd
- extra_concurrency
- extra_rpm

On create, pass all parsed values to the context function in one call rather than
creating the record and then patching it.

### 5. Update tests

LiveView tests for the new modal flow must:

- Click the trigger button before filling the form:
  ```elixir
  assert view |> element("#new-member-btn") |> render_click()
  ```
- Submit nested params using the form `as:` name:
  ```elixir
  |> form("#add-member-form", %{
       "add_member[email]" => email,
       "add_member[team_role]" => "user",
       "add_member[extra_daily_budget_usd]" => "5.00",
       ...
     })
  |> render_submit()
  ```
- Add a cancellation test that asserts the modal disappears.

### 6. Clean compile before precommit

Run `mix test <specific-file>` first. If compilation warnings about duplicate or
out-of-order functions appear, fix them immediately. A botched multi-patch sequence can
leave duplicated `handle_event/3` clauses or private helpers in the wrong section.

### 7. Expose base limits and per-item extras in the list/card view

Add/edit parity is not only about the modal. The summary card for each row should also
show the base limit and any per-item extras, and computed totals must include the base.

Example pattern (team-member budget card):

- Pass the team-level base pool into the row budget helper:
  ```elixir
  defp budget_for_member(member, team_pool, extra_alias_details, alias_map) do
    ...
    total_max = team_pool + member_extra + model_extra_total
    %{..., team_pool: team_pool, total_max: total_max}
  end
  ```
- Show a **"Tope base"** column alongside extras.
- Show per-model extras as editable rows or inline forms, not just checkboxes.
- Verify that **Consumo máximo estimado** equals base + general extras + model extras.

### 7a. Boolean toggle fields (checkbox) on a modal form

When adding feature flags (`prompt_cache_enabled`, `lazy_cleanup_enabled`, etc.) to a
modal form that already exists (e.g. an "Edit guard rails" modal), use the project's
`<.input>` component with `type="checkbox"`:

```heex
<.input
  field={@form[:prompt_cache_enabled]}
  type="checkbox"
  label="Prompt caching"
  hint="Reordena system prompts al frente para maximizar cache hits"
/>
```

**Pre-requisites — verify before adding the toggle to the template:**

1. The field is in the schema's `cast/3` call (Ecto silently drops uncast attrs and
   the form value never persists).
2. The schema declares `field :foo_enabled, :boolean, default: false` — the `default`
   is required so the form renders unchecked on existing rows that pre-date the migration.
3. The migration is `null: false` with a default, so old rows backfill cleanly.

Style guidance:
- Stack toggle fields after the long-form textarea, before the action buttons.
- Use the `hint` slot for a one-line Spanish explanation of the toggle's effect.
- No need for a separate "Save toggles" button — `phx-submit="save_<thing>"` already
  handles it because the form wraps all fields.
- If the toggle is a route/concrete-side trigger (e.g. enables prompt reordering in
  the proxy), wire it in the proxy controller AFTER the schema/cast step, not via
  a separate admin setting. One source of truth.

### 8. Per-item extra fields (e.g. per-model budget)

When each row in a list can carry its own numeric override:

- Use a small `<.form>` per item with hidden `member_id`/`alias_id` inputs plus the
  visible input and a save button.
- Keep the checkbox in the same form for toggling access; clicking it should still
  trigger the separate toggle event, while the number field + save button persists the
  budget.
- In tests, submit the nested form after enabling the checkbox:
  ```elixir
  view |> element("#extra-alias-member-id-alias-id") |> render_click()

  view
  |> form("#alias-extra-form-member-id-alias-id", %{
       alias_extra: %{member_id: member.id, alias_id: alias_.id, extra_daily_budget_usd: "7.50"}
     })
  |> render_submit()
  ```

### 9. Table column grouping (wide tables)

When a LiveView table has many flat columns (15-20+), group them visually with
a two-row `<thead>`:

1. **Group header row** — first `<tr>` with `<th colspan="N">` per group:
   ```heex
   <tr class="border-b-0">
     <th colspan="7" class="text-[10px] uppercase tracking-wider text-primary/70 bg-primary/5 border-r border-base-200">
       Identidad
     </th>
     <th colspan="5" class="text-[10px] uppercase tracking-wider text-accent/70 bg-accent/5 border-r border-base-200">
       Request
     </th>
     ...
   </tr>
   ```
2. **Column header row** — second `<tr>` with the individual `<th>` labels.
   Add `border-r border-base-200` to the last `<th>` of each group for a
   visual separator.
3. **Body cells** — add `border-r border-base-200` to the last `<td>` of each
   group in the `:for` row.
4. **Empty-state `colspan`** — update the `colspan` on the empty-state row to
   match the new total column count.
5. **Reorder columns** so they belong to their group — e.g. move "Proveedor"
   from after cost columns to the Identidad group where it logically belongs.

This makes wide tables scannable and reduces the "mezcladas" (mixed up) feel.

### 10. Sidebar section grouping

When a dashboard sidebar has links dumped in a flat list or duplicate section
headers:

1. **Group by domain** — Configuración, Acceso, Monitoreo, etc.
2. **Admin-only links inside each group** — use `:if={admin?(@current_scope)}`
   per link (not per group) so non-admin users still see the groups they have
   access to (e.g. Equipos and Logs are non-admin).
3. **No duplicate headers** — ensure each section header appears only once.
4. **Order within groups** — follow the user's specified order (e.g.
   Proveedores → Modelos → Equipos), not alphabetical.

## Pitfalls — additional

- **Nested params mismatch**: changing from a flat form (`%{"email" => ...}`) to a named
  form (`as: :add_member`) without updating both the event handler and the test params
  causes silent form failures or match errors.
- **Per-item form missing hidden IDs**: tests will fail with "could not find non-disabled
  input ... with name `alias_extra[alias_id]`" if the form relies only on `to_form/2`
  `as:` names for hidden IDs. Add explicit hidden inputs for foreign-key IDs:
  ```heex
  <input type="hidden" name="alias_extra[member_id]" value={member.id} />
  <input type="hidden" name="alias_extra[alias_id]" value={alias.id} />
  ```
- **Base limit omitted from computed total**: users expect the max budget to be
  `base + general_extra + model_extras`. If the helper only sums extras, the displayed
  total will be wrong even when each field is correct.
- **Duplicate functions after a failed patch**: when several patches leave the file in an
  inconsistent state (e.g. duplicated `handle_event` clauses, helpers in the wrong
  section), do not keep patching. Re-read the whole file and rewrite it cleanly with
  `write_file`.
- **Stale assign names**: remove the old form assign from `mount/3` and the template, and
  replace all template references (`@member_form` → `@add_form`).
- **Forgetting to reset the form on success**: the modal should reset so a second add does
  not show stale values.
- **Precommit blocker from unrelated warning**: if `mix precommit` fails on an unused
  alias in a sibling file, fix that warning too rather than leaving it for a separate
  commit.
- **Stale visibility guards after modal conversion**: when moving an inline form to a
  modal, sibling elements that had `:if={@editing_X_id != entity.id or @form == nil}`
  must have those guards removed — the list and trigger button must always render
  because the modal now overlays them. Forgetting this leaves the list disappearing
  when you click edit.
- **Loop variable in global modal**: a form that was inside `<:for>` uses the loop
  variable (`member`, `team`, etc.) directly. A global modal lives outside the loop,
  so you must resolve the entity via `Enum.find(@members, &(&1.id == @editing_id))`.
  Guard the form with `:if={member}` in case the assign is stale.
- **Breaking test selectors on form relocation**: tests reference element IDs like
  `#destination-form-#{team.id}` or `#override-form-#{member.id}`. When moving a form
  to a modal, preserve the ID format — just swap the source variable from the loop
  variable to the assign (e.g. `@editing_member_id`). Do NOT rename the ID scheme.

- **Colspan mismatch after column changes**: when you add or remove a column
  (e.g. adding "Streaming" to the logs table), the empty-state row's `colspan`
  must match the new total. A mismatch causes the empty-state row to render
  misaligned or invisible.
- **Forgetting to update `colspan` after column reordering**: when you add
  group header rows to a wide table, the `colspan` values on each group header
  must sum to the total number of data columns. Double-check the arithmetic.

### Virtual mirror field for unit conversion (column in ms, form in seconds)

When the form input expects a unit different from the DB column
(seconds vs milliseconds, bytes vs KB, requests vs RPM, etc.),
do NOT do the conversion in the LiveView's `handle_event`. The
form already loses precision once you transform strings in Elixir
(`.input type="number"` submits a string), and the `validate_number`
on the column range will reject the value as out-of-range. The clean
pattern is a **virtual mirror field + sync in the changeset**.

#### Step-by-step

1. **Add a virtual field on the schema** that mirrors the stored field
   in the form's unit:

   ```elixir
   schema "model_providers" do
     field :sticky_ttl_ms, :integer                              # stored (ms)
     field :sticky_ttl_seconds, :integer, virtual: true          # form (seconds)
     # ... other fields ...
   end
   ```

2. **Cast both**, validate each in its own unit, then sync in the changeset:

   ```elixir
   |> cast(attrs, [..., :sticky_ttl_ms, :sticky_ttl_seconds, ...])
   |> validate_number(:sticky_ttl_ms,
     greater_than_or_equal_to: 1_000,
     less_than_or_equal_to: 24 * 60 * 60 * 1000)
   |> validate_number(:sticky_ttl_seconds,
     greater_than_or_equal_to: 1,
     less_than_or_equal_to: 24 * 60 * 60)
   |> sync_sticky_ttl_fields()
   ```

3. **The sync helper** keeps both fields coherent — derived from the
   submitted one, with `force_change/3` to avoid "field was not cast" errors:

   ```elixir
   defp sync_sticky_ttl_fields(changeset) do
     seconds = get_field(changeset, :sticky_ttl_seconds)
     ms = get_field(changeset, :sticky_ttl_ms)

     case {seconds, ms} do
       # Edit pre-fill: stored value present, no submission.
       {nil, ms} when not is_nil(ms) ->
         changeset
         |> put_change(:sticky_ttl_seconds, div(ms, 1000))
         |> force_change(:sticky_ttl_ms, ms)

       # User submitted in seconds: derive ms.
       {seconds, _} when not is_nil(seconds) ->
         ms_value = seconds * 1000
         changeset
         |> put_change(:sticky_ttl_ms, ms_value)
         |> force_change(:sticky_ttl_seconds, seconds)

       # Both nil: user wants default (StickyTracker 15-min).
       _ ->
         changeset
         |> put_change(:sticky_ttl_ms, nil)
         |> put_change(:sticky_ttl_seconds, nil)
     end
   end
   ```

4. **The form binds to the virtual field** — HEEx never sees the raw
   column name:

   ```heex
   <.input
     field={@provider_form[:sticky_ttl_seconds]}
     type="number"
     label="TTL sticky (segundos)"
     hint="Vacío = 15 min (default). Mínimo 1 s, máximo 86 400 s (24 h)."
   />
   ```

5. **Edit pre-fill comes for free** — when `to_form(changeset, ...)` is
   built for an existing row, the virtual field is already populated
   by the sync (the `ms` branch above), so the form input shows `900`
   instead of `900_000`.

#### Why this beats a `handle_event` transform

- **Single source of truth.** The unit conversion lives in the
  schema's changeset, where it belongs. The LiveView is pure UI.
- **Edit pre-fill works automatically.** No need to manually divide
  in the LiveView when populating the form.
- **Validation is unit-aware.** Users see "min 1 s, max 24 h" in the
  form hint; the column validation enforces ms under the hood.
- **No DB migration.** The column stays in ms. Only the schema gains
  a virtual field.
- **Force change is required** when populating a field the user did
  not submit (the `ms` branch above) — `put_change/3` would raise
  "cannot change a field that was not cast" on the new value. Use
  `force_change/3` for the `ms` field in that branch.

#### Anti-pattern: dividing in `handle_event`

```elixir
# WRONG — accepts seconds from form, divides by 1000, sends to context
def handle_event("save_model_provider", %{"model_provider" => ap_params}, socket) do
  ap_params = Map.update(ap_params, "sticky_ttl_ms", nil, fn v ->
    case Integer.parse(v) do {n, ""} -> n * 1000; _ -> v end
  end)
  ...
end
```

This is brittle: empty string from the form, nil pre-fill, integer
overflows on `Integer.parse`, validation re-runs in the changeset on
a value you already "validated" client-side. The changeset pattern
above is one place, one rule, one round-trip.



- **Decimal.to_string/1 preserves full scale**: `Decimal.to_string(d)` outputs
  the full internal scale — a value stored as `20.00` in Postgres renders as
  `$20.000000` instead of `$20.00`. Always round before displaying:
  ```elixir
  defp format_decimal(%Decimal{} = d), do: d |> Decimal.round(2) |> Decimal.to_string()
  ```
  Search all LiveView modules for bare `Decimal.to_string` on Decimal values
  to find stale format helpers.

### 11. Live autocomplete (typeahead) on form inputs

When a form field expects a value that exists in the DB (e.g. "add member by
email"), replace the bare text input with a live-search autocomplete. The
pattern uses `phx-change` + `phx-debounce` to fire a search event, a dropdown
of clickable suggestions, and a `select` event to fill the input.

#### Backend

1. **Add a search function to the context** (e.g. `Accounts.search_users/2`)
   using `ilike/2` on the relevant fields, with a `LIMIT` (default 10) and a
   minimum query length guard (≥ 2 chars to avoid full-table scans on short
   strings):

   ```elixir
   def search_users(query, limit \\ 10) when is_binary(query) do
     pattern = "%#{String.downcase(query)}%"
     Repo.all(
       from u in User,
         where: ilike(u.email, ^pattern) or ilike(u.name, ^pattern),
         order_by: [asc: u.email],
         limit: ^limit
     )
   end
   ```

2. **Initialize an `email_suggestions` assign** in `mount` (default `[]`).

3. **`handle_event("search_email", ...)`** — debounce is handled client-side
   by `phx-debounce`, so the handler just queries and assigns:

   ```elixir
   def handle_event("search_email", %{"add_member" => %{"email" => query}}, socket) do
     suggestions =
       case String.trim(query) do
         "" -> []
         trimmed when byte_size(trimmed) < 2 -> []
         trimmed -> Accounts.search_users(trimmed)
       end
     {:noreply, assign(socket, :email_suggestions, suggestions)}
   end
   ```

4. **`handle_event("select_email", ...)`** — fills the form field and clears
   suggestions. Update the form params, not the input value directly:

   ```elixir
   def handle_event("select_email", %{"email" => email}, socket) do
     form =
       socket.assigns.add_form
       |> Map.update!(:params, fn params -> Map.put(params, "email", email) end)
     {:noreply,
      socket
      |> assign(:add_form, to_form(form.params, as: :add_member))
      |> assign(:email_suggestions, [])}
   end
   ```

   Rebuild the form with `to_form/2` so the input value updates in the DOM.

5. **Clear suggestions on modal close** — add `assign(:email_suggestions, [])`
   to the cancel handler so stale suggestions don't show on reopen.

#### Template

Wrap the input in a `relative` container and render a dropdown below it.
The input carries `phx-change="search_email"` and `phx-debounce="300"`:

```heex
<div class="sm:col-span-2 relative">
  <.input
    field={@add_form[:email]}
    type="email"
    label="Email del usuario"
    placeholder="usuario@ejemplo.com"
    phx-change="search_email"
    phx-debounce="300"
  />
  <div
    :if={@email_suggestions != []}
    class="absolute z-50 left-0 right-0 mt-1 bg-base-100 border border-base-300 rounded-lg shadow-lg max-h-60 overflow-y-auto"
  >
    <button
      :for={user <- @email_suggestions}
      type="button"
      phx-click="select_email"
      phx-value-email={user.email}
      class="w-full text-left px-3 py-2 hover:bg-base-200 transition-colors flex items-center gap-3"
    >
      <div class="flex-1 min-w-0">
        <p class="text-sm font-medium truncate">{user.email}</p>
        <p class="text-xs text-base-content/50 truncate">{user.name}</p>
      </div>
    </button>
  </div>
</div>
```

#### Pitfalls

- **`phx-debounce` on `<.input>`**: the core_components `<.input>` component
  passes through `phx-*` attributes to the underlying input element, so
  `phx-change` and `phx-debounce` work directly without extra wiring.
- **Form param shape**: when the form is built with `as: :add_member`, the
  `phx-change` event receives `%{"add_member" => %{"email" => "..."}}`, not
  a flat `%{"email" => "..."}`. Match the nested shape in the handler.
- **`z-index` on dropdown**: modals already use `z-50`, so the suggestion
  dropdown also needs `z-50` (or higher) to appear above the modal content.
- **Stale suggestions**: if the user clears the input, the `phx-change` fires
  with an empty string — the handler returns `[]` and the dropdown disappears.
  No extra JS needed.

### 11a. Select → autocomplete (replacing `<select>` with searchable dropdown)

When a `<select>` has too many options (teams, members, models), replace it
with a text input + filtered dropdown + hidden input pattern. This gives
typeahead search without a JS framework.

**Pattern:**
1. Replace `<.input type="select">` with:
   - A visible `<input type="text">` for the search/display value
   - A hidden `<input type="hidden">` for the actual FK value
   - A filtered dropdown of clickable suggestions below
2. Store the search text in a `*_search` assign (e.g. `@scope_team_search`)
3. Filter the full list in the template with `String.contains?` (case-insensitive)
4. On click, set both the hidden FK value AND the display text

```heex
<div class="relative">
  <label class="text-sm font-medium">Equipo exclusivo</label>
  <input
    type="text"
    value={@scope_team_search}
    placeholder="Escribe para buscar…"
    phx-keyup="scope_team_search"
    phx-debounce="200"
    class="input input-sm w-full"
    autocomplete="off"
  />
  <% filtered = Enum.filter(@teams, fn t ->
    search = String.downcase(@scope_team_search || "")
    search == "" or String.contains?(String.downcase(t.name), search)
  end) %>
  <%= if @scope_team_search != "" and filtered != [] do %>
    <div class="absolute z-50 left-0 right-0 mt-1 bg-base-100 border border-base-300 rounded-lg shadow-lg max-h-40 overflow-y-auto">
      <button
        :for={t <- Enum.take(filtered, 10)}
        type="button"
        phx-click="select_scope_team_item"
        phx-value-team_id={t.id}
        class="block w-full text-left px-3 py-2 hover:bg-primary/10 transition-colors"
      >
        {t.name}
      </button>
    </div>
  <% end %>
  <input type="hidden" name="model[team_id]" value={@selected_team_id} />
</div>
```

**Events:**
- `"scope_team_search"` → `assign(:scope_team_search, search_text)`
- `"select_scope_team_item"` → `assign(:selected_team_id, id) + assign(:scope_team_search, display_name)`

**Pitfalls:**
- Use `phx-keyup` (not `phx-change`) for text inputs outside a `<.form>` —
  `phx-change` requires a form wrapper
- Reset the search text and FK value when changing scope/section
- Filter with `Enum.take(filtered, 10)` to cap dropdown height
- The hidden input ensures the FK value is submitted with the form even though
  the visible input shows the display name

**Pitfall — dropdown stays open after selection, re-showing the picked item:**

The condition `search != "" and filtered != []` breaks when an item is picked
because the visible input's `value` is repopulated with the item's full label,
which still matches the `String.contains?` filter — so the same item re-appears
in the dropdown and the panel refuses to close.

Fix with a dedicated boolean assign, controlled explicitly by the two events:

```elixir
# mount: assign(:scope_team_open, false)
# scope_team_search handler: assign(:scope_team_open, search != "")
# select_scope_team_item handler: assign(:scope_team_search, label) + assign(:scope_team_open, false)
```

Then guard the dropdown `<%= if @scope_team_open and filtered != [] do %>`.

Reset `*_open` to `false` in every flow exit that doesn't leave a value picked
(`change_scope`, `cancel_model_provider`, modal open). Initialize it to `false`
in `mount`.

**Pitfall — edit modal prefill is empty when the FK has a stored value:**

If `edit_X` only assigns the FK id (`@current_scope_team_id`) but not the
display label (`@scope_team_search`), the input renders with `value=""` and
the user has no clue what team/member is currently bound. Resolve the related
entity via `Enum.find(@teams_for_select, &(&1.id == id))` and prefill the
search assign with `team.name` (or `member.user.email` for members).

**Pitfall — re-picking the same item is allowed:**

After an item is selected, the dropdown shows it again as a candidate. Drop it
from the filtered list so the user can't pick the same FK twice in the same
edit:

```elixir
teams_filtered =
  @teams_for_select
  |> Enum.reject(fn t -> t.id == @current_scope_team_id end)
  |> Enum.filter(fn t -> String.contains?(String.downcase(t.name), search) end)
```

Same `Enum.reject(m.id == @current_scope_member_id)` for the member dropdown.

### 12. In-memory stream filtering (search-as-you-type)

When the admin list is already loaded (e.g. `< 500 users`), filtering in-memory
avoids an extra DB query per keystroke. The pattern:

#### LiveView

1. **Add assigns** in `mount`:
   ```elixir
   |> assign(:search_query, "")
   ```

2. **Add a search handler** that re-filters and re-streams:
   ```elixir
   def handle_event("search_users", %{"q" => query}, socket) do
     {:noreply,
      socket
      |> assign(:search_query, query)
      |> load_users()}
   end
   ```

3. **Filter + sort inside `load_users/1`** — apply the search *before* streaming:
   ```elixir
   defp load_users(socket) do
     search = socket.assigns[:search_query] || ""
     users = Accounts.list_users()

     filtered =
       if search == "" do
         users
       else
         search_lower = String.downcase(search)
         Enum.filter(users, fn u ->
           String.contains?(String.downcase(u.name || ""), search_lower) or
             String.contains?(String.downcase(u.email), search_lower)
         end)
       end

     sorted =
       filtered
       |> Enum.sort_by(fn u ->
         {role_rank(u.global_role), String.downcase(u.name || u.email)}
       end)

     socket
     |> assign(:spend_by_user, MyApp.Budgets.spend_by_user())
     |> stream(:users, sorted, reset: true)
   end

   defp role_rank("admin"), do: 0
   defp role_rank(_), do: 1
   ```

   **Key**: `stream(..., reset: true)` replaces the entire stream — essential
   when filtering changes which items are visible.

#### Template

Wrap the search input in a `<.form>` with `phx-change` and `phx-debounce`.
Phoenix v1.8 requires the `for` attribute even on simple forms:

```heex
<.form for={%{}} phx-change="search_users" phx-submit="search_users" id="search-form">
  <div class="relative">
    <.icon name="hero-magnifying-glass" class="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-base-content/40" />
    <input
      type="text"
      name="q"
      placeholder="Buscar..."
      value={@search_query}
      phx-debounce="300"
      class="input input-sm input-bordered pl-9 w-64"
    />
  </div>
</.form>
```

Add `phx-submit` alongside `phx-change` — without it, pressing Enter inside
the form triggers a full page reload (HTML form default submit behavior).

#### Pitfalls

- **`for={%{}}` required**: Phoenix v1.8 `<.form>` raises a compile warning
  (`missing required attribute "for"`) if you omit it. Pass an empty map for
  forms without a changeset.
- **Don't nest `<.form>` components**: if the search form lives inside a
  `<.header>` with a button, put the `<.form>` and `<.button>` as siblings
  inside a wrapper `<div>`, not nested.
- **`reset: true` on stream**: without it, filtered-out items remain in the
  DOM and new filtered items get appended. Always use `reset: true` when the
  filtered set changes identity.

### 13. Loading related data for stream items

Streams don't carry associations. When each row needs related data (e.g.
teams for each user), load it as a separate map assign:

```elixir
defp load_users(socket) do
  users = Accounts.list_users()
  # ... filter + sort ...

  socket
  |> assign(:user_teams, load_user_teams(sorted))
  |> stream(:users, sorted, reset: true)
end

defp load_user_teams(users) do
  users
  |> Enum.map(fn user ->
    teams = Accounts.list_team_members_for_user(user.id) |> Enum.map(& &1.team)
    {user.id, teams}
  end)
  |> Map.new()
end
```

In the template, access via `Map.get(@user_teams, user.id, [])`:

```heex
<td>
  <div class="flex flex-wrap items-center gap-1">
    <%= for team <- Map.get(@user_teams, user.id, []) do %>
      <span class="badge badge-xs badge-outline">{team.name}</span>
    <% end %>
  </div>
</td>
```

#### Pitfalls

- **N+1 queries**: `list_team_members_for_user` runs per user. For lists
  < 100 items this is fine. For larger lists, batch-load all memberships
  in one query and group by `user_id` in Elixir.
- **Stale map on edit**: after creating/deleting a team membership, call
  `load_users/1` which rebuilds `@user_teams` — don't mutate the map.

## Verification checklist

- [ ] Add button opens a modal.
- [ ] Add modal has the same fields as the edit form.
- [ ] Submit creates the record with all provided fields in one call.
- [ ] Cancel closes the modal and resets the form.
- [ ] Tests click the trigger button and use nested param names.
- [ ] If an edit form was moved from inside a `:for` loop: entity resolved via
      `Enum.find`, old inline block removed, stale `:if` guards on siblings stripped.
- [ ] Form element IDs preserved (tests that reference `#form-#{id}` still pass).
- [ ] `mix test <page_test.exs>` passes.
- [ ] `mix precommit` passes.

## Form-less LiveView elements (selects, buttons outside forms)

When a `<select>` or `<input>` uses `phx-change` **without** being inside a `<.form>`,
LiveView does NOT reliably fire the event. Symptoms: the UI updates locally (the
browser's native select value changes) but the server never receives the event,
so no DB update happens and a refresh reverts the UI.

**Fix**: wrap the element in a `<.form for={%{}}>` and move `phx-change` to the form:

```heex
<!-- BROKEN: select alone -->
<select phx-change="set-timezone" name="timezone" id="tz-select">...</select>

<!-- FIXED: form wraps select -->
<.form for={%{}} phx-change="set-timezone" id="tz-form">
  <select name="timezone" id="tz-select">...</select>
</.form>
```

The handler receives `%{"timezone" => value}` in both cases, but only the form-wrapped
version actually triggers the server round-trip.

Related: when the event handler updates an assign that drives the same element's
`selected`/`value` attribute, also update the **source struct** (e.g. `current_user`)
so the sidebar/render reflects the change immediately. Updating only `socket.assigns[:timezone]`
while the template reads `@current_user.timezone` leaves the UI stale.

**Real-world case**: MyApp timezone selector. The `<select id="tz-select" phx-change="set-timezone">`
in the sidebar layout was outside any form. Changing the selection appeared to work in the DOM
but never persisted. Wrapping it in `<.form for={%{}} phx-change="set-timezone">` made the event
fire and the DB update. Additionally, the handler had to update both `socket.assigns[:timezone]`
and `socket.assigns[:current_user]` so the layout re-rendered with fresh data.

## Stats cards in card list views

When a list of entity cards (services, teams, models) needs real usage stats:

1. **Query `request_logs` grouped by the entity ID** — for services, `service.id` maps to
   `team_member_id` in logs (virtual member pattern). Use a 30-day window:
   ```elixir
   thirty_days_ago = DateTime.utc_now() |> DateTime.add(-30 * 86_400, :second)
   stats =
     from(l in RequestLog,
       where: l.team_member_id in ^service_ids and l.inserted_at >= ^thirty_days_ago,
       group_by: l.team_member_id,
       select: %{
         service_id: l.team_member_id,
         total_cost: sum(l.provider_cost_usd),
         total_requests: count(l.id),
         total_input_tokens: sum(l.prompt_tokens),
         total_output_tokens: sum(l.completion_tokens)
       }
     )
     |> Repo.all()
     |> Map.new(&{&1.service_id, &1})
   ```

2. **Default to zero values when no stats exist** — always render the stat cards,
   don't hide them behind an `if stats != %{}` guard. The user expects to see
   the card structure even when values are 0:
   ```heex
   <% has_activity = Map.get(@service_stats, service.id) != nil %>
   <% stats = Map.get(@service_stats, service.id, %{
     total_cost: Decimal.new(0),
     total_requests: 0,
     total_input_tokens: 0,
     total_output_tokens: 0
   }) %>
   <div class="mt-3 grid grid-cols-4 gap-3 w-full">
     <!-- 4 stat cards always render -->
   </div>
   <%= if !has_activity do %>
     <p class="text-xs text-base-content/40 mt-2">Sin actividad en los últimos 30 días</p>
   <% end %>
   ```

3. **Full-width 4-column grid** — use `grid-cols-4 gap-3 w-full` for stat cards
   inside entity cards. Don't use `grid-cols-2 sm:grid-cols-4` — the cards look
   cramped and inconsistent with the rest of the dashboard.

4. **Card style** — match the teams dashboard: `card bg-base-100 border border-base-300
   shadow-sm` with `card-body p-4`, icon in colored `bg-*/10` rounded box, label
   uppercase tracking-wide, value `text-lg font-bold`, period `text-xs text-base-content/40`.

## Injecting per-model system prompt prefixes (guard rails)

When a model alias needs custom system-level instructions injected before the user's
prompt:

1. **Add `guard_rails` column** to the schema (`:text`, nullable) via migration.
2. **Add a dedicated modal** in the LiveView (separate from the edit-alias modal) with
   a textarea. Reuse the same form assign pattern (`@guard_rails_form`) and event
   naming (`edit_guard_rails`, `cancel_guard_rails`, `save_guard_rails`).
3. **Inject in the proxy controller** before calling the provider adapter:

```elixir
defp inject_guard_rails(payload, model_alias) do
  case model_alias.guard_rails do
    nil -> payload
    "" -> payload
    guard_rails ->
      messages = Map.get(payload, "messages", [])
      case messages do
        [%{"role" => "system", "content" => content} | rest] ->
          Map.put(payload, "messages", [
            %{"role" => "system", "content" => guard_rails <> "\n\n" <> content} | rest
          ])
        _ ->
          Map.put(payload, "messages", [
            %{"role" => "system", "content" => guard_rails} | messages
          ])
      end
  end
end
```

Call it in both `execute/6` (non-streaming) and `execute_stream/6` after
`Map.put(payload, "model", route.model_responded)`.

4. **Load stats in card views**: when a card list needs real usage stats (cost,
   requests, tokens), query `request_logs` grouped by the entity ID that maps to
   `team_member_id` (for services, `service.id == team_member_id` in the virtual
   member mapping). Use a 30-day window and `Map.new` for O(1) lookup in the template.
