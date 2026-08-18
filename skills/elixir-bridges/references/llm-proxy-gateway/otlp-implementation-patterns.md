# OTLP Observability Implementation Patterns (Elixir/Oban)

Concrete implementation patterns for building the OTLP/JSON webhook
delivery pipeline in an Elixir/Phoenix LLM proxy: span builder, Oban
worker, dispatch function, and test harness.

These patterns were validated against the MyApp codebase (Phoenix +
Oban + Finch + Req). The companion file `otlp-genai-semantic-conventions.md`
documents the OTLP *format*; this file documents *how to build it*.

## OtlpBuilder — span construction from request logs

The builder converts `RequestLog` structs (metadata-only: token counts,
costs, latency, status — never prompt/completion content) into OTLP/JSON
spans. Key design decisions:

### Deterministic traceId / spanId

OTLP requires a 32-hex-char traceId and 16-hex-char spanId. Derive them
deterministically from the request log so the same log always produces
the same IDs (useful for dedup and debugging):

```elixir
defp trace_id(request_log) do
  :crypto.hash(:md5, "trace:" <> id <> ":" <> inserted_at)
  |> Base.encode16(case: :lower)
  |> String.slice(0, 32)
end

defp span_id(request_log) do
  :crypto.hash(:md5, "span:" <> id <> ":" <> inserted_at)
  |> Base.encode16(case: :lower)
  |> String.slice(0, 16)
end
```

The salt ("trace:" vs "span:") ensures traceId ≠ spanId prefix even
though both derive from the same log.

### Nano timestamps from inserted_at + latency_ms

OTLP timestamps are **string** nanoseconds. Convert `inserted_at`
(NaiveDateTime) → DateTime → nanos, and add `latency_ms * 1_000_000`
for the end time:

```elixir
defp start_time_nano(request_log) do
  request_log.inserted_at
  |> DateTime.from_naive!("Etc/UTC")
  |> DateTime.to_unix(:nanosecond)
  |> Integer.to_string()
end
```

Nil `latency_ms` defaults to 0 (end == start).

### OTLP keyvalue type helpers

OTLP attributes are typed value wrappers. Build helper functions to
produce the correct shape:

```elixir
# String (nil → empty string, not omitted)
defp kv(key, value) when is_binary(value),
  do: %{key: key, value: %{stringValue: value}}
defp kv(key, nil),
  do: %{key: key, value: %{stringValue: ""}}
defp kv(key, value),
  do: %{key: key, value: %{stringValue: to_string(value)}}

# Integer (nil → 0)
defp kv_int(key, nil), do: %{key: key, value: %{intValue: 0}}
defp kv_int(key, value), do: %{key: key, value: %{intValue: value}}

# Bool
defp kv_bool(key, value), do: %{key: key, value: %{boolValue: value}}

# Double — convert Decimal to float for cost attributes
defp kv_double(key, %Decimal{} = value),
  do: %{key: key, value: %{doubleValue: Decimal.to_float(value)}}
defp kv_double(key, nil),
  do: %{key: key, value: %{doubleValue: 0.0}}
```

### Span status mapping

OTLP status codes: `1` = STATUS_CODE_OK, `2` = STATUS_CODE_ERROR.

```elixir
defp build_status(%RequestLog{status_code: code})
     when is_integer(code) and code >= 200 and code < 300 do
  %{code: 1}
end
defp build_status(_), do: %{code: 2}
```

Nil status_code → error (code: 2).

### Privacy modes — REMOVED (2026-07)

The `privacy_mode` field was removed from the Destination schema
entirely. ALL metadata attributes are always sent, including
`team_member_id`, `service.name` (= `"$Team - $email"`), and
`trace.metadata.openrouter.api_key_name` (= `"$Team - $email"`).

Rationale: request_logs never stores prompt/completion content (by
design), so there's nothing to redact. The old privacy_mode only
controlled `team_member_id` — but `service.name` and `api_key_name`
already expose the user identity, making the filter pointless.

Implementation: remove the `privacy_mode` parameter from
`build_span/2`, `build_payload/2`, and `build_single_span/2`. Remove
the `maybe_add_privacy_attrs/3` function. `team_member_id` is always
included in the attributes list.

