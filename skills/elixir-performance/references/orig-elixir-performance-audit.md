---
name: elixir-performance-audit
description: "Use when auditing Phoenix apps for query/cache hot spots, auth hardening, and security gaps."
metadata:
  hermes:
    tags: [elixir, phoenix, ecto, performance, security, audit, liveview, cache]
---

# Proactive performance & security audit of an Elixir/Phoenix app

## When to Use / Trigger

- User asks for a performance analysis/audit of a Phoenix app (e.g. "analiza performance de tracker y tickets", "revisa queries y caché") — no slow query in hand; the job is to find hot spots by reading code.
- User asks for a security/hardening review against an internal baseline (e.g. "revisa performance y seguridad contra el glosario MyApp engineering") — especially when there's a MyApp/glosario with codified rules to check against.
- Producing a prioritized P0/P1/P2 (or 🔴/🟠/🟡) findings report with `path:line` evidence.

NOT for the *reactive* direction (slow query observed in monitoring → find its Ecto source): use `elixir-ecto-query-tracing` instead.

## Process — Start with the baseline

When Álvaro says "revisa contra el contenido de performance y seguridad" (or similar), the baseline lives in **MyApp `engineering` context** under the glosario MOC:

1. **Search the glosario first** — `mcp__dran_bravo__dran_search(context: "engineering", query: "performance")` and `query: "seguridad"` in parallel.
2. **Pull the MOC page** — `glosario-performance-y-seguridad-elixir-phoenix` lists every sub-page. Read the ones most relevant to the target repo's surface (cache, security, queries, web-hardening).
3. **Map findings to the glosario's numbered rules** — each finding should cite which rule it violates (e.g. "security #6 — admin routes without auth"). This makes the report directly comparable to past audits and lets Álvaro trace each finding back to a verified pattern.

This is the primary source of truth for audit criteria. Do NOT rely on generic Elixir security knowledge alone — the glosario is codified from real Hub/my_app_gateway incidents.

## Performance checklist (ordered by typical impact)

1. **LiveView mounts that load full tables** — grep LiveViews for `limit: :all` inside `mount`/`handle_params`. Red flag: a *detail* view (`params["id"]` present) loading every row of a type just to compute sidebar metrics (approvals, stagnation). Fix class: scope the batch to the item's context (parent/squad), or reuse a cached snapshot.
2. **Batch helpers exist but callers bypass them** — find batch functions (e.g. `pending_counts_for_ids`, `comment_counts_for_ids`, `children_progress`) and verify every hot path calls the batch version, not a per-item loop. A batch helper that exists but isn't called everywhere is a silent N+1.
3. **ETS read-through cache coverage** — map what IS cached (key shape, TTL, invalidation path) and then list hot reads that are NOT cached. For each uncached hot read ask: how often does it change vs how often is it read? Invalidation usually happens in the PubSub broadcast module — check `invalidate_pattern` calls there cover the new cache key.
4. **Index coverage vs ORDER BY** — for each hot query, compare its `ORDER BY` + `WHERE` against actual migrations (`create index` in `priv/repo/migrations`). Composite partial indexes (e.g. `(app_name, type, status, position, pinned DESC, inserted_at DESC) WHERE archived_at IS NULL`) are the pattern that works; verify direction columns match.
5. **Postgres `DISTINCT` + `ORDER BY` anti-pattern** — `distinct: a.work_item_id, order_by: [a.work_item_id, desc: a.inserted_at]` forces a sort/seq scan at scale. Fix class: `ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...)` in a subquery, filter `row_number = 1`. Verify with EXPLAIN ANALYZE, not vibes.
6. **Hybrid timestamp + Activity fallback doubling every query** — when a domain timestamp (e.g. `completed_at`) has an Activity-table fallback for legacy rows, every metric that touches it runs 2 queries. Count how many call sites do this; the class-level fix is a materialized view resolving the effective timestamp once, or backfilling the column.
7. **Metrics modules re-querying per metric** — if a stats module has N public functions that each re-fetch the same underlying rows, look for (or propose) a single `dashboard/1`-style entry point that loads once and derives all metrics in memory, with the individual functions kept as wrappers. LiveViews should call the aggregate, not orchestrate N cached calls that each recompute the shared base.
8. **ReAct/agent loops re-fetching history per step** — LLM runtimes that call `list_messages_for_llm(session_id)` inside a `max_steps` loop multiply the history query by N steps. Verify the underlying table has an index on `(session_id, inserted_at DESC)` and consider incremental fetch (only messages since last step). Real example: `lib/rafa/runtime/llm_runtime.ex` line 178.
9. **Auth path N+1 / double-write** — auth plugs that do `SELECT` + `UPDATE last_used_at` synchronously per request (e.g. `Rafa.ApiKeys.validate`) burn 2 round trips on every hot call. Fix class: ETS read-through cache with TTL ~60s, async `Task.start` for the `last_used_at` write. Same shape as Hub's `Contexts.ApiTokens.Cache` (TRACKER-TRAC-170560).
10. **Canary/security tokens generated but never verified** — `Rafa.Security.Canary.generate/0` is called on every prompt build, but `Canary.check/2` is never invoked on the response path. The token becomes decoration. Fix class: wire the check into the LLM response handler (post-`chat_completion`, pre-persistence), log + alert + redact on leak.

