# Hot-path audit checklist — Phoenix controllers

A hot-path audit traces every synchronous DB call from the moment a
request enters the router to the moment a response goes out. Each
DB call adds Postgres round-trip latency to every request, so the
budget is "zero synchronous DB calls before the upstream call".

## What "hot path" means

For a Phoenix app with synchronous controllers (no background
processing on the request thread), the hot path is the code path
executed by *every* successful request. In a proxy/gateway, that's
the `chat_completions` controller + its plug chain. In a regular
CRUD app, it's the most-trafficked POST/PATCH/DELETE controller.

The audit walks the path:

```
client → router → plug chain → controller action → response
                                              → async writes (Oban, PubSub, GenServer)
```

Anything synchronous between client and response must not hit DB.

## Step-by-step checklist

### 1. Trace the plug chain

```bash
# Find the plug ordering for the route under audit
grep -rn 'plug ' lib/<app>_web/router.ex | head -40
```

For each plug in the chain, open it and identify what it does. The
critical plug is the auth plug that resolves the API key / session
user — it almost always preloads associations. Note those preloads
explicitly:

```
Auth plug loads:
  - team_member.team
  - team_member.user
  - team_member.api_key

Anything downstream that re-preloads :team, :user, or :api_key
on the same struct is redundant.
```

### 2. Grep for `force: true` (critical signal)

```bash
grep -rn 'force: true' lib/<app> lib/<app>_web
```

`force: true` on `Repo.preload/3` ignores already-loaded data and
issues a new SELECT every call. In a hot path this is a critical
finding.

Example (MyApp audit): `lib/MyApp/routing/router.ex:246`

```elixir
defp maybe_preload_team(team_member) do
  MyApp.Repo.preload(team_member, [:team], force: true)
end
```

The auth plug already preloads `:team`. This `force: true`
overrides the no-op and re-queries. Cost: 1 extra SELECT per
proxied request.

Fix: drop `force: true`, or guard with `Ecto.assoc_loaded?/2`.

### 3. Find context helpers called more than once per request

For each hot-path controller, search for the names of context
helpers it uses. Then count how many times each helper is called:

```bash
grep -n 'effective_limits\|effective_spend\|load_budget\|list_team_members' \
  lib/<app>_web/controllers/<controller>.ex
```

In the MyApp audit, `Accounts.effective_limits/1` was called
twice in `proxy_controller.ex:68` AND `:204`. Each call issues
`Repo.preload(:team)` (because the helper does so unconditionally).
Two redundant queries per request.

Fix: compute once, pass into helpers that take a precomputed map.

### 4. Find lazy-load helpers in the hot path

Search for ETS-backed counters that lazy-load from DB:

```bash
grep -rn 'load_from_db\|seed_from_db\|ensure_loaded' lib/<app>
```

These are OK at low volume. In a hot path they cause a one-time
DB hit on the first request of each period (per member, per day).
With many members hitting the hot path concurrently, the first
request of the day becomes a synchronized burst of N aggregate
queries.

Mitigation patterns:

- Pre-warm: schedule an Oban cron to seed the ETS for all active
  members 1 minute before the day's first request.
- Async: defer the DB load to a background process; return an
  empty/zero value to the hot path while the load runs.

### 5. Find synchronous Oban/Worker calls in the request thread

```bash
grep -rn 'Oban.insert' lib/<app>_web
grep -rn 'GenServer.call\|Process.send_after' lib/<app>_web/controllers
```

Oban inserts via `Oban.insert/1` are normally fast (a single INSERT
into `oban_jobs`), but they are still synchronous DB writes. On
the hot path they add ~1-3ms per request. Acceptable, but if you
find one per request (e.g. enqueueing a log job + a metrics job +
a webhook job = 3 inserts per proxied request), consider batching.

`GenServer.call/2` on a singleton GenServer (e.g. the budget
manager, sticky tracker, breaker manager) is a per-request sync
RPC that serializes on the called process. If the GenServer
processes other work (e.g. the breaker manager runs `:allow?` for
*every* routing candidate on *every* proxied request), this is a
throughput bottleneck.

Mitigation: move the state into ETS and serve reads/writes from
the caller's process. The breaker can be a counter in ETS.

### 6. Check the controller's error-path branches

When the controller returns early (rate limited, budget exceeded,
upstream error), does the error branch hit DB? It often does
because the controller still wants to enqueue a log row for the
rejected request. Make sure the enqueue is the Oban insert and
not a synchronous `Logs.log_request`.

## Specific patterns to grep

```bash
# Auth-related plugs that resolve the principal
grep -rn 'get_team_member_by_api_key\|get_user_by_email\|fetch_member' \
  lib/<app>_web/plugs

# Force-preloads
grep -rn 'force: true' lib/<app> lib/<app>_web

# Repo.preload calls inside non-migration modules
grep -rn 'Repo\.preload' lib/<app> lib/<app>_web | grep -v test

# ETS lazy loads that touch DB
grep -rn 'load_from_db\|seed_from_db\|ensure_loaded' lib/<app>

# Synchronous Oban inserts
grep -rn 'Oban.insert\|new\(\)\s*|\>\s*Oban.insert' lib/<app>_web

# Sync GenServer calls on the hot path
grep -rn 'GenServer.call' lib/<app>_web/controllers lib/<app>/routing \
  lib/<app>/budgets/manager
```

## Already-good pattern (reference)

`lib/MyApp/logs/write_worker.ex`:

```elixir
def perform(%Oban.Job{args: args}) do
  # ... insert into request_logs (async, off the hot path)
  # broadcast {:new_log, log} (subscribers coalesce)
end
```

The controller calls `enqueue_log/8` which does
`WriteWorker.new() |> Oban.insert()` — fast (1 INSERT), no SELECT,
and the actual log write happens in a background process. This is
the right shape.

## Common false positives

- `Repo.preload(..., force: true)` in a test helper or migration —
  not in the hot path.
- `Oban.insert` in a `handle_event` (admin form submit) — not the
  hot path; only invoked on user action.
- `Repo.preload` inside an Oban worker (async, off the hot path) —
  acceptable, but check if the worker fires per-request and if the
  preload is unnecessary.