# Duplicated Helper Functions with Inconsistent Behavior

## Problem

Phoenix apps often have helpers defined in BOTH the LiveView module (`*_live.ex`) AND the layout (`layouts.ex`). These are separate modules with separate scopes. If both define a helper with the same name but different behavior, one component silently uses the wrong version.

## Real Example (MyApp, July 2026)

`budget_bar_width/1` existed in both `dashboard_live.ex` and `layouts.ex`:

### dashboard_live.ex (correct)
```elixir
def budget_bar_width(nil), do: "width: 0%"
def budget_bar_width(pct) when is_number(pct), do: "width: #{min(pct, 100)}%"
```

### layouts.ex (buggy)
```elixir
defp budget_bar_width(nil), do: 0
defp budget_bar_width(pct) when pct > 100.0, do: 100
defp budget_bar_width(pct) when pct < 0.0, do: 0
defp budget_bar_width(pct), do: round(pct)
```

### Result
- `$0.023 / $22 = 0.1%`
- `round(0.1)` = `0` → `width: 0%` (invisible bar)
- `min(0.1, 100)` = `0.1` → `width: 0.1%` (visible, correct)

## Diagnosis Pattern

When a UI element shows wrong values:
1. Search for the element ID in ALL `.heex` files (not just the LiveView template)
2. Find the helper function in each file that provides data to that element
3. Compare implementations — they may differ even if names match

```bash
# Find all .heex files with the element
search_files("element-id", file_glob="*.heex")

# Find all implementations of the helper
search_files("def budget_bar_width", file_glob="*.ex")
```

## Prevention

1. **Extract to shared module** — e.g., `MyAppWeb.Helpers.BudgetHelpers`
2. **Use the same implementation** in both places (copy-paste, not ideal)
3. **Avoid layout-level helpers** that duplicate LiveView logic
4. **Code review checklist** — when adding helpers to layouts.ex, check if LiveView already has one

## Related Patterns

- **Layout vs LiveView assign conflict** — assigns set in both places
- **Component vs LiveView function** — same name, different arity or behavior
- **Import vs qualified call** — `import` brings in local function, hiding module function