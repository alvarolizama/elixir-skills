---
name: git-workflow
description: "Git commit hygiene for parallel subagents and refactors."
version: 1.0.0
author: Álvaro Lizama
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [git, workflow, subagents, commits, parallel, recovery]
    related_skills: [github-pr-workflow, systematic-debugging]
---

# Git Workflow — Commit Hygiene for Multi-Agent Work

Procedures for keeping git history clean when working with parallel subagents,
large refactors, and mixed WIP changes.

## When to Use

- Dispatching parallel subagents that will commit to the same repo
- Starting a large refactor that touches many files
- Recovering from a commit that bundled multiple unrelated tasks
- Splitting mixed WIP + feature changes into separate commits

## Core Rules

### 1. Commit before starting big refactors

Álvaro's rule: *"primer haz commit de todo"* — commit all WIP before any
refactor. This isolates the refactor diff from pre-existing changes.

**Why:** If the refactor breaks something, you can `git diff` the refactor
commit alone. Mixed WIP + refactor makes bisection impossible.

### 2. Feature commits never sweep in unrelated pre-existing WIP

When WIP and new changes share a file, split hunks into separate commits with
`git add -p` instead of mixing or discarding.

**Pattern:**
```bash
# Stage only the hunks related to the feature
git add -p path/to/file.ex
# Commit the feature
git commit -m "feat: add user timezone selector"
# Stage remaining WIP hunks
git add -p path/to/file.ex
# Commit the WIP separately
git commit -m "wip: dashboard layout adjustments"
```

### 3. Parallel subagent git races

When multiple subagents commit to the same repo simultaneously, they race on
the git index and bundle multiple tasks into single commits.

**Recovery:**
```bash
# Soft reset to before the subagent commits
git reset --soft origin/main
# Re-commit each task individually with proper messages
git add -p  # select hunks for task 1
git commit -m "task 1: ..."
git add -p  # select hunks for task 2
git commit -m "task 2: ..."
```

**Prevention:**
- Dispatch committing tasks **serially**, not in parallel
- Or have the **parent agent commit** after verifying each subagent's work
- Or instruct subagents to **not commit** — return diffs, parent commits

## Multi-Agent Dispatch Patterns

| Pattern | Risk | When to use |
|---------|------|-------------|
| Parallel subagents, each commits | High race risk | Never for commits |
| Parallel subagents, parent commits | Low risk | Default for code changes |
| Serial subagents, each commits | Low risk | When tasks are independent |
| Serial subagents, parent commits | Lowest risk | High-stakes repos |

## Verification

Before reporting "done" on a multi-agent task:
```bash
git log --oneline -5          # Are commits atomic and well-named?
git diff HEAD~1 --stat        # Did any commit sweep unrelated files?
```

If a commit bundles multiple tasks, use the recovery procedure above.

## References

- `references/parallel-subagent-recovery.md` — detailed recovery walkthrough
- `references/split-hunks-guide.md` — `git add -p` interactive splitting
