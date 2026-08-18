---
name: phoenix-performance-audit
description: "Use when auditing Phoenix/Elixir app performance read-only."
version: 1.0.0
author: Álvaro Lizama
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [phoenix, elixir, performance, audit, ecto, liveview, n+1, pubsub, read-only]
    related_skills: [phoenix-analytics-rollups, phoenix-liveview-realtime-ui, llm-proxy-gateway, phoenix-security-audit]
---

# Phoenix/Elixir Performance Audit (READ-ONLY)

Performing a structured performance audit of a Phoenix/Elixir app — read-only.
No file edits, no commits, no migrations, no `mix` mutations. The audit is
evidenced by reading source code and producing a findings table; the user
applies the fixes.

## The cardinal rule: don't write

The user almost always asks for a read-only audit. When they say
"don't edit", "no commits", "read-only", or "no modifiques", that means:

- No `write_file` for *new* audit files either. The audit goes in the chat.
  (Lesson: writing `PERFORMANCE_AUDIT.md` is still a repo mutation — `git
  status` will show it. Deliver the report inline.)
- No `patch` to source files, even "obviously correct" fixes.
- No `terminal` commands that mutate state (mix tasks that write, git
  operations, package installs).

Verify before claiming read-only: at the end, run
`git status --porcelain <repo>` and confirm the output is empty.

## What "audit" means — produce structured findings

The user expects a single markdown table or per-finding block with a
uniform shape. The task spec that started this skill specifies
exactly five fields per finding; adopt that shape unless the user
overrides it:

```
- ID — short stable tag like P-01 (hot-path), N-04 (N+1), L-01 (list/limit),
  PS-02 (PubSub), B-01 (bug pattern), IX-01 (indexes), O-01 (other).
- Severity — critical / high / medium / low / informational.
- File:line — exact `lib/.../foo.ex:123` or `priv/.../migration.exs` path.
- Category — short noun phrase (N+1, pagination, PubSub storm, hot path,
  indexes, parser, preload).
- Description — what's wrong, evidenced by the function body, and the
  observed impact (queries per request, reloads per second).
- Fix — concrete change, not "consider refactoring".
```

Group findings by category (hot-path → cascades → unbounded lists → PubSub
→ bugs → indexes → other) so the user can scan and pick priorities.

## Severity rubric (tuned for Phoenix/Elixir)

- **critical** — DB call in the hot path of a request that already has
  everything preloaded (force-preload, redundant context helper called
  twice per request). Steady-state DB load scales with request rate.
- **high** — N+1 cascade triggered on PubSub reload (coalesced or not) so
  it executes under sustained traffic; unbounded list on a table that
  grows without bound (logs, request_logs, audit_logs); missing index
  for a GROUP BY column used by a hot dashboard.
- **medium** — N+1 in a mount/loader that runs only on navigation; missing
  cap on a small-ish catalog; redundant context call that preloads the
  same association twice in a single request.
- **low** — admin-only cascade; O(N²) in-memory pass on small N; informational
  preload gap that doesn't fire today.
- **informational** — pattern *not* found (e.g. user asked to check for
  `[:period || "today"]` bug and grep returns nothing — report "not present"
  so the user knows you looked).

N+1 in a single mount is normally medium; N+1 triggered by every
PubSub message is high; force-preload on every proxy request is critical.

## Audit methodology (concrete steps, in order)

The audit works best as a deterministic sweep. Skipping steps misses
findings because categories reinforce each other (an N+1 in `list_X`
often also means an unbounded list).

1. **Map the surface.** `search_files pattern="def list_" path="lib/<ctx>"`
   + `pattern="Repo\\.all"`. Build a list of every list-style query and
   every context-level `Repo.all` call. These are the candidates for
   `list_*` and `L-*` findings.

2. **Map preloads.** `search_files pattern="preload:" path="lib/<ctx>"`.
   Cross-reference every preload with the templates that consume it
   (find the field name in `lib/<app>_web/live/*.ex` and the corresponding
   `.html.heex`). If the template touches `member.user.email` but the
   query doesn't preload `:user`, that's a missing preload.

3. **Read plug chains for the hot path.** Before claiming any
   `Repo.preload` is redundant, trace *what the plug already preloaded*.
   In a Phoenix app with `ApiAuth`-style plugs, the auth plug runs
   `Repo.preload(member, [:team, :user, :api_key])`. Any *downstream*
   `Repo.preload(member, [:team], force: true)` in the controller/router
   is redundant and a critical hot-path finding. Search for `force: true`.

4. **Read every LiveView `mount/3`.** Look for:
   - `Enum.map(items, fn item -> Context.effective_limits(item) end)` —
     classic N+1 cascade (each call re-preloads).
   - `Enum.map(items, fn item -> Context.spend(item.id) end)` — cascade
     over an aggregate query per item.
   - `Budgets.list_member_budgets()` or similar "give me everything"
     calls that load all rows of a growing table.
   - `Repo.all(SomeContext)` with no `limit:` and no offset-based
     pagination.

