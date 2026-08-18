# Stacked bar chart with interactive model legend

Pattern for a per-hour stacked bar chart where each model gets a distinct
color and hovering a bar updates a side legend panel.

## Architecture

- **Query** returns 24 rows (hours 0-23) with `total_requests`, `total_cost_usd`,
  and `models: [%{model, requests, cost_usd, billing_mode}]`.
- **Stacked bars**: computed client-side via `model_segments/2` helper that
  turns hour data into `[%{model, height_pct, color}]` segments.
- **Legend panel**: right-side column showing per-model breakdown with color
  chips, request count, and cost.
- **Hover interaction**: `phx-mouseover="hour_hover"` + `phx-mouseleave="hour_leave"`
  → `legend_data/2` switches between "total period" and "hour N" view.

## Key implementation details

### Color palette (8 colors, cycling)

```elixir
def model_color_light(index) do
  colors = ["bg-primary/40", "bg-secondary/40", "bg-accent/40",
            "bg-success/40", "bg-warning/40", "bg-error/40",
            "bg-info/40", "bg-neutral/40"]
  Enum.at(colors, rem(index, length(colors)))
end
```

### Segment computation

Each model gets `height_pct = model_requests / hour_total * 100`.
Segments stack bottom-up (`flex-col-reverse`) and only show models present
in that hour. Empty model is skipped.

### `legend_data/2` dual mode

- `hovered_hour == nil` → aggregates ALL hours (sum by model)
- `hovered_hour == N` → shows only hour N's data

Both modes return the same shape: `%{entries: [...], total_requests, total_cost_usd}`.

### `Enum.find` default must include ALL map keys

When a model isn't present in a specific hour, `Enum.find` falls back to
a default. The default must include EVERY key accessed later —
`:billing_mode` omission caused `KeyError`.

```elixir
# WRONG: missing :billing_mode
%{requests: 0, cost_usd: Decimal.new(0)}

# RIGHT
%{requests: 0, cost_usd: Decimal.new(0), billing_mode: "unknown"}
```

### `COALESCE` not `||` in Ecto selects

Ecto rejects short-circuit operators in `select/3`:
```
** (Ecto.Query.CompileError) short-circuit operators are not supported: `||`
```

Use `fragment("COALESCE(?, ?)", a, b)` instead.