### Batch payload — single scopeSpans

`build_payload/2` maps multiple logs to spans, all grouped under ONE
`scopeSpans` entry (not one per span). This is the efficient batch
shape — one HTTP POST delivers N spans.

## WebhookWorker — Oban delivery with retry semantics

### Job args shape

```elixir
%{
  "destination_id" => dest_id,        # binary_id (UUID string)
  "request_log_ids" => [log_id, ...]  # list of UUID strings
}
```

Log IDs are passed as strings (Oban serializes to JSON; binary_id
UUIDs survive the round-trip as strings).

### perform/1 return values — the retry contract

| HTTP status | Return value | Oban behavior |
|-------------|-------------|---------------|
| 2xx | `:ok` | Success, no retry |
| 4xx | `{:discard, reason}` | Permanent failure, no retry |
| 5xx | `{:error, reason}` | Retry with backoff |
| Transport error | `{:error, reason}` | Retry with backoff |

**Why discard on 4xx:** the destination rejected the payload (bad URL,
auth failure, malformed). Retrying won't fix it.

**Why retry on 5xx:** the destination server is temporarily down.
Backoff gives it time to recover.

### HMAC-SHA256 signature header

```elixir
defp compute_signature(body) do
  secret = Application.get_env(:MyApp, :webhook_secret, "MyApp-dev-secret")
  mac = :crypto.mac(:hmac, :sha256, secret, body)
  "sha256=" <> Base.encode16(mac, case: :lower)
end
```

