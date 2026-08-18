# Aligning `mix.exs` version requirement with the resolved `mix.lock`

**Scenario.** `mix.exs` declares `{:tidewave, "~> 0.5", only: :dev}`, but `mix.lock` already resolved `tidewave 0.6.1` because `~> 0.5` allows any `0.6.x`. The user expected the manifest to reflect the concrete resolved version, not a loose requirement that silently picked a newer minor.

**Fix.**

1. Confirm what Hex actually resolved:
   ```bash
   mix deps.get
   grep '"tidewave"' mix.lock
   ```
2. Update `mix.exs` to match intent:
   - Pin to patch: `{:tidewave, "~> 0.6.1", only: :dev}`
   - Or allow the minor explicitly: `{:tidewave, "~> 0.6", only: :dev}`
3. Re-run `mix deps.get` to confirm the lock does not drift.
4. Commit both `mix.exs` and `mix.lock` together.

**Why it matters.** A requirement behind the lock makes the manifest inaccurate. It can confuse reviewers, break `mix deps.unlock --unused` expectations, or cause a fresh install to resolve a different version than the one currently in the lock.
