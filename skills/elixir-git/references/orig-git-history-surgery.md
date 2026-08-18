---
name: git-history-surgery
description: "Rescue and reshape git state when commits went wrong: selective feature reverts that keep salvageable work, untangling subagent commits that bundled multiple tasks, and restoring file sets from known-good commits with byte-exact verification. Also covers full worktree cleanup (git checkout . + git clean -fd) when Álvaro says 'limpia el worktree' / 'descarta los cambios'."
version: 1.0.0
author: Álvaro Lizama
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [git, revert, history, recovery, subagent, workflow]
    related_skills: [simplify-code, requesting-code-review]
---

# Git History Surgery

Reshaping git state when the happy path (revert the merge, reset --hard) would
destroy work that should survive. Two recurring situations:

1. **Selective feature revert** — a merged feature must be ripped out, but
   unrelated commits on top and salvageable parts must survive.
2. **Bundled subagent commits** — parallel subagents raced on the git index
   and packed several tasks into single commits that must be split.

## Situation 1: Selective feature revert

Do NOT `git revert <merge>` blindly when later commits exist on top — it
creates a confusing inverse chain and can resurrect files you later deleted.
Do file-level surgery instead:

### Step 1 — Inventory the blast radius

```bash
git log --oneline <last-good-commit>..HEAD
git diff <last-good-commit> HEAD --stat
```

Classify every changed file into three buckets:

- **Feature-only files** (new modules, new tests) → `git rm`
- **Feature-touched shared files** (existing modules the feature modified) →
  restore from the last good commit
- **Unrelated changes** (other features, fixes) → keep untouched

### Step 2 — Restore shared files from the known-good commit

Restore content directly from the commit — do NOT revert commits:

```bash
git show <last-good>:path/to/file.ex > path/to/file.ex
```

### Step 3 — Verify byte-exact restore, per file

```bash
git show <last-good>:path/to/file.ex | diff -q - path/to/file.ex && echo "OK: path/to/file.ex"
```

Run this across the whole restored set in one loop before compiling. A
partially-reverted file is worse than none — it looks done but isn't.

### Step 4 — Check gitignored companions

Feature config often lives in files git doesn't track: `.env`, credentials,
generated code. `git show` won't restore those. Grep for the feature's env
vars and remove them manually:

```bash
grep -n "FEATURE_VAR" .env
sed -i '' '/^FEATURE_VAR=/d' .env
```

### Step 5 — Parallelize with subagents for large file sets

Give each subagent a **disjoint bucket** (never two agents restoring the same
file), each verifies its own bucket with the diff check, then the parent runs
compile + the full test suite before committing. This is the same disjoint-
scope rule as any subagent fan-out, applied to restoration.

### Step 6 — Commit as ONE clean revert, keep salvage separate

One commit for the revert (`revert: remove <feature>` — list what was deleted
and what was restored), separate commits for any feature kept or added on
top. Future archaeology will thank you.

### Step 7 — Scan docs for shared vocabulary before finishing

A name that predates the feature is NOT collateral. Example: a "copilot chat"
widget existed before the "copilot agent" feature — reverting the agent must
not touch the widget's docs or README mentions. Revert the feature, not the
vocabulary.

### Step 8 — Full feature excision (when the user says "borra TODO lo de X")

A revert restores files; an **excision** removes the feature from every layer.
The file list from Step 1 is never complete — features leak into layers git
history doesn't group by commit. Sweep these spots explicitly:

- **Supervision tree** — `application.ex` / equivalent: registries, dynamic
  supervisors, GenServers the feature started. Orphaned entries crash the app
  at boot even though compile passes.
- **Layout/root mounts** — global widgets mount in the root layout
  (`<.live_component>` in `layouts.ex`), plus their `attr` declarations.
  Before deleting an attr, grep `attr_name=` across ALL templates — same-name
  attrs passed to LOCAL components (e.g. `page_type={@page_type}` to a
  `<.meta_fields>`) are a different concept and must survive.
