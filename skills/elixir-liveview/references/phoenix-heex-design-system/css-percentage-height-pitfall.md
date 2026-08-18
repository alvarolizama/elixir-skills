# CSS Percentage-Height Pitfall

## The Problem

When a child uses `height: X%`, the parent must have an explicit height. Wrapping a percentage-height element in a `div` without intrinsic height silently collapses it to 0px — the element becomes invisible.

## Broken Pattern (bar disappears)

```heex
<div class="flex items-end h-32">          <%!-- parent: explicit height --%>
  <div class="flex-1 h-full">             <%!-- column: h-full OK --%>
    <div class="relative w-full">         <%!-- wrapper: NO height → 0px --%>
      <div style="height: 45%"></div>     <%!-- 45% of 0 = invisible --%>
    </div>
  </div>
</div>
```

The `div.relative.w-full` has no explicit height, no `h-full`, nothing. The bar inside it calculates `45% of 0px = 0px`. Silent failure — no compile error, no runtime error.

## Fixed Pattern (relative on the bar itself)

```heex
<div class="flex items-end h-32">
  <div class="flex-1 h-full">
    <div class="relative" style="height: 45%">  <%!-- relative ON the bar --%>
      <div class="absolute -top-7 ...">tooltip</div>
    </div>
  </div>
</div>
```

No wrapper div. The `relative` positioning goes directly on the percentage-height element. The tooltip uses `absolute` relative to the bar.

## Rule

**Never wrap a percentage-height element in an extra div.** If you need `position: relative` for absolute children (tooltips, badges, labels), add it directly to the percentage-height element.

## Why This Happens

CSS percentage heights resolve against the **containing block's height**. If the containing block's height is `auto` (determined by content), the percentage is treated as `auto` — which for `height` means 0 if there's no content. A wrapper `div` with no explicit height creates this `auto` containing block.

The parent chain must be: `h-32` (explicit) → `h-full` (inherits) → `height: 45%` (resolves against h-full = h-32). Adding any `div` without height in this chain breaks the resolution.