## Security checklist (map each finding to the MyApp glosario rule it violates)

1. **Admin/LiveView routes without auth** (glosario seguridad #6) — grep `router.ex` for `live_session`/`scope "/admin"` blocks; confirm every one has `pipe_through [:browser, :require_auth]` (and ideally a permission plug). Absence = 🔴 critical.
2. **API auth without scope hierarchy** (glosario seguridad #4) — if `ApiAuth` plug only checks token validity, and the schema has a `scopes` column that's never read, scope enforcement is missing. Look for `conn.assigns.api_key.scopes` reads; if zero hits, flag it. Fix class: `RequireApiScope` plug with `read < write < admin` numeric hierarchy.
3. **Tuple-truthiness permission bypass** (glosario seguridad #1) — grep for `if Auth.require_perm(`, `if Permissions.has_perm?(`; any use where the return value isn't matched against `:ok` explicitly is a bypass (`{:error, ...}` is truthy). Real example: Hub `apps/api/lib/api/mcp/tools/update_status.ex` (TRACKER-TRAC-344183).
4. **Fail-open permission backends** (glosario seguridad #2) — backends with `try/rescue` returning `:unknown` on error are fail-open when they should be deny-capable. Deny-capable backends MUST rescue to `:deny`. Document the dispatcher contract so future backends don't repeat the bug.
5. **Permission caches without boot warmup** (glosario seguridad #3) — `:persistent_term`-backed permission maps that only fill on first request fail open after deploy. Look for a one-shot `Task` in the supervision tree calling `refresh_permissions!/0`. Absence = post-deploy window where revoked permissions are silently re-granted.
6. **Hardcoded role checks instead of codenames** (glosario seguridad #5) — grep for `user.level in [`, `user.role ==`, `user.admin?`; these bypass the central permission registry and are impossible to audit. Replace with `Permissions.has_perm?(user, "app.resource.action", resource)`.
7. **ETS tables without a GenServer owner** (glosario cache anti-patrón #4) — `:ets.new(:named_table, ...)` called from `Application.start/2` or any non-GenServer process creates an orphaned table that disappears if the owner crashes. Every named ETS table must be created inside a `GenServer.init/1` that's part of the supervision tree.
8. **Rate limiter race conditions** — `lookup` → `insert` in two steps is not atomic; concurrent requests double-count. Use `:ets.update_counter/4` with a default tuple. Also verify cleanup: `select_delete` of expired windows must run periodically, not just on read (a burst of writes from a single key can evade cleanup).
9. **Timing attacks on API key validation** — `Repo.get_by(ApiKey, key_hash: hash)` leaks whether a hash exists via response time. Fix: fetch by `prefix` (non-unique, indexed), then `Plug.Crypto.secure_compare/2` on the hash. Same shape as password `Bcrypt.verify_pass/2` + `Bcrypt.no_user_verify/0`.
10. **OutputScanner regex quality** — phone regex that matches any `\d{3}-\d{3}-\d{4}` sequence fires on version strings, IDs, partial credit cards → alert fatigue hides real PII. Either add context anchors (e.g. require "phone"/"tel" prefix within N chars) or use Luhn for credit cards and accept the noise floor on phones. Log before redacting so false positives are auditable.
11. **Body caps missing on Plug.Parsers** (glosario web-hardening) — `plug Plug.Parsers, parsers: [...]` without `length:` / `read_length:` lets a single huge body exhaust memory. Defaults: `length: 10_000_000, read_length: 1_000_000`.
12. **CSP / Permissions-Policy headers** (glosario web-hardening) — `put_secure_browser_headers` covers the basics but not CSP. Admin LiveViews serving user-generated content need an explicit CSP without `unsafe-inline`. API-only endpoints can skip.
13. **`mix_audit` in precommit** (glosario web-hardening) — check `mix.exs` aliases for `precommit`; if it doesn't include `mix audit`, CVEs in transitive deps slip through. One-line add.
14. **CSV formula injection in exports** (glosario web-hardening) — any controller/LiveView that exports user-controlled strings to CSV must prefix values starting with `=`, `+`, `-`, `@` with a single quote. Grep for `CSV.encode`, `|> Enum.map(&to_csv_row)`, `"text/csv"` responses.
15. **Audit log for sensitive actions** (glosario web-hardening) — user create/update/delete, password reset, credential toggle, status flips should all write to an audit log with actor + timestamp. Grep for `AuditLog`, `audit_log`, `log_action`; absence on admin handlers = finding.
16. **Sensitive params not filtered from logs** — check `config :phoenix, :filter_parameters` includes `:password, :token, :api_key, :secret, :key_hash`. Default Phoenix only filters `:password`.

## Process

- Read the cache module first (TTL, sweep, invalidation API) so later findings can be classified as "cached / cacheable / needs query fix".
- Quantify each finding before recommending: frequency problem (called often → cache) vs volume problem (returns many rows → limit/pagination/index). State which class each fix is.
- Every recommendation needs `path:line` evidence from the repo. No pattern asserted from memory.
- Verify query-shape claims with EXPLAIN ANALYZE where the user has DB access; on small dev tables, Seq Scan does NOT prove a missing index (planner preference) — check index *existence* in migrations and optionally `SET enable_seqscan = off`.

## References

- `references/ecto-performance-fix-impl.md` — Concrete Ecto implementer notes (gotchas, code patterns, EXPLAIN steps) from coding the fix classes identified here.
- `references/hub-performance-audit-2026-08.md` — Full Hub umbrella audit: findings, tracks created (P0-P3), validation against recent commits
- `references/rafa-audit-2026-08-10.md` — Rafa (non-umbrella) audit against MyApp glosario: 11 findings mapped to rules, track split recommendation, repo structure notes

- Sections by subsystem, each finding as a table row: file, problem, evidence `path:line`, fix class.
- A prioritized recommendation table (P0/P1/P2: impact × effort) at the end.
- Per Hub rules: NO code changes from the audit — findings go into Hub tracks first, each track gets its own scope.

8. **Validate findings against recent commits before creating tracks** — After the audit identifies fixes, run `git log --oneline -30 main` and grep for the relevant subsystems. PRs may have already shipped the exact fix. For each proposed track: `git show <commit> --stat` to see what files changed, then grep the current code to confirm the issue still exists. A finding from a code read is a snapshot in time — a merged PR between the read and the track creation invalidates it. This step prevents creating duplicate tracks for already-fixed issues.

## Pitfalls

- **Async ExUnit tests leak entries into a named ETS cache** — When tests run with `async: true`, the cache GenServer + its named ETS table outlive any single test and are shared across the module. The dangerous pattern: a test enables cache with `Application.put_env(:contexts, Contexts.Cache, enabled: true)` and its `on_exit` only restores the env — **it must also clear the table** (`Contexts.Cache.clear()`), otherwise entries populated by earlier tests make later cache tests read *stale* values. Signature symptom: a cache-coalescing test asserting `count == 1` gets `left: 0` because a prior test already warmed the same key (`{:board_snapshot_multi, ...}`), so the query never runs. Intermittent on CI, green in isolation. Fix class: every test that flips `enabled: true` adds `Contexts.Cache.clear()` to its `on_exit`.
- **Reproduce a flaky CI test before any code change** — CI logs print the seed: `gh run view <run> --log 2>&1 | grep "Running ExUnit with seed"`. Reproduce locally with `mix test <file> --seed <seed>`. Then run the SAME command on `main` before committing a fix: if the failure reproduces there too, it is pre-existing (not the PR under review) and the fix is a test-isolation fix, not a logic fix. Real case: `board_snapshot_multi` cache test failed identically on `main` and the PR branch with seed 102427 (`185/186` → `186/186` after clearing ETS in `on_exit`).
- **Don't flag deferred scope as defects** — check linked tracks/docs for "deferred to future track" notes before calling something a bug.
- **Snapshots cached in ETS contain structs with preloads** — serializing rich Ecto structs into ETS can bloat or fail; cache projections, preload outside the cache if needed.
- **Detail views vs board views share loader functions** — an optimization for the detail path must not starve the board path (boards genuinely need the full type listing).