- **In-app documentation** — docs/guide pages INSIDE the app (e.g. a DocsLive
  "guides" section) and API reference tables. Also check for documented
  endpoints that no longer exist in the router — docs drift is common and the
  excision is the moment to clean it.
- **Static assets** — screenshots, icons, example files under `docs/` or
  `priv/static` referenced only by the removed feature.
- **README + external docs** — feature bullets, screenshot table cells,
  config tables. When removing a screenshot cell from an HTML table, check
  the row still balances (4 cells → 3 is fine; 2 → 1 may need colspan).
- **DB tables** — `mix ecto.gen.migration drop_<table>` with
  `drop_if_exists table(:<table>)` (indexes die with the table). Run it in
  dev AND test DBs. Beware: if subagents generated the migration, the test
  DB may show the version in `schema_migrations` while the table still
  exists (something re-created it after a partial migrate) — verify with
  `\dt <table>*` in psql and drop manually if needed.
- **Gettext catalogs** — `mix gettext.extract && mix gettext.merge
  priv/gettext` AFTER the code deletions land (extract needs compile to
  pass). Fuzzy matches can mis-translate strings that reuse words from
  deleted ones — grep the affected msgids for `fuzzy` and fix `msgstr` by
  hand.
- **Skills/references that document the feature** — SKILL.md files and
  reference docs that teach the deleted code path. Mark them REMOVED with
  the date/commit; don't leave them teaching ghosts.

Then verify with a live server boot + curl the main pages + any MCP/API
endpoint — compile-clean does not prove boot-clean (supervision orphans only
crash at boot).

## Situation 2: Subagents bundled tasks into single commits

When parallel subagents commit to the same repo, they race on the git index
and bundle multiple tasks into single commits. Recovery:

```bash
git reset --soft origin/main   # keeps all changes staged, drops the bad commits
```

Then re-commit each task individually with its own message.

**Prevention beats recovery:**

- Dispatch committing subagents SERIALLY, or
- Have subagents report changes without committing; the parent commits after
  verifying each subagent's work (git diff + compile + tests per wave).

**The parent can bundle too (2026-07-27):** `git add -A <dir>` (or
`git add -A lib test`) in a repo with PRE-EXISTING dirty files sweeps the
user's unrelated work-in-progress into your feature commit — same bundling
bug, no subagent involved. Recovery is one step:

```bash
git reset --soft HEAD~1
git restore --staged path/to/not-mine-1.ex path/to/not-mine-2.ex
git commit -m "<original message>"   # now contains only your files
```

Prevention: when `git status` shows modifications you didn't make, stage
explicit file paths only — never `-A`. And `git show --stat HEAD` after every
commit to confirm the file list matches your scope before moving on.

