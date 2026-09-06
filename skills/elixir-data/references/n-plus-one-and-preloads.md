# N+1 & Preload Cookbook

The concrete N+1 shapes, the fix for each, and the false positives that waste
time. Grep → verify by reading the enclosing function → fix → batch.

## N-01 — `Enum.map` over a list calling a context helper that re-preloads

The most common cascade. The outer query preloads an association; the inner
helper preloads it again.

```elixir
# BAD
members = Repo.all(from tm in TeamMember, preload: [:user, :team])
Enum.map(members, fn m -> Accounts.effective_limits(m) end)
# effective_limits calls Repo.preload(m, [:team]) AGAIN. With N members = 1 + N queries.
```

Fix options:
1. Make the inner helper a pure function over data it doesn't own:
   `combine_effective_limits(m.team, m)` instead of `effective_limits(m)`.
2. Skip the inner preload when already loaded:
   `Ecto.assoc_loaded?(member.team) || Repo.preload(member, [:team])`.
3. Move the preload into the outer query and pass only loaded values.

(1) is usually the best — pure helpers can't re-query.

## N-02 — Per-item aggregate query in a loop

```elixir
# BAD — N aggregate queries for one page
Enum.map(members, fn m -> Budgets.monthly_spend_for_member(m.id, timezone) end)
# each runs: SELECT SUM(provider_cost_usd) FROM request_logs
#            WHERE team_member_id = $1 AND inserted_at >= $2
```

Fix — one batched aggregate, then look up per id:

```elixir
# GOOD — 1 query, look up by id
spend_map = Budgets.spend_by_member_ids(Enum.map(members, & &1.id), timezone)
# spend_map = %{daily: %{member_id => Decimal}, monthly: %{member_id => Decimal}}
Enum.map(members, fn m -> member_budget(m, spend_map) end)
```

The batched helper is one `WHERE team_member_id IN (^ids)` query grouped by
`team_member_id`, returning `{id, decimal}` pairs → `Map.new/2`.

## N-03 — Per-parent child query in a loop

```elixir
# BAD — T queries
teams = Accounts.list_teams()
|> Enum.map(fn t -> {t, Accounts.list_team_members_for_team(t.id)} end)
```

Fix — one preload, no loop:

```elixir
# GOOD — 1 query
teams =
  from(t in Team, preload: [team_members: [:user, :api_key]])
  |> Repo.all()
```

Multi-level (team → members → provider): nested preloads
`preload: [team_members: [user: [], api_key: []]]`.

## N-04 — `Repo.all` + post-processing that issues queries

```elixir
# BAD — hidden cascade
logs = Logs.list_logs(filters)
Enum.map(logs, fn log -> {log, Repo.get(TeamMember, log.team_member_id)} end)
```

Fix: preload on the log query, or join:

```elixir
from(l in RequestLog,
  join: tm in assoc(l, :team_member),
  join: u in assoc(tm, :user),
  where: ..., preload: [team_member: {tm, user: u}]
)
```

## N-05 — Helper called twice per request with the same argument

```elixir
limits = Accounts.effective_limits(member)              # 1 SELECT
# ...later...
member_monthly_budget = Accounts.effective_limits(member).monthly_budget_usd  # 2nd SELECT
```

Fix: compute once, pass the value into the helper. If the inner helper is hard
to refactor (deep call chain), memoize at the controller entry.

## N-06 — Helper that preloads redundantly (upstream cause)

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

Now the helper is safe to call on preloaded data without a second SELECT.

## N-07 — Missing template preload

`<%= for log <- @logs %>` accessing `{log.team_member.user.email}` needs
`preload: [team_member: [:user, :team]]` on the log query. Grep each preload
and verify the template only touches loaded fields.

## Hot-path signal: `force: true`

`Repo.preload(struct, [:team], force: true)` ignores already-loaded data and
issues a new SELECT every call. On the hot path (auth plug already preloads
`:team`), this is the highest-severity finding. Fix: drop `force: true`, or
guard with `Ecto.assoc_loaded?/2`.

## Detection recipe

```bash
# Find Enum.map calls in LiveView data loaders
grep -n 'Enum\.map\|Enum\.reduce' lib/<app>_web/live/*.ex

# Find context helpers that issue Repo.preload
grep -n 'Repo\.preload\|force: true' lib/<app>/*.ex

# Find per-item aggregate calls in a loop
grep -n 'monthly_spend_for\|daily_spend_for\|effective_limits' \
  lib/<app>_web/live/*.ex lib/<app>/*.ex

# Auth plugs that preload (they define what is ALREADY loaded downstream)
grep -rn 'preload' lib/<app>_web/plugs
```

Each match is a CANDIDATE; verify by reading the enclosing function.

## Common false positives

- `Enum.map(list, fn x -> %Row{x.id, x.name} end)` — pure data, no DB.
- `Enum.map(list, &String.upcase/1)` — pure transform.
- `Enum.map(list, &Budgets.Manager.spend/1)` — if the manager reads ETS, not
  DB, the first call per member per day MIGHT hit DB (one-time cold start, not
  a steady-state N+1). Verify by reading the manager; don't escalate.
- **`Repo.preload(struct, :assoc)` WITHOUT `force: true` is a no-op when the
  association is already loaded** — Ecto resolves it in memory, zero queries.
  Before reporting any N+1, trace whether the outer query already preloaded it.

## Verification

- Read the helper function body and the outer query: count queries by
  construction (1 outer + N inner = N+1; with the fix = 1).
- Telemetry/`EXPLAIN` on the rendered page: no per-item SELECTs in the log.
- Add a regression test that asserts query count (e.g. via
  `Ecto.Adapters.SQL.Sandbox` + telemetry) when the pattern recurs.