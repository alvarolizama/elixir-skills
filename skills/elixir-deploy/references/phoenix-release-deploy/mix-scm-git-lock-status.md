# Mix.SCM.Git — why "lock outdated" actually fires

Source: `elixir/lib/mix/lib/mix/scm/git.ex` (Elixir 1.20.1, branch `v1.20.1`).
Captured after a deploy to Coolify with Nixpacks failed repeatedly on
`heroicons` despite the lock and `mix.exs` apparently agreeing.

## The decision tree (`lock_status/1`)

```elixir
def lock_status(opts) do
  lock = opts[:lock]

  cond do
    lock_rev = get_lock_rev(lock, opts) ->
      %{origin: origin, rev: rev} = get_rev_info(opts[:checkout])

      if get_lock_repo(lock) == origin and lock_rev == rev do
        :ok
      else
        :mismatch
      end

    is_nil(lock) ->
      :mismatch

    true ->
      :outdated
  end
end
```

`:outdated` is the **last** branch. To get there, `get_lock_rev/2` must have
returned `nil` (so the first branch is skipped) and `lock` must be non-nil
(so the second branch is skipped). Translation: the lock entry exists but
its options no longer match what `mix.exs` declares.

## `get_lock_rev/2` — the comparison that fails

```elixir
defp get_lock_rev({:git, repo, lock, lock_opts}, opts) when is_binary(lock) do
  if repo == opts[:git] and lock_opts == get_lock_opts(opts) do
    lock
  end
end

defp get_lock_rev(_, _), do: nil
```

Two things must match exactly: the git URL **and** the lock-bearing options
keyword list. If either differs, the function returns `nil` (the `if` body
has no `else` and Elixir treats that as `nil`).

## `get_lock_opts/1` — what the comparison actually checks

```elixir
defp get_lock_opts(opts) do
  lock_opts = Keyword.take(opts, [:branch, :ref, :tag, :sparse, :subdir, :depth])

  if opts[:submodules] do
    lock_opts ++ [submodules: true]
  else
    lock_opts
  end
end
```

Only six keys are compared. Notably **not** in this list:
- `:app` (so `app: false` in `mix.exs` is harmless)
- `:compile` (so `compile: false` is harmless)
- `:runtime`, `:only`, `:targets` — also harmless for lock-status

What **is** checked and frequently breaks:
- `:ref` vs `:tag` vs `:branch` — must pick exactly one. If `mix.exs` says
  `ref:` but the lock entry was written when `mix.exs` said `tag:`, the
  keyword lists will not match literally and `:outdated` fires.
- **Order** of the four surviving keys. `Keyword.take/2` preserves the
  order of the source keyword list, so a `mix.exs` with
  `ref: "…", sparse: "optimized", depth: 1` produces a different literal
  list from one with `sparse: "optimized", ref: "…", depth: 1`.
- `:depth` with `:ref` requires the ref to be a full 40-char SHA
  (`@sha1_size 40`); if the ref is a short SHA, validation fails earlier
  with a different error.

## Why the message names the commit SHA

`format/1` prints `"#{redact_uri(opts[:git])} - #{rev}"` where
`rev = opts[:branch] || opts[:ref] || opts[:tag]`. So the SHA in the
error is the value from **`mix.exs`**, not from the lock. The
"outdated" label means the lock and `mix.exs` disagree on the *options
keyword list*, not on the commit itself.

## Practical fix recipes

```elixir
# Bad (lock had this when someone ran mix deps.get with tag:):
{:heroicons, github: "tailwindlabs/heroicons", tag: "v2.2.0",
 sparse: "optimized", app: false, compile: false, depth: 1}

# Good (lock has this after re-running mix deps.get with ref:):
{:heroicons, github: "tailwindlabs/heroicons",
 ref: "0435d4ca364a608cc75e2f8683d374e55abbae26",  # 40-char SHA
 sparse: "optimized", app: false, compile: false, depth: 1}
```

After changing `mix.exs`, you **must** re-run `mix deps.get` and commit
the new `mix.lock`. Otherwise the lock still carries the old `tag:`
option and the next `mix compile --env prod` will fail.

## How to verify without redeploying

```bash
# Reproduce the exact Nixpacks install+build sequence:
rm -rf _build/prod
MIX_ENV=prod mix local.hex --force
MIX_ENV=prod mix local.rebar --force
MIX_ENV=prod mix deps.get --only prod
MIX_ENV=prod mix compile
```

If this passes locally but fails in the PaaS, the issue is **not** your
`mix.exs` / `mix.lock` — it's a stale Docker layer or a cache in the
PaaS. Force a clean rebuild (no-cache build, or switch build pack to
Dockerfile with a multi-stage `Dockerfile` you control).

## If you need a different git identifier style

- `tag: "v2.2.0"` — matches the latest commit at that tag; can drift if
  the tag is moved.
- `branch: "main"` — matches the tip of the branch; drifts every push.
- `ref: "<full 40-char SHA>"` — pin to an exact commit; only this gives
  reproducible builds. Use this for production.
