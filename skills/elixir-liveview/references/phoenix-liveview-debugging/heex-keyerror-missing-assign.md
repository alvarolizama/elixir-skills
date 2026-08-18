# HEEx `@foo` is `Map.fetch!/2` — KeyError When Assign Is Missing

**Class:** runtime `KeyError` in a HEEx template because `@foo`
expands to `Map.fetch!(assigns, :foo)`, which raises when the key is
absent. Distinct from compile-time HEEx parser errors and from the
silent-attr-default bug (that one falls back to `default: %{}`; this
one crashes).

## The mechanism

In HEEx, `@foo` is NOT `Map.get(assigns, :foo)` — it is
`Map.fetch!(assigns, :foo)`. If the assign doesn't exist in the
socket's assign map, the template crashes at render time with:

```text
** (KeyError) key :foo not found in: %{active_tab: "users", ...}
```

This happens when:

1. **Build mismatch across deploy targets.** The template references
   `@wiki_google_open_signup` (added in commit X), but the production
   build is older than commit X and the `mount/3` that sets the assign
   doesn't include that line. The template (also from commit X)
   shouldn't exist either — BUT if a partial deploy, hot-patch, or
   mixed-state build serves the new template with the old module, the
   assign is never set. Result: `KeyError` on every page that renders
   that template region.

2. **Assign set in `mount/3` but `mount/3` crashes or returns early.**
   If a line before the assign raises, none of the assigns below it
   exist. The template still tries to render → `KeyError`.

3. **Conditionally-rendered template region references an assign that
   only exists in one code path.** E.g. a `:if={DranWeb.OAuth.Google.configured?()}`
   block references `@wiki_google_open_signup`. On builds where the
   assign exists this is fine (the block renders). On builds where it
   doesn't, the `:if` may still evaluate the attr expression on some
   LiveView lifecycle hooks.

## Real cases (my_app, two sessions in a row)

### Case 1: `@context[:slug]` → `UndefinedFunctionError` (previous session)

`@context[:slug]` in a HEEx template. `@context` is a struct (`%Context{}`),
not a map. Access syntax `struct[:key]` calls `Access.get/2`, which
calls `struct.__struct__() |> Map.fetch(key)` — but `Context` does not
implement `Access`. Result: `UndefinedFunctionError`.

Fix: `@context && @context.slug` (dot access on structs, with a nil guard).

### Case 2: `@wiki_google_open_signup` → `KeyError` (this session)

Template line:
```heex
<input type="checkbox" checked={@wiki_google_open_signup} ... />
```

`mount/3` line 66 sets `wiki_google_open_signup: Settings.get(...)`.
But on a production build older than the commit that added this line,
the assign never exists → `KeyError` on `/settings`.

Fix: guard with `Map.get/3`:
```heex
checked={Map.get(assigns, :wiki_google_open_signup, false)}
```

Degrades gracefully to `false` (toggle unchecked) instead of crashing.

## The fix pattern

### Defensive: use `Map.get(assigns, :key, default)` in the template

When an assign's existence depends on a feature flag, a recent commit,
or a conditional mount path, don't use `@key` — use:

```heex
<!-- Instead of @wiki_google_open_signup -->
checked={Map.get(assigns, :wiki_google_open_signup, false)}
```

This is the template-level equivalent of `assigns[:key]` (the
bracket-access form that returns `nil` instead of raising).

**When to use this:**
- The assign was recently added and not all deploy targets have the
  new `mount/3` code yet.
- The assign is set inside a `:if` block in `mount/3` that may not
  execute on all code paths.
- You're fixing a production `KeyError` and can't redeploy the
  full fix immediately — the `Map.get` guard is a safe hotfix.

**When NOT to use this:**
- The assign is always set in `mount/3` and the build is consistent.
  `@foo` is more readable and the `KeyError` would catch real bugs
  (a missing assign that SHOULD be there).
- Don't blanket-replace all `@foo` with `Map.get` — that masks genuine
  wiring bugs.

### Root cause: ensure the assign always exists

The real fix is making sure `mount/3` always sets the assign:

```elixir
# mount/3 — always assign, even if the value is a default
socket
|> assign(wiki_google_open_signup: Settings.get("wiki_google_open_signup") == true)
```

And ensuring the deploy target runs a build where both the `mount/3`
line and the template exist together (same commit).

## Diagnostic recipe

When you see `KeyError: key :foo not found in: %{...}`:

1. **Grep the template** for `@foo` — confirm the reference.
2. **Grep `mount/3`** for `assign(` containing `:foo` — is it set?
3. **If set in mount**: the build is stale / partial. Check which
   commit added the assign and whether the deploy target has it.
   `git log --oneline -- <file>` + the deploy's build hash.
4. **If NOT set in mount**: the assign was never wired. Add it to
   `mount/3`.
5. **Quick fix**: `Map.get(assigns, :foo, default)` in the template
   to stop the crash while the real deploy propagates.

## Related

- `references/heex-parser-and-clause-bugs.md` — HEEx *compile-time*
  parser errors (different class — this file is *runtime* KeyError).
- `references/silent-attr-default-worked-example.md` — function
  component attrs with `default: %{}` silently returning empty (a
  *silent* bug, not a crash).
- `references/layout-assign-boundary.md` — layout function components
  don't inherit socket assigns (same symptom family, different cause).
- `references/stale-beam-code-reload.md` — running VM serving old
  modules after a deploy (another cause of "template references
  something the code doesn't set").
