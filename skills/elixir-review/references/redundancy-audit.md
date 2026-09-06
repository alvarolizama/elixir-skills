# Redundancy Audit

Find duplicated and reusable Elixir/Phoenix code. Works read-only; pairs
well with a follow-up consolidation plan.

## Why not clone detectors

`jscpd` has NO Elixir parser — running it against `.ex` files silently
analyzes 0 files and reports "No duplicates found" with `Files analyzed: 0`
in the stats table. That is a false negative, not a clean codebase. If you
run it anyway, CHECK the stats table before trusting the result. The
effective method is manual pattern-hunting with grep + diff.

## Workflow

1. **Size the codebase**:
   ```bash
   find lib -name "*.ex" | sed 's|/[^/]*$||' | sort | uniq -c | sort -rn
   ```
   Directories with many same-sized sibling files (LiveViews per type,
   controllers per resource, schemas per table) are prime duplication
   candidates.

2. **Spot structurally similar siblings** — files of near-identical line
   count in the same directory (e.g. 9 LiveViews at 300-340 lines each).
   Diff two of them:
   ```bash
   diff <(sed -n '110,230p' a.ex) <(sed -n '110,230p' b.ex)
   ```
   Few differing lines = clone.

3. **Grep for copy-paste fingerprints** — private helpers and idiomatic
   blocks that tend to travel together:
   - `defp format_errors` / `traverse_errors` — every hand-written API
     controller copies the changeset error formatter
   - `defp titleize` / `def titleize`
   - `get_or_create` / `get_or_insert`
   - Scheduled-job entry points — jobs copy the same preamble (default-context resolution, per-workspace iteration)
   - `on_conflict` — idempotent insert patterns get cloned with the
     surrounding boilerplate
   - Domain-specific blocks: try/rescue wrappers, `if context do ... else
     404` guards. Grep a distinctive inner call and count files — N files
     with the same N-line block = extraction candidate.

4. **Check for a partially-adopted shared module** — the codebase often
   ALREADY started consolidating (a shared helper, a `__using__` macro)
   and only some callers adopted it:
   ```bash
   grep -c "SharedModule.handle_event" lib/**/*_live.ex
   ```
   `grep -c` per caller reveals adopters vs laggards. The finding is then
   "finish the adoption", not "invent an abstraction".

5. **Verify dead code before claiming it** — a public `def` with no
   callers needs a repo-wide grep of the function name (all arities)
   across `lib/`, `test/`, and templates before being declared unused:
   ```bash
   grep -rn "fn_name" lib/ test/ | grep -v "def fn_name"
   ```

## Report format

Per finding:

- **What** — one line
- **Where** — file:line per copy
- **Evidence** — diff result or identical snippet
- **Suggestion** — extract to X / delegate to existing Y
- **Impact** — high/medium/low + estimated LOC saved

End with a quick-wins table ordered by impact/effort. Only verified
file:line findings — no guesses.

## Pitfalls

- **Prefer "finish existing adoption" over new abstractions** —
  introducing a second shared module next to a half-adopted one makes the
  mess worse.
- **Count adoption, not just duplication** — `grep -c` per sibling file
  tells you whether the pattern is "never extracted" or "half the callers
  still copy".
- **Umbrella apps**: run per-app (`apps/*/lib`), not just the root
  `lib/`.
- Don't propose extracting a helper used only twice unless a third
  consumer is obviously coming (the get-or-create factory pays off when
  more materializers/agents are on the roadmap).
- **Hidden auto-imports cause false duplication reports** — check
  `my_app_web.ex` first (the `live_view` macro imports helpers into every
  LiveView). A function called in 11 files but defined in one
  auto-imported module is NOT duplicated. Only report duplication when
  the same `defp` is DEFINED (not just called) in 2+ files.