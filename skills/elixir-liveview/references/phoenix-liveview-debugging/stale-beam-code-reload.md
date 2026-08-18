# Stale Beam Code in a Running Dev Server

## Symptom

A Phoenix dev server (`mix phx.server`) shows old UI / old logic even after you
edited and recompiled the file. The `.beam` on disk is newer than the source,
but the rendered output still matches the previous version of the module.

Classic tell: a tooltip/text that the new code would render differently keeps
showing the old string.

## Root Cause

The BEAM VM loads modules into memory once. Phoenix's dev code reloader picks
up most recompiles, but not always — especially for modules rendered inside a
long-lived layout/component chain or when the reload watcher did not fire. The
process keeps running the module version that was loaded at boot.

## Diagnostic (authoritative — do this before guessing)

Check whether the *running* module actually has your new function. Spin a
throwaway script in the same `MIX_ENV` the server runs:

```bash
MIX_ENV=dev mix run -e '
  funcs = MyAppWeb.Layouts.__info__(:functions)
  IO.inspect(Keyword.has_key?(funcs, :my_new_function), label: "new fn loaded?")
  IO.inspect(:code.which(MyAppWeb.Layouts), label: "beam path")
'
```

- `new fn loaded? → false` ⇒ the running VM has the OLD module. Restart the server.
- `true` ⇒ code is current; the bug is elsewhere (data, assigns, another layer).

Compare beam mtime vs source mtime only as a first hint — the `__info__` probe
is the ground truth about what the live VM holds.

## Fix

Restart the dev server (kill the `beam.smp`/`mix phx.server` PID and relaunch).
Do not trust a recompile alone to refresh a long-running process.

## Pitfalls

- Don't assume "the beam file is newer" means the server reloaded it — verify in
  the running VM with `__info__`.
- A stale server makes every subsequent code-based hypothesis wrong: you end up
  debugging logic that isn't even running. Rule out staleness FIRST when UI
  doesn't match the code you just wrote.
- The same applies to long-running releases in prod: a new build is not live
  until the release is redeployed — the old release keeps serving old modules.

## Related

- Prod equivalent: production serving stale code means the deploy didn't pick up
  the new commit — check the release build timestamp vs the latest commit, not
  just "is the commit pushed".