5. **Read every `handle_info` in LiveViews.** If the LiveView subscribes
   to a PubSub topic with `Phoenix.PubSub.subscribe`, check whether the
   handler runs a DB query. Topics that broadcast per-request
   (`"logs:new"`, `"metrics:updated"`) under sustained traffic become
   storm generators. Even with `Process.send_after` coalescing, a DB query
   per message is too much — fix it by switching to ETS for hot counters.

6. **Read controllers on the hot path.** Look for:
   - Calls to context helpers that issue `Repo.preload(..., force: true)`.
   - Helpers called multiple times per request with the same arguments
     (same `effective_limits/1` called twice).
   - Lazy-load helpers (`Manager.load_from_db`, `Budgets.ensure_loaded`)
     that hit Postgres the first time per period per key.
   - ETS/RDBMS cache invalidation patterns.

7. **Check migrations for indexes on the GROUP BY columns.** Read every
   migration that creates or alters the hot table (`request_logs`,
   `audit_logs`, etc.) and grep for `CREATE INDEX`. Cross-reference the
   columns used in every `group_by` from step 5's rollup queries.
   `request_logs` partitioned on `inserted_at` (daily) usually has only
   `(inserted_at)` and `(team_member_id, inserted_at)` — rollups by
   `model_alias_id`, `provider_id`, `status_code`, `agent_type`,
   `api_key_prefix` need new composite indexes that include
   `inserted_at` to remain partition-pruned.

7b. **Check partition lifecycle (verified critical: my_app_gateway 2026-08).**
    A `PARTITION BY RANGE` table without a cron creating daily partitions
    ahead of time means **every insert falls into the DEFAULT partition**
    — partition pruning never kicks in and every query scans the full
    default partition. Grep `config/` and `lib/` for a partition-creation
    worker/cron (`grep -rn 'PARTITION OF' config/ lib/`). If only the
    migration creates partitions, that's a critical finding (PT-01).
    Also check for duplicate indexes (ASC+DESC on the same column pair)
    and legacy columns/FKs from removed features (PT-02, PT-03). See
    `references/postgres-partition-lifecycle.md` for the full cookbook.

8. **Check for the well-known bug patterns** (the user often lists
   them explicitly):
   - `socket.assigns[:period || "today"]` — the atom `:period` is always
     truthy, so the fallback never applies. Grep
     `assigns\[:\w+\s*\|\|`.
   - `String.to_integer(value)` / `String.to_float(value)` /
     `Decimal.new(value)` on user input in `handle_event` — use
     `Integer.parse/1`, `Float.parse/1`, `Decimal.parse/1` and pattern
     match.
   - Helpers that drop opts with a `[]` literal (callers expect keyword
     but get ignored). Grep `Rollup\\.\\w+\\(.*\\[\\]\\)` /
     `Logs\\.\\w+\\(.*\\[\\]\\)`.

9. **Confirm findings by reading the actual function.** Every reported
   N+1 must be evidenced by the function body — show the line, the
   loop, and the inner call. A finding without a cited line is
   noise; the user will reject it.

9b. **Beware the Ecto-preload false positive (verified in production — a
    subagent had to retract 4 of 10 findings).** `Repo.preload(struct, :assoc)`
    WITHOUT `force: true` is a no-op when the association is already loaded —
    Ecto resolves it in memory, zero queries. Before reporting an N+1, trace
    whether the outer query already preloaded the association. If yes, the
    inner `Repo.preload` / `effective_limits`-style helper is NOT a query.
    The 4 retracted findings all looked like `Enum.map(items, &helper/1)`
    cascades, but the helper's preload was cached. Only `force: true`
    preloads, fresh `Repo.all`/`Repo.one` per item, or per-item GenServer
    calls are real N+1.

9c. **Falsify moduledoc architecture claims (verified 2026-08 — two claims in
    one repo were both false).** Moduledocs state intent, not behavior:
    "Postgres is touched asynchronously via Oban" sat above a controller whose
    router did 3 uncached DB queries per call, and "a `:timer` entry per key
    expires the cache" sat above an ETS cache with no timer and no sweep.
    Treat every moduledoc claim about caching, TTLs, async writes, and
    coalescing as a hypothesis: grep for the mechanism it names
    (`:timer`, `handle_info(:sweep`, `expires_at` on the READ path) and
    report the mismatch as a finding — stale-routing/stale-auth bugs hide
    behind docs that describe the design the author wished for.

10. **Report structure.** Group by category, present a summary table at
    the top (ID | Sev | File:line | Category), then full descriptions.
    End with priority recommendations (1–5) and the literal line
    "Ningún archivo fue editado durante esta auditoría" / "No files were
    edited during this audit" so the user can grep it.

