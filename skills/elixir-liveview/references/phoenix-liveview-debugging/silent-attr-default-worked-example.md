# Worked Example: The Silent-Attr-Default Page-Count Bug

## Symptom

Phoenix app sidebar context selector shows "Personal (0)" instead of
"Personal (36)". Direct SQL confirms 36 pages belong to the context. The
context function `page_counts_by_context/0` returns the correct map.

## Investigation Sequence (exact commands)

### 1. Find the data source and its callers

```
read_file lib/my_app/brain.ex
search_files "page_counts_by_context" path=lib/my_app   # whole lib tree
```

Found the function at `lib/my_app/brain.ex:48`. Found ONE caller:
`lib/dran_web/plugs/auth.ex:105` — `assign_to_socket/2`.

### 2. Trace the assign to the socket

`auth.ex:112`:
```elixir
|> Phoenix.Component.assign(:page_counts, page_counts)
```

The assign IS set on the socket. So the data layer is fine.

### 3. Find where the assign is READ in templates

```
search_files "page_counts" path=lib/dran_web   # .ex includes HEEx function components
```

Found the read site: `lib/dran_web/components/layouts.ex:466`:
```elixir
{ctx.name} ({Map.get(@page_counts, ctx.id, 0)})
```

This is inside `context_selector/1`, a **function component** with:
```elixir
attr :page_counts, :map, default: %{}
```

### 4. Check the boundary — is the attr forwarded?

```
search_files "page_counts=" path=lib/dran_web/live
# Result: 0 matches
```

Zero matches across all 22 LiveViews. No LiveView passes `page_counts={@page_counts}`
to `<Layouts.app>`. The attr's `default: %{}` silently kicks in → `Map.get(%{}, ctx.id, 0)` → `0`.

### 5. Confirm the data/types are NOT the problem (red-herring check)

```sql
SELECT id, name, slug, pg_typeof(id) FROM contexts;
-- 1 row: 962037b8-... | Personal | personal | uuid

SELECT context_id, count(*), pg_typeof(context_id) FROM pages GROUP BY context_id;
-- 1 row: 962037b8-... | 36 | uuid
```

Both `Context.id` and `Page.context_id` are `:binary_id` (UUID). The map keys
and the lookup key `ctx.id` are the same type. Types are correct — the bug is
wiring, not data.

## Root Cause

`Auth.assign_to_socket/2` sets `:page_counts` on the LiveView socket, but no
LiveView's `render/1` forwards `@page_counts` to `<Layouts.app>`. The component's
`attr :page_counts, :map, default: %{}` silently returns an empty map, and
`Map.get(%{}, ctx.id, 0)` returns `0`.

## Why the Test Didn't Catch It

The test (`test/dran_web/controllers/session_controller_test.exs:126`) only
asserts on `Brain.page_counts_by_context()` — the function-level result. It
never renders the HTML or checks the LiveView's wired output, so the missing
attr-forwarding goes undetected.

## The Fix (applied in production)

**Chosen: self-fetch in `Layouts.app/1`** — zero caller changes, all 22
LiveViews fixed at once, future LiveViews get it for free. Applied to
`lib/dran_web/components/layouts.ex` in `app/1`:

```elixir
def app(assigns) do
  counts = compute_counts(assigns[:context_slug])

  page_counts =
    case assigns[:page_counts] do
      m when is_map(m) and map_size(m) > 0 -> m
      _ ->
        try do
          my_app.Brain.page_counts_by_context()
        rescue
          _ -> %{}
        catch
          _, _ -> %{}
        end
    end

  assigns = assign(assigns, counts: counts, page_counts: page_counts)
  ~H\"\"\" ... \"\"\"
end
```

Result: selector shows "Personal (36)". Verified: `mix compile
--warnings-as-errors` clean, `mix test` 250/250 passed, live browser check.

(Alternative, rejected: adding `page_counts={@page_counts}` to every
`<Layouts.app>` call — 22 files, and silently breaks again on the next new
LiveView.)

## Key Lesson

The fastest path to this bug is the boundary check (step 4): grep for
`assign_name=` in the LiveView directory. If zero matches, it's a forwarding
bug. Do NOT start with DB/type probes — they'll all pass and waste time.
