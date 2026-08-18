# Heroicon Component Attribute Traps

## `:title` attribute rejected

Heroicon function components (from `heroicons_elixir` or Petal Components) do **not** accept a `:title` attribute. Passing it raises:

```
** (Phoenix.LiveView.Tokenizer.ParseError) unsupported attribute :title
```

or a compile-time warning about unknown attributes.

## Wrong

```heex
<Heroicons.icon name="question-mark-circle" title="Help text" />
```

## Right — wrap in a `<span>` with `title`

```heex
<span title="Help text">
  <Heroicons.icon name="question-mark-circle" />
</span>
```

Or use a `data-tooltip` attribute + CSS/JS tooltip system if the app has one.

## Why

Heroicon components use `Phoenix.Component` with a strict `attr` schema. Only declared attributes (`name`, `class`, `outline`, `solid`, `mini`) are accepted. Everything else is rejected at compile time.

## Real-world case

MyApp dashboard KPI cards — attempted to add `title` to a heroicon for accessibility. Compile error. Fixed by wrapping in `<span title="...">`.