## Patterns to look for — quick reference

### Hot-path DB calls (critical)

- `Repo.preload(struct, [...], force: true)` in a controller, router,
  or proxy module — the auth plug almost certainly already preloaded
  the same association. Grep `force: true`.
- `Accounts.effective_limits/1` (or similar) called more than once per
  request with the same arg — every call re-preloads.
- A pure helper (`combine_foo`, `compute_bar`) wrapped inside a context
  function that the caller could have called directly with preloaded
  data.

### N+1 cascades (medium → high)

- `Enum.map(list, fn x -> Context.effective_limits(x) end)` — the inner
  helper re-preloads what the outer query already loaded.
- `Enum.map(list, fn x -> Context.spend(x.id) end)` where `spend`
  issues an aggregate query per id.
- `Repo.all(...) |> Enum.map(fn row -> {row, Related.list_for(row.id)} end)`
  — the related list should be one query with `where id in ^row_ids`.

### N GenServer/Registry calls in a dashboard loader (medium)

Dashboard pages that render a status badge per process often do
`Enum.map(creds, &Manager.status(&1.id))` — one lookup + sync `GenServer.call`
per item, per page reload. **Fix pattern (verified in production):** add a `status_all/0` that sweeps the Registry ONCE
with `Registry.select([{{:"$1", :"$2", :"$3"}, [], [{{:"$1", :"$2"}}]}])` and
builds the `%{id => state}` map, plus a filtered variant
(`open_breakers/0` returning only non-closed states) so admin alert pages
load from the DB ONLY the rows they'll actually render — instead of loading
every credential and filtering in memory.

### Double-compute rollups (medium)

Caller loads `list_member_budgets(tz)` AND `list_team_budgets(tz)` — but the
team function internally calls the member function again, so members are
queried and spend computed twice per reload. **Fix (verified in production):** make the private rollup helper public
(`rollup_team_budgets/1`) and have the caller derive the rollup from the
already-loaded list: `team_budgets = Budgets.rollup_team_budgets(budgets)`.

### Missing preloads (medium)

- Template accesses `member.user.email` but the query that produced
  `member` doesn't preload `:user`.
- Template accesses `team.members` but the team query doesn't preload
  `:members`.
- `from(t in Team, preload: [:team_members])` — team_members preloaded
  but their `:user`/`:api_key` not, and the template uses them.

### Unbounded lists (high when table grows without bound)

- `def list_X, do: Repo.all(X)` with no `limit:` and the table grows
  per request (request_logs, audit_logs).
- `from(s in Service, preload: [:api_key])` in an admin LiveView that
  doesn't paginate.
- `Repo.all(from(tma in TeamModelAlias, ...))` in a join-table query
  to build a per-team map — count grows with teams × aliases.
- **Keystroke-amplified lifetime aggregates (verified high).** A context
  function doing `SUM(...) GROUP BY ...` with NO date bound over an
  unbounded table (`total_spend_by_user` shape) is bad on mount — but
  check the CALLERS: when `search`/`sort`/`toggle` `handle_event`s all
  call the same `load_users/1`, every keystroke re-runs the full-table
  scan. Grep the aggregate, then grep its name across
  `lib/<app>_web/live` and read every `handle_event` that reaches it.
- **Rollup functions that SELECT row-per-request and reduce in Elixir.**
  The `peak_concurrency` shape: `SELECT inserted_at, latency_ms` for
  every row in the window → `Enum.flat_map` to 2N events → `Enum.sort`.
  That's O(rows) BEAM memory + sort per call, not an aggregate query —
  a 90d admin view on a busy table loads millions of rows into one
  process. Grep rollup modules for `|> Repo.all() |> Enum.flat_map` /
  `Enum.sort` after a bare row select; fix with a SQL window function
  or bucketed aggregation.

### PubSub storms (high)

- `Phoenix.PubSub.subscribe(@pubsub, "logs:new")` where `logs:new` is
  broadcast per proxied request (verify by reading the broadcaster —
  `Logs.WriteWorker` is the usual culprit). The handler must NOT do a
  DB query per message. Use coalescing with `Process.send_after` AND
  read from ETS (or local buffer), not Postgres.
- `handle_info({:new_log, log}, socket)` that calls `load_X(socket)` →
  `Enum.map(members, &member_budget/1)` → cascade N+1. Under sustained
  traffic this is one of the worst-case patterns.
- **Unguarded `send_after` = timer flood (verified: top finding of the
  2026-08 gateway audit).** `send_after` in a handler is NOT proof of
  coalescing — only an assign-flag guard is. `handle_info({:metrics_updated, _})`
  doing bare `Process.send_after(self(), :refresh, 200)` schedules one timer
  PER MESSAGE; at 100 msg/s the LiveView's mailbox accumulates `:refresh`
  faster than it can drain, and each drain costs its DB queries + ETS scans.
  Self-DoS from a single open tab. Audit grep: for every `handle_info`
  matching a broadcast, confirm the `send_after` sits behind
  `if socket.assigns[:*_scheduled]`. Unguarded = high.

