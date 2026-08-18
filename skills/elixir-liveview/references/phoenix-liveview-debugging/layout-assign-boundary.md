# Layout Function Components Do NOT Inherit Socket Assigns

**Class:** silent assign-default bug in Phoenix LiveView layout function components.

## The bug

A `<Layouts.dashboard current_scope={@current_user}>` call from a `.heex` template passes ONLY the attrs you explicitly write. Socket assigns like `@timezone`, `@locale`, `@theme` are NOT auto-forwarded. If the layout body reads `assigns[:timezone]`, it silently gets `nil` and falls back to the attr default (e.g. `"Etc/UTC"`).

The `on_mount` hook CAN have assigned `@timezone` perfectly on the socket — the layout still won't see it, because function components receive only their declared attrs, not the caller's assign map.

## Symptom

A navbar / topbar / sidebar layout widget always shows the default (UTC, English, light theme) even though:
- the LiveView socket has the right value,
- the `on_mount` hook assigned it correctly,
- the LiveView's own template reads `@timezone` fine elsewhere.

Only the layout widget is wrong — that's the tell.

## Diagnosis recipe

1. Grep the layout function component for `assigns[:<key>]` — that's the fallback path firing.
   `grep -n "assigns\[:timezone\]" lib/my_app_web/components/layouts.ex`
2. Grep every template that invokes the layout and confirm the key is NOT passed:
   `grep -rn "<Layouts.dashboard" lib/my_app_web/live/`
3. Confirm the socket DOES have the assign (the hook or mount assigned it). If yes, the bug is the missing attr pass, not the assign itself. Don't go chasing the `on_mount` hook — it's fine.

## Two fixes (pick one)

**A. Pass it explicitly in every template** — `<Layouts.dashboard timezone={@timezone} ...>`. Works but is error-prone: easy to forget on the 14th template and on every future one.

**B. (Preferred) Read from an attr that IS already passed.** If every template already passes `current_scope={@current_user}`, derive inside the layout:

```elixir
<.dashboard_topbar
  current_scope={@current_scope}
  timezone={(@current_scope && @current_scope.timezone) || assigns[:timezone] || "Etc/UTC"}
/>
```

One change fixes all call sites and can't be forgotten on future templates. Keep `assigns[:timezone]` as a fallback for the odd caller that does pass it explicitly.

## Real case (MyApp, 2026-07-31)

13 LiveView templates rendered `<Layouts.dashboard flash={@flash} current_scope={@current_user} impersonator={@impersonator}>` — no `timezone` attr. The navbar budget chip computed daily/monthly calendar boundaries in UTC (`assigns[:timezone] || "Etc/UTC"`), showing `$0` for users in `America/Merida` / `America/Mexico_City` whose local calendar day (still the 31st) had not yet rolled over in UTC (already the 1st). The LiveView's own date formatting was correct elsewhere because those templates read `@timezone` directly. Fixed with option B: layout reads `@current_scope.timezone`.

## Related

- `references/on-mount-assign-flow.md` — `on_mount` hook assign chain (event updates one assign but UI reads from a nested struct).
- MyApp timezone-aware calculation pitfalls (naive `timestamp` columns, `AT TIME ZONE` double-conversion, `Periods` module): skill `MyApp-cost-accounting`, `references/timezone-calculations-2026-07-31.md`.
