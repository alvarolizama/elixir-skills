# Table & KPI Card Standardization Conventions

Reusable conventions for Phoenix dashboards with multiple data views (stats, breakdowns, filtered views).

## Table Column Naming (Spanish UI)

Use these exact names everywhere — no abbreviations, no variants:

| ❌ Don't | ✅ Do |
|----------|-------|
| Real | Costo real |
| Estimado / Estimado mercado | Mercado |
| Tok in / Tok out | Tokens in / Tokens out |
| Ahorros | Ahorro |

## Standard Column Order

**Full cost table** (8 cols):
`Entity | Requests | Costo real | Mercado | Ahorro | Tokens in | Tokens out | TPS`

**Compact table** (4 cols, for Top-5 mini-tables):
`Entity | Requests | Costo real | Ahorro`

**Team filter with fewer metrics** (6 cols):
`Entity | Requests | Costo real | Mercado | Ahorro | TPS`

"Entity" = Modelo / Equipo / Usuario / Proveedor · Modelo depending on context.

## Table Styling

```heex
<table class="table table-sm table-zebra">
  <thead>
    <tr>
      <th>Modelo</th>
      <th class="text-right">Requests</th>
      <th class="text-right">Costo real</th>
      <th class="text-right">Mercado</th>
      <th class="text-right">Ahorro</th>
      <th class="text-right">Tokens in</th>
      <th class="text-right">Tokens out</th>
      <th class="text-right">TPS</th>
    </tr>
  </thead>
  <tbody>
    <tr :for={row <- @data} id={"bd-item-#{row.id}"}>
      <td class="font-medium">{row.name}</td>
      <td class="text-right font-mono">{format_number(row.request_count)}</td>
      <td class="text-right font-mono">${format_decimal(row.provider_cost_usd)}</td>
      <td class="text-right font-mono text-base-content/60">${format_decimal(row.estimated_cost_usd)}</td>
      <td class="text-right font-mono text-success">${format_decimal(row.savings_usd)}</td>
      <td class="text-right font-mono">{format_number(row.prompt_tokens)}</td>
      <td class="text-right font-mono">{format_number(row.completion_tokens)}</td>
      <td class="text-right font-mono">{format_tps(row.avg_tps)}</td>
    </tr>
  </tbody>
</table>
```

Key rules:
- Always `table-zebra` for alternating row stripes
- Numeric columns: `text-right font-mono`
- Mercado column: `text-base-content/60` (muted, it's reference price)
- Ahorro column: `text-success` (positive signal)
- Entity column: `font-medium` (bold for scannability)
- Linkable entities: `<.link patch={...} class="link link-hover">`

## KPI Card Pattern

Standard order: **Costo real → Mercado → Ahorro → Requests → Tokens → TPS**

```heex
<div class="grid grid-cols-2 lg:grid-cols-3 gap-4">
  <div class="card bg-base-100 border border-base-300 shadow-sm">
    <div class="card-body p-5">
      <div class="flex items-center justify-between">
        <span class="text-xs font-medium text-base-content/60 uppercase tracking-wide">Costo real</span>
        <span class={["flex items-center justify-center w-9 h-9 rounded-lg", accent_bg("accent")]}>
          <.icon name="hero-currency-dollar" class={["w-5 h-5", accent_text("accent")]} />
        </span>
      </div>
      <p class="mt-2 text-2xl font-bold">${format_decimal(@metrics.provider_cost_usd)}</p>
    </div>
  </div>
</div>
```

Icon mapping:
| Metric | Icon | Accent |
|--------|------|--------|
| Costo real | hero-currency-dollar | accent |
| Mercado | hero-calculator | primary |
| Ahorro | hero-banknotes | success |
| Requests | hero-arrow-trending-up | primary |
| Tokens | hero-cpu-chip | primary |
| TPS | hero-bolt | accent |

Tokens card uses split layout (`flex items-baseline gap-3`) with `in`/`out` sub-labels.

## Cross-Page Consistency

When the same data appears on multiple pages (dashboard, stats, team filter, model filter):
- Same column names everywhere
- Same column order everywhere
- Same `table-zebra` class everywhere
- Same KPI card order and icons everywhere
- Renaming a column on one page means renaming on ALL pages

## HEEx Editing Pitfall: Removing Sections

When removing a section from a HEEx template, watch for:
1. Stray `/>` — if you remove a component opening tag but leave a self-closing `/>` from a child, the parser breaks
2. Mismatched `<% end %>` — each `<%= if ... do %>` needs exactly one `<% end %>`. Removing a section with conditional blocks can leave orphaned `end` tags
3. Orphaned `</div>` — removing a `<div>` wrapper but leaving its closing `</div>`

Always re-read the full section boundaries after a removal and count open/close tags.