### Index gaps (medium-high)

- `request_logs` partitioned by `inserted_at` but rollups do
  `group_by: rl.model_alias_id` with no `(model_alias_id, inserted_at)`
  index → sequential scan inside each partition.
- Same for `provider_id`, `status_code` (especially `>= 400` filters),
  `agent_type`, `api_key_prefix`.

### Bug patterns (informational unless found)

- `assigns[:\w+\s*\|\|` — atom-truthy fallback bug.
- `String.to_integer\(` / `String.to_float\(` / `Decimal.new\(` on user
  input in `handle_event`.
- Helpers receiving `[]` instead of `opts` (opts dropped).

## Patterns to call out as already-good (so the user trusts the audit)

Real audits have false positives. When you confirm something is *not*
a problem, say so explicitly — it shows the user you actually looked:

- `request_logs` *does* have indexes for the most common access patterns.
- `Logs.list_logs/1` *does* have a clamp_limit + default.
- `Metrics.Collector` *does* use ETS for hot counters.
- `process.send_after` coalescing *is* present in the dashboard LiveView.
- No `assigns[:period || ...]` bug found (cite the grep you ran).

## JSONB `meta` filtering patterns (second-brain / kanban / EAV-style apps)

Apps that stuff row attributes into a `meta`/`props` JSONB column (MyApp,
Notion-likes, kanban boards) have two recurring perf traps that don't show
up in the relational-focused checks above. Verified in MyApp 2026-08.

### J-01. Post-query in-memory filter on a JSONB key breaks pagination (high)

Pattern: the query applies `limit`/`offset`, THEN `Enum.filter`s the result
on a `meta` key in Elixir. Pagination silently lies — page N returns fewer
than `limit` rows (or zero) because discarded rows still consumed the
`offset`, and you transfer rows you'll throw away:

```elixir
# DANGEROUS — limit/offset applied, then props filtered in memory (MyApp Brain.list_pages)
pages = Repo.all(query_with_limit_offset)
if is_map(props) do
  Enum.filter(pages, fn p -> get_in(p.meta, ["props", k]) == v end)
end
```

**Fix:** push the filter into SQL so `limit`/`offset` stay honest. JSONB
containment uses the GIN index on `meta` (if present):
```elixir
where(query, [p], fragment("meta->'props' @> ?", ^Jason.encode!(props)))
```
Rate high — it corrupts pagination AND wastes I/O; medium if the list is
small and unpaginated.

### J-02. `fragment("?->>'key' = ?")` filters with no expression index (high at scale)

Kanban/status/assignee filters on JSONB keys (`meta->>'kanban_status' = ?`,
`meta->>'plan_slug' = ?`) can't use a plain btree index — every board view
seq-scans the table. The schema often HAS good GIN indexes on `tags` and a
`search_vector` column, which lulls you into thinking indexes are covered;
they don't help `->>'...'` equality filters.

**Audit grep:**
```bash
grep -rn "->>'" lib/ | grep -i 'where\|fragment'
# each filtered key: does a migration index the EXPRESSION?
grep -rn "meta->>'" priv/repo/migrations/
```

**Fix (pick one):**
- Expression index per hot key, partial to the relevant row type:
  `CREATE INDEX ... ON pages ((meta->>'kanban_status')) WHERE page_type = 'todo'`
- Better long-term: promote the hottest keys (`kanban_status`, `assignee`,
  `plan_slug`) to real typed columns with their own btree indexes — query
  planner stats, FK checks, and no fragments. JSONB is fine for the long
  tail of props, wrong for fields you filter/sort every request.

Rate high once the table outgrows a few thousand rows; medium below that.

### J-03. Per-query context/config reload inside a query pipeline (medium)

A `maybe_*` query-builder helper that itself runs `Repo.get(Context, id)` to
decide whether to add a `where` — every `list_*` call costs a bonus query:

```elixir
# DANGEROUS — extra query per list_pages call (MyApp maybe_exclude_disabled_types)
defp maybe_exclude_disabled_types(query, context_id) do
  case Repo.get(Context, context_id) do
    %Context{disabled_page_types: d} when d != [] -> where(query, [p], p.page_type not in ^d)
    _ -> query
  end
end
```

**Fix:** the caller almost always already loaded the `%Context{}` (the
LiveView did, to render the page) — pass the struct (or just the
`disabled_page_types` list) into the query builder instead of the id.
Rate medium — one extra indexed PK lookup per list call; high if the list
function sits on a hot dashboard that reloads on PubSub.

## Patterns specific to LLM-proxy-style apps

