# N+1 cookbook — Phoenix/Elixir

Concrete patterns to grep for and how to fix each. Each section maps
to a finding ID prefix from `phoenix-performance-audit` (N-01, N-02, …).

## N-01 — `Enum.map` over a list calling a context helper that re-preloads

The most common cascade. The outer query pre-loads an association;
the inner helper pre-loads it again.

```elixir
# BAD
members = Repo.all(from tm in TeamMember, preload: [:user, :team])
Enum.map(members, fn m -> Accounts.effective_limits(m) end)
# effective_limits calls Repo.preload(m, [:team]) AGAIN
# per member. With N members = 1 + N queries.
```

Fix options:

1. Make the inner helper accept the preloaded data instead of the
   struct: `combine_effective_limits(m.team, m)` instead of
   `effective_limits(m)`.
2. Skip the inner preload when already preloaded:
   `Ecto.assoc_loaded?(member.team) || Repo.preload(member, [:team])`.
3. Move the preload into the outer query as `preload: [:team, :user]`
   *and* pass only the loaded values to the helper.

The best fix is usually (1) — make the helper a pure function over
data it doesn't own.

## N-02 — Per-item aggregate query in a loop

```elixir
# BAD — N aggregate queries for one page
Enum.map(members, fn m ->
  Budgets.monthly_spend_for_member(m.id, timezone)
end)

# monthly_spend_for_member runs:
#   SELECT SUM(provider_cost_usd) FROM request_logs
#   WHERE team_member_id = $1 AND inserted_at >= $2
```

Fix: replace with a single batched aggregate that returns a map and
look up per-id:

```elixir
# GOOD — 1 query, look up by id
spend_map = Budgets.spend_by_member_ids(Enum.map(members, & &1.id), timezone)
# spend_map = %{daily: %{member_id => Decimal}, monthly: %{member_id => Decimal}}
Enum.map(members, fn m -> member_budget(m, spend_map) end)
```

The batched helper already exists in most MyApp-style codebases
(`MyApp.Budgets.spend_by_member_ids`). When it doesn't, write it:
one `WHERE team_member_id IN (^ids)` query grouped by
`team_member_id`, returning `{id, decimal_sum}` pairs, then
`Map.new/2`.

## N-03 — Per-team (or per-parent) child query in a loop

```elixir
# BAD — T queries
teams = Accounts.list_teams()
|> Enum.map(fn t -> {t, Accounts.list_team_members_for_team(t.id)} end)
```

Fix: one preload, no loop.

```elixir
# GOOD — 1 query
teams =
  from(t in Team, preload: [team_members: [:user, :api_key]])
  |> Repo.all()
```

For multi-level (team → members → … → provider), use nested preloads:
`preload: [team_members: [user: [], api_key: []]]`.

## N-04 — `Repo.all` + post-processing that issues queries

```elixir
# BAD — hidden cascade
logs = Logs.list_logs(filters)
Enum.map(logs, fn log ->
  {log, Repo.get(TeamMember, log.team_member_id)}
end)
```

Fix: log query should preload `team_member: [:user, :team]`. Or use a
join:

```elixir
from(l in RequestLog,
  join: tm in assoc(l, :team_member),
  join: u in assoc(tm, :user),
  where: ..., preload: [team_member: {tm, user: u}]
)
```

## N-05 — Effective-limits style helper called twice per request

Found in `proxy_controller.ex:68` AND `:204` in the MyApp audit:
both `limits = Accounts.effective_limits(member)` (top) and
`member_monthly_budget = Accounts.effective_limits(member).monthly_budget_usd`
(`check_budget`). Each call issues a `Repo.preload(:team)`.

Fix: compute once, pass into the helper.

```elixir
limits = Accounts.effective_limits(member)              # 1 SELECT
# ...
member_monthly_budget = limits.monthly_budget_usd       # reuse
```

If the inner helper is hard to refactor (deep call chain), memoize
the value at the controller entry.

## N-06 — Effective-limits helper that preloads redundantly

`Accounts.effective_limits/1` does `Repo.preload(team_member, [:team])`
unconditionally even when `:team` is already preloaded. This is the
upstream cause of N-05 and N-01. The fix at the helper level:

```elixir
def effective_limits(%TeamMember{} = team_member) do
  team_member = maybe_preload(team_member, :team)
  # ...
end

defp maybe_preload(struct, assoc) do
  if Ecto.assoc_loaded?(Map.get(struct, assoc)),
    do: struct,
    else: Repo.preload(struct, [assoc])
end
```

Now the helper is safe to call on preloaded data without triggering
a second SELECT.

## N-07 — Stream that fetches more when the template accesses nested data

A `<%= for log <- @logs %>` that does `{log.team_member.user.email}`
needs `preload: [team_member: [:user, :team]]` on the log query. This
is the "missing preload in templates" finding (audit category 2c).
Grep each preload and verify the template only touches loaded fields.

## Detection recipe

```bash
# Find Enum.map calls in LiveView data loaders
grep -n 'Enum\.map\|Enum\.reduce' lib/<app>_web/live/*.ex

# Find context helpers that issue Repo.preload
grep -n 'Repo\.preload\|force: true' lib/<app>/*.ex

# Find per-item aggregate calls in a loop
grep -n 'monthly_spend_for\|daily_spend_for\|spend(member\|effective_limits' \
  lib/<app>_web/live/*.ex lib/<app>/*.ex
```

Each match above is a candidate N+1; verify by reading the enclosing
function.

## Common false positives

- `Enum.map(list, fn x -> %Row{x.id, x.name} end)` — pure data, no DB.
- `Enum.map(list, &String.upcase/1)` — pure transform.
- `Enum.map(list, &Budgets.Manager.spend/1)` — `Budgets.Manager.spend`
  reads ETS, not DB; first call per member per day *might* hit DB,
  but that's a one-time cold start, not a steady-state N+1. Verify
  by reading the manager; if it lazy-loads from DB on cold start,
  note it but don't escalate.