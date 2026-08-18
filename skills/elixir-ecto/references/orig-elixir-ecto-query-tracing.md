---
name: elixir-ecto-query-tracing
description: "Use when tracing an observed SQL query to its Ecto source."
tags: [elixir, ecto, performance, database, debugging, phoenix]
metadata:
  hermes:
    tags: [elixir, ecto, performance, database, debugging, phoenix]
---

# Tracing an observed SQL query to its Ecto call site

## Trigger

You have a raw SQL query from an observability tool (RDS Performance Insights, `pg_stat_statements`, APM, slow-query log) and the question "who in the codebase executes this?" The query text alone does not name the module — you must fingerprint it and eliminate candidates.

## Procedure

1. **Fingerprint the query** — extract the discriminating features before searching:
   - `ORDER BY` clause verbatim (column set + directions, e.g. `position, pinned DESC, inserted_at DESC`) — the single most discriminating feature; search for `desc: :pinned` / `order_by.*position.*pinned` first.
   - `WHERE` shape: `field = ANY($n)` means Ecto `field in ^list`; `field = $n` means scalar `field: ^value`. This alone often eliminates lookalike candidates.
   - `LIMIT` / `OFFSET` presence or absence — a candidate that always applies `limit/2` cannot be the source of an unbounded query.
   - Table + selected columns: a full column list with no aggregates suggests a schema `Repo.all(query)` (whole struct), not a `select/3` projection.
2. **Search the codebase** with the fingerprint (`search_files`, regex on the ORDER BY first, then the WHERE predicates). Expect multiple candidates sharing a table — batch the searches.
3. **Check git history for prior partial fixes** (`git log --since="<recent>" --oneline -- <candidate files>`) before proposing anything. If a fix already shipped for this query, the live problem is usually that the fix was *partial* — e.g. a cached wrapper was added but the unbounded query still runs on every cache miss, or a paginated function was created but never wired into the hot path. State what the prior commit did and did NOT change; that gap is often the real root cause.
3. **Eliminate candidates with evidence, not vibes** — for each candidate, check against the fingerprint:
   - arity/shape of the filter helper (`filter_by_type(query, type), do: where(query, type: ^type)` is scalar `=` — cannot produce `= ANY`).
   - hard `limit` applied unconditionally → eliminated if the observed query has no LIMIT.
   - different preload set or join shape → eliminated if columns don't match.
4. **Name the function and ALL its callers** (`search_files` for the function name across apps). In a LiveView umbrella, distinguish callers that go through a cache/snapshot layer from those that hit the DB directly — the direct ones on hot paths are the resource problem.
5. **Quantify before fixing**: get avg execution time × call count from the monitoring tool. A 600ms query called 15k times is a different fix (frequency/caching) than a 600ms query called 10 times (volume/pagination). Frequency problem → cache the result; volume problem → LIMIT/pagination/index. State which class of fix you're proposing.
6. **Verify the fix with `EXPLAIN (ANALYZE)` on the real query text** — see `references/explain-analyze-verification.md` for the planner-preference pitfall (small tables produce Seq Scan even with a perfect index; that does NOT mean the index is wrong).

## Pitfalls

- **Multiple functions share the same ORDER BY** — ORDER BY match is necessary, not sufficient. Cross-check `= ANY` vs scalar and LIMIT before naming a culprit.
- **A wrapper function delegates to another** — the public function you found may be a thin wrapper; read its body to see what it actually calls, and count callers of the inner one too.
- **`EXPLAIN` shows Seq Scan in dev** — on small dev tables the planner prefers Seq Scan even when a perfect index exists. Confirm index *existence* and force with `SET enable_seqscan = off` to see which index the planner prefers at scale; don't conclude the index is unused in prod.
- **Repo.query returns `{:ok, %Postgrex.Result{}}` in scripts** — pattern-match `{:ok, %{rows: rows}}`, not `%{rows: rows}`.
- **Verify by behavior, not just suite green** — after changing data-access code, count actual queries (telemetry) or run a fresh ad-hoc script against a dev server. See the sibling skill `phoenix-liveview-adhoc-verification` for the harness pattern.

## Support files

- `references/explain-analyze-verification.md` — EXPLAIN/ANALYZE recipes for Ecto-generated queries: planner preference on small tables, forcing index usage, reading the plan, index-existence checks.
- `references/ecto-query-construction-gotchas.md` — pitfalls while *authoring* Ecto queries (not tracing): `fragment()` + `order_by` "undefined variable w" (fix: split into two chained `order_by`), `Repo.update_all` needs a `from` query not `where:` kwargs, replicating an in-Elixir sort in a new pagination function + parity test, JSONB priority CASE cost, OFFSET/LIMIT page overlap without a unique tiebreaker (+ ad-hoc proof pattern), `fragment(^built_string)` compile error (fix: literal fragments composed with `dynamic/2`), correlated scalar subquery + COALESCE as a single-query fallback (and why LEFT JOIN LATERAL with `ON is_nil(...)` fails silently), materialized views invisible in Ecto Sandbox, `type(^dt, :utc_datetime)` casts for timestamp fragments, `= ANY(?)` vs `IN ?` inside fragments, reusing fragment SQL via module constants.