When the app is a proxy/gateway (chat-completions passthrough, multi-
provider routing), the hot path is a separate concern:

- API key lookup should be cached (ETS, not per-request DB). If the plug
  reads `accounts.get_team_member_by_api_key` per request without an
  ETS cache, that's a critical hot-path finding.
- `check_budget` should read ETS counters, not aggregate Postgres.
- `record_outcome` should be ETS-only; circuit-breaker state should be
  in ETS (per-credential `:gen_statem` is OK at low credential count
  but is a sync-RPC bottleneck when you have many).
- Webhook/Oban log writes must be async — `Logs.WriteWorker` enqueuing
  Oban jobs is correct; a synchronous `Repo.insert` in the controller
  is critical. Nuance: `Oban.insert/1` itself is still a SYNCHRONOUS
  INSERT into `oban_jobs` on the request thread (~1 DB round-trip +
  pool checkout per request). "Async via Oban" means the *work* is
  async, not that the hot path is DB-free — count the enqueue when
  tallying per-request DB ops against the pool size.
- **SSE streaming path (verified: two real findings in the 2026-08
  gateway audit).** For every `Finch.stream_while`/SSE upstream task:
  (a) `Task.start` (unlinked) leaks the upstream connection + fd when
  the request process dies by any path other than the handled
  client-disconnect — the caller monitors the task, but nothing kills
  the task when the CALLER dies; (b) a `receive` loop without `after`
  has no idle/total cap — Finch's `receive_timeout` is per-recv, so a
  slow-drip provider holds a request process + concurrency slot forever.
  Checklist and kill-path verification recipe:
  `references/streaming-leak-audit.md`.

## ETS-specific hot-path patterns (counters, registries, caches)

Elixir gateway apps lean hard on ETS for budgets, limits, metrics, and
in-flight registries. ETS is fast, but these three misuse patterns show
up constantly and only hurt at scale — grep for them explicitly:

### E-01. Read-modify-write on an ETS list/map value (medium → high)

Pattern: read a list out of ETS, prepend/transform, write the whole
thing back. Two concurrent writers lose each other's updates, and the
samples you lose are exactly the high-latency outliers (they take
longest, so their writes land last and get overwritten).

```elixir
# DANGEROUS — non-atomic RMW (verified: Metrics.Collector.push_latency)
current = :ets.lookup_element(@table, :latency_samples, 2)
new_list = [latency_ms | current] |> Enum.take(@max_samples)
:ets.insert(@table, {:latency_samples, new_list})
```

The tell: a moduledoc or comment admitting "occasional lost writes are
acceptable" — that's the author papering over the race. It IS acceptable
for approximations (p95 dashboards), but then the impact statement must
say the metric is *biased low under load*, not just "approximate".

**Fixes (pick one):**
- N keys instead of one list: `{:latency, slot}` with round-robin
  `:ets.update_counter` to pick the slot — no shared mutable value.
- Histogram in `:atomics` with fixed buckets (0-50ms, 50-100, ...) —
  exact p95 at read time, zero lists, lock-free.
- If a list is genuinely needed, route writes through the owning
  GenServer (serialize) — acceptable only off the hot path.

**Audit grep:**
```bash
grep -n 'lookup_element\|:ets.insert' lib/*/metrics/*.ex lib/*/logs/*.ex
# for each hit: is the inserted value derived from the looked-up value? RMW.
```

### E-02. One Oban job enqueued per request for drift correction (medium)

Pattern: every successful proxied request enqueues a background job
(budget sync, stats refresh, cache invalidation). At 1k RPM that's 1k
jobs/min for work that could be batched — Oban handles it, but the jobs
table churn and the worker pool saturation crowd out real jobs.

**Fix — debounce with an ETS flag:**
```elixir
# Only enqueue when no sync is already pending for this key:
case :ets.insert_new(@table, {{:sync_pending, member_id}, true}) do
  true -> Oban.insert(SyncWorker.new(%{member_id: member_id}))
  false -> :ok  # a job is already queued; it'll pick up the latest state
end
# The worker deletes the flag at the START of perform/1.
```
Or time-based: sync each key at most once per N seconds, tracked with
`{:last_sync, key} => monotonic_ms` in ETS. Rate medium; high if the
per-request job itself does an aggregate query.

**Audit grep:**
```bash
grep -n 'Oban.insert\|\.new() |> Oban' lib/ | grep -v worker.ex
# each call site: is it on the request hot path? is there a dedup flag?
```

### E-03. Full `:ets.tab2list` to compute a tiny aggregate (medium)

Pattern: dashboard reads like "in-flight count per model" copy the
ENTIRE ETS table into the caller process, then group/sort in Elixir —
per LiveView render, per connected client.

```elixir
# DANGEROUS at scale — copies every entry per render
@table
|> :ets.tab2list()
|> Enum.group_by(& &1.model_requested)
```

