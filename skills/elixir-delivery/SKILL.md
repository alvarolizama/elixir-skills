---
name: elixir-delivery
description: "Use when committing, gating, or shipping a Phoenix wave."
version: 1.0.0
author: Álvaro Lizama
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [git, commits, precommit, sobelow, triage, review, deploy, release, docker, readme, screenshots]
    related_skills: [elixir-skills, elixir-review, elixir-setup]
---

# Elixir Delivery — Waves, Precommit Gates, Release, Docs

Delivery is the last mile of a Phoenix change wave: read the tree, gate it,
commit it in coherent pieces, ship it, and document it. Every rule here is
imperative; load a reference for the full mechanism of the section you are in.

```mermaid
flowchart TD
    A[Delivery task on a Phoenix repo] --> B{"git status: what is in the tree?"}
    B -- "one coherent wave" --> C["ONE atomic commit, conventional prefix"]
    B -- "several entangled waves" --> D[Partitioned commit waves]
    C --> E[Precommit gates in order]
    D --> E
    E --> F{"All gates green?"}
    F -- "no: sobelow" --> G["Disposition: .sobelow-conf fix<br/>or stash-baseline diff"]
    F -- "no: tests" --> H[Three-way test triage]
    F -- "no: compile or format" --> I["Fix in-wave, re-run EVERY gate"]
    G --> E
    H --> E
    I --> E
    F -- "yes" --> J{"Migrations in the wave?"}
    J -- "yes" --> K[structure.sql drift check]
    J -- "no" --> L[Adversarial review gate]
    K --> L
    L --> M{"APPROVE?"}
    M -- "no: real blockers" --> I
    M -- "yes" --> N[Commit each partition]
    N --> O{"REST endpoints added?"}
    O -- "yes" --> P[API e2e smoke on a real server]
    P --> Q[Push]
    O -- "no" --> Q
    Q --> R{"What ships next?"}
    R -- "deploy" --> S[mix release to PaaS]
    R -- "docs" --> T[README + screenshot capture]
    S --> U[VERIFY gates]
    T --> U
```

## 1. Read the wave first

1. `git status` + `git log --oneline` + `git diff --stat` (and `--cached`)
   before anything else.
2. Classify:
   - One coherent feature wave (migration + context + LiveView + docs move
     together) → **ONE atomic commit** with a conventional prefix
     (`feat(scope):`, `fix(scope):`, `docs:`, `chore:`), matching the repo's
     history.
   - Several logical waves in one tree → **partitioned commit waves**
     (reference: `partitioned-commit-waves.md`).
3. Never `git stash` a staged+unstaged hybrid — `git reset` (index only) and
   rebuild from explicit per-file lists instead.
4. Commit all WIP **before** starting a big refactor; a mixed WIP+refactor
   diff makes bisection impossible.
5. Stage explicit paths, never `git add -A` in a dirty repo — unrelated WIP
   gets silently bundled.

## 2. Precommit gates in order

`mix precommit` expands to: compile → deps.unlock → format → deps.audit →
`sobelow --exit medium` → test. It dies at sobelow whenever preexisting
findings exist: test never runs through the alias in that state, and format
— which is BEFORE sobelow in the order — may already have run.
Reference: `precommit-gates.md`.

- **Sobelow disposition (a) — constant false positive:** `Config.CSP` fires
  on every Phoenix 1.8 app because sobelow can't parse the CSP that
  `put_secure_browser_headers` ships by default. Fix once:
  `mix sobelow --save-config --exit medium -i Config.CSP` writes
  `.sobelow-conf` — commit it. The alias then runs end-to-end green.
- **Sobelow disposition (b) — genuine preexisting findings:** prove "no NEW
  findings" with a stash baseline (`git stash -u` → sobelow → pop → sobelow),
  compare sorted `File:/Function:/Line:` sets; line-number-only diffs = same
  findings. Real new findings block the commit.
- **Format idempotency:** the check is `mix format --check-formatted`
  (writes nothing; exit 0 = tree already formatted). To prove `mix format`
  itself changes nothing, compare file HASHES before/after — a
  `git status --porcelain` count can stay equal while files are rewritten.
