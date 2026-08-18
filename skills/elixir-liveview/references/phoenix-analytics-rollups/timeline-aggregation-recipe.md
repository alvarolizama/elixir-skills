# Timeline / Journey Aggregation Recipe

Proven in `my_app.Journey` (my_app second-brain app, 2026-08). Builds a
chronological "journey" timeline — cells created over time — from an
append-only create-event log, grouped by adaptive period.

## When this beats SQL `date_trunc`

When the log has a `context_id`/`action` filter producing a modest result
set (personal knowledge base, thousands of rows), fetching ordered rows and
grouping in Elixir is simpler and just as fast as SQL bucketing. The plan
deliberately skips adding a composite `(context_id, inserted_at)` index:
Postgres uses the existing `context_id` index + in-memory sort for personal
volumes. Only add the composite index if >100k rows/context.

## Data shape

Log rows like `%{subject, details: %{page_type, created_by}, inserted_at}`
where `inserted_at` is `:utc_datetime` (an Elixir `DateTime`).

## The four pieces that make it a "timeline", not just a histogram

1. **Query** — filter by `context_id` AND `action` (`"page.create"`),
   `order_by: [asc: inserted_at]`. Empty result → return an `empty_payload/0`
   with every key shape preserved (buckets `[]`, total 0, stats zeros,
   trajectory `[]`, axis/range nils). LiveView can render the empty state
   without a nil-checking branch on a different shape.

2. **Adaptive granularity** — pick day/month/year from span:
   - `span <= 32 * 86_400` → `"day"`
   - `span <= 18 * 30 * 86_400` → `"month"`
   - else → `"year"`
   Suggested via a `suggest_granularity(min_ts, max_ts)` public function so
   it's independently unit-testable with bare unix-seconds.

3. **Buckets** — `Enum.group_by(e -> period_key(e.inserted_at, granularity))`
   where the key is a compound tuple `{y,m,d}` / `{y,m}` / `{y}`. Tuples
   sort chronologically with plain `Enum.sort_by(fn {key,_} -> key end)`
   — no string date keys needed. Then per bucket compute `label`
   (from the bucket's start timestamp → unix → `DateTime.from_unix!`),
   `pages` (project each row to `%{slug, page_type, created_by}`),
   `total`, `recency` (normalized 0..1 position within span), and
   `dominant_type` (`Enum.frequencies_by(& &1.page_type)` max).

4. **Cumulative trajectory (sparkline)** — running total across buckets:
   `Enum.scan(0, fn b, acc -> acc + b.total end) |> Enum.drop(1)`. Last
   point equals total. This yields the monotonic cumulative line for a
   growth sparkline; assert `result == Enum.sort(result)` in tests.

## Two time-conversion helpers (utc_datetime safety)

`inserted_at` may arrive as `%DateTime{}` or `%NaiveDateTime{}` depending on
schema/DB. Handle both:

```elixir
defp to_unix(%DateTime{} = dt), do: DateTime.to_unix(dt)
defp to_unix(%NaiveDateTime{} = ndt),
  do: ndt |> DateTime.from_naive!("Etc/UTC") |> DateTime.to_unix()
```

Same dual-dispatch for `period_key/2`. In `period_key`, convert NaiveDateTime
to UTC DateTime first, then match on the DateTime clauses.

## Deterministic per-category colors (golden-angle HSL)

Assign a color to each `page_type` deterministically with golden-angle hue
spacing so adjacent types differ and the map is stable across renders:

```elixir
types |> Enum.with_index() |> Enum.map(fn {t, i} ->
  hue = rem(round(i * 137.508), 360)
  {t, hsl_to_hex(hue, 0.55, 0.62)}
end) |> Map.new()
```

`hsl_to_hex/3` is the standard HSL→RGB→hex conversion (c, x, m sector math,
clamp 0..255, pad-2 hex). Verify determinism + distinctness in tests:
`colors == Journey.type_colors()` and
`colors |> Map.values() |> Enum.uniq() |> length() == map_size(colors)`.
A golden-angle spacing value assertion (`colors["note"] == "#D36969"`)
locks the math to the plan.

## Test conventions for this pattern (my_app)

- `use my_app.DataCase, async: false`.
- `setup` disables inference so `create_page` doesn't call external
  embedding/rerank APIs:
  ```elixir
  original = Application.get_env(:my_app, :inference)
  Application.put_env(:my_app, :inference, base_url: nil, api_key: nil,
    embedding_model: nil, rerank_model: nil, timeout: 100, schedule_async: false)
  on_exit(fn -> original |> is_nil() |> ...restore or delete end)
  ```
- Create an isolated context per test (`Brain.create_context`) rather than
  sharing "personal", so queries only see that test's rows.
- TDD: write test → confirm RED (`module my_app.Journey not compiled`) →
  implement → GREEN → `mix compile --warnings-as-errors`.
