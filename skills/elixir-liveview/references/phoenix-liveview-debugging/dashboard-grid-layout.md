# Dashboard Grid Layout — Equal-Width & Equal-Height Cards

## Symptom

A Phoenix LiveView dashboard shows multiple cards in a grid. Cards have
different heights (one has a table, another just text, another buttons)
and different widths because some span more columns than others. The user
reports: "las filas tienen diferente tamaño" or "no tienen el mismo ancho".

## Root Cause

Two separate issues:

1. **Height**: Cards are in the same grid but each has intrinsically
   different content. `h-full` only works when the grid row itself has a
   height; if one card is 253px and another 79px, the grid row stretches
   to 253px and `h-full` fills it — but if cards are in *different* rows
   (e.g. one spans 3 columns and wraps to its own row), `h-full` does
   nothing.

2. **Width**: Cards use `col-span` to force some wider than others.
   E.g. `md:col-span-2 lg:col-span-3` makes the models card span the full
   grid width while team cards take 1 column each.

## Fix Strategy

### Same width for all cards

Put all cards in the **same grid** and give each the **same column span**.
If you want them stacked vertically (full width), use `grid-cols-1` for
every card:

```heex
<div class="grid grid-cols-1 gap-4">
  <div class="card">Team card</div>
  <div class="card">Models card</div>
  <div class="card">Supervised card</div>
</div>
```

If you want them side-by-side, use the same `grid-cols-N` and no
`col-span` overrides:

```heex
<div class="grid grid-cols-1 md:grid-cols-3 gap-4">
  <div class="card">Team</div>
  <div class="card">Models</div>
  <div class="card">Supervised</div>
</div>
```

### Same height for all cards

Add a **uniform `min-h-[Xpx]`** to every card where `X` is the height of
the tallest card. Then use `flex flex-col h-full` inside each card so
content distributes evenly:

```heex
<div class="card min-h-[253px] h-full">
  <div class="card-body flex flex-col h-full">
    <!-- header -->
    <div class="mt-auto">
      <!-- pushed to bottom -->
    </div>
  </div>
</div>
```

### When to use `mt-auto`

Use `mt-auto` on the last section of a card to push it to the bottom,
creating a uniform "footer" look even when content above varies.

## Checklist

- [ ] All cards in the SAME grid container (not separate `<section>`s)
- [ ] Same `col-span` (or no span) for equal width
- [ ] Same `min-h-[Xpx]` for equal height
- [ ] `h-full` on the card + `flex flex-col h-full` on `card-body`
- [ ] `mt-auto` on the bottom section for uniform alignment
