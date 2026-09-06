# Partitioned Commit Waves — several features in one dirty tree

Symptom: "commit everything" lands on a tree holding multiple logical waves
at once — a cross-cutting rename, a feature, a cleanup, generated digests —
with staged AND unstaged changes entangled on the same files. Some staged
entries are renames with unstaged modifications stacked on top.

## Mechanism — why the obvious tools fail

- `git stash` round-trips a full snapshot; on a staged+unstaged hybrid it is
  fragile (pop conflicts, lost index state, mangled renames). Do NOT stash
  through it.
- Eye-driven partitioning misses files: in a ~100-file wave, one unassigned
  file is typical. The coverage check below exists because the eye misses it.

## Fix — the working procedure

1. **`git reset`** — index only, working tree untouched. This un-stages the
   hybrid without losing anything.
2. **Explicit per-file lists per commit** (one text file per wave). Directories
   may be listed as specs; expand them with `find` only during validation,
   never in the lists themselves.
3. **Coverage check BEFORE committing.** Union the expanded lists against the
   pending tree, minus deliberate exclusions (scratch dirs like `.spike/`,
   generated artifacts left untracked on purpose):

   ```bash
   cat lists/c1-rename.txt lists/c2-feature.txt lists/c3-cleanup.txt \
     | sort -u > /tmp/assigned.txt
   git status --porcelain | awk '{print $NF}' \
     | grep -vE '^\.spike/' | sort -u > /tmp/pending.txt
   comm -23 /tmp/pending.txt /tmp/assigned.txt   # MUST print nothing
   ```

   `git status --porcelain` renders renames as `R  old -> new`; normalize the
   lines (`awk '{print $NF}'` keeps only the new path) before comparing. The
   check catches the file the eye missed — expect it to find one.
4. **Intra-file theme mixes go to the dominant-theme commit**, with the bleed
   declared in the commit body (e.g. a file whose rename lines go to C1 and
   whose feature lines go to C2 stays whole in C1; one moduledoc mention of a
   C2 module does not break C1's standalone compile — but verify that).
5. **Commit each partition** with its conventional prefix
   (`refactor!:`, `feat(scope):`, `chore:`, `docs:`), then run the full gate
   suite once more at the end.
6. **Untracked files with hash names:** `git add` inside a batch script
   failed once with `pathspec did not match` while the identical add worked
   individually (verified). Retry the specific add before debugging anything.

## The priv/static nuance

The rule "don't commit `priv/static`" is really "don't commit GENERATED
churn". Decide per repo:

```bash
git ls-files priv/static/
```

- Bundles (`priv/static/assets/*`) and `cache_manifest.json`: normally
  gitignored — regenerate artifacts of `mix assets.deploy` get cleaned with
  `git status --porcelain` + `rm` before committing.
- If the repo deliberately tracks digest files of a type (favicon, robots,
  logo archives), new digests of the same type follow that precedent — commit
  them with the digest wave, not silently in a feature commit.

## Verification

- `comm -23` output empty — every pending file assigned (minus documented
  exclusions).
- `git show --stat HEAD~n` per commit — the file list matches that
  partition's explicit list exactly, nothing swept in.
- `git log --oneline` — one commit per wave, conventional prefixes.
- Full test suite green after the last partition; each partition compiles
  standalone where the order interleaves concerns.
- Deliberate exclusions (scratch/mockup dirs) still untracked and documented
  in the final report.
