# Performance Audit Funnel (read-only)

How to find hot spots by reading code — no slow query in hand. Structured
findings with `file:line` evidence; the user applies the fixes. Verified
methodology across several audits.

## The cardinal rule: don't write

- No file writes for audit files — deliver the report inline.
- No patches to source files, even "obviously correct" fixes.
- No terminal commands that mutate state.
- Verify at the end: `git status --porcelain` must be empty. Report the line:
  "No files were edited during this audit."

## Severity rubric

| Severity | Definition |
|---|---|
| **critical** | DB call in the hot path of every request (force-preload past an already-preloaded auth plug, per-request `Repo.all` on a growing table). Steady-state DB load scales with request rate. |
| **high** | N+1 triggered by every PubSub message under sustained traffic; unbounded list on a table that grows without bound; missing index for a GROUP BY column on a hot dashboard. |
| **medium** | N+1 in a mount/loader that runs only on navigation; missing cap on a small catalog; redundant context call that preloads the same association twice in one request. |
| **low** | Admin-only cascade; O(N²) in-memory pass on small N; preload gap that doesn't fire today. |
| **informational** | Pattern *not* found — report "not present" so the user knows you looked. |

## Methodology (in order — categories reinforce each other)

### 1. Map the query surface

```bash
search_files pattern="def list_" path="lib/<ctx>"
search_files pattern="Repo\.all" path="lib/<ctx>"
```

These are candidates for unbounded-list findings.

### 2. Map preloads and their consumers

```bash
search_files pattern="preload:" path="lib/<ctx>"
```

Cross-reference with LiveView templates. If a template accesses
`item.user.email` but the query doesn't preload `:user` — missing preload
(medium unless on the hot path).

### 3. Trace the hot-path plug chain

Auth plugs usually run `Repo.preload(member, [:team, :user, :api_key])`. Any
downstream `Repo.preload(member, [:team], force: true)` is redundant and
critical — `force: true` ignores already-loaded data and issues a new SELECT
every call:

```bash
grep -rn 'force: true' lib/<app> lib/<app>_web
```

### 4. Read every LiveView `mount/3`

Look for `Enum.map(items, fn item -> Context.helper(item) end)` (classic N+1
cascade), `list_all()`-style calls with no `limit:`, `Repo.all(...)` with no
pagination.

### 5. Read every `handle_info` in LiveViews

For each PubSub subscriber classify the handler: reads ETS only → OK (cheap);
reads ETS + runs a DB query → storm candidate; runs `Enum.map` with a context
helper → compound storm.

The **unguarded send_after** anti-pattern:
`Process.send_after(self(), :refresh, 200)` without
`if socket.assigns[:*_scheduled]` schedules one timer per message — at 100
msg/s the mailbox accumulates `:refresh` faster than it drains: self-DoS from
a single open tab.

### 6. Read controllers on the hot path

- `Repo.preload(..., force: true)` calls.
- Helpers called multiple times per request with the same arguments.
- Lazy-load helpers (`load_from_db`, `ensure_loaded`) that hit Postgres on
  first call per period per key — the first request of the day becomes a
  synchronized burst of N aggregate queries. Mitigate with pre-warm (Oban cron
  seeding ETS before the first request) or async deferral.

### 7. Check migrations for indexes on GROUP BY / ORDER BY columns

For every hot query, compare its `ORDER BY`/`WHERE`/`group_by` against actual
migrations (`grep -rn 'create index\|CREATE INDEX' priv/repo/migrations/`).
Composite indexes must match the query shape (key columns + sort directions).

Partitioned tables: indexes must be created on the parent (propagates);
`CONCURRENTLY` is NOT supported on partitioned parents; partial indexes must be
added per partition. See `references/partition-maintenance.md`.

### 8. Check partition lifecycle

`PARTITION BY RANGE` without a cron creating partitions ahead of time = every
insert into the DEFAULT partition, pruning dead:

```bash
grep -rn 'PARTITION OF' config/ lib/ priv/
```

If only the migration creates partitions, that's critical.

### 9. Check for known bug patterns

- `assigns[:period || "today"]` — atom `:period` is always truthy, the
  fallback never applies. Grep: `assigns\[\:\w+\s*\|\|`.
- `String.to_integer(value)` on user input in `handle_event` — use
  `Integer.parse/1` and pattern-match.
- Helpers that drop opts with a `[]` literal (callers pass keyword, get ignored).

### 10. Falsify moduledoc architecture claims

Moduledocs state intent, not behavior. Treat every claim about caching, TTLs,
async writes, and coalescing as a hypothesis: grep for the mechanism it named
(`:timer`, `handle_info(:sweep`, `expires_at` on the read path) and report
mismatches.

### 11. Confirm every finding by reading the actual function

Every reported N+1 must be evidenced by the function body — show the line, the
loop, the inner call. A finding without a cited line is noise.

**Ecto preload false positive:** `Repo.preload(struct, :assoc)` WITHOUT
`force: true` is a no-op when the association is already loaded. Trace whether
the outer query already preloaded it before reporting.

## Hot-path checklist (controllers)

Budget: zero synchronous DB calls between client and response.

1. Trace the plug chain — `grep -rn 'plug ' lib/<app>_web/router.ex | head -40`; note what the auth plug preloads.
2. Grep `force: true` — critical signal.
3. Count helper invocations per request — helpers called twice with the same arg are redundant work.
4. Lazy-load helpers → pre-warm or async.
5. Synchronous Oban inserts / `GenServer.call/2` on singletons — measurable per-request latency; move state to ETS where possible.
6. Error-path branches — make sure rejected-request logging is a fast queue insert, not a synchronous `Logs.log_request`.

## PubSub storm fix priority

1. Move hot counters to ETS (eliminates DB reads entirely).
2. Stream inserts (`stream_insert` into a LiveView stream).
3. Cap/consolidate subscribers.
4. Increase the coalescing window as a stopgap.

## Redundancy audit (N-query overlap)

When a caller loads `list_X(tz)` AND `list_Y(tz)` but the second function
internally calls the first, the data is computed twice. Find by reading the
public function body of each list helper and checking whether it calls another
list helper on the same data.

## Output format

Group by category (hot-path → cascades → PubSub → indexes → ETS → bugs →
other). Summary table at top:

| ID | Severity | File:line | Category |
|----|----------|-----------|----------|

Then full descriptions with cited lines, then 1-5 priority recommendations,
ending with "No files were edited during this audit."

## Verification

```bash
git status --porcelain   # must be empty
```

If it isn't, you wrote something — name it, admit it in the report, remove the file.