Header name: `X-MyApp-Signature` (or your proxy's equivalent).
Format: `sha256=<lowercase-hex-hmac>`.

The signature is computed over the **raw JSON body bytes**, not a
normalized form. The destination must recompute HMAC over the exact
bytes received.

### Custom header forwarding

Destination configs can include custom headers. Normalize to lowercase
keys (HTTP headers are case-insensitive) and merge with the required
headers:

```elixir
defp build_headers(destination, body) do
  custom = normalize_headers(destination.headers || %{})
  Map.merge(custom, %{
    "content-type" => "application/json",
    "x-MyApp-signature" => compute_signature(body)
  })
  |> Enum.to_list()
end
```

Required headers (content-type, signature) override custom headers if
there's a collision.

### HTTP client choice

Use **Req** (preferred per Phoenix AGENTS.md) with the app's Finch pool:

```elixir
Req.post(url, body: body, headers: headers,
  receive_timeout: 30_000, finch: MyApp.Finch)
```

The existing OpenAI adapter in the same codebase uses Finch directly
(raw chunk control for SSE), but for non-streaming webhook POSTs, Req's
ergonomics are better.

## dispatch/1 — job enqueuing

The dispatch function is a **plain function** (not the Oban callback)
that the proxy's hot path calls after a request completes. It enqueues
one Oban job per configured destination.

**Destinations are team-scoped.** The Organization layer was removed
and destinations were re-scoped to `team_id` (FK to `teams` table).
`Observability.list_destinations(team_id)` returns destinations for
that team only. The dispatch resolves the team from the request log's
`team_member_id` → `team_member.team_id` chain.

```elixir
def dispatch(%RequestLog{id: log_id, team_member_id: tm_id} = _request_log) do
  team_id = resolve_team_id(tm_id)
  destinations = MyApp.Observability.list_destinations(team_id)

  count =
    Enum.reduce(destinations, 0, fn destination, acc ->
      %{destination_id: destination.id, request_log_ids: [to_string(log_id)]}
      |> __MODULE__.new()
      |> Oban.insert!()

      acc + 1
    end)

  {:ok, count}
end
```

Log ID is passed as `to_string(log_id)` — binary_id UUIDs serialize
cleanly through Oban's JSON args.

**Team-scoping is IMPLEMENTED (2026-07).** The migration
`add_team_to_observability_destinations` adds `team_id` FK to
`observability_destinations` and drops `privacy_mode`.
`Observability.list_destinations(team_id)` filters by team.
`dispatch/1` resolves the team from the request log's
`team_member_id` → `Repo.get(TeamMember, tm_id).team_id` chain.

**Pitfall — dispatch must pass `log_id`, NOT `tm_id`, as the
request_log_id.** A subagent wrote `request_log_ids: [to_string(tm_id)]`
instead of `request_log_ids: [to_string(log_id)]`. The Oban job then
tries to fetch a request log by the team_member's UUID — it finds
nothing and discards the job with "no request logs found". Always
pattern-match BOTH `id` and `team_member_id` from the RequestLog
struct and use `id` for the job args:

```elixir
def dispatch(%RequestLog{id: log_id, team_member_id: tm_id} = _request_log)
    when is_binary(log_id) and is_binary(tm_id) do
  team_member = Repo.get(TeamMember, tm_id)
  team_id = team_member && team_member.team_id
  # ...
  %{destination_id: destination.id, request_log_ids: [to_string(log_id)]}
  # ...
end
```

### Privacy modes — REMOVED (2026-07)

The `privacy_mode` field was removed from the Destination schema.
All metadata is always sent — `team_member_id`, `service.name`
(= `"$Team - $email"`), and `trace.metadata.openrouter.api_key_name`
(= `"$Team - $email"`). No content is ever stored or sent.

The Destination schema now has `belongs_to :team` instead of
`privacy_mode`. The `@required` list is `~w(name type team_id)a`
(no `privacy_mode`). The `@permitted` list includes `team_id`.

### WebhookWorker dispatch — team-scoped (IMPLEMENTED 2026-07)

`dispatch/1` resolves the team from the request log's `team_member_id`
→ `Repo.get(TeamMember, tm_id).team_id`, then calls
`list_destinations(team_id)` to get only that team's destinations.
Only destinations belonging to the same team as the request log
receive the webhook. Cross-team data leak is fixed.

Tests must create destinations with the SAME `team_id` as the
team_member's team — `destination_fixture(url, team.id)`. The dispatch
test for "enqueues one job per destination" must use the team from
`team_member_fixture()` (which now returns `{tm, team}`).

### Webhook UI — inline in TeamsLive (IMPLEMENTED 2026-07)

Webhook destinations are managed as an inline section in each team
card on the Teams page (`/dashboard/teams`), NOT a separate route.
Each team card shows: a "Webhooks de observabilidad" section with an
"Agregar webhook" button, a list of existing destinations (name, URL,
type badge, edit/delete buttons), and an inline form when adding/editing.

The form uses `to_form(changeset, as: :destination)` with fields:
`name` (required), `url` (required), `headers` (textarea, JSON).
`team_id` is set programmatically from `editing_webhook_team_id`,
NOT from a form field. The `save_webhook` handler injects it:
`Map.put(destination_params, "team_id", team_id)`.

**Pitfall — `:if` conditions on webhook form visibility must use
`@webhook_form == nil`, NOT `@editing_webhook_id == nil`.** The
subagent wrote `@editing_webhook_team_id != team.id or
@editing_webhook_id == nil` for the "show button" condition. This is
wrong because `editing_webhook_id` starts as `nil` (not `:new`), so
the condition is always true and the form never appears. Use
`@webhook_form == nil` instead — it directly tracks whether a form
is open.

**Pitfall — `write_file` double-escapes quotes in .exs files.** When
using `write_file` to create an Elixir test file containing
`%{"error" => "boom"}`, the tool escapes the inner quotes as
`%{\"error\" => \"boom\"}`, which is invalid Elixir syntax
(`SyntaxError: unexpected token: "\"`). Always verify written `.exs`
files with `mix compile` or `mix test` immediately after writing, and
fix any double-escaped quotes with `patch` before running tests.

**Pitfall — subagents corrupt HEEx pattern match syntax.** A subagent
rewrote `%{"id" => team_id}` as `%{["id"] => team_id}` (adding square
brackets around the key). This compiles silently as a different
pattern that never matches, causing `FunctionClauseError` at runtime
when the event fires. Always grep for `%{[` in HEEx-bearing files
after a subagent wave and fix any matches to `%{"key" => value}`.

**Pitfall — HEEx hint attributes with escaped quotes break compilation.**
`hint="Ej.: {\"Authorization\": \"Bearer xxx\"}"` in a `.ex` file with
`~H` sigil causes `ParseError: invalid character in attribute name`.
Use HTML entities: `hint="Ej.: {&quot;Authorization&quot;: &quot;Bearer xxx&quot;}"`.
Or simplify the hint text to avoid curly braces and quotes entirely.

**Pitfall — a compilation error in one LiveView blocks dev server
recompilation of ALL LiveViews.** If `users_live.ex` has a syntax error
(unmatched closing tag), the Phoenix code reloader fails to compile
it, and `teams_live.ex` changes are NOT reloaded — the dev server
serves the old compiled version. Symptom: you fix `teams_live.ex`,
reload the page, but the fix doesn't take effect. Check the dev server
console for compilation errors in OTHER files and fix those first.

### Preloads needed for service.name and api_key_name

The builder needs `team_member → user` (for email) and
`team_member → team` (for team name) to construct the
`"$Team.name - $User.email"` string used in both `service.name` and
`trace.metadata.openrouter.api_key_name`.

`RequestLog` has a `belongs_to :team_member` association (added with
`references: :id, foreign_key: :team_member_id, type: :binary_id`).
The WebhookWorker query preloads it:

```elixir
from rl in RequestLog,
  where: rl.id in ^log_ids,
  order_by: [asc: rl.inserted_at],
  preload: [team_member: [:user, :team]]
```

**Pitfall — don't define both `field :team_member_id` AND
`belongs_to :team_member, foreign_key: :team_member_id`.** The
`belongs_to` macro auto-creates the `team_member_id` field; defining
it separately raises `ArgumentError: field/association :team_member_id
already exists on schema`. Remove the bare `field :team_member_id`
line when adding the `belongs_to`. Keep `provider_id` and
`model_alias_id` as bare fields (they have no association defined).

### build_identity/1 — the "$Team - $email" helper

```elixir
def build_identity(%RequestLog{team_member: %TeamMember{} = tm}) do
  team = Map.get(tm, :team)
  user = Map.get(tm, :user)
  case {team, user} do
    {%Team{name: team_name}, %User{email: email}}
    when is_binary(team_name) and is_binary(email) ->
      "#{team_name} - #{email}"
    _ -> "MyApp"
  end
end
def build_identity(_), do: "MyApp"
```

Called from `build_attributes/1` (for `api_key_name`) and
`wrap_in_resource_spans/2` (for `service.name`). Both receive the
identity string; the span builder passes it up from the first log in
a batch. Falls back to `"MyApp"` when associations are not loaded.

## Testing patterns

### OtlpBuilder — pure unit tests (async: true)

The builder is a pure function — no DB, no processes. Test with
`async: true` using struct fixtures built directly (no DB inserts).

Key assertions:
- Trace/span ID format (32/16 hex chars, deterministic, differ per log)
- Nano timestamp math (start = inserted_at in nanos, end = start + latency)
- Attribute values (Decimal → doubleValue, nil → default)
- `gen_ai.usage.total_tokens` = prompt_tokens + completion_tokens
- `gen_ai.usage.total_cost` = provider_cost_usd (NOT cost_usd)
- `service.name` = "$Team.name - $User.email" (requires team_member preload)
- `trace.metadata.openrouter.api_key_name` = same as service.name (namespace is `openrouter`, NOT `MyApp`)
- `team_member_id` always present (no privacy mode)
- Batch: N logs → N spans in one scopeSpans

**Fixture pattern for identity tests:** the `request_log()` fixture in
the unit test needs a `team_member` preloaded with `team` and `user`
structs to test the `service.name` / `api_key_name` identity string.
Build them as plain structs (no DB needed — OtlpBuilder is pure):

```elixir
defp team_member(attrs \\ %{}) do
  struct(%TeamMember{
    id: "tm-1", team_id: "team-1", user_id: "user-1",
    team: %Team{id: "team-1", name: "Engineering"},
    user: %User{id: "user-1", email: "user@example.com"}
  }, attrs)
end

defp request_log_with_team_member(attrs \\ %{}) do
  request_log(Map.merge(%{team_member: team_member()}, attrs))
end
```

Then assert `service.name` == `"Engineering - user@example.com"` and
`api_key_name` == same. Also test the fallback: a `request_log()`
without `team_member` loaded should produce `service.name` == `"MyApp"`.

### WebhookWorker — integration tests with Bandit + Oban.Testing

```elixir
use MyApp.DataCase, async: false   # DB + Oban sandbox
use Oban.Testing, repo: MyApp.Repo
```

#### Bandit test plug

Start a Bandit server with a test plug that captures the request
details and routes by path marker:

```elixir
defmodule TestPlug do
  import Plug.Conn
  def call(conn, _opts) do
    {:ok, body, conn} = read_body(conn)
    send(test_pid, {:captured, %{body: body, signature: get_req_header(conn, "x-MyApp-signature")}})
    cond do
      "bad" in conn.path_info -> json(conn, 400, %{})
      "broken" in conn.path_info -> json(conn, 500, %{})
      true -> json(conn, 200, %{})
    end
  end
end

setup do
  start_supervised!({Bandit, plug: TestPlug, scheme: :http, ip: :loopback, port: @port})
  :ok
end
```

#### HMAC verification in tests

Recompute the HMAC in the test and assert it matches what the worker
sent:

```elixir
assert_receive {:captured, %{body: body, signature: [sig]}}
secret = Application.get_env(:MyApp, :webhook_secret, "MyApp-dev-secret")
expected = "sha256=" <> Base.encode16(:crypto.mac(:hmac, :sha256, secret, body), case: :lower)
assert sig == expected
```

#### Oban.Testing for dispatch/1

```elixir
assert {:ok, 2} = WebhookWorker.dispatch(log)

assert_enqueued(
  worker: WebhookWorker,
  args: %{"destination_id" => dest.id, "request_log_ids" => [to_string(log.id)]}
)
```

#### Nonexistent log IDs — use valid UUIDs

When testing the "no logs found" path, pass a valid UUID format, not a
plain string. `binary_id` columns cast to `{:in, :binary_id}` in Ecto
queries, and a non-UUID string raises `Ecto.Query.CastError`:

```elixir
# WRONG — raises CastError
job = %Oban.Job{args: %{"request_log_ids" => ["nonexistent-id"]}}

# RIGHT — valid UUID that doesn't exist in DB
fake_id = Ecto.UUID.generate()
job = %Oban.Job{args: %{"request_log_ids" => [fake_id]}}
```

### Full DB fixture chain

WebhookWorker integration tests need the full team → team_member
→ request_log chain via real context functions. The
`team_member_fixture` now returns `{team_member, team}` so the
destination fixture can use the correct `team_id`:

```elixir
defp team_member_fixture do
  team = team_fixture()
  user = user_fixture()
  {:ok, team_member} = Accounts.create_team_member(%{
    "user_id" => user.id, "team_id" => team.id
  })
  {team_member, team}
end

defp destination_fixture(url, team_id, attrs \\ %{}) do
  {:ok, dest} = Observability.create_destination(
    Map.merge(%{
      "name" => "OTLP Collector",
      "type" => "otlp_webhook",
      "url" => url,
      "team_id" => team_id
    }, attrs)
  )
  dest
end
```

Usage in tests:
```elixir
{tm, team} = team_member_fixture()
log = log_fixture(tm.id)
dest = destination_fixture(base_url(), team.id)
```

The dispatch test for team-scoping: create destinations for TWO
different teams, dispatch a log from team 1's member, assert
`{:ok, 1}` (only team 1's destination is enqueued, not team 2's).

### API key lifecycle (no auto-generation)

`create_team_member/1` does NOT generate an API key automatically.
The admin creates the member, then generates the key from the API Keys
page. `replace_api_key/1` works for both initial generation (no existing
key → inserts) and replacement (existing key → updates in place).

Tests that need a token must call `replace_api_key/1` after creating
the member:

```elixir
{:ok, tm} = Accounts.create_team_member(valid_team_member_attrs(user, team))
{:ok, _api_key, token} = Accounts.replace_api_key(tm)
```

**Pitfall:** the old `replace_api_key/1` used `Ecto.Multi.update/3` for
both cases (existing key AND no key). `Multi.update` fails on a fresh
`%ApiKey{}` struct that was never inserted — it tries to UPDATE a row
that doesn't exist. Fix: branch on `team_member.api_key` — `Repo.update`
for existing keys, `Repo.insert` for new ones.
