# Diff Review Rules — Performance, Architecture & Hygiene (PF, AR, I18N, LG, NM)

Part 3 of 3 of the diff-review rulebook for Elixir/Phoenix codebases
(LiveView + Ecto + gettext + ExMachina). Every rule has a **severity**, a
**why**, an **anti-pattern**, and the **correct form**. Rule IDs are stable
across the whole rulebook — cite them in review comments (`PF-01: index
every foreign key`). Companion families: `diff-review-style-rules.md` (EX)
and `diff-review-correctness-rules.md` (TS/ERR).

Severity legend:

- **high** — merge blocker: bugs, leaks, broken contracts, data-loss risk.
- **medium** — should fix: readability, testability, idiomatic Elixir.
- **low** — nit: optional polish, style preference.

## Performance / DB

### PF-01 — Always index foreign keys in migrations
**Severity:** high

**Why:** A `references/2` column without its index makes joins and lookups
full table scans.

```elixir
alter table(:context_templates) do
  add(:active, :boolean, default: true)
  add(:workflow_config_id, references(:workflow_configs, on_delete: :nilify_all))
end

create index(:context_templates, [:workflow_config_id])
```

### PF-02 — Order composite index columns for the real queries
**Severity:** high

**Why:** A composite index is only usable when leading columns match the
query's filter prefix (highest selectivity / always-filtered first).

```elixir
# anti-pattern: queries always filter by entity_type first
create index(:events, [:entity_id, :entity_type, :event_type_id])
# correct: entity_type leads
create index(:events, [:entity_type, :entity_id, :event_type_id])
```

### PF-03 — Don't duplicate external database repos
**Severity:** high

**Why:** A second `Ecto.Repo` on the same external DB doubles the pool,
can exhaust DB limits, and hides the second repo from monitoring. Reuse the
existing repo or move it to the semantically owning app.

### PF-04 — Use `Repo.update_all` with an explicit query instead of get + update
**Severity:** medium

**Why:** get + update issues 2 queries; `update_all` with a `from` is one
`UPDATE ... WHERE`.

```elixir
update_query =
  from(c in "accounts",
    where: c.id == ^account_id,
    update: [set: [status: ^new_status]]
  )

ExternalRepo.update_all(update_query, [])
```

### PF-05 — Batch N+1 lookups into one `WHERE IN` query
**Severity:** high

**Why:** Per-item lookups inside template `:for` comprehensions multiply
queries (8 tags × 50 pages = 250+ queries). Add a batch function returning
a map, pre-load once before rendering.

```elixir
def get_pages_by_slugs(slugs, context_id) do
  from(p in Page, where: p.slug in ^slugs and p.context_id == ^context_id)
  |> Repo.all()
  |> Map.new(&{&1.slug, &1})
end
```

### PF-06 — Deterministic pagination tiebreak
**Severity:** medium

**Why:** Plain `OFFSET` pages drift when rows are inserted/deleted between
pages. Order by a stable unique key so the boundary is deterministic.

```elixir
from(p in Page, order_by: [asc: p.id], offset: ^offset, limit: ^limit)
```

## Architecture / Design

### AR-01 — Don't duplicate repos — move them to their semantically owning app
**Severity:** high

**Why:** In an umbrella, each external-DB `Ecto.Repo` lives in the app that
owns it. Two apps needing the same external DB share through the
dependency — never duplicate the repo module.

**Correct:**

```elixir
# Option A: use the owning app's repo if the dependency exists
alias CoreApp.ExternalRepo

# Option B: if the other app is the semantic owner, move the repo there
# and have the first app consume it
```

### AR-02 — Use typed structs in port callbacks instead of generic maps
**Severity:** medium

**Why:** `@callback` with `map()` defeats Dialyzer. Structs with explicit
types document exactly what the port accepts and make contracts verifiable.

```elixir
# anti-pattern — map() defeats Dialyzer
@callback upsert_interaction(attrs :: map()) ::
            {:ok, Interaction.t()} | {:error, Error.t()}
# correct — an explicit struct type documents the port contract
@callback upsert_interaction(Interaction.t()) ::
            {:ok, Interaction.t()} | {:error, Error.t()}
```

### AR-03 — No hardcoded environment URLs — use runtime configuration
**Severity:** medium

**Why:** Hardcoded endpoints prevent per-environment configuration. Read
them from config: `System.get_env/2` in `config/runtime.exs`, then
`Application.get_env/3` / `fetch_env!/2` (runtime read) or
`Application.compile_env/3` (compile-time keys set in `config/*.exs` —
there is no `compile_env!/3`; the bang variant is `compile_env!/2`).

