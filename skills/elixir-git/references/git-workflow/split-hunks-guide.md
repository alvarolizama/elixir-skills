# Splitting Hunks with `git add -p`

Interactive staging to separate mixed changes into atomic commits.

## Basic Flow

```bash
git add -p path/to/file.ex
```

Git presents each hunk and asks:

```
Stage this hunk [y,n,q,a,d,s,e,?]?
```

| Key | Action |
|-----|--------|
| `y` | Stage this hunk |
| `n` | Skip this hunk |
| `q` | Quit — don't stage any more hunks in this file |
| `a` | Stage this and all remaining hunks in this file |
| `d` | Skip this and all remaining hunks in this file |
| `s` | Split the hunk into smaller hunks (if possible) |
| `e` | Manually edit the hunk |
| `?` | Help |

## Pattern: Feature + WIP in Same File

```bash
# 1. Stage only feature hunks
git add -p lib/MyApp/feature.ex
# → y for feature hunks, n for WIP hunks

# 2. Commit the feature
git commit -m "feat: add timezone selector"

# 3. Stage remaining WIP hunks
git add -p lib/MyApp/feature.ex
# → y for WIP hunks (previously skipped)

# 4. Commit the WIP
git commit -m "wip: layout adjustments"
```

## Pattern: Multiple Features in One File

```bash
# Stage feature A
git add -p lib/MyApp/multi.ex
# → y for feature-A hunks, n for feature-B hunks

git commit -m "feat: add search"

# Stage feature B
git add -p lib/MyApp/multi.ex
# → y for remaining hunks

git commit -m "feat: add filters"
```

## When Hunks Are Too Big

Use `s` (split) to break a large hunk into smaller ones. If git can't split
it automatically, use `e` (edit) to manually remove lines from the hunk.

## Verification

After each `git add -p` + commit:

```bash
git show --stat HEAD          # Verify only expected files changed
git diff --cached             # Verify nothing is still staged accidentally
```
