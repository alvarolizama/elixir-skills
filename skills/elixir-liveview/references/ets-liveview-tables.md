# ETS-Backed LiveView Tables — Two-Table Design

**Symptom:** a LiveView renders a table fed by an ETS KV cache (captured
requests, prompts, logs, in-flight entries, sparkline windows). The UI
freezes or lags as the table grows; the LiveView process memory balloons;
stalls appear on mount, on every filter change, and on row click.

The user asking *"is everything loaded in memory? shouldn't it query ETS
live?"* has already made the diagnosis — confirm it, then fix it.

## Mechanism: the "dump everything" freeze

A `Cache.list()` that returns the WHOLE ETS table into the LiveView process
is the classic mistake. It fires in three places:

1. **`mount`** — `Cache.list()` → `:ets.select` copies every entry (each
   carrying its full payload: message lists, JSON bodies) into the
   LiveView process heap. Only a capped stream (e.g. 200 rows) reaches
   the client — the other ~1800 entries are wasted copy + GC churn.
2. **Every filter** — the reset handler calls `Cache.list()` again →
   another full dump.
3. **Row click** — `Enum.find(Cache.list(), &(&1.id == id))` → a THIRD
   full dump just to fetch one entry by id.

Compounding it: if capture broadcasts the **full entry** over PubSub,
every row pushes its full body over the WebSocket even though the table
renders only a short preview. That inflates the socket and the DOM.

Freeze signature: stalls that scale with table size; heap spikes on
mount / filter / modal-open; GC churn under sustained capture load.

## Fix: two tables (light rows + full by id)

Keep ETS as the KV source of truth, but split storage so the
list/broadcast path never touches heavy payloads:

1. **rows table** — lightweight maps WITHOUT the heavy payload
   (`Map.delete(entry, :messages)`), plus a precomputed `last_preview`
   for the table cell. Served by `list_recent(limit, filters)`.
2. **full table** — entries WITH the payload. Served by `get(id)` only,
   when the user opens the detail view / modal.
3. `list_recent(limit, filters)` reads ONLY the rows table (cheap),
   filters in memory (no payloads), sorts newest-first, `Enum.take(limit)`.
4. `get(id)` = a single `:ets.lookup` by key. Replace any
   `Enum.find(Cache.list(), ...)` with it.
5. **Broadcast the ROW over PubSub, not the full entry.** `handle_info`
   checks the row against the current filters, then `stream_insert` with
   the row (rows carry all filter fields, so filtering still works). The
   template renders `row.last_preview` instead of slicing the payload.
6. `delete` and sweeps (TTL / cap / memory) purge from BOTH tables via a
   shared `purge(id)` helper so they never desync (full entry without a
   row, or vice versa).

Keep `list/0` (full entries) around for backward compat and tests; the
LiveView just stops calling it.

## API shape (caller-process — no GenServer bottleneck on reads)

```elixir
defmodule MyApp.Prompts.Cache do
  @table :my_app_prompts_cache       # full entries (with payload)
  @rows_table :my_app_prompts_rows   # rows = Map.delete(entry, :messages)

  def capture(attrs)
  #  ^ inserts BOTH tables; broadcasts {:prompt_captured, row}
  def list_recent(limit, filters \\ nil)
  #  ^ rows table only; filter; sort started_at desc; take(limit)
  def matches_filters?(row, filters) # email contains / type exact; "" matches all
  def get(id)          # single :ets.lookup on @table → full entry | nil
  def list()           # kept for backward compat + tests
  def delete(id)       # purge(id) → deletes from BOTH tables
end
```

LiveView wiring:

```elixir
mount:      rows = Cache.list_recent(@max_rows, filters)
filter:     rows = Cache.list_recent(@max_rows, new_filters)  # same helper
handle_info({:prompt_captured, row}) ->
  if Cache.matches_filters?(row, filters),
    do: stream_insert(socket, :prompts, row, at: 0, limit: @max_rows)
show_row:   entry = Cache.get(id)     # NOT Enum.find(Cache.list(), ...)
template:   {row.last_preview || ""}  # never touches the payload
```

## Hot-reload pitfall: guard named ETS with `:ets.whereis`

A **brand-new named table does not exist on already-running nodes** — the
dev code reloader does NOT restart the supervision tree, so a node that
hot-reloaded the cache module has the new code but not the new table.
Guard every insert with `:ets.whereis` on BOTH tables and no-op if either
is missing. Never insert into one table and crash on the other: that
leaves partial state (full entry without a row, no broadcast).

The cache is an optimization, never a hard dependency — the hot path must
keep working without it.

## Verification

- `mix compile --warnings-as-errors` clean; focused cache + LiveView
  tests green; then the project's full suite gate.
- Ad-hoc probe through `mix run probe.exs` exercising the REAL tables
  (delete the script afterward):
  - capture returns the full entry; the broadcast row has NO payload key;
  - `list_recent` rows are light, newest-first, respect limit + filters;
  - `get(id)` returns the full entry; `nil` for unknown ids;
  - `delete` removes from both tables.
- Test assertions worth pinning:

```elixir
refute Map.has_key?(row, :messages)        # on broadcast AND list_recent rows
assert fetched.messages == messages        # get(id) returns the payload
assert Cache.get(id) == nil                # after delete…
refute Enum.any?(Cache.list_recent(100, nil), &(&1.id == id))
```