```elixir
# config/runtime.exs
config :my_app_web, :onboarding_url,
  System.get_env("ONBOARDING_URL", "https://onboarding.example.com/")

# in the module — runtime.exs keys are read at RUNTIME
defp onboarding_url, do: Application.fetch_env!(:my_app_web, :onboarding_url)
```

## Documentation / i18n

### I18N-01 — Use `gettext` for all user-visible strings in HEEx
**Severity:** medium · **Convention rule:** n/a if the repo has no gettext.

**Why:** Every user-visible string must be wrapped in `gettext(...)`;
hardcoded strings break translation. CI can detect them.

```heex
<!-- anti-pattern -->
<h1 class="text-2xl font-semibold text-gray-900">Recurring payments</h1>
<!-- correct -->
<h1 class="text-2xl font-semibold text-gray-900"><%= gettext("Recurring payments") %></h1>
```

### I18N-02 — Group related configs under the same namespace key
**Severity:** low

**Why:** Scattered config keys hurt readability and autocomplete. Group
related entries under one namespace.

## Correctness

### LG-01 — Don't ship unverified TLS as a default
**Severity:** medium

**Why:** `ssl_opts: [verify: :verify_none]` committed in any config makes
"encrypt without peer verification" the default — and encryption without
peer verification does not stop a MITM. `verify_peer` with the provider's
or system CA bundle (`:public_key.cacerts_get()` / `cacertfile`) is the
default in every environment, dev included: keep committed dev config
clean and put self-signed overrides in a local, uncommitted file.
`verify_none` is an explicit, temporary opt-out for a known-local DB only
— never a silent fallback. (The delivery-side recipe is in
`elixir-delivery/references/release-deploy.md`.)

### LG-02 — Implement an expiry strategy in in-memory caches
**Severity:** medium

**Why:** A GenServer cache with no TTL/sweep grows forever; restart-only
cleanup is not a strategy. Store `{value, expires_at}` and sweep on a
timer.

```elixir
@ttl_ms :timer.minutes(30)
@sweep_interval_ms :timer.minutes(5)

def init(state) do
  schedule_sweep()
  {:ok, state}
end

defp schedule_sweep do
  Process.send_after(self(), :sweep, @sweep_interval_ms)
end

def handle_info(:sweep, state) do
  now = System.monotonic_time(:millisecond)
  new_state = Map.reject(state, fn {_k, {_v, expires_at}} -> expires_at < now end)
  schedule_sweep()
  {:noreply, new_state}
end
```

## Naming / Readability

### NM-01 — Use consistent canonical values in analytics event attributes
**Severity:** medium

**Why:** Dimension values must match the rest of the system's constants,
or dashboards fragment.

```heex
<!-- anti-pattern -->
<div id="panel-switch-tracker" phx-hook="PanelSwitchTracker" data-current-panel={@preset.name}>
<!-- correct -->
<div id="panel-switch-tracker" phx-hook="PanelSwitchTracker"
     data-current-panel="active_portfolio"
     data-preset-name={@preset && @preset.name}>
```

## Automation — most frequent patterns and the tools that catch them

| # | Pattern | Rule IDs | Tool |
|---|---------|----------|------|
| 1 | Nested `case` / deep `if-else` | EX-01, EX-02 | **Credo** — `CondStatements`, `CyclomaticComplexity` |
| 2 | Chained `assign/3` calls | EX-03 | **Credo** — custom check counting pipes into `assign` |
| 3 | Hardcoded strings without `gettext` | I18N-01 | `mix gettext.extract` + CI check for untranslated strings |
| 4 | FK without index in migrations | PF-01 | `mix ecto.migrations` + custom linter (every `references/2` has its `create index`) |
| 5 | Hardcoded URLs in source | AR-03 | **Credo** — custom check matching `https?://` literals |
| 6 | Single-transform `\|>` pipe | EX-05 | **Credo** — `PipeChainStart` |
| 7 | `Repo.get` without nil handling | ERR-04 | **Dialyzer** / custom linter detecting `Repo.get` without pattern-match |

## Pitfalls

- **Read the code before citing a rule** — a finding needs a real
  file:line, never a paraphrase of someone else's summary.
- **Convention-dependent rules** — TS-01/I18N-01 apply only when the repo
  uses the library; otherwise mark n/a.
- **Don't apply low-severity rules as merge blockers** — keep severity
  honest; nitpicking erodes review trust.
- **Adjust for repo shape** — the catalog assumes idiomatic LiveView/
  Phoenix; adapt for GenServer apps, umbrella boundaries (PF-03/AR-01),
  and repos without gettext.