- **A foreign writer in the tree invalidates the aggregate gates.** `mix
  precommit` runs a global `mix format`, which rewrites whatever another session
  has in flight — its WIP, not yours. Run the pieces individually and format
  ONLY your files (`mix format <path>...`); `mix format --check-formatted`
  (writes nothing) shows the rest of the tree's state. Attribute failures with
  evidence before reporting them as yours: `git show HEAD:<file> | grep -c
  '<the string the failure names>'` — a suite that only fails on the other
  writer's in-flight strings is green for your change. A co-writer's commit
  can also land mid-staging and clear the index, and NEVER
  `git checkout-index -f` to unstage — it writes the index into the working
  tree and eats their hunks (`git reset -- <paths>` is the unstage that
  leaves the working tree alone). See `git-hygiene-and-hunks.md`.
- **Compile strict:** `mix compile --warnings-as-errors` after every fix, not
  once per wave — each fix is new code and the previous green run expires.
- **Full suite in background** with output to a file. Piping through `tail`
  LOSES the numbered failure list (it lives above the tail window). Index
  failures: `grep -nE '^  [0-9]+\) test' /tmp/mix_test_full.txt`.
- **Non-Elixir waves** (Dockerfile/ENV/docs only): the compile+precommit gate
  is pure overhead — `grep` the literal value and document the choice.

## 3. Test-failure triage — three-way verdict, not two

Reference: `test-failure-triage.md`. Read each failure; classify:

- **Environmental** (contaminated test DB, sandbox races that pass isolated)
  → report, don't touch.
- **Stale expectation encoding the CORRECT contract** (production drifted,
  test asserts the old behavior) → the failure points at a latent bug; fix
  production + test together in a SEPARATE scoped `fix:` commit, never mixed
  into the feature wave.
- **Product decision** (test asserts UI a refactor removed) → report, ask
  which side is right; don't guess.

**Flake confirmation loop:** `mix test --failed` passes → suspect flake; full
suite once more → green → confirmed flake. Only failures reproducing in BOTH
runs get triaged. Never patch code for a single-run failure.

**Stash-baseline pitfall:** if the test DB already has the wave's migrations,
HEAD runs old code against the new schema — HEAD fails spuriously on anything
querying dropped columns. Discard schema-mismatch noise; only same-named
tests failing for the same reason count as evidence.

## 4. structure.sql drift

Territory: **elixir-data** owns the migration-authoring rules (renames,
backfill-before-drop, duplicate indexes —
`skills/elixir-data/references/migrations-and-structure-sql.md`); delivery
owns the ship-time drift check: a wave with migrations must ship
`priv/repo/structure.sql` matching ALL of them. Stale-dump signature: the
`schema_migrations` INSERT block lists fewer versions than there are
`priv/repo/migrations/*.exs` files, or dropped columns still declared.
Reference: `structure-sql-drift.md`.

- `mix ecto.migrations` shows all `up` on dev (the dump reads the dev DB),
  then `mix ecto.dump`, then grep re-verification.
- pg_dump `\restrict`/`\unrestrict` meta-commands are version churn, NOT
  drift — compare table DDL / indexes / version rows, not raw diff size.

## 5. Adversarial review gate before committing

Reference: `adversarial-review-gate.md`. A `delegate_task` review pass with
the diff as the only input — who writes does not self-approve. This is the
delivery-side dispatch gate; the general reviewer protocol it implements
lives in `skills/elixir-review/references/adversarial-review-protocol.md`.

- Blocking criteria: secrets, debug leftovers, hardcoded credentials,
  migration/structure.sql drift, missing module references.
- Subagent died 503/max_iterations → **NOT an approval**. Re-dispatch once
  with a narrow goal; if that fails too, do your own adversarial pass on the
  diff and record "review delegated: not completed (503)".
- The full verdict lives in the delegation summary file, not the truncated
  transcript tail. A late async notification after you closed triage →
  mandatory re-triage.
- Findings on the uncommitted wave → fixes go in the SAME wave commit; after
  each fix re-run `mix compile --warnings-as-errors` + full gates.
- Validate and EXTEND a finding before fixing: reproduce it yourself
  (`mix run --no-start`; plain `mix run` dies `:eaddrinuse` with the dev
  server up) and grep the CONSUMERS of the buggy function — the naive fix can
  break a consumer the review never looked at.
- Post-push findings: warn that self-corrects or a misleading comment →
  separate `docs:` commit; style nits / pre-existing debt → report only.

## 6. API-wave e2e smoke (beyond ConnCase)

