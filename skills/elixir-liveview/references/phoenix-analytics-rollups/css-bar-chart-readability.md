# CSS Bar Chart Readability for Analytics Dashboards

Patterns from MyApp's `hour-distribution` chart readability fix (2026-08-07).
Applies to ANY hand-rolled CSS/div bar chart in LiveView dashboards — no JS
charting library required.

## Problem: linear scale hides the small bars

Hour-of-day request distributions have extreme skew: lunch-hour peaks of
thousands of requests, madrugada valleys of single digits. With a linear
scale (`requests / max * 100`), the valley bars render at <1% height (~1px)
and look EMPTY — the user reads it as "faltan datos en las barras".

## Fix 1: sqrt scale + minimum height floor

```elixir
def hour_usage_bar_height(requests, max) when max > 0 do
  pct = :math.sqrt(requests / max) * 100
  max(Float.round(pct, 1), 8.0)  # floor: valleys stay visible
end

def hour_usage_bar_height(_requests, _max), do: 0
```

sqrt compresses peaks (max still = 100%) while lifting valleys
(a 1%-of-max bar becomes 10%). Order is preserved; honest relative reading
stays possible. Disclose it in the card copy: "Escala √ para hacer visibles
las horas de poco uso."

## Fix 2: Y axis with nice-number ticks, positioned on the same scale

Generate ticks with a "nice ceiling" (1/2/5 × 10^n), then place labels and
gridlines using the SAME sqrt transform as the bars — a linearly-positioned
tick on a sqrt chart is a lie.

```elixir
def nice_ceiling(value) when value <= 0, do: 10
def nice_ceiling(value) do
  exp = :math.log10(value) |> Float.floor() |> round()
  base = :math.pow(10, exp)
  fraction = value / base
  nice_fraction = cond do
    fraction <= 1 -> 1
    fraction <= 2 -> 2
    fraction <= 5 -> 5
    true -> 10
  end
  round(nice_fraction * base)
end

def y_axis_ticks(max, count \\ 3) do
  ceiling = nice_ceiling(max)
  1..count |> Enum.map(fn i -> round(ceiling * i / count) end) |> Enum.uniq()
end
```

```heex
<div class="relative h-36 w-10 shrink-0">
  <span :for={tick <- y_ticks}
        class="absolute right-0 text-[9px] text-base-content/50 tabular-nums -translate-y-1/2"
        style={"bottom: #{:math.sqrt(tick / max) * 100}%"}>
    {format_number(tick)}
  </span>
</div>
<%!-- dashed gridlines at the same positions, inside the chart container --%>
<div :for={tick <- y_ticks}
     class="absolute left-0 right-0 border-t border-base-300/50 border-dashed"
     style={"bottom: #{:math.sqrt(tick / max) * 100}%"} />
```

## Fix 3: per-bar tooltip via pure CSS `group-hover`

No JS hook needed. The bar wrapper gets `group relative`; the tooltip is a
`hidden group-hover:block absolute` sibling positioned above the bar:

```heex
<div class="group relative flex-1 flex flex-col items-center justify-end h-full"
     phx-mouseover="hour_hover" phx-value-hour={row.hour} phx-mouseleave="hour_leave">
  <div class="hidden group-hover:block absolute -top-1 -translate-y-full left-1/2 -translate-x-1/2 z-20 pointer-events-none">
    <div class="bg-base-300 text-base-content text-[10px] rounded-md px-2.5 py-1.5 shadow-lg whitespace-nowrap">
      <div class="font-semibold">{hour_label(row.hour)} · {format_number(row.total_requests)} req</div>
      <div :if={row.included_requests > 0} class="text-base-content/70">
        included: {format_number(row.included_requests)}
      </div>
      <div :if={pay_per_token_requests(row) > 0} class="text-base-content/70">
        pay_per_token: {format_number(pay_per_token_requests(row))}
      </div>
    </div>
  </div>
  <%!-- the bar itself --%>
</div>
```

Pitfall: `relative` MUST be on the same element that has `group`, or the
absolute tooltip anchors to the wrong container. Keep `pointer-events-none`
on the tooltip or it swallows the mouseover and flickers.

## Fix 4: solid colors, not washed-out `/40` variants

daisyUI semantic colors at 40% opacity (`bg-primary/40`, `bg-secondary/40`)
all render as indistinguishable dark-muddy segments on small bars. Use the
SOLID class (`model_color/1`, not `model_color_light/1`) for both the bar
segments AND the legend swatches — if the two disagree, the legend lies.
Delete the orphaned light helper when nothing else references it.

## Fix 5: denser X labels with a visual hierarchy

Every-6-hours labels leave 5 unlabeled bars between ticks — impossible to
pinpoint an hour. Label every 3rd hour, but weight every 6th heavier:

```heex
<span :if={rem(row.hour, 3) == 0}
      class={[
        "text-[10px]",
        if(rem(row.hour, 6) == 0,
          do: "text-base-content/60 font-medium",
          else: "text-base-content/40")
      ]}>
  {hour_label(row.hour)}
</span>
```

Remember the Y-axis column shifts the bars right — offset the label row to
match (`ml-12` for a `w-10` axis + `gap-2`).

## Verification

Unit-test the scale helpers (sqrt math, floor, zero-max, nice ceilings,
tick ascending-ness) as pure functions in the LiveView's test file. For the
rendered result, the existing integration tests (`has_element?(view,
"#hour-distribution")`) suffice — visual feel still needs a human eyeball
pass; say so instead of claiming "se ve bien".
