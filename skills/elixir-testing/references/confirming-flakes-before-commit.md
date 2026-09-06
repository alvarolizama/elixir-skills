# Confirming a flake before blaming your change

Symptom: the full suite goes red on a test UNRELATED to your diff. The cheapest
honest check is the isolation run — only failures that REPRODUCE in isolation
block the commit.

## The protocol

1. Re-run only the failures: `mix test --failed`, twice.
   - Green both times = shared-DB/ordering flake, not a regression.
2. Re-run the full suite once. Green = proceed with the commit; report the
   flake in your summary.
3. Only block the commit on a failure that REPRODUCES in both runs — a
   failure that never comes back twice in a row is a flake, not your bug.

Do NOT weaken the flaky test's assertions to make it pass — that hides a real
signal. Do NOT block unrelated commits on a non-reproducing failure.

## Honest failure attribution — baseline worktree diff

When you fix tests on a repo that ALREADY had failures, "the suite is green"
on your branch proves nothing — the count alone can't separate **failures you
introduced** from **failures that were already there**. Separate them:

1. Identify the last commit BEFORE your changes (`git log --oneline`).
2. Create a throwaway worktree at that baseline and run the SAME suite there:

```bash
git worktree add -q /tmp/repo-baseline <baseline_sha>
cd /tmp/repo-baseline && mix deps.get -q   # or pnpm install / pip install
MIX_ENV=test mix test 2>&1 | grep -E "^\s+[0-9]+\) test " \
  | sed 's/^[0-9 ]*) //' | sort > /tmp/base.txt
```

3. Run the suite on your working branch, same extraction:

```bash
cd /path/to/repo
mix test 2>&1 | grep -E "^\s+[0-9]+\) test " \
  | sed 's/^[0-9 ]*) //' | sort > /tmp/mine.txt
```

4. Diff the two name lists:

```bash
comm -23 /tmp/mine.txt /tmp/base.txt   # failures ONLY in mine → these are YOURS
comm -13 /tmp/mine.txt /tmp/base.txt   # failures ONLY in base → you FIXED these
```

Empty first list = zero regressions. The second list is credit you can claim.

**Why the extraction matters:**

- Grep the `N) test <name>` block headers, NOT the `file.exs:LINE` stack lines
  — stack lines shift as you edit, so line-number diffs produce phantom "new"
  failures. Test NAMES are stable across your edits.
- `sed 's/^[0-9 ]*) //'` strips the leading index (which changes with seed) so
  `sort` + `comm` line up correctly.
- Flaky suites vary run-to-run; if the baseline count wobbles, run it twice
  and intersect before diffing, or compare names not counts.

5. Cleanup:

```bash
git worktree remove --force /tmp/repo-baseline
```

## Worked instance

`GET /api/search/semantic returns semantic search results` uses a
`Req.Test.stub(MyApp.Inference.Client, ...)` and creates a page with a vector
embedding. Under full-suite load it intermittently fails:

```
assert length(data) == 1   → left: 0
** (ArgumentError) construction of binary failed: segment 1 of type 'binary':
   expected a binary but got: nil
```

It always passes solo (verified 2×) and the full suite went back to green on
re-run. Root cause was NOT diagnosed — treat as a known flake; do not weaken
its assertions, do not block unrelated commits on it.

## Verification

```bash
mix test test/.../file.exs    # twice — the isolation run
mix test                       # full suite once more
# only a failure reproducing in BOTH full-suite runs AND solo gets triaged
```