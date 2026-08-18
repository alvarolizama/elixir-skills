# Dual-Line SVG Comparison Chart (Real vs Estimated)

Full recipe for building a cost comparison calculator with a dual-line
SVG chart in Phoenix LiveView. Proven in MyApp's CalculatorLive
(`/dashboard/calculator`, 2026-08).

## When to use

When you need to compare two time-series side-by-side on the same chart
— typically "what actually happened" (real provider cost) vs "what we
estimated" (calculated from custom pricing params). Distinct from:
- **Sparklines** (single compact series, 120×30 viewBox).
- **Stacked bar charts** (multiple categories summing to a total).
- **Bar charts** (distribution, not time-series comparison).

## Architecture

1. **Rollup query** — `hourly_series_for_model/2` returns per-hour
   buckets with token breakdown (prompt, completion, cache_read,
   cache_creation) + real cost (`provider_cost_usd`).
2. **LiveView** — `handle_event("calculate", params, socket)` parses
   form inputs, calls the rollup, computes estimated cost per hour,
   builds chart point strings.
3. **Template** — `<.form phx-change="calculate">` (no submit needed),
   summary cards, SVG chart, hourly breakdown table.

## Rollup query pattern

```elixir
def hourly_series_for_model(model_alias_id, opts \\ []) do
  # WHERE rl.model_alias_id == ^model_alias_id
  # date_trunc('hour', inserted_at AT TIME ZONE tz) AT TIME ZONE tz
  # GROUP BY bucket → count, SUM(cost), SUM(prompt), SUM(completion),
  #   SUM(cache_read), SUM(cache_creation)
  # Returns [%{hour: DateTime, request_count: int, cost_usd: Decimal,
  #   prompt_tokens: int, completion_tokens: int, ...}]
end
```

Uses the same subquery-materialization pattern as `hourly_series/2` —
the `date_trunc(... AT TIME ZONE ?)` expression must be materialized in a
subquery before GROUP BY to avoid the 42803 grouping_error.

## Estimated cost formula

Given user-supplied pricing parameters (all per 1M tokens):
- `cost_input` — price for fresh (non-cached) input tokens
- `cost_cache` — price for cached input tokens (typically cheaper)
- `cost_output` — price for output/completion tokens
- `hit_rate` — fraction of total input that hits cache (0-100%)

### ⚠️ UsageNormalizer already subtracts cache from prompt_tokens

`UsageNormalizer.normalize/2` subtracts `cached_tokens` from
`prompt_tokens` for OpenAI (which includes them in the raw count) so
`prompt_tokens` in the DB is **non-cached input only**. The total input
the model saw is `prompt_tokens + cache_read_tokens`.

**WRONG** (double-counts cache, the initial bug):
```elixir
# This treats prompt_tokens as TOTAL input — but it's already non-cached!
fresh_tokens = trunc(prompt_tokens * miss_rate)
cache_tokens = prompt_tokens - fresh_tokens
```

**CORRECT**:
```elixir
per_million = Decimal.new("0.000001")
hit_rate = parse_float(hit_rate_str, 90.0) / 100.0

# prompt_tokens = non-cached input (already normalized)
# cache_read_tokens = cached input
# total_input = what the model actually saw
total_input = prompt_tokens + cache_read_tokens
sim_cache_tokens = trunc(total_input * hit_rate)
sim_fresh_tokens = total_input - sim_cache_tokens

est_input  = cost_input  |> Decimal.mult(Decimal.new(sim_fresh_tokens))  |> Decimal.mult(per_million)
est_cache  = cost_cache  |> Decimal.mult(Decimal.new(sim_cache_tokens))   |> Decimal.mult(per_million)
est_output = cost_output |> Decimal.mult(Decimal.new(completion_tokens))   |> Decimal.mult(per_million)

estimated_cost = [est_input, est_cache, est_output]
  |> Enum.reduce(Decimal.new(0), &Decimal.add/2)
  |> Decimal.round(6)
```

The "real" cost is `row.cost_usd` from the rollup — this already
includes both `pay_per_token` and `included` billing modes because
`provider_cost_usd` is the single source of truth (included = $0).

### When real cost shows $0.00 with requests > 0

If `provider_cost_usd` is $0 for all rows but `request_count > 0`, it
means the upstream provider doesn't report `usage.cost` (OpenAI direct
doesn't; OpenRouter does). `CostCalculator.provider_cost("pay_per_token", nil)`
returns `$0` by design — no phantom costs. Show a small note under the
card: "El proveedor no reporta costo" when
`Decimal.compare(total_real, 0) == :eq and total_requests > 0`.

