# Why `rm -rf _build/<env>/lib/<app>/priv` deletes source files

## What happened

In an Elixir/Phoenix umbrella, each app's `priv` directory is copied/synchronized to `_build/<env>/lib/<app>/priv` during compilation. The synchronization is not one-way. Deleting files from `_build/<env>/lib/<app>/priv/<subpath>` can delete the corresponding files from `apps/<app>/priv/<subpath>`.

Real session example: running

```bash
rm -rf _build/test/lib/core/priv/repo/migrations
```

deleting all migration files from `apps/core/priv/repo/migrations/`, even though the command targeted `_build`.

## Why it happens

The build tools treat `priv` as an overlay that is mirrored between source and the build output. Some build steps use hardlinks, symlinks, or file-walking sync. Removing the whole copied tree can remove the links or trigger a reverse sync. The safe rule is therefore: never surgically delete directories inside `_build/lib/<app>/priv`. Wipe the whole `_build` tree instead.

## Safe cleanup commands

```bash
# Clean just compiled artifacts but keep deps
mix clean

# Clean all BEAM artifacts and rebuild
mix clean && mix compile

# Nuclear option after weird build state
rm -rf _build
mix deps.get
mix compile

# Clean cached deps too when needed
rm -rf _build deps
mix deps.get
mix compile
```

## When this matters most

- After renaming migration files
- After adding/removing static assets in `priv/static`
- After changing `priv/repo/migrations` because of new DB features
- After a failed migration that left `_build` migrations out of sync with source

## Recovery recipe

If you already deleted source `priv` files:

1. Restore from git if tracked:
   ```bash
   git checkout -- apps/<app>/priv/
   ```
2. If untracked files were lost, recreate them or copy backups.
3. Reset the build tree:
   ```bash
   rm -rf _build
   mix deps.get
   mix compile
   ```
4. Reset the database to match the restored migrations:
   ```bash
   MIX_ENV=test mix ecto.reset
   ```

## Prevention

- Prefer `mix clean` or `mix deps.clean` over manual `_build` surgery.
- If you must delete `_build`, delete the whole directory, not subdirectories.
- Keep migrations tracked in git so they are restorable.
