# Cache Hit Rate in Stats (Semantic + Multi-File Surfacing)

## The one semantic that matters

`cache_read_tokens` is a **subset** of `prompt_tokens`. OpenAI reports
`prompt_tokens` as the raw total INCLUDING cached input; `cache_read_tokens`
counts only the cache-hit portion. Therefore:

- **hit rate = `cache_read_tokens / prompt_tokens * 100`** — the denominator
  is the full raw input, NOT `prompt - cache_read`. Computing it over
  `prompt - cache_read` overstates the rate.
- `cache_creation_tokens` is a write cost, not a hit — excluded from the rate.
- `format_cache_value(read, creation)` shows the `read + creation` sum but
  returns `"—"` when both are `0`/`nil`, so empty slots stay visually empty.

This is the SAME convention the cost calculator uses: `prompt_tokens` = total
raw, `cache_read_tokens` = the cached subset, and the calculator SUBTRACTS the
subset to bill only the uncached portion. Keep the two consistent.

## Surfacing it in every stats breakdown (my_app_gateway)

The `Cache %` column (tables) and the `in / out / cache · hit%` triplet (KPI
cards) repeat across many places. Adding or fixing cache display touches all of:

1. **Rollup SELECT + return map** — every `breakdown_by_*` that feeds a tokens
   table must add `cache_read_tokens: fragment("COALESCE(SUM(?), 0)", rl.cache_read_tokens)`
   to the SELECT **and** `cache_read_tokens: row.cache_read_tokens` to the
   returned map. In my_app_gateway, `breakdown_by_model` and
   `breakdown_by_provider_for_model` already had it; `breakdown_by_member`,
   `_team`, `_service`, and `_model_for_member` were missing it. Grep every
   `breakdown_by_*` to confirm before wiring a column.
2. **`breakdown_total/1`** — the shared footer aggregator must sum
   `cache_read_tokens` so `x_total.cache_read_tokens` exists for footers. Use
   `Map.get(&1, :cache_read_tokens, 0)` so rows that predate the field don't
   crash the reduce.
3. **Template, per table** — three coordinated edits:
   - header `<th title="Porcentaje de prompt tokens con cache hit">Cache %</th>`
     between "Tokens out" and "TPS";
   - body `<td>` calling `cache_hit_pct(row.prompt_tokens, Map.get(row, :cache_read_tokens, 0))`;
   - footer `<td>` calling `cache_hit_pct(x_total.prompt_tokens, x_total.cache_read_tokens)`.
4. **KPI cards** (team/model/service drilldowns) — add a third segment
   `in / out / cache · hit%` mirroring the main `/dashboard` card, using the
   shared `format_cache_value/2` + `format_hit_rate(cache_hit_rate/2)` helpers
   from `KpiHelpers`. Import them into the LiveView
   (`import TokengateWeb.KpiHelpers, only: [format_cache_value: 2, format_hit_rate: 1, cache_hit_rate: 2]`);
   `cache_hit_pct/2` is a separate local helper that returns a `"42.5%"` string
   directly (used in table cells).

## Pitfalls

- **Patch disambiguation.** The "Tokens out → TPS" header blocks are byte-identical
  across the provider/model/member/team/service tables, so a bare `old_string`
  matches 2–6 times. Anchor on the UNIQUE `<tr :for=... id={"bd-*-...">}` line
  immediately below `</thead><tbody>` to disambiguate. (This session hit
  "Found 2 matches" repeatedly; for the two genuinely-identical model tables
  (teams + services) `replace_all` was correct, the rest needed the id anchor.)
- **Hand edits drift indentation; the patch tool doesn't lint `.heex`.** After
  inline edits run `mix format` on the template, then `mix format --check-formatted`
  before `mix compile` — otherwise `--check-formatted` flags the drift late.
- **Import gap.** Table cells use the LiveView-local `cache_hit_pct/2`; KPI
  cards use `KpiHelpers` helpers. Adding the KPI-card triplet without widening
  the `import ... only:` list fails to compile (`undefined function`).

## Verified in my_app_gateway (2026-08)

Added `Cache %` to provider / model(teams+services) / member / team / service
tables and the member model table, plus `cache · hit%` triplets to the three
drilldown KPI cards. `mix precommit` green (868 tests).