**Fixes:**
- `:ets.select` with a match spec projecting only the fields needed
  (e.g. just `model_requested`) — still O(n) but no full-map copies.
- Better: maintain aggregate counters alongside the registry. On
  `start_request` bump `{model, count}`, on `finish_request` decrement —
  reads become O(1). Verified pattern: rate-limit/inflight tables
  already do this for totals (`total_inflight` via `update_counter`);
  per-dimension aggregates are the same trick.
- `:ets.info(@table, :size)` for bare counts — never `length(tab2list())`.

**Audit grep:**
```bash
grep -n 'tab2list\|:ets.foldl' lib/
# for each: how big can the table get, and how often is this called?
```

### E-04. Uncached routing/config lookups per request (high)

Pattern: the router calls a context function (`list_model_providers_for_member`,
`list_accessible_aliases`) on EVERY proxied request to decide where to
send it — but the underlying data (providers, aliases, grants) changes
only when an admin edits it. At 100 RPM that's 100 identical
multi-join queries per minute.

**Fix:** ETS cache keyed by `{model_alias_id, team_id}` with a short
TTL (30-60s) OR explicit invalidation via PubSub broadcast from the
admin LiveView that edits providers. The invalidation-on-write variant
is strictly better (no staleness window) — but verify the broadcast
actually fires from every mutation path (LiveView, seeds, migrations
that touch the tables). Rate high: it's the top DB-load reducer for
gateway apps.

**Audit grep:**
```bash
grep -n 'def route\|def models_for' lib/*/routing/*.ex
# read what context queries fire per call — are they ETS-backed or Repo-backed?
```

### E-05. Dead TTL: `expires_at` stored but never checked / no sweep (medium)

Two shapes, both verified in the 2026-08 gateway audit:

1. **TTL never enforced on read.** `put` stores `{key, value, expires_at}`
   and the moduledoc advertises a TTL, but the read clause matches
   `_expires_at` (dead giveaway) and returns the value unconditionally, and
   the owning GenServer has no `handle_info(:sweep, ...)`. Entries live
   until explicit invalidation — fine while every write path invalidates,
   a landmine the day one doesn't (a reactivated credential staying
   unroutable forever is the canonical blast radius).
2. **TTL checked on read, expired entries never evicted.** `read` returns
   `:miss` for stale entries but nobody deletes them → the table grows by
   `keyspace × entry size` forever (e.g. `{user_id, period, timezone}` →
   full dashboard bundles). Slow node-memory leak.

**Audit grep:**
```bash
grep -n 'expires_at\|_expires_at\|ttl' lib/*/routing/cache.ex lib/*/metrics/*.ex
# for each cache: (a) does any read clause CHECK the timestamp?
# (b) does ANY handle_info/timer delete expired entries?
# Both must be yes, or the TTL is decorative.
```

**Fix:** enforce the TTL in the read clause AND add a periodic
`:ets.select_delete` sweep (match spec on `expires_at < now`) in the table
owner — cheap, runs in the GenServer that already exists.

### E-06. O(n²) dedup inside pre-flight payload transforms (medium)

Pre-flight transforms applied to the request payload before forwarding
upstream can hide quadratic passes inside "pure" helper functions. The
canonical offender is a system-message dedup that compares each message
against every already-seen message:

```elixir
# DANGEROUS — O(n²) in system messages (verified my_app_gateway 2026-08)
Enum.reduce(systems, [], fn msg, acc ->
  if Enum.any?(acc, fn existing ->
       String.trim(Map.get(existing, "content")) == normalized end) do
    acc
  else
    [msg | acc]
  end
end)
```

With payloads carrying many system messages (tool definitions, long
system prompts with injected guard rails), this is quadratic in the
system-message count — on the proxy hot path, per request.

**Fix:** dedup against a `MapSet` of normalized contents (O(n)):
```elixir
{deduped, _seen} =
  Enum.reduce(systems, {[], MapSet.new()}, fn msg, {acc, seen} ->
    content = Map.get(msg, "content")
    key = if is_binary(content), do: String.trim(content), else: make_ref()
    if MapSet.member?(seen, key) do
      {acc, seen}
    else
      {[msg | acc], MapSet.put(seen, key)}
    end
  end)
```

**Audit grep:**
```bash
grep -n 'Enum.any?(acc\|Enum.find(acc' lib/*/proxy/*.ex
# any reduce-while-scanning-accumulator pattern is a candidate for MapSet
```

Rate medium — only fires on large system-message payloads, but it's on the
per-request hot path.

### E-07. DB query inside the saturated-fallback path (high)

When a credential's concurrency is exhausted, the fallback logic often
needs to know "how many alternatives remain" to decide whether to wait in
a queue or fall back immediately. If that count is computed via a fresh
Postgres query (not the routing cache), the saturated path — already
latency-sensitive — adds a synchronous DB round-trip:

