# Honest Failure Attribution — Baseline Worktree Diff

When you fix flaky/broken tests (or any bug) on a repo that ALREADY has failing
tests, the user will ask "tests resueltos?" — and the honest answer requires
separating **failures you introduced** from **failures that were already there**.
Never claim "all green" by only re-running the suite on your branch; the count
alone proves nothing if the baseline was already red.

## The technique

1. Identify the last commit BEFORE your changes (`git log --oneline`).
2. Create a throwaway worktree at that baseline and run the SAME suite there:

```bash
git worktree add -q /tmp/repo-baseline <baseline_sha>
cd /tmp/repo-baseline && mix deps.get -q   # or pnpm install / pip install
MIX_ENV=test mix test 2>&1 | grep -E "^\s+[0-9]+\) test " | sed 's/^[0-9 ]*) //' | sort > /tmp/base.txt
```

3. Run the suite on your working branch, same extraction:

```bash
cd /path/to/repo
mix test 2>&1 | grep -E "^\s+[0-9]+\) test " | sed 's/^[0-9 ]*) //' | sort > /tmp/mine.txt
```

4. Diff the two name lists:

```bash
comm -23 /tmp/mine.txt /tmp/base.txt   # failures ONLY in mine  → these are YOURS
comm -13 /tmp/mine.txt /tmp/base.txt   # failures ONLY in base  → you FIXED these
```

Empty first list = zero regressions. The second list is credit you can claim.

## Why the extraction matters

- Grep the `N) test <name>` block headers, NOT the `file.exs:LINE` stack lines —
  stack lines shift as you edit, so line-number diffs produce phantom "new"
  failures. Test NAMES are stable across your edits.
- `sed 's/^[0-9 ]*) //'` strips the leading number (which is just an ordering
  index that changes with seed) so `sort` + `comm` line up correctly.
- Flaky suites vary run-to-run; if the baseline count wobbles, run it twice and
  intersect before diffing, or compare names not counts.

## Cleanup

```bash
git worktree remove --force /tmp/repo-baseline
```

## Reporting to the user

State it split, al chile:

> Mis tests nuevos/arreglados: X/X pasan. Preexistentes (ya venían rotos en
> baseline <sha>): N, ninguno mío — verificado con worktree diff. ¿Los arreglo
> aparte o los dejo porque ya venían?

Distinguishing "resueltos" (mine) from "preexisting" (not mine, not in scope) is
the difference between an honest report and a green-washed one.