ConnCase mocks prove the controller contract, not the HTTP surface (router
plugs, real auth pipelines, JSON encoding). For waves adding REST endpoints:
real server on an alternate port, curl cycle create → duplicate → search →
401 → cross-workspace 404, then kill the server and clean the e2e rows from
the dev DB. Reference: `api-e2e-smoke.md`.

## 7. Git hygiene, surgery, signing

Hunk splitting, subagent git races, bundled-commit recovery, selective
reverts, full feature excision, worktree cleanup, GPG/SSH signing —
references: `git-hygiene-and-hunks.md`, `git-commit-signing.md`.

## 8. Release and deploy

Ship as a `mix release` to a container PaaS: `mix phx.gen.release`, verify
the release boots locally (`bin/<app> eval "IO.puts(:ok)"` prints `:ok`) — a
passing `mix precommit` does NOT prove the `:prod` boot. Pre-deploy hook is
`bin/migrate` (DB exists) or idempotent `bin/setup` (first run, single
instance). The 403-on-POST, Ecto SSL, force_ssl, and build-pack failure
signatures live in `release-deploy.md`.

## 9. Docs: README and screenshots

Every claimed feature must exist in the codebase; every UI claim must have a
route. The router file is the page inventory; verify each old-doc claim with
a grep before carrying it over; read env defaults from config source, never
from the old doc; report discrepancies back explicitly. Screenshots: confirm
login actually landed before shooting, vision-gate every capture, copy each
PNG immediately. Reference: `readme-and-screenshots.md`.

## VERIFY

Category gates for this skill's own build — self-contained, run from the
root of the repo that carries `skills/elixir-delivery/`:

```bash
# Frontmatter, DAG, exact VERIFY headings, reference integrity/lengths,
# category size, and relative-link resolution across the full framework.
python3 scripts/validate.py
```

Per-wave delivery gates (the ones the skill itself enforces):

```bash
# gates, in order — each must pass before the next matters
mix compile --warnings-as-errors        # exit 0, no output
mix format                              # then:
mix format --check-formatted            # exit 0 = tree formatted (idempotent)
mix test > /tmp/mix_test_full.txt 2>&1  # background; index failures with grep
grep -nE '^  [0-9]+\) test' /tmp/mix_test_full.txt   # every failure dispositioned

# migration waves: dump freshness
ls priv/repo/migrations/*.exs | wc -l   # == versions listed under schema_migrations

# commits
git log --oneline -5                    # one commit per wave, conventional prefixes
git show --stat HEAD                    # file list == that partition's explicit list

# release waves (only when release code/config changed)
DATABASE_URL=ecto://nope:nope@127.0.0.1:1/nope SECRET_KEY_BASE=test \
  _build/prod/rel/<app>/bin/<app> eval "IO.puts(:ok)"   # prints :ok
```

A wave is deliverable when: all gates green or dispositioned with evidence,
review verdict read from the full summary (no blockers open), every commit
matches its explicit file list, and — for deploy-affecting waves — the
release smoke test passes.

## References

- `references/precommit-gates.md` — mix precommit order, sobelow dispositions, format/compile/test gates, JS-only and non-Elixir waves.
- `references/partitioned-commit-waves.md` — committing several entangled waves from one dirty tree with a coverage check.
- `references/test-failure-triage.md` — three-way verdict, flake loop, stash-baseline pitfall, test-DB contamination.
- `references/structure-sql-drift.md` — stale structure.sql detection, re-dump checklist, pg_dump noise. Migration-authoring rules (renames, backfills) live in the elixir-data skill (`skills/elixir-data/references/migrations-and-structure-sql.md`).
- `references/adversarial-review-gate.md` — pre-commit review dispatch, death protocol, verdict recovery, finding validation, post-push dispositions. The general reviewer protocol is `skills/elixir-review/references/adversarial-review-protocol.md`.
- `references/api-e2e-smoke.md` — real-server curl cycle for REST waves, cleanup of e2e rows.
- `references/git-hygiene-and-hunks.md` — hunk splitting, subagent races, history surgery, excision, worktree cleanup.
- `references/git-commit-signing.md` — GPG/SSH signing diagnosis, pinentry fix, end-to-end verification.
- `references/release-deploy.md` — mix release workflow, release.ex/runtime.exs pitfalls, CSRF/SSL/403 signatures, build-time fixes.
- `references/readme-and-screenshots.md` — codebase-verified README authoring and UI screenshot capture.