## Chart builder function

```elixir
def chart_points(chart_data) do
  width = 800; height = 220
  pad_left = 70; pad_right = 20; pad_top = 10; pad_bottom = 35
  plot_w = width - pad_left - pad_right
  plot_h = height - pad_top - pad_bottom
  count = length(chart_data)

  max_val = chart_data
    |> Enum.map(&max(Decimal.to_float(&1.real_cost), Decimal.to_float(&1.estimated_cost)))
    |> Enum.max()
    |> max(0.01)
    |> (&(&1 * 1.1)).()

  step_x = if count > 1, do: plot_w / (count - 1), else: 0.0

  points = chart_data
    |> Enum.with_index()
    |> Enum.map(fn {row, i} ->
      x = pad_left + i * step_x
      real_y = pad_top + plot_h - (Decimal.to_float(row.real_cost) / max_val * plot_h)
      est_y  = pad_top + plot_h - (Decimal.to_float(row.estimated_cost) / max_val * plot_h)
      {Float.round(x, 1), Float.round(real_y, 1), Float.round(est_y, 1)}
    end)

  real_pts = points |> Enum.map(fn {x, y, _} -> "#{x},#{y}" end) |> Enum.join(" ")
  est_pts  = points |> Enum.map(fn {x, _, y} -> "#{x},#{y}" end) |> Enum.join(" ")

  # Area path: start bottom-left, trace real line, close to bottom-right
  {first_x, _, _} = List.first(points)
  {last_x, _, _}  = List.last(points)
  real_area = "M#{first_x},#{pad_top + plot_h} L#{real_pts} L#{last_x},#{pad_top + plot_h} Z"

  %{real_points: real_pts, est_points: est_pts, real_area: real_area, ...}
end
```

## HEEx template

```heex
<.form for={%{}} id="calculator-form" phx-change="calculate" phx-submit="calculate">
  <select name="model_id">...</select>
  <select name="period">...</select>
  <input name="hit_rate" type="number" min="0" max="100" step="1" />
  <input name="cost_input" type="number" min="0" step="0.01" />
  <input name="cost_cache" type="number" min="0" step="0.01" />
  <input name="cost_output" type="number" min="0" step="0.01" />
</.form>
```

SVG chart with dual polylines:

```heex
<svg viewBox="0 0 800 220" class="w-full h-auto min-w-[600px]">
  <%!-- Y-axis grid + labels --%>
  <line x1={pad_left} y1={tick.y} x2="790" y2={tick.y}
    class="stroke-base-200" stroke-width="0.5" />
  <text x={pad_left - 5} y={tick.y + 4} text-anchor="end"
    class="fill-base-content/40 text-[9px]">${tick.value}</text>

  <%!-- Real cost area + line --%>
  <path d={chart.real_area} class="fill-success/10" />
  <polyline points={chart.real_points} fill="none"
    class="stroke-success" stroke-width="2" />

  <%!-- Estimated cost line (dashed) --%>
  <polyline points={chart.est_points} fill="none"
    class="stroke-primary" stroke-width="2"
    stroke-dasharray="4,2" />
</svg>
```

## Summary cards

5 cards in a responsive grid:
- **Gasto Real** (success) — `Decimal.add` of all `real_cost`
- **Gasto Estimado** (primary) — `Decimal.add` of all `estimated_cost`
- **Diferencia** (success if neg = real < estimated, error if pos)
- **Requests** — sum of `request_count`
- **Tokens Total** — sum of prompt + completion

## Verification

```bash
mix compile --warnings-as-errors
mix test test/<app>_web/live/calculator_live_test.exs
```

Test pattern: register admin via `Accounts.register_user/1`, login via
`post(~p"/login", %{email: ..., password: ...}) |> recycle()`, then
`live(conn, ~p"/dashboard/calculator")`.

```
Result: 2 passed
```

## Pitfalls

- **`form/1` requires `for`** — omitting it compiles but emits a
  runtime warning into the page HTML. Pass `for={%{}}`.
- **`Decimal.from_float/1` on integers** — use `Decimal.new(int)` for
  integer-to-Decimal, `Decimal.from_float/1` only for actual floats.
  `trunc(prompt * miss_rate)` is an integer → wrap with `Decimal.new/1`.
- **Empty chart_data** — guard with `if chart_data == []` before
  computing max/step or you get `Enum.max([])` crash.
- **`Calendar.strftime/2` for x-axis labels** — needs `%d/%m %H:%M`
  format for readable timestamps. `DateTime.to_string/1` is too verbose.