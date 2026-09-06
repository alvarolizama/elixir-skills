# Masked `mix test` failures and swallowed output (parallel subagent sessions)

Symptom class: a batch of changes "passed" because the numbers you looked at
were the wrong numbers — a pipeline that masked the exit code, a timeout
misread as failure (or success), or output from a sibling app hiding the real
result.

## Piped verification commands mask the exit code

**Symptom.** `mix precommit 2>&1 | tail -25` prints a failure but the command
reports exit 0.

**Mechanism.** The shell reports the LAST command in the pipeline (`tail`),
not `mix`. Exit-code gates built on pipes are silently defeated.

**Fix.**

```bash
mix precommit > /tmp/verify.log 2>&1; echo "EXIT: $?"   # real exit code
# or
set -o pipefail; mix precommit 2>&1 | tee /tmp/verify.log
```

Use the file-based form when a downstream tool needs BOTH the output and the
truthful status.

## Subagent timeout ≠ work not done

**Mechanism.** A background agent's timeout is an artifact of its REPORT not
finishing in time, not of the work failing. The work is often already on disk
(and even committed).

**Check before re-dispatching:**

```bash
git log --oneline -5          # commit with the task message?
git status --short            # expected files modified?
mix compile --warnings-as-errors
mix test
```

All four pass → the work is done; do not re-dispatch. The inverse also
exists: an agent stuck in a read/grep discovery loop writes NOTHING — check
file mtimes (`stat -f "%Sm %N" <files>`); if the target was never touched,
the work does not exist, and you should do the small edit yourself rather
than re-dispatch the same prompt.

## Compile hangs at 0% CPU — beam lock or zombie process

**Symptom.** `mix compile` never finishes, prints nothing, 0% CPU.

**Mechanism.** A running `mix phx.server` beam holds file locks on `.beam`
files; a zombie compile from a timed-out subagent lingers similarly.

**Recovery.**

```bash
ps aux | grep -E 'mix (compile|phx.server)|beam.smp'   # identify owners first
kill -9 <compile_pid>                                    # zombie compile
kill <phx_server_pid>                                    # dev server
mix compile --force --warnings-as-errors
```

**Prevention.** Check for a running dev server before compile/test/precommit.

## Parallel agents racing the same file = mangled macros

**Mechanism.** Two agents editing the same `*Web.ex` (or layout/component
module) concurrently leaves missing imports, duplicated imports, or an
unwired `verified_routes` — anything that compiles to broken HTML.

**Fix.** Batch subagents by file dependency, not task count: disjoint file
sets may run in parallel; same-file tasks must be sequential or merged. After
every parallel batch the orchestrator re-reads the touched files, rewrites
any mangled one cleanly, and runs `mix compile --warnings-as-errors` before
the next batch.

## Subagent sweeps the parent's uncommitted work into its own commit

**Mechanism.** A single subagent that runs `git add -A` bundles whatever the
parent left uncommitted under its own message; commit messages become lies
and the parent cannot tell whether its edits are in or lost.

**Check after any subagent batch:**

```bash
git log --oneline -3
git show <sha> --stat          # are the parent's files in the diff?
git status --short             # clean + edits absent = lost → re-apply
```

**Prevention.** Commit parent work first, or tell the subagent explicitly to
stage ONLY a listed set of files — never `git add -A`.

## `.env` multiline secrets break mise

**Symptom.** `malformed value in .env`.

**Mechanism.** Secrets pasted with line continuations (`\`) are invalid for
mise's parser.

**Fix.** Paste as single-line strings; then `mise trust` and
`mise exec -- elixir --version`.

## `mix.lock` corruption after parallel scaffolding

**Symptom.** `** (Mix.Error) Your mix.lock contains invalid data`.

**Mechanism.** Parallel agents each ran `mix deps.get` and overwrote
`mix.lock` concurrently.

**Fix.** Regenerate sequentially (`mix deps.get`, `mix deps.update --all` if
needed) and commit `mix.lock` yourself before dispatching the next batch.
Orchestrator rule: the parent runs `mix deps.get` after parallel batches; it
is a single-writer file.

## Verification

```bash
mix precommit > /tmp/verify.log 2>&1; echo "EXIT: $?"   # truthful gate
mix compile --warnings-as-errors                         # after every batch
git status --short && git log --oneline -3               # what really landed
```