```elixir
# DANGEROUS — DB query on the saturated path (verified my_app_gateway 2026-08)
def count_remaining_included(model_requested, team_member, exclude_id) do
  model_providers = Providers.list_model_providers_for_member(...)  # ← Repo query
  Enum.count(model_providers, &included_and_active?/1)
end
```

The routing cache (`Routing.Cache.fetch_model_providers/3`) already holds
the provider list for 60s — but the fallback path bypasses it and queries
directly. At saturation, every queued request does this query.

**Fix:** read from the existing ETS cache instead of the context function.
The cache is stale-tolerant (the fallback matrix re-routes on a dead
credential anyway), so a 60s-old count is acceptable for timeout
calculation.

**Audit grep:**
```bash
grep -n 'count_remaining\|list_model_providers' lib/*/routing/*.ex lib/*/controllers/*.ex
# any call NOT going through Routing.Cache.fetch_model_providers = flag
```

Rate high — it's a DB call on the path that's already the slowest in the
system.

### E-08. ETS table created without `heir` — table lost on GenServer restart (medium)

Pattern: the GenServer creates its ETS table in `init/1` with
`:ets.new(@table, [:set, :public, ...])` but passes no `heir` option.
If the GenServer crashes (OOM, supervisor restart, hot-reload), **the
table is destroyed and all accumulated state is lost** — budget counters
reset to zero, routing cache empties, metrics vanish. Recovery depends
entirely on traffic re-populating the table, which means budget checks
fail open (allowing overspend) until the lazy-load re-seeds from DB.

```elixir
# DANGEROUS — no heir, table dies with the GenServer (verified my_app_gateway 2026-08)
def init(_opts) do
  ensure_table()  # :ets.new without heir
  {:ok, %{}}
end
```

**Fix:** pass `{:heir, heir_pid, heir_data}` to `:ets.new/2`, where
`heir_pid` is a long-lived process (e.g. a dedicated `TableHeir`
GenServer started before the table owner). On GenServer restart, the
table survives and the new GenServer can `:ets.give_away/3` it back.

**Audit grep:**
```bash
grep -n ':ets.new' lib/ | grep -v heir
# every table owner: does init pass {:heir, ...}?
```

Rate medium — crashes are rare, but when they happen the data loss is
silent and the fail-open window is the danger.

### E-09. ETS hot-read tables missing `read_concurrency: true` (medium)

Pattern: tables that serve frequent reads from LiveView processes
(`snapshot/0`, `list/0`, `count/0`) but are created without
`read_concurrency: true`. Without it, reads and writes contend on the
same lock even though the reads are pure lookups — the write path
(`update_counter`, `insert`) stalls the read path and vice versa.

```elixir
# DANGEROUS — hot read table without read_concurrency (verified my_app_gateway 2026-08)
:ets.new(@table, [:set, :public, :named_table, write_concurrency: true])
# ← read path (snapshot/0) contends with write path (record_request/1)
```

`write_concurrency: true` is often set (good) but `read_concurrency: true`
is missed. The fix is just adding the flag to `:ets.new/2` — it has no
downside for read-heavy tables.

**Audit grep:**
```bash
grep -n ':ets.new' lib/ | grep -v read_concurrency
# tables with frequent :ets.lookup/lookup_element/tab2list reads = flag
```

### E-10. `update_counter` with default object silently resets evicted entries (medium → high)

Pattern: `:ets.update_counter(@table, key, {pos, inc}, default_object)`
is used as a convenient "increment or create" — but if the entry was
evicted between the `ensure_loaded` check and the `bump_counter` call
(e.g. by a `select_delete` sweep, a restart without heir, or memory
pressure), the default object recreates the entry at `0 + inc` —
**losing all accumulated state**. The comment usually admits "rare race"
but the impact is budget overspend: a counter that was at $4.99 resets
to $0.01, and the next request sees the budget as not-exhausted.

```elixir
# DANGEROUS — default object masks eviction race (verified my_app_gateway 2026-08)
defp bump_counter(key, inc) do
  period = elem(key, 1)
  default = {key, 0, false, current_period_stamp(period)}  # ← if evicted, starts at 0
  :ets.update_counter(@table, key, {2, inc}, default)
end
```

**Fix:** separate the "ensure exists" from the "increment" — if
`ensure_loaded` already seeded the entry, `bump_counter` should NOT
pass a default object (let it fail loudly if the entry is missing,
rather than silently recreating it at zero). Or re-seed from DB in the
rescue clause before incrementing.

Rate medium normally, high when the table is under memory pressure or
when the owning GenServer restarts (see E-08 — no heir means full table
loss, then every `bump_counter` silently starts at zero).

### E-11. Unbounded ETS growth via unvalidated dimension keys (medium → high)

