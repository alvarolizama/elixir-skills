# HEEx Template Parser & Clause-Matching Bugs

Session-specific detail for the phoenix-liveview-debugging skill. See
SKILL.md "Pitfalls" for the summary entries.

## 1. `Parser.to_tree/4` FunctionClauseError inside `<%= for %>`

**Error:** `** (FunctionClauseError) no function clause matching in
Phoenix.LiveView.TagEngine.Parser.to_tree/4` during
`Phoenix.Component.sigil_H/2` expansion. The stack points at the whole
template (`render/1`), never at the offending line.

**Cause:** a bare tag carrying a `:if` directive placed adjacent to a
`<%= if %>` block inside a `<%= for ... do %>` loop body — the parser
can't build the tree when conditional tags and block constructs mix at
the same nesting level. Converting a `:for={...}` attribute loop into
`<%= for %>` form and forgetting the closing `<% end %>` before the
parent tag produces the exact same error.

**Broken:**

```heex
<%= for {ap, prev} <- Enum.zip(providers, prevs) do %>
  <tr :if={ap.group != prev} class="border-t-2">...</tr>   <%!-- trips parser --%>
  <tr id={"row-#{ap.id}"}>...</tr>
<% end %>
```

**Fixed — explicit block for every conditional tag:**

```heex
<%= for {ap, prev} <- Enum.zip(providers, prevs) do %>
  <%= if ap.group != prev do %>
    <tr class="border-t-2"><td colspan="8">Exclusivos por equipo</td></tr>
  <% end %>
  <tr id={"row-#{ap.id}"}>...</tr>
<% end %>
```

Debugging recipe: when `Parser.to_tree/4` fires, bisect the template
region you last touched by reverting half of it; the error message will
never name the line.

## 2. Group separator rows inside a sortable tbody

When a `<tbody phx-hook="SortableProviders" data-alias-id=...>` renders
subtitle/divider rows between scope groups (e.g. global → team → member
sections):

- Separator row: `class="pointer-events-none border-t-2 border-base-300"`,
  `<td colspan="N">` spanning the full table, uppercase small text.
- Do NOT give separator rows `id`/`data-id`/`draggable` — the drag hook
  collects every `data-id` and posts it as the new priority order; a
  separator id would either corrupt priorities or let users drag real
  rows across groups (server re-sorts on reload → confusing snap-back).
- The first group (the "default" section, e.g. Global) needs no header —
  headers only mark transitions to non-default groups.
- Pattern to compute "did the group change" inside the loop:
  `prev_groups = [nil | Enum.drop(groups, -1)]` then
  `Enum.zip(items, prev_groups)` — the first item compares against nil
  so group boundaries are detectable without index access.

## 3. Struct-vs-string helper clauses — "badge ALWAYS says Global"

**Symptom:** every row in a table shows the same badge/label value.

**Cause:** helper defined with string clauses
(`def scope_badge("member"), do: "badge-warning"`,
`def scope_badge(_), do: "badge-ghost"`) but the template calls it with
the full struct: `scope_badge(ap)`. Every struct hits the catch-all.

**Fix:** add struct-pattern clauses deriving the value from FKs/flags:

```elixir
def scope_badge(%ModelProvider{exclusive_to_team_member_id: id}) when not is_nil(id),
  do: "badge-warning"
def scope_badge(%ModelProvider{exclusive_to_team_id: id}) when not is_nil(id),
  do: "badge-info"
def scope_badge(%ModelProvider{}), do: "badge-ghost"
```

Keep the old string clauses if other call sites pass `@current_scope`
strings — check all callers with grep before deleting.

**General rule:** when a UI value is constant regardless of data, check
the argument TYPE the function clauses expect vs what the template
passes BEFORE touching CSS or data loading.

## 4. Ecto `field == ^nil` — forms that render pickers before entity selection

**Error:** `(ArgumentError) comparing tma.model_alias_id with nil is
forbidden as it is unsafe. If you want to check if a value is nil, use
is_nil/1 instead` — raised from a helper called during render, e.g.
`members_with_model_access(@members_for_select, @provider_form_alias_id)`
when the form is for a NEW entity and the alias id assign is still nil.

**Fix — nil clause at the boundary:**

```elixir
def members_with_model_access(_members, nil), do: []
def members_with_model_access(members, model_alias_id) do ... end
```

Check ALL sibling helpers of the same shape (in the session:
`teams_with_model_access` had the identical latent bug on the adjacent
form branch).
