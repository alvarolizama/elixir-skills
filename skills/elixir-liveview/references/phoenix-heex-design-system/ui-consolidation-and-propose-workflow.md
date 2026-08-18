# UI consolidation & propose-then-implement workflow

Two patterns learned from dashboard refactors in Phoenix LiveView projects
(verified on MyApp 2026-07-27).

## 1. Merging duplicate sections that share the same data

### Detection

A LiveView page renders two or more `<section>` blocks that iterate over
lists derived from the same underlying query. Each section duplicates its
own empty state, its own header, and forces the user to scroll past
redundant context.

**Example (MyApp dashboard before):**
- Section "Tus claves" — iterates `@memberships`, shows API key per membership
- Section "Tus equipos" — iterates `@team_budgets` (built from the same
  memberships via `Enum.uniq_by(& &1.team_id)`), shows budget bars per team

Both sections showed a "No perteneces a ningún equipo todavía." empty state
when the user had no memberships — duplicated message, duplicated icon,
duplicated scroll.

### Consolidation pattern

1. **Verify the data is actually 1:1** before merging. Check for unique
   constraints on the join table (e.g. `unique_constraint(:team_id, name:
   :team_members_user_team_unique_index)` confirms one membership per team
   per user). If the two lists have different cardinalities (one is
   `uniq_by(& &1.team_id)`, the other is raw), you need to preserve that
   distinction — but usually they're the same and the `uniq_by` was defensive.

2. **Build a single combined data structure** in the LiveView's
   `load_personal_data` (or equivalent). Map each item to a flat map with
   all fields both sections needed:

   ```elixir
   teams =
     Enum.map(memberships, fn membership ->
       limits = Accounts.effective_limits(membership)
       spend = Budgets.spend(membership.id)

       %{
         membership: membership,
         team: membership.team,
         team_role: membership.team_role,
         api_key: membership.api_key,
         daily_limit: limits.daily_budget_usd,
         monthly_limit: limits.monthly_budget_usd,
         daily_spend: spend.daily_usd,
         monthly_spend: spend.monthly_usd
       }
     end)
   ```

   Assign it as a single `@teams` list. Delete the old `build_team_budgets/1`
   helper and the `:team_budgets` assign.

3. **Merge the templates into one `<section>`** with one header, one empty
   state, and one `for` loop. Inside each card, use a visual divider
   (`border-t border-base-200 pt-4`) to separate concerns (key management vs
   budget bars) without splitting into separate cards.

4. **Update test selectors**: IDs that referenced the old sections
   (`#membership-#{id}`, `#team-budget-#{id}`) become a single
   `#team-#{team.id}`. Update assertions that checked for old section headers
   (`assert html =~ "Tus claves"`) to the new unified header
   (`assert html =~ "Tus equipos"`).

5. **Helper functions that pattern-match on struct shape** (e.g.
   `masked_key(%{api_key: %{key_prefix: prefix}})`) work unchanged when you
   pass a plain map instead of a struct — as long as the map has the same
   key shape. No need to rewrite helpers.

### Visual layout within a unified card (top to bottom)

- Header row: entity name + role badge + status badge + optional nav link
- Primary concern (e.g. API key): label, masked value, creation date, action buttons
- Divider (`border-t border-base-200 mt-4 pt-4`)
- Secondary concern (e.g. budget): progress bars with spend/limit labels

This reduces two empty states to one, halves the scroll depth, and groups
related information that the user mentally associates anyway.

## 2. Propose-then-implement workflow (Álvaro's preference)

When Álvaro asks to simplify, reorganize, or refactor a UI page, he prefers a
**propose-then-implement** flow:

1. **Read the current code and see the page live** (browser tools if a dev
   server is running) before saying anything. Do not propose based on a guess.

2. **Propose 3-4 concrete options** with trade-offs. Each option should be a
   distinct approach (not variations of the same idea). Include a clear
   recommendation with reasoning. Present as a numbered list or table.

3. **Let him pick** — he'll say "La 1", "la 3", or describe his own variant.
   Do not jump straight to code without proposing. Do not propose without
   first reading the actual template and LiveView module.

4. **Execute the chosen option fully**:
   - Implement the change in the LiveView module + template
   - Update tests (selectors, assertions)
   - Run `mix precommit` (or `mix compile --warnings-as-errors` + `mix test`)
   - Verify visually with browser tools if a dev server is available
   - Report what changed with a summary

### Seed data for visual verification

When the admin/test user has no team memberships, the dashboard's team
section shows an empty state. To visually verify a consolidated card layout,
create a team + membership + API key for the admin user before loading the
page:

```elixir
admin = Accounts.get_user_by_email("admin@MyApp.local")
{:ok, team} = Accounts.create_team(%{name: "Dev Team"})
{:ok, member} = Accounts.create_team_member(%{
  user_id: admin.id, team_id: team.id, team_role: "manager"
})
{:ok, _api_key, _token} = Accounts.replace_api_key(member)
```

This is throwaway dev data — clean it up if needed, or leave it for future
visual checks.