Pattern: an ETS metrics table tracks per-dimension counters (e.g.
`{:requests, {:agent, agent_type}}`), and the dimension value comes from
a user-controlled header (`X-Agent-Type`) without truncation, validation,
or a whitelist. Each unique value creates a new ETS key — a client sending
a unique header per request creates one key per request, growing the
table without bound.

```elixir
# DANGEROUS — unvalidated agent_type creates unbounded ETS keys (verified my_app_gateway 2026-08)
defp agent_type(conn) do
  case get_req_header(conn, "x-agent-type") do
    [type | _] when byte_size(type) > 0 -> type  # no truncation, no whitelist
  end
end
# ...later:
incr({:requests, {:agent, agent_type}})  # one ETS key per unique header value
```

**Fix:** truncate to 255 chars, normalize to a known set, or hash to a
fixed number of buckets. The same validation should apply to any
user-controlled dimension that becomes an ETS key.

**Audit grep:**
```bash
grep -n 'incr(\|update_counter' lib/*/metrics/*.ex
# for each dimension key: trace the value source — is it user-controlled?
```

## Partitioned-table lifecycle patterns (Postgres native partitioning)

Apps using native Postgres `PARTITION BY RANGE` on a log table (the
canonical pattern for `request_logs`) have a second class of problems
beyond index gaps. See `references/postgres-partition-lifecycle.md`
for the full cookbook. Key patterns:

### PT-01. No partition creation cron — everything falls to the default partition (critical)

The migration creates `CREATE TABLE ... PARTITION BY RANGE (inserted_at)`
with one explicit partition and a `DEFAULT` partition. Without an Oban
cron that creates daily partitions ahead of time, **every insert falls
into the default partition**. Partition pruning never kicks in — every
query scans the entire default partition regardless of the `inserted_at`
filter. The partitioned architecture exists but provides zero benefit.

**Audit grep:**
```bash
# Check for partition creation in Oban crontab or workers
grep -rn 'PARTITION OF\|CREATE TABLE.*request_logs_' config/ lib/ priv/
# If only the migration creates partitions and no cron/worker = critical
```

### PT-02. Duplicate indexes — ASC + DESC on same column pair (medium)

Two migrations created indexes on `(model_alias_id, inserted_at)` — one
ASC, one DESC — an hour apart. The ASC index is never used (all queries
`ORDER BY inserted_at DESC`). Pure write overhead.

**Audit grep:**
```bash
# Find index definitions on the same column set
grep -rn 'CREATE INDEX.*request_logs' priv/repo/migrations/ | sort
# Any two indexes on the same columns with different sort direction = flag
```

### PT-03. Legacy columns/FKs not dropped after feature removal (medium)

`subscription_id` FK in `request_logs` referencing a dropped table,
`cost_usd`/`savings_usd`/`estimated_cost_usd` columns still present
after `provider_cost_usd` became the sole cost field. Each is 16-24
bytes/row of wasted space × millions of rows.

**Audit grep:**
```bash
# Compare schema fields vs migration columns
grep -rhn 'ADD COLUMN\|CREATE TABLE.*request_logs' priv/repo/migrations/
# Cross-reference with the Ecto schema — columns in DB but not in schema = legacy
```

## Output template

Adopt this exact structure unless the user asks for something else
(the task spec that originated this skill requires
"Ningún archivo fue editado durante esta auditoría" as the last line —
keep that line so the user can grep it):

```markdown
# <App> — Auditoría de performance (READ-ONLY)

<one-paragraph summary of the worst findings>

## Tabla resumen
| ID | Sev | Archivo:línea | Categoría |

## 1. Hot path del proxy
### P-01 — <title>
- **Severidad:** critical
- **Archivo:** lib/...
- **Categoría:** ...
- **Descripción:** ...
- **Fix:** ...

## 2. Cascadas N+1
...

## Patrones positivos encontrados
- ...

---

**Ningún archivo fue editado durante esta auditoría.**
```

## Verification

Before declaring the audit done:

```bash
git -C <repo> status --porcelain
```

The output must be empty. If it isn't, you wrote something — name it,
admit it in the report's preface, and `rm` the file before the final
message.

## References

- `references/n-plus-one-cookbook.md` — common N+1 shapes in
  LiveView mounts and loaders, with concrete fix snippets.
- `references/pubsub-storm-detection.md` — how to identify a
  PubSub storm from the broadcaster side and the subscriber side.
- `references/hot-path-checklist.md` — the proxy/gateway-specific
  hot-path audit: API key lookup, ETS caches, sync RPCs.
- `references/migration-index-cookbook.md` — Postgres composite
  indexes for partitioned log tables; verifying with EXPLAIN.
- `references/postgres-partition-lifecycle.md` — native Postgres
  RANGE partition lifecycle: creation cron, cleanup, duplicate index
  detection, legacy column/FK drops, partial indexes on partitions.