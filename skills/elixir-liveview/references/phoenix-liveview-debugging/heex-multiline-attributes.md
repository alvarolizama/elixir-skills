# HEEx attribute multi-line pitfalls

This class of HEEx parse errors shows up when a LiveView attribute value
is a block expression rather than a single-line `elixir`.

## Symptom

```
** (Phoenix.LiveView.TagEngine.Tokenizer.ParseError) unmatched closing tag.
   Expected </stat_card> for <stat_card> at line 356, got: </div>
```

The parser loses track of which tags are open when the attribute
expression spans multiple lines with implicit return (a `case`/`cond`
without explicit `do/end`).

## Why it happens

HEEx's `<Component attr={...}>` parses the brace block as a single
expression. Multi-line `case`/`cond`/`if` with implicit `do:` and no
explicit `end` token are normal Elixir — but HEEx often can't tell the
end of the expression from the end of the next line. Adding a sibling
component (e.g. `</div>` for `<div class="grid">`) confuses the matcher
into closing the wrong tag.

## Triggers

```heex
   <.stat_card
     label="Último request"
     value={
       case @summary_5d.last_request_at do
         nil -> "—"
         dt -> format_datetime(dt, @timezone)
       end
     }
     sub="latency prom: " <> fmt_ms(@summary_5d.avg_latency_ms)
     icon="hero-clock"
   />
```

```heex
   <.input
     title={
       cond do
         not ap.enabled -> "Activar"
         provider_active?(ap) -> "Desactivar"
         true -> "Credential desactivada — activa en /dashboard/providers"
       end
     }
   />
```

These DO compile with raw Elixir but BREAK in HEEx. The compiler
attribute `--warnings-as-errors` does not catch them — they fail at
HEEx parse time, not at Elixir compile time.

## Fix: extract the block into a private function

The reliable workaround is one helper per multi-line attribute:

```elixir
defp last_request_label(nil, _tz), do: "—"
defp last_request_label(%DateTime{} = dt, tz),
  do: MyAppWeb.TimezoneHelper.format_datetime(dt, tz)

defp toggle_title(%{enabled: false}), do: "Activar"
defp toggle_title(ap), do: toggle_title_effective(ap)

defp toggle_title_effective(ap) do
  if provider_active?(ap),
    do: "Desactivar",
    else: "Credential desactivada — activa en /dashboard/providers"
end
```

HEEx:
```heex
<.stat_card
  label="Último request"
  value={last_request_label(@summary_5d.last_request_at, @timezone)}
  sub={"latency prom: " <> fmt_ms(@summary_5d.avg_latency_ms)}
  icon="hero-clock"
/>
```

Single-line expression → HEEx happy.

## Alternative: explicit `do/end` block on one line

If the expression is short enough:

```heex
<.input title={if ap.enabled, do: "Desactivar", else: "Activar"} />
```

If longer than ~80 chars, prefer the extracted helper.

## Related: filter strings / list literals in attributes

These also break HEEx if multi-line:

```heex
<b>{Integer.to_string(@count)} · "{@status}"</b>   # ok, single line
<b>
  {Integer.to_string(@count)} · "{@status}"
</b>                                                    # also ok
```

But:
```heex
<b>{
  count = @summary.count;
  status = if @active, do: "active", else: "inactive"
  "#{count} · #{status}"
}</b>
```

breaks. Use `Map.get` / helpers / pipeline in a single expression
instead.

## Diagnosing

When the error message points to line N but your visual diff shows only
a comment change around line 100, suspect HEEx attribute parsing. Run
`mix compile` without `--warnings-as-errors` first to see if it's a real
Elixir error or only an HEEx one. If only HEEx fails, look at attribute
spans near the offending line that contain `do`, `case`, `cond`, `if`,
`receive`, `try`, or `PipeExpr` (`|>`).
