# Parallel Subagent Git Race — Recovery Walkthrough

## The Problem

When 3+ subagents work on the same repo simultaneously and each runs
`git commit`, they race on the git index. The result: one commit contains
 hunks from multiple unrelated tasks, or later commits overwrite earlier
ones because the index was stale.

## Symptoms

- `git log` shows one commit with 3+ unrelated file changes
- Commit message mentions only one task but touches files from another
- `git diff HEAD~1` shows changes you don't recognize from the named task

## Recovery Procedure

### Step 1: Identify the mixed commits

```bash
git log --oneline -10
# Look for commits that bundle multiple scopes
```

### Step 2: Soft reset to before the race

```bash
# Find the last good commit before the subagent commits started
git reset --soft <last-good-commit>
# Or reset to origin/main if the race was on main
git reset --soft origin/main
```

### Step 3: Re-stage and re-commit atomically

```bash
# For each task, stage only its hunks
git add -p path/to/file1.ex   # select task-1 hunks
git add -p path/to/file2.ex   # select task-1 hunks
git commit -m "task 1: descriptive message"

git add -p path/to/file1.ex   # select task-2 hunks
git add -p path/to/file3.ex   # select task-2 hunks
git commit -m "task 2: descriptive message"
```

### Step 4: Verify

```bash
git log --oneline -5
git show --stat HEAD          # Should touch only task-N files
git show --stat HEAD~1        # Should touch only task-(N-1) files
```

## Prevention

1. **Dispatch committing tasks serially** — wait for subagent A to finish and
   commit before dispatching subagent B.

2. **Parent commits after verification** — subagents return diffs or file
   paths, parent reviews and commits:

   ```
   subagent: "Modified lib/foo.ex and test/foo_test.exs"
   parent:   git diff lib/foo.ex test/foo_test.exs
   parent:   git add -p  # verify hunks
   parent:   git commit -m "task: ..."
   ```

3. **No-commit instruction** — tell subagents explicitly: "Do NOT run
   git commit. Return the list of changed files and a summary."

## Real-world Case

MyApp multi-agent refactor (2026-07): 3 subagents dispatched in parallel,
each committed. Result: 1 commit with changes from 3 unrelated tasks. Recovery
took 20 minutes of `git add -p` to split. Prevention now: parent always
commits after verifying each subagent's output.
