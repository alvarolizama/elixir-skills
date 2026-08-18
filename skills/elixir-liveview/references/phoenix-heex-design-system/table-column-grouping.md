# Table Column Grouping (Wide Data Tables)

Worked reference for reorganizing a flat 20-column Phoenix LiveView table
into visual groups with colored sub-headers and vertical separators.
Verified on MyApp's `/dashboard/logs` table (2026-07-28).

## The problem

A table with 15-20 columns in a flat `<thead><tr>` is unreadable — the user
can't tell which columns are related. Related columns (e.g. "Proveedor" and
"Costo real") end up separated by unrelated ones, or a column that belongs
to the identity group (Proveedor) sits among cost columns because it was
added later.

## Solution: grouped header row

### 1. Two-row `<thead>` — group headers + column headers

```heex
<thead>
  <tr class="border-b-0">
    <th colspan="7" class="text-[10px] uppercase tracking-wider text-primary/70 bg-primary/5 border-r border-base-200">
      Identidad
    </th>
    <th colspan="5" class="text-[10px] uppercase tracking-wider text-accent/70 bg-accent/5 border-r border-base-200">
      Request
    </th>
    <th colspan="5" class="text-[10px] uppercase tracking-wider text-info/70 bg-info/5 border-r border-base-200">
      Rendimiento
    </th>
    <th colspan="4" class="text-[10px] uppercase tracking-wider text-success/70 bg-success/5">
      Costos
    </th>
  </tr>
  <tr>
    <th>Fecha</th>
    <th>Modelo</th>
    <th>Usuario</th>
    <th>Equipo</th>
    <th>API Key</th>
    <th>Credencial</th>
    <th class="border-r border-base-200">Proveedor</th>
    <th>Agente</th>
    <th>Estado</th>
    <th>Think</th>
    <th>Effort</th>
    <th class="border-r border-base-200">Streaming</th>
    <th class="text-right">Input</th>
    <th class="text-right">Output</th>
    <th class="text-right">TPS</th>
    <th title="Time to first token — solo streaming">TTFT</th>
    <th class="border-r border-base-200">Latencia</th>
    <th class="text-right">Estimado</th>
    <th class="text-right">Costo</th>
    <th class="text-right">Costo real</th>
    <th class="text-right">Ahorro</th>
  </tr>
</thead>
```

### 2. Body rows mirror the separators

The last `<td>` of each group gets `border-r border-base-200`:

```heex
<tr :for={{id, log} <- @streams.logs} id={id}>
  <td class="whitespace-nowrap text-sm">{format_datetime(log.inserted_at)}</td>
  <td class="text-sm">{model_display(log.model_requested, log.model_responded)}</td>
  <td class="text-sm">{member_email(log)}</td>
  <td class="text-sm">{member_team(log)}</td>
  <td class="text-sm">{log.api_key_prefix || "—"}</td>
  <td class="text-sm">{log.credential_name || "—"}</td>
  <td class="text-sm border-r border-base-200">{provider_name(log)}</td>
  <td>...</td>
  <td class="text-sm border-r border-base-200">{if log.streaming, do: "Sí", else: "No"}</td>
  <td>...</td>
  <td class="text-sm border-r border-base-200">{log.latency_ms}ms</td>
  <td>...</td>
</tr>
```

### 3. Update the empty-state colspan

```heex
<tr id="logs-empty" class="hidden only:table-row">
  <td colspan="21" class="text-center py-8 text-base-content/40">
    No hay logs que coincidan con los filtros.
  </td>
</tr>
```

The colspan must equal the sum of all group colspans (7+5+5+4 = 21).

## Class reference

| Class | Purpose |
|---|---|
| `text-[10px]` | Group header text — small enough to read as a label, not a column header |
| `uppercase tracking-wider` | Makes the group label visually distinct from column headers |
| `text-{semantic}/70` | Foreground color — use daisyUI semantic tokens (primary, accent, info, success) |
| `bg-{semantic}/5` | Background tint — 5% opacity is subtle enough to not compete with zebra striping |
| `border-r border-base-200` | Vertical separator between groups — applied to last `<th>` and `<td>` of each group |
| `border-b-0` on group `<tr>` | Prevents double border between group header row and column header row |

## Column grouping strategy

Group columns by **domain logic**, not by data type:

| Group | What goes here | Example columns |
|---|---|---|
| Identidad | Who/what/when — the row's identity | Fecha, Modelo, Usuario, Equipo, API Key, Credencial, Proveedor |
| Request | Request metadata | Agente, Estado, Think, Effort, Streaming |
| Rendimiento | Performance metrics | Input tokens, Output tokens, TPS, TTFT, Latencia |
| Costos | Financial columns | Estimado, Costo, Costo real, Ahorro |

## Pitfalls

- **Forgetting `border-r` on body `<td>`s** — if only header `<th>`s have
  separators, the visual grouping breaks on row hover (zebra striping
  fills the gap).
- **Wrong `colspan` on empty state** — must be the total column count
  (sum of all group colspans), not the old flat count.
- **Group header on `table-zebra`** — DaisyUI zebra striping can make the
  group header row hard to read. Use `border-b-0` + `bg-{semantic}/5` to
  override the zebra background on the group header row.
- **Reordering columns breaks test selectors** — tests that reference
  column text (not IDs) may break if you move columns. Check tests with
  `search_files` for `logs_live` before reordering.
