# N+1 & Preload Rules

The recurring shapes, the rule for each, and the false positives that waste
time. Grep → verify by reading the enclosing function → fix → batch.

## Rules

1. **Re-preload cascade** — the outer query preloads an association, but a
   helper called per item preloads it again (1 + N queries). Fix: make the
   helper pure over data it doesn't own (best — pure helpers cannot
   re-query), or skip the inner preload when already loaded
   (`Ecto.assoc_loaded?/2`), or move the preload into the outer query.
2. **Per-item aggregate in a loop** — one SUM/COUNT per row of a page. Fix:
   one batched aggregate `WHERE id IN (^ids)` grouped by id → map → the pure
   per-row function takes the map.
3. **Per-parent child query in a loop** — one query per parent. Fix: a
   single preload on the parent query; nested preloads for multi-level
   chains.
4. **`Repo.all` + post-processing that queries** — mapping results through
   `Repo.get` or context calls. Fix: preload or join on the base query so
   downstream code (templates included) never touches unloaded associations.
5. **Same helper called twice per request** — compute once, pass the value
   down; memoize at the controller entry when the call chain is deep.
6. **Defensively preloading helpers** — an internal guard
   (`Ecto.assoc_loaded?/2` before `Repo.preload`) makes a helper safe to
   call on already-preloaded structs without a second SELECT.
7. **Missing template preload** — a template rendering
   `nested.assoc.field` needs the matching preload on the feeding query.
   Grep each preload and verify templates only touch loaded fields.

## Hot-path signal: `force: true`

`Repo.preload(struct, assoc, force: true)` ignores already-loaded data and
issues a new SELECT on every call. On the hot path (e.g. right after an auth
plug already preloaded the same assoc) this is the highest-severity finding.
Fix: drop `force: true`, or guard with `Ecto.assoc_loaded?/2`.

## Detection recipe

```bash
# Enum.map/reduce in LiveView data loaders
grep -n 'Enum\.map\|Enum\.reduce' lib/<app>_web/live/*.ex

# Context helpers issuing preloads (or forcing them)
grep -n 'Repo\.preload\|force: true' lib/<app>/*.ex

# Context/helper calls inside per-item loops — read each one
grep -n -A2 'Enum\.map' lib/<app>_web/live/*.ex | grep '<app>\.'

# Auth plugs that preload (they define what is ALREADY loaded downstream)
grep -rn 'preload' lib/<app>_web/plugs
```

Each match is a CANDIDATE; verify by reading the enclosing function.

## Common false positives

- Mapping over a list to build plain structs or transform strings — pure
  data, no DB.
- A per-item call that reads ETS/cache instead of the DB — at most a
  one-time cold-start query per period, not a steady-state N+1. Read the
  manager; don't escalate.
- **`Repo.preload(struct, :assoc)` WITHOUT `force: true` is a no-op when the
  association is already loaded** — Ecto resolves it in memory, zero
  queries. Before reporting any N+1, trace whether the outer query already
  preloaded it.

## Verification

- Read the helper body and the outer query: count queries by construction
  (1 outer + N inner = N+1; with the fix = 1).
- Telemetry/`EXPLAIN` on the rendered page: no per-item SELECTs in the log.
- Add a query-count regression test when the pattern recurs.
