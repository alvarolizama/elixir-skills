# Plan-Driven Subagent Waves — pnpm/TypeScript playbook

Variant of `plan-driven-waves.md` for pnpm monorepos with TypeScript, Vite,
and vitest. Distilled from running the open-delta rename + widget library
plan (4 phases, ~49 tasks) in July 2026.

## Before wave 1: clean slate

1. `git status --short` + `git diff --stat` — commit the dirty tree as
   atomic commits BEFORE dispatching anything. Subagents starting on a dirty
   tree bundle pre-existing changes into their commits.
2. Baseline check: `pnpm typecheck` + `pnpm test` + `pnpm build` + `pnpm check`
   all green. If typecheck fails due to `@types/react` version mismatch
   (common after `pnpm install` regenerates the lockfile), run
   `rm -rf node_modules packages/*/node_modules apps/*/node_modules && pnpm install`
   to get a clean resolution.

## Verify the plan against the repo — plans lie

Same principles as the Elixir playbook:
- Line numbers drift — never quote exact lines to subagents; give them
  function/symbol names and let them search.
- Some tasks are already done — grep before dispatching.
- Record dropped/modified tasks and why.

## pnpm-specific baseline traps

- **`pnpm install` regenerates the lockfile** when package names change (e.g.
  rename). The new lockfile can hoist different `@types/react` versions than
  the original, causing 100+ phantom TS2786 errors ("cannot be used as JSX
  component"). Fix: `rm -rf node_modules` + `pnpm install` for a clean tree.
- **Stale `pnpm-lock.yaml`** can cause `ERR_PNPM_OUTDATED_LOCKFILE` with
  `--frozen-lockfile` in CI. After renaming package names, you MUST run
  `pnpm install` (not `--frozen-lockfile`) to regenerate.
- **Turbo cache** can mask failures — `pnpm build` says "FULL TURBO" and
  exits 0 even if the build would fail on a clean run. Use
  `turbo run build --force` to bypass cache when verifying.

## Batching: disjoint file scope per wave

Same rule: each agent in a wave gets explicit file ownership, no two agents
share a file in the same wave.

For mechanical renames across a monorepo (e.g. open-slide → open-delta),
consider doing the deterministic part (find-replace across `packages/core/src/`)
with a Python `execute_code` script instead of dispatching subagents. This is
faster, guaranteed consistent, and avoids the "two agents edit the same file"
problem entirely. Reserve subagent fan-out for files that need judgment
(web app content, docs, skills — where you need to understand context to
know what to change vs. what to leave alone).

## Between waves

1. `git status --short` — see what each agent actually left.
2. `pnpm typecheck` + `pnpm test` + `pnpm check` (biome) + `pnpm build`.
3. One atomic commit per wave — the parent commits, never the agents.
4. If an agent's work is missing: check filesystem mtimes before re-dispatching.
   If files exist but report never came: verify and integrate yourself.
5. **Biome check:** run `pnpm check:fix` first for auto-fixable issues, then
   `pnpm check` to see remaining manual fixes. See the `react-ssr-component-testing`
   skill for biome lint patterns specific to React widget code.

## TypeScript/pnpm verification commands

```bash
# Full verification suite (run between waves)
pnpm typecheck        # tsc --noEmit across workspace
pnpm test             # vitest run
pnpm check            # biome check . (format + lint)
pnpm check:fix        # biome --write (auto-fix what it can)
pnpm build            # turbo run build (may cache — use --force to bypass)

# Filter to one package
pnpm core typecheck   # pnpm --filter @open-delta/core typecheck
pnpm core test

# Find remaining old references after a rename
grep -rn "open-slide" . --include=*.ts --include=*.tsx --include=*.css \
  --include=*.md --include=*.mdx --include=*.json --include=*.mjs \
  | grep -v node_modules | grep -v .git | grep -v CHANGELOG | grep -v pnpm-lock
```

## Subagent timeout handling (pnpm variant)

Two distinct timeout patterns — distinguish by checking the filesystem:

### Pattern A: timeout = work complete, report missing

A timed-out subagent (600s) often completed its file writes but didn't
deliver its summary. Check `git status --short` and `grep -rl` for the
patterns the subagent was supposed to change. If the files are there and
correct, verify with typecheck + tests and commit — don't re-dispatch.

### Pattern B: timeout = stuck subagent, zero work done

If `status=timeout` with only 2-3 API calls AND `git status --short` shows
NO new/modified files in the target directory, the subagent got stuck early
on a slow API call — it never did the work. In this case you MUST
re-dispatch. Use a tighter prompt: "WORK FAST — do not over-read files,
just create the files directly. Do not search for existing patterns first."

**How to tell the difference:** check `ls -la <target-directory>/` and
`git status --short | grep <target-directory>`. If zero files: Pattern B
(re-dispatch). If files present: Pattern A (verify and integrate).

## Post-rename asset check

After a rename wave where code references to assets (`.png`, `.webp`, `.svg`)
were changed, subagents rename the references in code but forget to `mv`
the actual files. The build breaks with:

```
Module not found: Can't resolve '../../public/assets/screenshots/open-delta-cover.webp'
```

Fix: after each rename wave, `grep` for renamed asset references and `mv`
the physical files:

```bash
# Find renamed asset references that don't have matching physical files
grep -rn "open-delta\." apps/web/ --include="*.tsx" --include="*.ts" | grep -v node_modules
# Then check if the physical file exists
ls apps/web/public/open-delta.png 2>/dev/null || echo "MISSING — rename from old name"
mv apps/web/public/open-slide.png apps/web/public/open-delta.png
```

## Post-rename default-value check

A mechanical rename script replaces identifiers and string literals across
files it processes, but hardcoded default values in **separate code paths**
are easy to miss. Example: renaming `slidesDir` → `contentDir` in `config.ts`
succeeds, but the Vite plugin file (`open-delta-plugin.ts`) contains
`config.contentDir ?? 'slides'` — the field name was updated by the rename
script, but the string literal default `'slides'` was NOT in the replacement
list (it wasn't `slidesDir`, it was just `'slides'` as a raw string).

**Symptom:** the dev server starts successfully but finds zero content
directories — slides don't appear in the home page list, and navigating
to `/s/<id>` returns "Slide not found." No error is thrown; the fallback
default silently points to a non-existent `slides/` directory.

**Fix:** after a rename that changes a config field AND its semantic default,
grep for the old default string literal in all source files:

```bash
grep -rn "?? 'slides'" packages/core/src/  # Find the stale default
# Fix: config.contentDir ?? 'content'
```

**General rule:** a rename script should include the old DEFAULT VALUE as a
replacement target (`'slides'` → `'content'`), not just the field name
(`slidesDir` → `contentDir`). If the default value is a common word that
could appear in unrelated contexts, grep after the script runs to verify
only the intended occurrences were changed.
