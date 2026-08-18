# Budget models for LLM proxy/gateway

## Dual-cap with min() (current implementation — MyApp)

Two **independent** caps checked in parallel. A request passes only if it fits
under **both**. The binding constraint is `min(team_available, member_available)`.

```elixir
# Budgets.Manager.check_ladder/7

team_available   = team_daily_budget - team_spend_usd
member_available = member_daily_budget + member_extra_daily + model_extra_daily - member_spend_usd

available = min(team_available, member_available)
# nil cap = :unlimited for that dimension
```

### How it works

| Cap | Source | Spend subtracted | Scope |
|-----|--------|------------------|-------|
| **Team cap** | `team.team_daily_budget_usd` | SUM of ALL team members' spend | Shared across all members of the team |
| **Member cap** | `team.default_daily_budget_usd` + `member.extra_daily_budget_usd` + per-model extras | Only this member's spend | Per-member, personal |

### Worked example

- Team cap: $100/day
- User A: base $50, spent $20 today → member_remaining = $30
- User B: base $50 + $50 extras, spent $50 today → member_remaining = $50
- Team spend = $20 + $50 = $70 → team_remaining = $30

When User B makes another request:
```
team_available   = $100 - $70 = $30
member_available = $100 - $50 = $50
available = min($30, $50) = $30
```

User B can spend $30 more (reaching $80 total), NOT $50 — the team cap binds
first. User A's unused $30 does NOT flow to User B automatically.

### Key design points

- `record_spend/2` accumulates against `member.id` only. Team spend is derived
  by summing all members' ETS counters via `team_spend/1`.
- `nil` for either cap means unlimited for that dimension. If both are `nil`,
  the request always passes.
- Per-model extras (`TeamMemberExtraAlias.extra_daily_budget_usd`) add to the
  **member cap only**, not to the team cap.
- Monthly budgets are eliminated. The monthly view is informational
  (daily_limit × 30).
- Daily ETS entries carry a Date stamp; stale entries re-seed from DB on rollover.

### DB schema

```
teams:
  default_daily_budget_usd   — member base daily limit
  team_daily_budget_usd      — shared team daily cap (nullable = unlimited)

team_members:
  extra_daily_budget_usd     — additional member budget (nullable)

team_member_extra_aliases:
  extra_daily_budget_usd      — per-model extra budget (nullable)
```

### UI display

```
┌─ Team config ──────────────────────────┐
│  Tope diario por usuario: $50           │
│  Tope diario del equipo: $100           │
│  Gasto del equipo hoy: $70              │
└─────────────────────────────────────────┘

┌─ Member: user@email.com ───────────────┐
│  Gasto hoy: $50                        │
│  Tope base: $50                        │
│  Extra general: +$50/day               │
│  Extras por modelo:                    │
│    gpt-4o: +$20/day                   │
│  Consumo máximo estimado: $120/day     │
│  (base + general + model extras)       │
└─────────────────────────────────────────┘
```

Note: "Consumo máximo estimado" shows the member's personal cap ceiling
(base + all extras), NOT the team cap. The actual available is the min of
team_remaining and member_remaining at request time.

## Alternative: flat additive (simpler, not used in MyApp)

Each member's effective limit = `team.default_daily_budget_usd + member.extra_daily_budget_usd`.
No team pool — every member has their own base. No `min()` — the member cap IS
the only cap.

**Use when**: you don't need shared team budgets or model-level extras.
