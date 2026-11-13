# Precommit Gates — mix precommit, Sobelow, Format, Compile, Test

Symptom: `mix precommit` dies before finishing, or a green-looking run hides
new findings. Mechanism: the alias runs its gates in a fixed order and dies
at the first failing one — passing later gates proves nothing about earlier
ones. Fix: run the gates in order, isolate the failure, disposition it, and
re-run everything after any fix.

## The alias and its order

`mix precommit` expands to:

```
compile → deps.unlock → format → deps.audit → sobelow --exit medium → test
```

- It dies at `sobelow --exit medium` whenever preexisting findings exist —
  TEST never runs through the alias in that repo state. FORMAT sits BEFORE
  sobelow in the order and may already have run (and rewritten files) by
  the time sobelow dies — never assume the earlier gates didn't execute.
- `mix format` running inside the alias does not dirty the tree — but verify
  with `git status --porcelain` afterwards; do not assume.
- When the alias dies at sobelow, run the later gates directly instead of
  assuming they ran: `mix compile --warnings-as-errors`, `mix format
  --check-formatted`, `mix test`.

## Sobelow disposition 1 — constant false positive (fix once)

`Config.CSP` fires on every Phoenix 1.8 app: sobelow cannot parse the CSP
that `put_secure_browser_headers` ships by default
(`deps/phoenix/lib/phoenix/controller.ex` sets
`content-security-policy: base-uri 'self'; frame-ancestors 'self'`).

Fix once, commit the config:

```bash
mix sobelow --save-config --exit medium -i Config.CSP   # writes .sobelow-conf
git add .sobelow-conf
```

`mix precommit` then runs end-to-end green (exit 0 through format + audit +
test) (verified).

## Sobelow disposition 2 — genuine preexisting findings → baseline diff

Prove "no NEW findings" instead of fixing old ones:

```bash
git stash -u
mix sobelow --exit medium > /tmp/sobelow_clean.txt 2>&1; echo exit=$?
git stash pop
mix sobelow --exit medium > /tmp/sobelow_dirty.txt 2>&1; echo exit=$?
```

Compare the sorted sets of identifying lines:

```bash
grep -E 'File:|Function:|Line:' /tmp/sobelow_clean.txt | sort > /tmp/clean.set
grep -E 'File:|Function:|Line:' /tmp/sobelow_dirty.txt | sort > /tmp/dirty.set
comm -13 /tmp/clean.set /tmp/dirty.set   # findings only in the dirty tree = NEW
```

Line-number-only differences = the same findings, shifted code. Real new
findings block the commit.

## Sobelow on new raw SQL — the rewrite that actually clears it

Flagged: `Variable: sql` on a `Repo.query` call. Rewrites that do NOT clear
it: interpolated fragments; a bare `sql` variable even when assigned from a
module attribute. What clears it: compile-time constant attributes and a
direct call per branch:

```elixir
@feedback_helpful_sql "..."
@feedback_unhelpful_sql "..."

def record_feedback(id, :helpful),   do: Repo.query(@feedback_helpful_sql, [uuid])
def record_feedback(id, :unhelpful), do: Repo.query(@feedback_unhelpful_sql, [uuid])
```

Zero new findings versus the stash baseline (verified). Do not burn attempts
on `~S` sigils or fragment tricks — go straight to constant attrs per branch.

## UUID params to raw SQL

Postgrex expects 16-byte binaries for uuid columns. Pass the
`Ecto.UUID.dump(id)` result — it also converts invalid-uuid input into a
clean `:not_found` clause. `WHERE id = $1::uuid` does NOT help: Postgrex
encodes parameters before the cast runs.

## Format idempotency

```bash
mix format --check-formatted    # writes nothing; exit 0 = already formatted
```

To prove `mix format` itself changes nothing, compare hashes — a count of
`git status --porcelain` lines can stay equal while files are rewritten:

```bash
find lib test -name '*.ex' -o -name '*.exs' | sort | xargs shasum > /tmp/fmt_before.sha
mix format
find lib test -name '*.ex' -o -name '*.exs' | sort | xargs shasum > /tmp/fmt_after.sha
diff /tmp/fmt_before.sha /tmp/fmt_after.sha   # empty = idempotent
```

## Compile strict

```bash
mix compile --warnings-as-errors   # exit 0, no output
```

Run after every fix, not once per wave — each fix is new code and the
previous green run expires.

## Full test suite in background

A full-size suite exceeds foreground timeouts. Run it in the background with
full output to a file:

```bash
mix test > /tmp/mix_test_full.txt 2>&1
grep -nE '^  [0-9]+\) test' /tmp/mix_test_full.txt   # numbered failure list
```

Piping through `tail` LOSES the numbered failure list — it lives above the
tail window. Triage every failure via the reference
`test-failure-triage.md`.

## JS-only waves

- View the real diff, comments stripped, to prove no accidental code changes:
  `git diff -- assets/js/app.js | grep -E '^[+-]' | grep -vE '^[+-][+-]'`.
- `MIX_ENV=prod mix assets.deploy` regenerates the bundle AND digest files
  (`priv/static/favicon-*.svg`, `images/logo-*.svg.gz`, ...).
- Whether to keep or delete those artifacts is a repo-precedent question:
  `git ls-files priv/static/` decides. Churn in `priv/static/assets/*` and
  `cache_manifest.json` is normally gitignored — clean it before committing;
  new digests of an already-tracked type follow the repo precedent.

## Scope-down for non-Elixir waves

Dockerfile / ENV / doc-only changes: a compile + full precommit gate is pure
overhead. Verify the literal value (`grep -n "4001" Dockerfile` after a port
re-baseline) and document the deliberate choice (e.g. `EXPOSE` removed on
purpose) in the commit body.

## Verification

- `mix precommit` exit 0, or sobelow dispositioned and each gate run
  individually green.
- `git status --porcelain` free of format and asset artifacts.
- `comm -13 clean.set dirty.set` empty — no new sobelow findings.
- Every test failure dispositioned through the triage reference.
