# Logs Table Colspan Maintenance (Grouped Headers + Empty State)

Companion to `request-log-denormalization.md` ("Table column count maintenance").
That doc covers the empty-state row; this doc covers the GROUPED header row —
they are independent counts and both drift when columns move.

## The table has THREE counts to keep in sync

my_app_gateway's logs table (and any grouped-header table) has:

1. **Group header row** — `<th colspan="N">` per visual section
   (Cliente / Proveedor / Respuesta / Rendimiento / Costos). Each N is the
   number of leaf `<th>` columns UNDER that group.
2. **Leaf header row** — one `<th>` per column.
3. **Empty-state row** — `<td colspan="TOTAL">` (hidden until zero rows).

A column that MOVES between groups (not added/removed) keeps the total constant
but breaks the group rows: e.g. Input/Output belong under "Rendimiento", but
after a refactor "Respuesta" carried colspan=5 and swallowed Input, shifting
every later group border one column left — visible as misaligned section
borders, not a rendering error, so it survives review.

## Detection and fix

1. Count leaf `<th>` entries in the second header row.
2. Walk the groups: for each `<th colspan>`, verify the span equals the number
   of leaf columns that semantically belong to it.
3. Fix any drifted `colspan` values AND re-verify the empty-state colspan
   (sum of groups == leaf count == empty-state colspan).

## Session evidence (2026-08)

Input was visually under "Respuesta" but semantically belongs to
"Rendimiento". Drift: Respuesta 5→4, Rendimiento 5→6, Costos 4→1,
empty-state 25→22 (leaf count 22). Fix was colspan-only; no markup reorder,
no test changes needed beyond `mix precommit`.

## Why it slips through

- Group misalignment renders as slightly-off section borders — no console
  error, no test failure, no crash.
- Stream rows (`phx-update="stream"`) have no `<td>` count assertions in
  LiveView tests; header colspan is invisible to `render/1` assertions unless
  explicitly checked.
- The empty-state row is `hidden only:table-row` — only visible at zero rows.
