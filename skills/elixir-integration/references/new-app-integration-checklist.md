# New App Integration Checklist

Every new umbrella app must be planned and verified against five integration
tracks. Missing one does not fail at compile time — it fails in production with
a security hole or an invisible feature. Treat them as a checklist before the
first deploy, not as an afterthought.

Pattern: **symptom → mechanism → fix → verification** for each track.

## Track 1 — Permission module + config registration

**Symptom.** A fresh app ships open: any authenticated user can call every
mutation, because nothing checks authorization — or checks it against a
hard-coded `true` stub left over from scaffolding.

**Mechanism.** Scaffolds optimize for "it runs". Authorization has no
scaffold, so absent a deliberate module nothing enforces it. New surface areas
(copy this file's list) inherit the gap silently.

**Fix.**

1. Create one policy module per umbrella app, consulted by every context
   function that mutates or crosses scope:

```elixir
defmodule MyApp.Policy do
  @doc "Returns :ok or {:error, :unauthorized}. Fail closed on unknown input."
  def authorize(actor, action, resource)
end
```

2. Register the app and its policy in the host application's config so the
   host router, token scopes, and MCP server can discover it:

```elixir
# config/config.exs of the HOST app
config :my_app_host, :apps, %{
  my_feature: %{policy: MyApp.Policy, scopes: ["my_feature:read", "my_feature:write"]}
}
```

3. Context functions call the policy first — before any query runs. Fail
   closed: unknown actor, unknown action, or unknown resource is
   `{:error, :unauthorized}`.

**Verification.**

- `grep -rn "def change\|def create\|def update\|def delete" lib/` — every hit
  in a context module either calls the policy or is documented as public.
- A test asserting a second, unrelated user gets `{:error, :unauthorized}` on
  every mutating context function.

## Track 2 — MCP server registration

**Symptom.** The app's tools never appear in an agent session, or appear for
users who must not see them.

**Mechanism.** An MCP server is only reachable if three separate pieces are
wired: the supervised server process, the HTTP route, and per-user context
authorization. Any one can be skipped and the other two still "work".

**Fix.**

1. Supervise the server: add the child spec to the host's supervision tree.
2. Mount the route (usually `/api/mcp` or similar) in the host router with the
   correct `Accept: application/json, text/event-stream` wire contract.
3. Authorize inside the server: resolve the user from the transport (bearer
   token / session), validate context access, inject the user's default
   context into `params["arguments"]["context"]` — NOT `params["context"]`.

**Verification.** Handshake smoke over HTTP with the server RUNNING:

```bash
curl -i -X POST http://localhost:4000/api/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Authorization: Bearer <token>' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"probe","version":"0.1"}}}'
# expect HTTP 200 + mcp-session-id response header
```

Then call every tool once and classify the result text (see
`mcp-server-development.md`).

## Track 3 — PubSub events

**Symptom.** One app's UI never learns about another app's state changes; each
ends up polling.

**Mechanism.** Umbrella apps share a PubSub server only if they broadcast on a
conventionally-named topic. Without a naming convention, topics drift and
subscribers silently match nothing.

**Fix.**

1. Convention: topic is `"<domain>:<scope>"`, e.g. `"team:#{team_id}"`.
2. Broadcast from the context function after a successful transaction —
   nowhere else (a broadcast outside the transaction can announce a rollback).
3. Subscribe in each consumer's `mount/3` (LiveView) or a dedicated GenServer;
   handle in `handle_info/2`.

**Verification.** In an IEx session against the running app:
`Phoenix.PubSub.broadcast(MyApp.PubSub, "team:1", :ping)` — the subscribed
LiveView/GenServer receives it.

## Track 4 — API token scopes

**Symptom.** A token issued for read-only reporting can call destructive
mutations.

**Mechanism.** Scopes are checked only if the auth plug compares the token's
scope list against the route's requirement. New apps forget to declare their
scopes, so the plug's default (empty = allow-all) takes over.

**Fix.**

1. Declare scopes in the app registration (Track 1 config).
2. The API auth plug validates: token exists and is hashed-compared, then
   `required_scope in token.scopes` — deny by default, log denials.
3. Route-level requirement: `pipe_through [:api, :api_auth]` plus a scope
   assertion per controller action (plug or `action_fallback` guard).

**Verification.** Test pair: a token WITH the scope gets 200, a token WITHOUT
gets 403 — for every mutating endpoint.

## Track 5 — Router mounting in the host router

**Symptom.** The app's pages 404 in the deployed host even though they pass
tests in isolation; or the pages are reachable but sessionless.

**Mechanism.** Umbrella web apps only expose routes through the HOST router.
An app-local router that is never `forward`ed works in isolation (its own
tests use its endpoint) and vanishes in production. Pipelines also belong to
the host: a mounted scope inherits host pipelines, not app-local ones.

**Fix.**

1. `forward "/myfeature", MyAppWeb.Router` in the host router, inside the
   correct pipeline scope (`:browser` for pages, `:api` for endpoints).
2. Auth-required pages go behind the host's `require_authenticated_user`
   pipeline; public callbacks (OAuth) go BEFORE it in `:browser`.
3. LiveView pages that need admin: use the host's `live_session :admin` +
   `on_mount` guard (see `security-audit-method.md`).

**Verification.** Against the RUNNING host server:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:4000/myfeature/health
# expect 200 from the mounted app, not 404 from the host
```

## Pre-deploy order

1. Tracks 1 + 4 first (permissions + scopes): they gate everything else.
2. Track 5 (router) so surfaces are reachable at all.
3. Tracks 2 + 3 (MCP + PubSub) once the base surface exists.
4. Re-run every track's verification against the fully assembled host —
   isolation tests do not prove integration.
