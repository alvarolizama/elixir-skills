# Branch validation in umbrella projects (warnings isolation + clean test output)

**Symptom.** You try to gate a branch locally with
`mix compile --warnings-as-errors` before push, and it fails on warnings from
apps the branch never touched. Separately, `mix test apps/<app>`
"passes" but you cannot see the test count.

## Pre-existing warnings break `--warnings-as-errors` for the whole umbrella

**Mechanism.** `mix compile` from the umbrella root compiles ALL apps; the
`--warnings-as-errors` flag applies to the union of every warning. One
untouched app with stale warnings (unused aliases, deprecated functions) makes
the whole-umbrella gate impossible locally. "Compile clean on my branch"
cannot be proven with a single boolean.

**Fix — isolate branch warnings from codebase warnings:**

```bash
# 1. List the files this branch touches
git diff origin/main..HEAD --name-only

# 2. Compile WITHOUT the flag — this must be exit 0
mix compile

# 3. Capture warnings and cross-reference against branch files
mix compile 2>&1 | grep -i warning | tee /tmp/warnings.txt

# 4. Only flag warnings on files the branch actually modified
#    (warnings touching files OUTSIDE the diff are pre-existing, not yours)
```

Do not commit a gate that requires a pristine umbrella — unless the whole
codebase is already warning-free, it will fail on unrelated code and get
ignored. The branch's own proof is: compile exit 0 + zero warnings on the
diff files.

## `mix test apps/<app>` swallows the suite summary

**Symptom.** `mix test apps/api` runs, but `Finished in Xs / N tests passed`
never appears on screen. Exit code is still correct, but you can't see the
count (or the failures).

**Mechanism.** In an umbrella, compilation warnings from sibling apps
(especially apps with many LiveView modules) dominate stderr, pushing the
test summary off-screen. Compile and test are fused in one command, so
warnings and results mix.

**Fix — separate compile from test:**

```bash
MIX_ENV=test mix compile 2>/dev/null   # warm the cache, absorb warnings
mix test apps/api 2>/dev/null          # now test output is clean
# If you still need the count:
mix test apps/api 2>/dev/null | tail -3
```

The second command reuses the warm cache, so no warnings are emitted and the
summary is visible.

## Detached HEAD after git operations

**Symptom.** `git diff origin/main..HEAD` returns empty (or different commits
than expected), or the working tree shows files that the diff says do not
exist. The commits you validated against are not the ones in your working
tree.

**Mechanism.** A `git checkout` (e.g., for a server restart) left the repo in
detached HEAD state — the working tree matches a commit, not the branch.

**Check.**

```bash
git rev-parse --abbrev-ref HEAD
# returns "HEAD" instead of a branch name → detached
```

**Fix.** `git checkout <branch-name>`.

**Rule.** Before any validation that compares the working tree to branch
history, confirm you are on the branch. Every "sanity" gate that starts with
`git diff origin/main..HEAD` first checks the ref.

## Ad-hoc query verification without the web port

See `runtime-config-overrides.md` — the `MIX_ENV=test mix run -e` pattern is
the same family of "separate concerns so one output doesn't swallow another".

## Verification

```bash
git rev-parse --abbrev-ref HEAD                        # a branch name, not HEAD
mix compile                                            # exit 0
mix compile 2>&1 | grep -c "warning"                    # count vs. branch diff
MIX_ENV=test mix compile 2>/dev/null && mix test apps/api 2>/dev/null | tail -3
# → Finished in ... : N tests, M failures
```