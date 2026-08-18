# Compact dashboard/metric tables (user-approved pattern)

For dense stats tables inside dashboard cards (e.g. MyApp's model catalog with per-scope metrics). All conventions below come from Álvaro's live corrections (2026-08).

## Badge placement: inline with the name, never a dedicated column

- **Rating/tier badges go BEFORE the entity name.** Reuse the same scoring source and badge colors as the dedicated stats page — don't invent a second ranking. In MyApp: `Rollup.model_ranking(nil, from:, to:)` → `model_id → tier` map assign, plus a `tier_badge_class/1` helper copied from `stats_live.ex` (S→`badge-success`, A→`badge-info`, B→`badge-warning`, C→`badge-warning badge-outline`, D→`badge-error`, nil→`badge-ghost` showing "—"). One batched query in the loader, NOT per-row lookups.
- **Category badges (e.g. `model_type`) go AFTER the name and render the raw value dynamically**: `{model.model_type}` + a small `model_type_badge_class/1` helper (`"embedding"`→`badge-info`, `"rerank"`→`badge-warning`, `_`→`badge-ghost`). Do NOT hardcode one HEEx branch per type with fixed labels — Álvaro: "no es llm no mas, puede ser segun el tipo del modelo". A future type added to the schema should appear automatically with the catch-all color.
- **Never hide the default value.** First iteration showed "—" for `llm` (the schema default) and Álvaro reported it as broken: "no se carga el tipo aquí". Then a later iteration dropped the `llm` badge again and he corrected: "pero quitaste el tipo, deben verse los dos". Rule: **badge every value, including defaults**.
- **A column of "—" cells looks like the column failed to load.** If most rows render "—", the design is wrong, not the data.

## Long free-text cells: constrain width AND wrap, never truncate

Álvaro rejected `truncate` + ellipsis explicitly ("mas que truncado que sea wrap de la line para que se vaya a una segunda"):

```heex
<td class="py-1.5 text-base-content/60 max-w-48">
  <div class="whitespace-normal break-words">
    {model.description || "—"}
  </div>
</td>
```

`max-w-48` (or similar) on the `<td>` + `whitespace-normal break-words` on an inner div lets text flow to a second line instead of eating the row width or clipping.

## Multi-scope metric cells (user / team / org)

Same two-line shape for every metric column (requests, latency, cost, tokens):

```heex
<td class="py-1.5 text-right tabular-nums text-base-content/70">
  <%= if stats.user.request_count > 0 do %>
    <div>{format_compact(stats.user.request_count)}</div>
    <div class="text-[10px] text-base-content/40">
      {format_compact(stats.team.request_count)} / {format_compact(stats.org.request_count)}
    </div>
  <% else %>
    —
  <% end %>
</td>
```

- Primary scope (user) full-size on top; secondary scopes in one `text-[10px] text-base-content/40` line as `team / org`.
- Header carries the explanation in a `title` tooltip: `title="Requests (user / team / org)"`.
- When Álvaro asks for a new metric "de la misma forma que gasto latencia y tokens", clone this exact shape — don't freestyle a new layout.