**Mixed concerns in the SAME file (2026-07-27):** when pre-existing WIP and
your changes share one file (e.g. you add a banner to `layouts.ex` that
already holds someone's uncommitted topbar widget), file-level staging can't
separate them — split at the HUNK level instead:

```bash
git add <all-your-other-files>           # explicit paths, never -A
git diff <file> | grep -n "^@@"          # count hunks, map each to a concern
printf 'y\ny\nn\nn\n' | git add -p <file>  # answer per hunk, in order
git diff --cached <file> | grep -c <marker>  # prove staged set is pure (0 for WIP marker)
git commit -m "feat: <your change>"
git add <file> && git commit -m "feat: <the WIP, now complete>"  # separate commit
```

Rules: `git add -p` reads one answer per hunk in order — count the `@@`
lines first and verify the staged diff contains your markers and ZERO of the
WIP's before committing. Only safe when the two concerns are in disjoint
hunks; if a single hunk mixes both, commit the file once and say so in the
message (or hand-split with `git add -e`).

### `git add -p` is interactive — use a scriptable alternative

`git add -p` and `git add -e` both require a TTY. When the agent runs from
`execute_code`, a delegated subagent, a CI pipeline, or any non-interactive
context, you cannot send the `y/n` answers. Symptoms:

- The command hangs waiting for input that never arrives.
- It silently stages nothing and exits with no error — the "commit" then
  contains everything (the original bundling problem) or nothing.

**Programmable equivalent (MyApp 2026-08-01):** when you can split a
single file's working-tree changes into two commits because the two concerns
live in **non-contiguous regions** of the file (concern A in lines 1-300,
concern B in lines 700+, with no overlap), do it by hand rather than fight
with `git add -p`:

1. Save the current full file to `/tmp/<name>.full.ext`.
2. `git diff <file>` to a string, then split the diff **at the first hunk
   header `@@ ... @@` whose body contains a unique marker from concern B**.
   Everything above that line = concern A; below = concern B.
3. Write each half to `/tmp/<name>.<concern>.patch`. The "above" half keeps
   the `diff --git` / `index` / `---` / `+++` headers from the original
   diff. The "below" half needs a synthetic header prepended (it lost the
   original header when you split mid-file).
4. `git checkout HEAD -- <file>` to revert to the known-good baseline.
5. Apply the concern-A patch with `git apply /tmp/<name>.<concern-A>.patch`,
   verify the diff is exactly what you expect (`git diff --stat`), commit.
6. Re-write the working file to the saved full version (`cp
   /tmp/<name>.full.ext <file>`) — OR apply the concern-B patch on top of
   the just-committed concern-A state — then commit concern B.

When to use this vs `git add -p`:

| Situation | Use |
|---|---|
| Two concerns in non-contiguous hunks, no TTY / scripted context | Programmable split (above) |
| Two concerns in non-contiguous hunks, interactive terminal available | `git add -p` (faster, less ceremony) |
| Two concerns INTERLEAVED in the same hunk (mixed `-` and `+` lines) | Single commit with a note; neither approach is safe |

The non-contiguity check matters: if concerns are interleaved (e.g. a UI
rename that touches every other line), even the programmatic split produces
two broken files. The save-and-restore step (step 6 first variant) is the
safe fallback.

## Worktree Cleanup — "limpia el worktree" / "descarta los cambios"

When Álvaro asks to discard pending changes (`haz checkout para limpiar`,
`limpia el worktree`, `descarta todo lo pendiente sin commitear`), **he means
a full clean**: tracked changes reverted AND untracked files removed.

**Pattern (always run both):**
```bash
git status --short            # show what's pending first
git checkout .                # revert tracked modifications
git clean -nfd                # dry-run: list untracked that would be removed
git clean -fd                 # remove untracked files/dirs
git status --short            # verify clean
```

**Pitfalls:**
- `git checkout .` alone leaves untracked files behind (new migrations,
  new tests, new plugs). Álvaro will follow up with "descarta todo" — do the
  full clean up front when he says "todo lo pendiente".
- Worktree cleanup is **irreversible**: uncommitted work is lost forever.
  Before executing, flag what's at stake (e.g. "uncommitted security hardening
  in my_app_gateway would be lost") and confirm the repo + scope with `clarify`.
- Álvaro keeps several repos with WIP (MyApp, my_app_gateway, doquant, slide_forgery).
  "Limpia el worktree" may mean **all of them**, not just the current cwd —
  check git status in sibling repos or ask which ones.
- `git clean` is flagged by Hermes smart approval — expected, proceed.

## Verification checklist (both situations)

- [ ] `git status` clean except intended changes
- [ ] Every restored file passes the byte-exact `git show | diff -q` check
- [ ] Gitignored companions (`.env`, generated files) cleaned manually
- [ ] `mix compile --warnings-as-errors` (or project equivalent) passes
- [ ] Full test suite passes; any failures confirmed pre-existing (stash and
      re-run on the base commit to prove it)
- [ ] Revert commit is ONE commit; salvage is separate commits
- [ ] Docs/README scanned for feature vocabulary that predates the feature
