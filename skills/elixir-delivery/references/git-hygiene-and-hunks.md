# Git Hygiene and Hunks — splitting, races, surgery, excision, cleanup

Symptom: history that bundles unrelated tasks, races from parallel agents,
or a feature that must come back out of a shared branch. Mechanism: git
records what is staged, not what you meant; every pattern below controls the
staging surface explicitly.

## Commit hygiene rules

1. **Commit before big refactors.** Isolate WIP so the refactor diff stands
   alone; mixed WIP + refactor makes bisection impossible.
2. **Never sweep unrelated WIP into feature commits.** Split at hunk level
   (below) instead of mixing or discarding.
3. **Stage explicit paths, never `git add -A` in a dirty repo** — it bundles
   pre-existing dirty files into your commit. After every commit,
   `git show --stat HEAD` and confirm the file list matches your scope.
4. Verify with `git log --oneline -5` (atomic, well-named) and
   `git diff HEAD~1 --stat` (no swept files).

## Splitting hunks with `git add -p` (interactive)

```bash
git diff <file> | grep -n "^@@"             # count hunks, map each to a concern
printf 'y\ny\nn\nn\n' | git add -p <file>   # answer per hunk, in order
git diff --cached <file> | grep -c <marker> # staged set must contain ONLY your markers
git commit -m "feat: your change"
git add <file> && git commit -m "feat: the WIP, now complete"
```

Keys: `y` stage / `n` skip / `q` quit / `a` stage rest / `d` skip rest /
`s` split hunk / `e` edit hunk. Only safe when concerns sit in disjoint
hunks; a single hunk mixing both → one commit with a note (or `git add -e`).

## Programmatic split (no TTY — agents, CI)

`git add -p` / `-e` require a TTY; scripted contexts hang or silently stage
nothing. When the two concerns live in NON-CONTIGUOUS regions of a file:

1. Save the full working file to `/tmp/<name>.full.ext`.
2. Split the diff at the first hunk header whose body contains a unique
   marker of concern B; above = concern A, below = concern B. The lower half
   needs a synthetic `diff --git`/`---`/`+++` header prepended.
3. `git checkout HEAD -- <file>`, apply patch A, verify `git diff --stat`,
   commit.
4. Restore the full file (`cp /tmp/<name>.full.ext <file>`) or apply patch B,
   commit concern B.

Interleaved concerns in the same hunk → neither approach is safe; single
commit with a note.

## Parallel subagent git races

Symptoms: one commit mixing 3+ unrelated tasks; commit message naming one
task while touching another's files; `git diff HEAD~1` showing unrecognized
changes.

Recovery:

```bash
git reset --soft <last-good-commit>    # or origin/main; keeps changes staged
git add -p <file>                      # per task: select its hunks
git commit -m "feat: task 1"
git add -p <file>
git commit -m "feat: task 2"
```

Prevention: dispatch committing tasks serially, or have subagents return
diffs/changed-file lists and the parent commits after verifying each.

Parent-side bundling: `git add -A <dir>` sweeps the user's unrelated WIP.
Recovery: `git reset --soft HEAD~1`,
`git restore --staged path/to/not-mine.ex`, re-commit the original message.

## Selective feature revert (blade, not `git revert`)

Blind `git revert <merge>` on top of later commits creates confusing inverse
chains. Do file-level surgery:

1. Inventory: `git log --oneline <last-good>..HEAD` +
   `git diff <last-good> HEAD --stat`. Classify every file: feature-only →
   `git rm`; feature-touched shared → restore from last-good; unrelated →
   keep.
2. Restore: `git show <last-good>:path/to/file.ex > path/to/file.ex`.
3. Byte-exact verify per file, in one loop before compiling:
   `git show <last-good>:path/to/file.ex | diff -q - path/to/file.ex`.
4. Gitignored companions (`.env`, credentials, generated code) — grep and
   remove manually.
5. ONE revert commit (`revert: remove <feature>`); salvage in separate
   commits.
6. Shared vocabulary that predates the feature is NOT collateral — revert
   the feature, not the words.

## Full feature excision ("remove everything related to X")

A revert restores files; an excision sweeps layers git history doesn't group
by commit:

- Supervision tree (`application.ex`): registries, dynamic supervisors,
  GenServers — orphans crash at BOOT though compile passes.
- Root layout mounts + their `attr`s — grep `attr_name=` across ALL
  templates first; same-name attrs passed to local components are different
  concepts and must survive.
- In-app docs/guide pages and API reference tables (endpoints the router no
  longer has).
- Static assets referenced only by the feature.
- README bullets, screenshot table cells, config tables (check HTML row
  balance after removing cells).
- DB: `mix ecto.gen.migration drop_<table>` with
  `drop_if_exists table(:<table>)` in dev AND test; verify `\\dt <table>*`
  in psql — the test DB can show the version while the table still exists.
- Gettext: `mix gettext.extract && mix gettext.merge priv/gettext` AFTER
  deletions; grep affected msgids for `fuzzy`, fix `msgstr` by hand.

Final verification: live server boot + curl the main pages — compile-clean
does not prove boot-clean.

## Worktree cleanup ("discard all pending changes")

```bash
git status --short        # show what's pending first
git checkout .            # revert tracked modifications
git clean -nfd            # dry-run: list what would be removed
git clean -fd             # remove untracked files/dirs
git status --short        # verify clean
```

- `git checkout .` alone leaves untracked files behind — always run both.
- Irreversible: flag what's at stake before executing and confirm scope
  (the user may mean several sibling repos, not just cwd).

## Verification

- `git log --oneline -5`: atomic commits, conventional messages.
- `git show --stat HEAD`: file list == intended scope.
- Restored files pass the byte-exact diff check.
- `mix compile --warnings-as-errors` + full suite after surgery; failures
  proven preexisting.
- Excisions: server boots and main pages respond.
