# UI Shows Zero — Data-Flow Tracing Methodology

## The class of bug

The UI displays a zero, empty, or null value for a count/list, but the
database clearly has the data. This is NOT a data-layer bug — it is a
**data-forwarding bug**: the data exists but doesn't reach the template
because some link in the assigns → component → template chain is broken.

## The forwarding chain (Phoenix LiveView)

For a value to render in a LiveView template, it must survive this entire
chain:

```
DB → Ecto query → Context module function → Plug/Auth assigns to socket
  → LiveView mount reads from socket → LiveView render passes to <Layouts.app>
  → Layout component attr → nested component (e.g. context_selector)
  → Map.get/lookup in HEEx template
```

A break at ANY link produces `0` or `nil` in the UI, even though the DB and
Ecto query are correct.

## Systematic tracing procedure

### Step 1: Confirm the data exists (psql)

```bash
psql -U brain -d dran_dev -c "SELECT context_id, COUNT(*) FROM pages GROUP BY context_id;"
```

If data exists → data layer is NOT the problem (unless there's a type
mismatch, which Step 2 rules out). Do NOT re-run this query.

### Step 2: Confirm the Ecto query returns correct data with correct types

```bash
mix run --no-start -e '
Application.ensure_all_started(:postgrex)
Application.ensure_all_started(:ecto_sql)
{:ok, _} = my_app.Repo.start_link()

r = my_app.Brain.page_counts_by_context()
IO.inspect(r, label: "counts")
k = Map.keys(r) |> List.first()
IO.inspect(is_binary(k), label: "first key is_binary")

# Simulate the EXACT lookup the template does
contexts = my_app.Brain.list_contexts()
Enum.each(contexts, fn ctx ->
  IO.inspect({ctx.name, ctx.id, Map.get(r, ctx.id, 0)}, label: "UI lookup result")
end)
'
```

Key things to verify:
- **Map key type**: `binary_id` UUIDs come back as **strings** from Ecto
  queries (`"962037b8-..."`), not binaries/atoms.
- **`ctx.id` type**: also a string (from `:binary_id` schema).
- **`Map.get(map, ctx.id, 0)` result**: if this returns the correct count,
  the data layer and lookup logic are both correct. The bug is upstream in
  the rendering chain.

If the Ecto probe returns the correct count and `Map.get` works → STOP
probing the data layer. The bug is in the UI rendering chain.

### Step 3: Trace the assigns → component forwarding

This is where the bug usually hides. Check each link:

**Link A — Plug assigns to socket:**
Find the plug/callback that loads the data and assigns it:

```bash
search_files("page_counts_by_context|page_counts", path="lib/myapp_web/plugs")
```

Verify it does `assign(socket, :page_counts, page_counts)` — this is usually
correct (the data IS loaded).

**Link B — LiveView mount calls the plug:**
```bash
search_files("assign_to_socket|Auth.assign", path="lib/myapp_web/live")
```

Verify each LiveView's `mount/3` calls the function that assigns `page_counts`.

**Link C — LiveView render passes the assign to the layout component:**
This is the MOST COMMON failure point. Check the `<Layouts.app>` call:

```bash
# Find all Layouts.app invocations
grep -rn 'Layouts.app' lib/myapp_web/live/
```

Then read each invocation and verify it passes the assign:

```elixir
# BROKEN — page_counts NOT passed, defaults to %{} in the component
<Layouts.app
  flash={@flash}
  current_scope={@current_scope}
  contexts={@contexts}
>

# FIXED — page_counts forwarded to the layout
<Layouts.app
  flash={@flash}
  current_scope={@current_scope}
  contexts={@contexts}
  page_counts={@page_counts}   # ← this was missing
>
```

**Why this is the common failure point:** Phoenix function components with
`attr :foo, :map, default: %{}` silently default to `%{}` when the attr is
not passed. There is NO compile error or warning — the component just gets an
empty map and `Map.get(%{}, key, 0)` returns the default `0`.

### Step 4: Confirm the fix

After adding the missing attr pass-through, the fix is verified by:
1. The UI now shows the correct count (e.g. "Personal (36)").
2. No data layer changes needed.

## Root cause pattern summary

| Symptom | Likely cause | Where to look |
|---------|-------------|---------------|
| UI shows 0 but DB has data | Missing attr in `<Layouts.app>` call | `grep -rn 'Layouts.app' lib/*/live/` |
| UI shows 0, Ecto also returns 0 | Query filter / WHERE clause wrong | Context module function |
| UI shows 0, Ecto returns correct count, `Map.get` returns 0 | Type mismatch (binary vs string UUID) | Schema `@primary_key` type vs query return |
| UI shows 0 for ONE context but not others | Duplicate context rows / wrong context selected | `SELECT * FROM contexts` for duplicates |

## Generalization

This methodology applies to ANY "UI shows default/empty but data exists"
bug in Phoenix LiveView, not just page counts. The chain is always:
DB → Ecto → Context function → assigns → component attr → template lookup.
Trace it link by link, and the break is usually at the assigns → component
attr boundary, because `attr :foo, default: ...` silently masks missing
pass-throughs.
