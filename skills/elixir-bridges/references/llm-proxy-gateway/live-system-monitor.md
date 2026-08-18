# Live System Monitor (OTP VM + DB health) in a Phoenix LiveView dashboard

How to add a "Monitor del sistema" section to an ops dashboard (e.g. the logs
LiveView of an LLM proxy) with **live RAM, CPU load, process count, DB health,
I/O, and uptime** — pure OTP introspection, zero external dependencies, no
`:os_mon`, no telemetry plumbing.

## The pattern

1. A `:timer.send_interval(@tick_ms, :refresh_system_metrics)` started in
   `mount/3` when `connected?(socket)` (2s is a good cadence for an ops page).
2. A `handle_info(:refresh_system_metrics, socket)` that re-assigns a
   `:system_metrics` map from a `collect_system_metrics/0` pure function.
3. A grid of small daisyUI cards reading the assign. Admin-only via
   `:if={@is_admin}` on the wrapper, same gate as the rest of the admin page.

## What to read (all pure OTP, all instantaneous)

| Metric | Call | Notes |
|--------|------|-------|
| RAM total / processes / ets / atom / binary | `:erlang.memory()` | **Returns a KEYWORD LIST, not a map** — use `Keyword.get/3`, never `Map.get/3` (see pitfall). |
| Live processes | `:erlang.system_info(:process_count)` | Pair with `:process_limit` for the card. |
| Run queue (CPU saturation proxy) | `:erlang.statistics(:run_queue)` | With `:schedulers_online`. |
| Schedulers | `:erlang.system_info(:schedulers)` / `:schedulers_online` | |
| I/O bytes in/out | `:erlang.statistics(:io)` → `{{:input, in}, {:output, out}}` | Cumulative since boot. |
| Uptime | `:erlang.statistics(:wall_clock)` → `{ms, _}` | Format as `Xd Yh` / `Xh Ym` / `Xm`. |
| DB pool size | `Repo.config() |> Keyword.get(:pool_size, 10)` | Config value, always available. |
| DB health | timed `Repo.query!("SELECT 1", [], timeout: 2_000)` | Latency in ms as the health signal. |

## The two honest approximations (don't fake precision)

- **CPU %**: OTP does not expose a top-style %CPU without sampling
  `scheduler_wall_time` across two ticks in a GenServer. The cheap honest
  proxy is `run_queue / schedulers_online` as a **saturation %** (>100% = more
  runnable work than capacity). Color it: `<50` success, `<90` warning, else
  error. If a real %CPU is ever needed, sample
  `:erlang.statistics(:scheduler_wall_time)` in a GenServer between ticks —
  do NOT fake it from a single instantaneous call.
- **DB busy connections**: there is NO public API to count checked-out
  DBConnection pool connections. Do not invent one with
  `Process.whereis(DBConnection.Pool)` (always nil) or
  `Repo.checked_out_connections()` (does not exist). A timed `SELECT 1`
  latency is a more useful health signal anyway — a slow pool shows up as a
  slow probe. Report `pool_size` (config) + `query_ms`, not a guessed "busy".

## Pitfall: `:erlang.memory()` is a keyword list

`:erlang.memory()` returns `[total: 112320105, processes: 19894944, ...]`,
NOT a map. `Map.get(mem, :total)` raises `BadMapError` at runtime the first
time the collector runs — and in a LiveView that crash happens inside
`mount/3`, taking the whole page down. Use `Keyword.get/3`:

```elixir
mem = :erlang.memory()
%{total: Keyword.get(mem, :total, 0), processes: Keyword.get(mem, :processes, 0)}
```

This only shows up at runtime (mount), not at compile time — a LiveView test
that mounts the page catches it immediately.

## Formatters worth copying

```elixir
defp format_bytes(b) when is_integer(b) and b >= 1_073_741_824, do: "#{Float.round(b / 1_073_741_824, 2)} GB"
defp format_bytes(b) when is_integer(b) and b >= 1_048_576, do: "#{Float.round(b / 1_048_576, 1)} MB"
defp format_bytes(b) when is_integer(b) and b >= 1_024, do: "#{Float.round(b / 1_024, 1)} KB"
defp format_bytes(b) when is_integer(b), do: "#{b} B"
defp format_bytes(_), do: "—"

defp format_uptime(ms) when is_integer(ms) do
  s = div(ms, 1000)
  cond do
    div(s, 86_400) > 0 -> "#{div(s, 86_400)}d #{div(rem(s, 86_400), 3600)}h"
    div(s, 3600) > 0   -> "#{div(s, 3600)}h #{div(rem(s, 3600), 60)}m"
    true               -> "#{div(s, 60)}m"
  end
end
```

## Testing

- `has_element?(view, "#system-monitor")` + one per card (`#mon-ram`, etc.)
  for an admin user.
- Fire the tick directly — `send(view.pid, :refresh_system_metrics)` — and
  assert the section still renders (proves the collector ran without
  crashing). Don't assert specific live values (process counts vary).
- Non-admin on an admin-only dashboard gets redirected by the `live_session`
  BEFORE mount — assert the `{:error, {:redirect, ...}}`, not the absence of
  the section. A "user can't see the section" test that calls `live/2`
  expecting a 200 will fail on the redirect.
