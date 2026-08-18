# Request Log Enrichment — Denormalized Write-Time Fields

Applies when the proxy's request log needs to display fields that exist on related records (provider name, credential name, API key prefix). The pattern avoids join-at-query-time by writing denormalized copies when the request completes.

## The write pipeline

```
proxy (enqueue_log)
  → Inflight entry (ETS) — for live "pending" rows
  → WriteWorker (Oban) — async insert into request_logs (Postgres)
  → Phoenix PubSub broadcast — connected LogsLive receives the row
  → Template renders the denormalized field (already on the struct)
```

## What to denormalize and where to get it

| Field | Source | Where captured |
|-------|--------|---------------|
| `provider_name` | `route.model_provider.credential.provider.name` | `register_inflight/4` + `enqueue_log/8` |
| `credential_name` | `route.credential.name` | `register_inflight/4` + `enqueue_log/8` |
| `api_key_prefix` | `member.api_key.key_prefix` | `register_inflight/4` + `enqueue_log/8` |

All three flow through the same three layers:

1. **Inflight entry** — the ETS entry carries the field so the "Pending" table shows it live.
2. **WriteWorker** — the Oban job attrs carry the field so it lands in `request_logs`.
3. **Schema** — `request_log.ex` adds the field to `@permitted` + schema fields.

## The `register_inflight` pattern (proxy controller)

```elixir
defp register_inflight(conn, member, payload, route) do
  {think, effort} = MyApp.Proxy.Reasoning.parse(payload)

  conn = conn |> assign(:think, think) |> assign(:effort, effort)

  entry =
    MyApp.Logs.Inflight.start_request(%{
      team_member_id: member.id,
      user_email: member.user && member.user.email,
      team_name: member.team && member.team.name,
      model_requested: payload["model"],
      agent_type: conn.assigns.agent_type,
      streaming: payload["stream"] == true,
      think: think,
      effort: effort,
      provider_name: route.model_provider.credential.provider.name,
      credential_name: route.credential.name,
      api_key_prefix: member.api_key && member.api_key.key_prefix
    })

  {conn, entry}
end
```

## The `enqueue_log` pattern (add the field to the Oban args map)

```elixir
%{
  ...
  "api_key_prefix" => member.api_key && member.api_key.key_prefix,
  "credential_name" => route.credential.name
}
|> WriteWorker.new()
|> Oban.insert()
```

## Template addition

Every denormalized field shows at column-level, not in a tooltip. Add the column header unconditionally, render `field || "—"` for the cell value.

## Why denormalize instead of join

- The Inflight ETS registry has no joins — it's a flat map.
- Oban's `perform/1` runs asynchronously; joining at the query layer adds complexity (preloads in the worker, query-time joins in the LiveView list query).
- LiveView streams are flat structs — adding a join changes the query signature.
- These fields are write-once-read-many and never change after the log is created, so denormalization has zero consistency cost.

## Table column count maintenance

Every time you add a column to the logs table, update the `colspan` on the empty-state row (`<td colspan="N" class="text-center ...">`). Count columns by the `<th>` entries in the `<thead>` — one `<th>` = one colspan unit. This is easy to miss (the empty row is `class="hidden only:table-row"` so it's invisible until the table has zero rows).
