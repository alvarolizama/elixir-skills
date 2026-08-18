---
name: phoenix-security-audit
description: "Read-only security audit of Phoenix/Elixir web apps."
version: 1.0.0
author: Álvaro Lizama
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [phoenix, elixir, security, audit, authorization, idor, liveview, owasp]
    related_skills: [requesting-code-review, phoenix-liveview-debugging, hermes-extools, llm-proxy-gateway]
---

# Phoenix/Elixir Web Security Audit

## When to Use

- User asks to "review", "audit", "check for vulnerabilities", or "find security issues" in a Phoenix/Elixir web application
- User asks to review the "web layer", "controllers", "LiveViews", "plugs", or "router" for security problems
- User asks specifically about authorization holes, IDOR, N+1 queries, pagination, secrets, or LiveView bugs
- Pre-deployment security review of a Phoenix app

**This skill vs `requesting-code-review`:** That skill scans YOUR diff before
committing. This skill is a read-only audit of an existing codebase — no edits,
no commits, just a report.

## Core Principle

**Read every file, verify every finding against the real code, never report
what you haven't confirmed.** A false positive in a security report erodes trust
in every real finding. When in doubt, read the context function, check the
schema, trace the data flow — then report.

## Audit Workflow

### Phase 1 — Map the attack surface

Read these files in order to understand the auth architecture:

1. **`router.ex`** — identify pipelines (`:browser`, `:browser_auth`, `:browser_admin`, `:api`), which routes are behind which pipeline, `live_session` blocks and their `on_mount` hooks.
2. **Plugs** (`plugs/*.ex`) — how auth is enforced: `fetch_current_user`, `require_authenticated`, `require_admin`, API key auth.
- **`user_auth.ex`** (or equivalent on_mount module) — the LiveView analogue of the plugs.
4. **Controllers** — session, OAuth, any non-LiveView controllers (export, proxy, etc.).
5. **All LiveViews** — mount, handle_event, handle_info, handle_params.
6. **Runtime/deploy config when in scope** — `mix deps.audit` for known
   advisories, `Dockerfile` + entrypoint for hardcoded seed credentials and
   security features disabled by default, `config/runtime.exs` for SSL/TLS
   verification modes and env-var fallbacks. See `references/deploy-config-audit.md`.

### Phase 2 — Check each vulnerability category

Work through the 6 categories below. For each, note: file, line number, severity,
category, description, and suggested fix.

### Phase 3 — Verify and cross-reference

Before reporting any finding:
- Read the context function the code calls (e.g., if `handle_event` calls `Accounts.get_team_member!`, read that function to check preloads and scope).
- Check if the vulnerability is mitigated elsewhere (e.g., a router guard that the code doesn't repeat but that still protects the route).
- Verify the data flow: does user-controlled input actually reach the dangerous operation?

### Phase 4 — Report

Produce a structured, prioritized report:
- **Severity levels**: crítico / alto / medio / bajo (or critical/high/medium/low)
- **Format per finding**: ID, severity, file:line, category, description, fix suggested
- **Summary table** by category and severity
- **Prioritized remediation list** (what to fix first)
- **Explicit statement** that no files were edited

---

## Category 1 — Authorization Holes

### 1a. Routes/mounts without admin guard

Check every `live_session` and `scope` block in `router.ex`. Each admin-only
LiveView should be behind `live_session :admin` with
`on_mount: [{...UserAuth, :require_admin}]`.

**Common gap:** A LiveView is in the `:admin` live_session but its `mount/3`
doesn't verify `global_role == "admin"` — it trusts the router. This is
defense-in-depth failure: if the router is reconfigured, the LiveView is exposed.

**Audit grep:**
```bash
# LiveViews behind :admin live_session:
grep -A5 'live_session :admin' lib/*/router.ex
# Which of those check is_admin in mount?
grep -l 'global_role.*admin' lib/*/live/*_live.ex
```

### 1b. handle_event without permission check

**The #1 authorization finding in Phoenix LiveView apps.** Templates hide
destructive buttons with `<%= if @is_admin do %>`, but the `handle_event`
handler behind that button may not check permissions. A malicious client can
fire the event directly via WebSocket, bypassing the template guard.

**Fast triage — count attach_hook vs handle_event per LiveView:**
```bash
for f in lib/*/live/*_live.ex; do
  echo "$f: events=$(grep -c 'def handle_event' $f) hook=$(grep -c attach_hook $f)"
done
```
Three states result:
- `hook > 0` → whole-LiveView guard present (safe pattern below) ✓
- `hook = 0` but handlers contain `is_admin`/`global_role` inline → per-handler checks ✓ (verify each destructive handler)
- `hook = 0` AND mount-only check (`if user.global_role != "admin"` in mount, nothing in handlers) → **the gap**. The mount redirect protects initial HTTP + navigation, but a socket that already mounted keeps firing events — and nothing re-validates. Flag every destructive handler in that file.

**Distinguish from 1a:** mount-only check with the LiveView correctly behind
`live_session :admin` = high (defense-in-depth, events unguarded), NOT medium.
1a (mount doesn't re-check AND router protects) is medium. The tell: does the
file's mount check the role but its handlers don't? That's 1b-high.

**Sharper tell — `assign(:is_admin, true)` hardcoded.** Grep
`grep -n 'assign(:is_admin, true)' lib/*/live/*_live.ex`: an UNCONDITIONAL
`true` means mount never reads the role at all (verified my_app_gateway 2026-08,
MonitorLive — no mount check, no hook, router-only protection; rate 1b-high).
Don't flag the benign variant: when the assign sits in the `else` branch of
an explicit mount role check (`if user.global_role != "admin" -> redirect`),
only admins reach it and `true` is correct (verified my_app_gateway ServicesLive/
TeamsLive — the require_admin_hook afterwards then works as intended).

**Pattern to flag:**
```elixir
# DANGEROUS — template hides the button, but handler doesn't check
def handle_event("delete_provider", %{"id" => id}, socket) do
  provider = Providers.get_provider!(id)
  Providers.delete_provider(provider)  # ← no is_admin check!
  ...
end
```

**Safe pattern (per-handler):**
```elixir
def handle_event("delete_provider", %{"id" => id}, socket) do
  if socket.assigns.is_admin do
    # ... delete logic
  else
    {:noreply, put_flash(socket, :error, "No tienes permisos para esta acción.")}
  end
end
```

**Safe pattern (whole-LiveView, preferred for admin-only pages):** a single
`attach_hook` in mount halts EVERY event for non-admins — no per-handler
edits, and future events added to the LiveView are covered automatically.
Verified in MyApp (ProvidersLive / UsersLive / AlertsLive):

```elixir
def mount(_params, _session, socket) do
  user = socket.assigns[:current_user]

  socket =
    socket
    |> assign(:is_admin, user && user.global_role == "admin")
    |> attach_hook(:require_admin, :handle_event, fn _event, _params, socket ->
      if socket.assigns[:is_admin] do
        {:cont, socket}
      else
        {:halt, put_flash(socket, :error, "No autorizado.")}
      end
    end)

  {:ok, socket}
end
```

Note: `socket.assigns[:current_user]` is available in mount only when the
LiveView sits behind a `live_session` whose `on_mount` hook assigns it
(e.g. `UserAuth :require_authenticated`). Verify that first — the hook
pattern guards events, it does not authenticate the mount.

**Audit grep:**
```bash
# Find all handle_event clauses:
grep -n 'def handle_event' lib/*/live/*_live.ex
# Find which check is_admin:
grep -n 'is_admin\|global_role.*admin' lib/*/live/*_live.ex
# Files in list 1 but not in list 2 = potential gap
```

### 1c. IDOR — access to resources of another team/scope by ID

Check every controller action and LiveView handler that accepts a resource ID
from the client. The ID must be validated against the user's scope before use.

**Common IDOR patterns:**
- Controller accepts `team_id` query param and passes it directly to a query
  function without checking team membership.
- LiveView `handle_params` accepts `%{"id" => team_id}` and loads the team
  without verifying the user manages that team.
- Export endpoint takes `model_id` or `team_id` and returns cross-scope data.

**Audit pattern:**
```bash
# Find handlers that accept IDs from params:
grep -n 'params\[.id.\]\|%{.id. =>\|team_id.*params\|model_id.*params' lib/*/controllers/*.ex lib/*/live/*_live.ex
# Then trace each to its query — does it apply scope?
```

See `references/MyApp-audit-example.md` for a worked IDOR example in a
stats export controller.

### 1d. Analytics scoping drift — the "always-nil scope" bug

Role-scoped analytics pages (dashboards, stats) often route queries through a
scoping helper that builds a filter map. The silent failure mode: the helper
**never sets the filter key to a restrictive value**, so every downstream
query is org-wide for every role:

```elixir
# DANGEROUS — team_id is nil in EVERY clause: admin, manager AND user
defp scope_for(%{global_role: "admin"}), do: %{team_id: nil, ...}
defp scope_for(%{global_role: "user"} = user) do
  # computes manager_team_ids / member_ids... but still returns team_id: nil
end

# caller: Rollup.breakdown_by_model(scope[:team_id], opts) → always org-wide
```

The tell on the page: scoped KPI cards next to an unscoped breakdown table
(one part of the page was fixed, the other drifted). Verify by reading the
helper — at least one clause must return a restrictive value, and EVERY
consumer query must apply it. Rate it high when the leak exposes emails or
per-person/per-team consumption.

**Fix pattern (verified in MyApp):** centralize scope resolution in the
context as `Accounts.scope_member_ids(user)` → `nil` for admin (unrestricted),
member ids for manager (all members of managed teams) and user (own
memberships). Thread it into rollup queries via a generic option + `maybe_`
helper where `nil` = no filter and `[]` = matches nothing (fail-closed for
users with no memberships):

```elixir
defp maybe_member_ids(query, nil), do: query
defp maybe_member_ids(query, ids) when is_list(ids),
  do: where(query, [rl], rl.team_member_id in ^ids)
```

**Variant — dual-scope pages: audit the RENDER layer, not just the
queries.** Dashboards visible to all authenticated users often compute BOTH
user-scoped and org-wide stats deliberately ("you vs team vs org" cards).
The queries can be perfectly scoped while the template leaks: org
aggregates rendered with zero role guards. Verified my_app_gateway 2026-08:
`/dashboard` (all-users live_session) computed `model_usage_stats_org/2`
for every user and the .heex rendered `stats.org.cost_usd` etc. with no
`@is_admin` anywhere — despite a code comment stating "the org-wide view
lives in /dashboard/stats" (the admin page). Audit step: after verifying
query scoping, `grep -n 'is_admin\|global_role' lib/*/live/*.heex` — zero
hits on a page that computes org stats is the finding. Rate Medium for
aggregates (no per-user PII), High when per-person rows leak.

### 1e. Drill-down URL params bypass guards (IDOR via handle_params)

LiveViews that accept resource ids from URL params for drill-down tables
(`?team_id=`, `?model_id=`) frequently lack the authorization guard that a
sibling controller has. Worked example: a CSV export controller guarded team
drill-downs with `team_export_allowed?/2`, but the stats LiveView rendered
member emails + consumption for ANY crafted `?team_id=` — the LiveView was
the unguarded back door showing the same data.

**Audit pattern:** for every `handle_params` that assigns a resource id from
params, find the query it feeds and check the id is validated against the
user's managed scope first. Compare against the equivalent controller/export
guard — if the controller has one and the LiveView doesn't, that's the
finding. Fix fail-closed: unvalidated id → empty tables, never cross-scope
data.

**Audit grep:**
```bash
# LiveViews assigning resource ids from URL params:
grep -n 'params\["team_id"\]\|params\["model_id"\]\|params\["id"\]' lib/*/live/*_live.ex
# Scoping helpers that never return a restrictive value:
grep -n 'team_id: nil' lib/*/live/*_live.ex
```

### 1e. Audit log written but never fed (audit coverage gap)

The audit subsystem exists (`Auditing.audit/5`, an `audit_logs` table) but
only a couple of actions call it — typically impersonation. Everything else
sensitive (user create/edit/suspend/delete, password resets, credential
creation, API key replacement by admins, destructive resets like
"reset logs") writes to the DB with no audit row. When an incident happens,
there is no trail of who did what.

**Audit grep:**
```bash
# What calls the audit function?
grep -rn 'Auditing.audit' lib/ --include='*.ex'
# Then compare against the list of admin/destructive actions:
grep -n 'def handle_event' lib/*/live/*_live.ex | wc -l
# A handful of audit call sites vs dozens of destructive handlers = the gap.
```

**Rate Medium.** Not directly exploitable, but it defeats the purpose of
having the table, and incident response becomes guesswork. Fix: instrument
the user-management, credential-management and destructive-reset context
functions (not every LiveView handler — centralize at the context layer so
future callers inherit it).

### 1f. Orphaned LiveView files not registered in the router

The inverse of 1a — a LiveView module exists on disk but has NO route in
`router.ex`. Not exploitable today, but it's a live grenade: the file usually
does its own authorization dance in mount (or worse, doesn't) because it was
written before the `live_session :admin` pattern existed. The day someone
adds a route for it — without placing it in the right live_session — the
weak mount check is all that stands between a regular user and a
cross-team destructive action.

**Worked example (MyApp 2026-08):** `api_keys_live.ex` let any
"manager" revoke API keys across teams. It had no route (dead code) and
only checked `manager?/2` in mount — no `attach_hook`, not in
`live_session :admin`. One `live "/dashboard/api-keys", ApiKeysLive` line
added to the wrong scope would have exposed revocation of any team's key
to any authenticated user.

**Audit grep:**
```bash
# LiveViews on disk:
ls lib/*/live/*_live.ex | xargs -n1 basename
# Modules referenced in router:
grep -o '[A-Z][A-Za-z]*Live' lib/*/router.ex | sort -u
# Any file in list 1 whose module is absent from list 2 = orphan. Flag as
# MEDIUM with "add to :admin live_session or delete the file".
```

### 1g. Fail-open identity defaults — session identity not backed by a DB row

The inverse of a missing check: a check whose "record not found" branch
grants MORE privilege. Typical shape: login caches `is_admin` in the session
by looking up the user; when `get_user_by_email/1` returns nil (deleted user,
legacy pre-multi-user session), a `nil -> true` / `nil -> :all` branch turns
the session into full admin with access to every scope instead of killing it.

**Verified MyApp 2026-08:** `Plugs.Auth.login/3` (`nil -> true` for the
session `is_admin` flag), `assign_to_socket/2` (`nil -> {all_contexts, true}`),
`switch_context` (`is_nil(user) -> :all`). Deleting a user row while their
session is alive ESCALATES the session to admin instead of ending it.

**Audit grep:**
```bash
grep -rn 'nil -> true\|nil -> :all' lib/ | grep -i 'admin\|context\|scope\|role'
```

**Fix:** fail closed — `nil -> false`, or force logout
(`configure_session(drop: true)` + redirect to login) when the session
identity has no backing row. Rate High when admin rights or cross-scope
access attach to the nil branch.

### 1h. JSON-RPC / MCP dispatch bypasses the HTTP-layer scope check (context-in-body IDOR)

Apps exposing MCP or JSON-RPC endpoints over HTTP often authenticate at the
controller and validate scope against a TOP-LEVEL HTTP param
(`conn.params["context"]`, query string), while the operation's real scope
travels NESTED inside the JSON-RPC body (`params.arguments.context`) or in a
resource URI (`page://{context}/{slug}`). If the authenticated identity is
never threaded into the dispatcher, the scope check is security theater.

**Verified CRITICAL, MyApp 2026-08 (scope 2 audit):** `MCPController`
validated `conn.params["context"] || default`, but `MCP.process_message`
called `execute_tool(tool_name, args)` — the `user` was never passed. An
`inject_user_context` helper only filled a DEFAULT context when args lacked
one; a caller-supplied `"context"` was honored untouched. Any low-privilege
user token (or a single-context API key) could read/update/DELETE pages in
ANY context via `tools/call` with `arguments: %{"context" => "other"}`, and
via `resources/read` on `page://other/secret`. 18 tools, none re-validated.

**Audit recipe (do all three):**
1. Find where the scope identifier is READ for the auth check
   (controller: `conn.params[...]`).
2. Find where the scope identifier is USED for the operation (dispatcher:
   `args["context"]`, URI segments). If (1) ≠ (2), the check is bypassable.
3. Check whether the authenticated identity reaches the dispatch function at
   all. `execute_tool(name, args)` without the user = every method is IDOR.
   Also trace session/agent-lookup methods that take NO scope param
   (e.g. poll-by-UUID) — they need `record.scope_id ∈ user.scopes` checks
   that a generic context-fix won't cover.

**Fix:** thread the identity into dispatch and validate the effective
context per call (centralize in `process_message` so future methods can't
skip it); for scope-less lookups, load the record and check its scope FK.
Rate Critical when destructive methods are reachable cross-scope.

**Audit grep:**
```bash
# Does the dispatcher receive the identity?
grep -n 'execute_tool\|process_message\|dispatch' lib/*/mcp.ex
# Where is the scope read vs used?
grep -n 'conn.params\["context"\]\|args\["context"\]' lib/ -r
```

### 1i. Mass assignment — diff the controller's param filtering against the changeset's cast list

Controllers that blacklist keys (`Map.drop(params, ["slug", "context"])`)
instead of whitelisting leak every changeset-castable field to the client.
The audit technique is a DIFF: list the changeset's `cast(attrs, [...])`
fields, subtract what the controller drops/whitelists — the remainder is
client-settable. Verified MyApp 2026-08: REST `PUT /api/pages/:slug` dropped
only slug/context, and the changeset cast `:context_id, :owner, :created_by,
:updated_by` → pages could be MOVED across silo contexts (relations left
dangling) and provenance forged, while the sibling MCP tool whitelisted and
was clean — the mismatch proves it wasn't intentional. Also check the
changeset for missing `foreign_key_constraint`s: without one, a bogus FK in
client params raises `Ecto.ConstraintError` (500) instead of a 422.

**Fix:** whitelist at the controller boundary (mirror the safe sibling), or
a dedicated API changeset that excludes scope FKs and provenance fields.

**Severity calibration — latent vs live (verified my_app_gateway 2026-08):** an
over-broad changeset (e.g. `registration_changeset` casting `global_role`/
`status` from a shared `@permitted` list) is CRITICAL only when a live
caller/route feeds it client params. Before rating, grep callers
(`grep -rn 'register_user' lib/ | grep -v 'def register_user'`) and the
router for a registration route. Zero callers + zero routes = latent: rate
Medium ("any future endpoint wired to this is instantly exploitable"), and
note the sibling changesets that ARE safe (e.g. `google_oauth_changeset`
casting only profile fields).

### 1j. Suspension/deactivation never reaches the data plane (status revocation gap)

Admin UIs let you suspend a user — but every auth path must honor it. Trace
what "suspend" actually WRITES (often only `users.status` via an
`admin_update_user` changeset), then audit EVERY non-session auth path for
a status re-check: API-key plugs, bearer auth, WS/token auth. The classic
gap: the API-key plug checks the KEY's status (`ak.status == "active"`)
and maybe the MEMBERSHIP's status, but never `member.user.status` — so a
"suspended" user keeps full data-plane access (spend keeps accruing) until
every key is individually revoked.

**Verified HIGH, my_app_gateway 2026-08:** `toggle_status` →
`admin_update_user(%{"status" => "suspended"})` touched only `user.status`;
`ApiAuth.active_membership/1` pattern-matched `TeamMember.status` only;
`get_team_member_by_api_key/1` filtered only `ak.status == "active"`.
Suspend was cosmetic on the proxy API.

**Audit recipe:**
1. Find the suspend/deactivate action; read exactly which rows/columns it
   updates (user only? memberships? keys?).
2. For each auth path (session plug, API-key plug, WS token), read the
   lookup's `where` and any `active_*` guard: does it re-check the USER's
   status, or only the credential's?
3. Fail condition: any path where a suspended user's credential still
   authenticates.

**Fix:** cascade on suspend (suspend memberships and/or revoke keys in the
same transaction) AND check `member.user.status` in the credential guard
(revocation can race, so do both). Rate High: the admin's action is
silently ineffective exactly where abuse costs money.

---

## Category 2 — N+1 Queries and Missing Preloads

### 2a. N+1 in LiveView mount

Check `mount/3` for loops that call context functions per item:

```elixir
# N+1 — one query per membership
Enum.map(memberships, fn membership ->
  limits = Accounts.effective_limits(membership)  # ← query per item
  spend = Budgets.spend(membership.id)             # ← query per item
  ...
end)
```

### 2b. N+1 in data loading helpers

Check `load_*` private functions for per-item queries:

```elixir
# N+1 — list_destinations per team
teams |> Enum.map(fn team ->
  {team, Observability.list_destinations(team.id)}  # ← query per team
end)
```

### 2c. Missing preloads

Check `preloads` in context functions — if a template accesses
`member.user.email`, the context function must preload `:user`. Missing
preloads cause `KeyError` at runtime or silent nil access.

**Audit grep:**
```bash
# Find preload usage:
grep -n 'preload:' lib/*/accounts.ex lib/*/logs.ex
# Find template access patterns:
grep -n 'member\.user\.\|team\.name\|\.api_key\.' lib/*/live/*_live.ex
```

### 2d. N+1 of WRITES — one UPDATE per row in batch jobs

The mirror of the read N+1: batch recomputes that issue one `Repo.update_all`
per row. Verified MyApp 2026-08 (scope 3): `Graph.refresh_pagerank/1` and
`refresh_communities/1` run one `UPDATE pages SET meta = meta || ?` per page
(graph.ex:155-171, 281-297) — thousands of individual UPDATEs on the nightly
cron. Fix: single `UPDATE ... CASE` / CTE, or chunked `Repo.update_all` over
id batches.

### 2e. N+1 inside search/excerpt builders (context layer)

Not just mounts/loaders: query-per-result inside a context function.
Verified MyApp 2026-08: `fts_search/2` runs one `Repo.one(ts_headline...)`
per result row (`Enum.map(results, ...)` — brain.ex:1662-1676): 21 queries
per search at the default limit, 51 via hybrid. With a small pool and no
`statement_timeout` this starves concurrent requests. Fix: compute the
excerpt in the main query's `select` (same `where`), not per row.

See `references/MyApp-audit-example.md` for concrete N+1 findings.

---

## Category 3 — Missing Pagination and Limits

Check every `list_*` function and every `Repo.all` call:

```elixir
# DANGEROUS — loads ALL records
def list_users, do: Repo.all(User)
```

**Safe pattern:**
```elixir
def list_users(limit \\ 100) do
  Repo.all(from(u in User, limit: ^limit, order_by: u.inserted_at))
end
```

Key tables to check for pagination:
- Users (admin user list)
- Teams (admin team list)
- Logs / audit trails (can grow unbounded)
- Team members (per team)

**Audit grep:**
```bash
grep -n 'def list_\|Repo.all' lib/*/*.ex | grep -v 'limit\|limit:'
```

LiveView streams with `phx-update="stream"` can hide the problem (only visible
items render), but the server still loads everything into memory.

**Retention-less append-only tables feeding full-scan views.** Check audit/
activity log tables (`*_log`) for any pruning/retention job, then check every
VIEW built on them. Verified MyApp 2026-08: `brain_log` grows forever (no
pruning anywhere — the only prune job targets report pages) and
`Journey.timeline/1` loads ALL `page.create` rows into memory with no `limit`
(journey.ex:34-41); a timeline that degrades as the log grows. Also grep for
dangerous DEFAULTS: `graph_data/2` with `max_nodes: nil` as the default loads
the whole graph — safe today only because the single caller passes a cap.

**Unbounded task fan-out.** `Enum.each(list, fn x ->
Task.Supervisor.start_child(sup, fn -> work(x) end) end)` spawns one process
per item with no concurrency bound — a backfill over N rows = N simultaneous
tasks against the DB and any external API. Also check per-save hooks: MyApp
fired TWO task-spawning schedules (`Embeddings.schedule/1` +
`PageAugmenter.schedule/1`) on every page create/update (brain.ex:506-507),
so an import of N pages = 2N tasks. Fix: `Task.async_stream(...,
max_concurrency: N, timeout: :infinity)` (the project's own AGENTS.md often
already recommends exactly this). Rate Medium.

**Limit-request vs clamp-ceiling mismatch (export completeness, verified
my_app_gateway 2026-08):** when a caller passes an explicit high limit (CSV
export `limit: 50_000`) but the context's `clamp_limit` caps at a small
`@max_limit` (500), the export silently truncates with no error — and the
audit trail ("we exported the logs") now documents incomplete data. Not a
security hole, but cross-check every explicit `limit:` at call sites
against the context's ceiling; flag a mismatch as Low.

---

## Category 4 — Insecure Secret Handling

### 4a. Plaintext secrets in database

Check schema files for fields named `*_encrypted` that are actually plaintext:

```elixir
# credential.ex
field :api_key_encrypted, :string  # ← is it actually encrypted?
```

**Three-step verification recipe (do all three before reporting):**

1. **Read the moduledoc.** "Encryption-at-rest is a post-MVP concern" or
   "stored as-is for now" = plaintext. The name `*_encrypted` is a red flag
   by itself — authors rarely mislabel ciphertext.
2. **`grep -rn 'encrypt\|decrypt\|Cloak\|EncryptedField\|crypto_one_time'` in
   `lib/`.** Zero hits in the module that owns the field = no encryption at
   the schema layer. (Hits in `deps/` only count if the module actually uses
   them — e.g., `Map.get(credential, :api_key_encrypted)` is a *read*, not a
   decrypt.)
3. **Check the migration column type.** `add :api_key_encrypted, :string`
   with no `cloak_encrypted: true` or `{:array, :binary}` is plaintext at
   rest. Postgres has no schema-level encryption; the field type is the
   tell.

**Fix pattern:** `cloak_ecto` (drop-in `Encrypted` field type backed by
AES-GCM) or roll your own with `:crypto.crypto_one_time_aead/6` and a
`:binary` column. Keep the encryption key in `SECRET_KEY_BASE` or a
dedicated `MY_APP_ENCRYPTION_KEY` env var; never bundle it with the
runtime that writes request logs.

**Re-audit pitfall (verified my_app_gateway 2026-08 follow-up):** before
re-reporting a previously documented finding as "still open", re-verify
against the CURRENT tree — remediation may have landed between audits.
Two confirmed regressions from a follow-up that didn't: flagging CSV
formula injection in `stats_export_controller` when
`csv_sanitize_formula/1` already prefixes `= + - @` (check
`grep -n 'sanitize_formula' lib/` first), and flagging "no login rate
limiting" when `plugs/attack.ex` (IP throttle on `/login`) already
exists in the endpoint. Both were fixed during the original audit's
concurrent remediation. The cheap guard: grep for the FIX function/
module name before writing the finding, and diff the report against
this skill's `references/*-audit-*.md` files for the repo — only report
net-new or still-broken items.

**Variant — app-issued auth tokens stored plaintext next to a hashed sibling
table.** The 4a recipe covers upstream provider keys; also check tokens YOUR
app issues (user API tokens, session tokens). Verified MyApp 2026-08:
`users.api_token` stored raw with `Repo.get_by(User, api_token: token)`
lookup, while the sibling `api_keys` table in the SAME codebase stores
SHA-256 `token_hash` + display `token_prefix` + virtual plaintext field
(api_key.ex). The coexistence is the tell — the secure pattern already
exists in the repo, it just wasn't applied to the user schema. Any DB read
(dump, replica, error page) yields fully usable tokens. Fix: migrate to the
sibling's hash+prefix pattern and rotate existing tokens. Rate High.

**Severity:** Critical. A SQL dump, a SQL injection, a compromised read
replica, or a leaked backup recovers every upstream provider key in plaintext.
These keys grant billing-eligible access to OpenAI/Anthropic/etc. — direct
financial exposure.

### 4b. Secrets in forms with type="text"

Check credential forms — API key inputs should use `type="password"`, not
`type="text"`:

```elixir
# DANGEROUS — key visible in DOM
<.input field={@form[:api_key_encrypted]} type="text" label="API key" />

# SAFE — masked input
<.input field={@form[:api_key_encrypted]} type="password" label="API key" />
```

**Variant — `type="password"` still ships the value in the DOM on EDIT
forms.** Phoenix's `<.input>` core component renders
`value={Phoenix.HTML.Form.normalize_value(@type, @value)}` for every type,
including `"password"`. An edit modal built from the persisted struct
(`to_form(changeset_from_credential)`) therefore embeds the FULL secret in
the page HTML — readable via view-source/DevTools and by any XSS on the
page, even though it displays as dots. Verified my_app_gateway 2026-08
(providers_live.ex `edit_credential` + core_components.ex).
**Fix:** blank the field before `to_form/1` on the edit path
(`put_change(changeset, :api_key_encrypted, nil)`) — the save handler
usually already treats an empty field as "keep current".

**Variant — webhook/observability destination headers (customer Bearer
tokens) rendered into edit-form textareas.** Destination configs that store
custom headers as a plaintext `:map` column and render the map back as JSON
in a `<textarea>` value expose stored `Authorization: Bearer` tokens in the
DOM on every edit. Fix: redact header *values* on render (show keys only)
and require re-entry of secrets, mirroring the credential edit flow.

### 4c. Secrets rendered in templates

Check for `mask_key` / masking functions — the full value should never reach
the template. Verify the masking function doesn't just slice a plaintext value
that's already in the assigns (the full value is in memory even if masked in
HTML).

**The non-obvious variant — full secret in LiveView assigns even though only
the last 4 chars render.** The `mask_key` function looks safe:
```elixir
def mask_key(key) do
  len = String.length(key)
  String.slice(key, len - 4, 4) |> then(&"••••••#{&1}")
end
```
…but the LiveView did `Repo.all(from(p in Provider, preload: [credentials: c]))`
first, which loaded every credential's `api_key_encrypted` into the socket
process. The HTML only shows `••••••abc1`, but the BEAM holds the full key.
Worse: the LiveView debug toolbar, a future HEEx debugger, or one accidental
`IO.inspect` dumps the entire struct.

**Defense-in-depth fix patterns (pick one):**

1. **Project away the column at the Repo boundary** — most defensive, no
   ciphertext to decrypt just to throw 99% of it away:
   ```elixir
   from(p in Provider,
     left_join: c in assoc(p, :credentials),
     select: %{
       p
       | credentials: %{
         c
         | api_key_encrypted: fragment("'••••••' || right(?, 4)", c.api_key_encrypted)
       }
     }
   )
   ```
   The socket now holds a fake-masked string in `:api_key_encrypted`, so
   existing templates (`{mask_key(cred.api_key_encrypted)}`) keep working
   with zero changes, and the secret never enters the BEAM.

2. **Add a virtual `masked_key` field on the schema** and project it in the
   query; remove `api_key_encrypted` from preloads.

3. **After SEC-001 (real encryption) lands**, hold the ciphertext in the
   struct and expose only the masked ciphertext tail for display. Plaintext
   only exists when actually calling the upstream.

**Severity:** High — expands blast radius of any future memory-disclosure bug
or HEEx debug mistake. Independent of SEC-001 (the plaintext-in-DB issue):
even after encryption-at-rest, the LiveView still decrypts into the socket.

**Audit grep:**
```bash
# Find every place that loads api_key_encrypted into a preload:
grep -rn 'preload.*credential\|assoc.*:credential' lib/
# Find every place that calls mask_key/masked_key on a credential field:
grep -rn 'mask_key.*api_key_encrypted\|masked_key.*api_key' lib/
```

**Fragment-display variant — "prefix" helpers can leak MORE than
`mask_key`, and fragments get PERSISTED.** Display helpers are not
uniformly safe: a helper that shows the FIRST 8 chars of a plaintext key
(`String.slice(key, 0, 8) <> "…"`) exposes real key material for providers
whose keys have no fixed prefix (worse than the conventional last-4), and
short-key fallback clauses like `def api_key_prefix(key), do: key` return
the WHOLE key for short values. Also trace fragments into persisted copies:
a `provider_key_prefix`-style column written into a request/audit log
table makes the fragment permanent and readable by anyone with DB access,
even where the live display was deemed acceptable. Verified my_app_gateway
2026-08 (monitor_live.ex first-8 display + whole-key fallback;
proxy_controller.ex last-4 persisted into request_logs.provider_key_prefix
and rendered in the logs UI).

**`data-*` attribute variant — full secret in the DOM via HTML data
attributes.** A `<code data-token={@api_token}>` or `<div
data-secret={@secret}>` renders the FULL value into the page HTML even
when the visible text is truncated or masked. View-source, DevTools, or
any XSS reads it straight from the DOM. Verified MyApp 2026-08
(dashboard_live.ex `data-token={@user_api_token}` — the template showed
`String.slice(token, 0, 8) <> "••••••••••••"` but the `data-token`
attribute carried the complete token; the JS hook read `dataset.token`
to copy it). Fix: never put the full secret in a `data-*` attribute —
render only the prefix, and fetch the full value via a dedicated
authenticated endpoint when the user explicitly requests it (e.g. a
"copy" button that pushes the value via `push_event` from the server,
never storing it in assigns).

### 4d. Secrets in logs

Check if API keys or tokens are logged. Search for `IO.inspect`, `Logger`,
or `require Logger` in modules that handle secrets.

**Audit grep:**
```bash
grep -rn 'IO\.inspect\|Logger\.\(debug\|info\|warn\|error\)\|require Logger' lib/
```

**Adjacent variant — upstream error messages may echo the bad key.** When
your gateway/proxy calls a third-party API and gets a 401/402/403, common
patterns persist the upstream's error body to a `error_message` column for
later admin triage. Upstreams (notably OpenAI) **echo a partial key** in
their error envelope — e.g., `"Incorrect API key provided: sk-proj-…XXXX"`.
That fragment ends up in the DB even though the admin UI only shows the
short `error_reason` (`auth_error_401`). Anyone with read access to the DB
sees the partial key.

**Fix pattern — scrub before persisting** (in the adapter, not the
controller, so the trust boundary is one place):
```elixir
defp scrub(msg) when is_binary(msg) do
  String.replace(
    msg,
    ~r/\b(sk-|gsk_|key-|sk-proj-|sk-ant-)[A-Za-z0-9_-]{6,}/,
    "[REDACTED]"
  )
end
```
Apply in `extract_error_message/1` BEFORE returning the message to the
controller. The same scrub should run on any error you serialize to a
client response or webhook body.

**Severity:** Medium. Not directly exploitable, but quietly expands the
secret footprint beyond the encrypted/database level.

### 4e. `Phoenix.Logger` parameter filter not configured

A defense-in-depth gap that costs nothing to fix. Phoenix's default
`:filter_parameters` is `[]` — if a `Plug.Logger` is ever added to the
endpoint pipeline, or if any LiveView request logger dumps `conn.params`,
fields like `password`, `token`, `api_key`, `secret` land in production
logs in plaintext.

**Verify with:**
```bash
grep -rn 'filter_parameters' config/
```
Empty result = unguarded.

**Fix:** Add to `config/config.exs`:
```elixir
config :phoenix, :filter_parameters,
       ["password", "secret", "token", "api_key", "client_secret", "authorization"]
```
The `{:keep, [...]}` variant enforces a positive list instead — useful when
you want to know exactly what's in the log format.

**Severity:** Medium. Becomes critical the moment a logger is added or any
third-party plug (Sentry, AppSignal, etc.) serializes params.

### 8d. `inspect/1` on unexpected error tuples leaks internals to the client

Error-handling catch-all clauses that format an unexpected error for the
client response often use `inspect/1` on the raw term:

```elixir
# DANGEROUS — leaks internal structures, IDs, tuples on unknown errors
defp error_details(other), do: {500, "api_error", "internal_error", inspect(other)}
```

An unhandled error shape (a tuple with provider IDs, a struct with
credential names, an Ecto changeset) gets serialized into the JSON
response body. The client sees internal identifiers, route maps, or
partial credentials that the application never intended to surface.

**Fix:** use a generic message for the client, log the `inspect` server-side:
```elixir
defp error_details(other) do
  Logger.error("unhandled proxy error: #{inspect(other)}")
  {500, "api_error", "internal_error", "Internal error"}
end
```

**Severity:** Medium. Not directly exploitable, but expands the information
footprint on error paths and can leak IDs/structs that aid further attacks.

**Audit grep:**
```bash
grep -n 'inspect(' lib/*/controllers/*.ex | grep -i 'error\|detail\|message'
```

---

## Category 5 — LiveView-Specific Bugs

### 5a. Missing assigns causing crashes

Check that every assign used in `render/1` is set in `mount/3` or
`handle_params/3`. Missing assigns cause `KeyError` on first render.

### 5b. Events without rate limiting on destructive actions

LiveView `handle_event` has no built-in rate limiting. Check all destructive
events (delete, revoke, replace, suspend, reset password) for:
- Rate limiting (Hammer, custom plug, or at minimum `data-confirm`)
- No way to spam-generate API keys or mass-suspend users

### 5c. PubSub storms

Check `handle_info` for PubSub handlers that execute DB queries on every
message. In high-traffic apps, every broadcast triggers a query in every
connected LiveView — no debounce = potential DB storm.

**Canonical offender:** a "metrics updated" topic broadcast on every proxied
request, with every connected dashboard doing a full metrics reload (5+
Postgres queries) per message. Same for a "new log" topic refreshing a
summary query per log line.

**Fix pattern — coalesce with `Process.send_after/3`:** cap reloads at one
per interval per connected LiveView (verified in MyApp, 2s window).
When ONE handler carries multiple reload triggers, **each trigger needs its
own flag + timer** — coalescing the budget reload but not the error reload
(verified MyApp Aug 2026, AlertsLive) still leaves one query per
broadcast on the uncoalesced path. Check every `load_*` call inside
`handle_info` for a matching `_scheduled` flag.

```elixir
@reload_interval_ms 2_000

def handle_info({:metrics_updated, _}, socket) do
  if socket.assigns[:reload_scheduled] do
    {:noreply, socket}
  else
    Process.send_after(self(), :reload_metrics, @reload_interval_ms)
    {:noreply, assign(socket, :reload_scheduled, true)}
  end
end

def handle_info(:reload_metrics, socket) do
  {:noreply,
   socket
   |> assign(:reload_scheduled, false)
   |> load_metrics(socket.assigns.current_user)}
end
```

Requires initializing `assign(:reload_scheduled, false)` in mount. The UI
stays "real-time" (≤2s lag) while DB load becomes independent of traffic.

**Emit-side amplification — one write, many broadcast cycles.** The inverse
of the receiver storm: a single context write that fans out into cascading
writes, each with its own broadcast/log/snapshot/background task. Verified
MyApp 2026-08: one todo status change → `update_page` (version snapshot +
log + full-struct broadcast + embed schedule) → `sync_todo_links` →
`recompute_goal_progress` → ANOTHER full `update_page` on the parent goal →
`recompute_project_health` → TWO more `update_page_meta_field` calls —
3-4 complete write cycles and 3-4 full-struct PubSub broadcasts per single
user edit (brain.ex:1148-1331). The tell: internal recomputes calling the
full public `update_*` instead of a side-effect-free path. Fix: derived
fields go through `Repo.update_all` + jsonb merge (the codebase's own
`Graph.refresh_pagerank` already does exactly this to avoid the side
effects — cite it), and consolidate multiple meta writes into one. Also
note WHAT gets broadcast: a full struct with `body` on every save, and
agent frameworks that rebroadcast every step (with tool results containing
page bodies) to a shared `agents:all` topic — payload confidentiality +
frequency, not just query load.

### 5d. Elixir syntax bugs in assigns access

Check for the `socket.assigns[:period || "today"]` pattern — this evaluates
the atom `:period` (always truthy) instead of the variable. Should be
`socket.assigns[:period] || "today"`.

### 5e. Unvalidated client input in handle_event

Check that `team_role`, `status`, and other enum values from client events are
validated before passing to `update_*` functions. The template's `<select>`
only offers valid values, but a malicious client can send any string.

### 5f. Dropped keyword opts in delegating helpers

Correctness bug adjacent to audits: helpers that delegate to context/rollup
functions but drop the caller's options with a literal `[]` — the period
filter silently stops applying:

```elixir
# BUG — period selected in the UI is ignored; breakdown always lifetime
defp load_member_breakdown(%{manager_team_ids: ids}, opts) do
  Enum.flat_map(ids, fn team_id -> Rollup.breakdown_by_member(team_id, []) end)
end
```

The tell is `, [])` on a call whose sibling calls pass real opts. When a page
shows "correct KPIs, wrong table for the selected period", look here. Fix:
thread opts through; if scoping moved into the query layer (see 1d), collapse
the per-team flat_map into a single scoped query.

### 5g. Crash-on-input parsers in handle_event

`Decimal.new/1` and `String.to_integer/1` raise on malformed input — a crafted
(or sloppy numeric) form field kills the LiveView process. Check every
`handle_event` that parses numbers from params. Fix with `Decimal.parse/1` /
`Integer.parse/1` in a `with` chain and an error flash on `:error`.

**REST API controller variants (verified MyApp 2026-08, scope 2):** the same
class appears in JSON controllers, where a 500 is also the WRONG status
(should be 400/404):
- `params["limit"] && String.to_integer(params["limit"])` on query params →
  `ArgumentError` on `?limit=abc`.
- `Repo.get(Schema, id)` on a `:binary_id` primary key with a non-UUID path
  param (`PUT /api/todos/abc`) → `Ecto.Query.CastError`. Fix:
  `Ecto.UUID.cast/1` first, 400/404 on `:error` (the correct pattern usually
  already exists somewhere in the same codebase — grep for `UUID.cast`).
- Negative `limit`/`offset` reaching Ecto → `Postgrex.Error`
  ("LIMIT must not be negative"). Clamp to `[1, max]` / `>= 0` at the
  controller boundary; a `min(limit, 500)` cap without a floor is not enough.
- JSON-RPC `params` that aren't a map (string/array) hitting
  `params["name"]` → `ArgumentError` via Access on binary/list. Add
  `when is_map(params)` guards and return the protocol error (`-32602`).

**LiveView bang-lookup variant (verified my_app_gateway 2026-08):**
`Accounts.get_team!(id)` / `get_service!(id)` / `get_destination!(id)` on
`handle_event` params — unknown id → `Ecto.NoResultsError` kills the
LiveView; non-UUID id → `Ecto.Query.CastError` (same class as the REST
`Repo.get` variant above). Common on admin CRUD pages where every event
carries a row id. When all callers are admin-gated, rate Low
(availability-only) and note the pattern per 1d/1e; fix is non-bang `get_`
+ nil→flash, or `Ecto.UUID.cast` at the event boundary.

### 5h. Polymorphic helper called with a struct it doesn't match (badge/label always falls through)

Helpers that derive a badge, label, or style from a string discriminator
(`"member"`/`"team"`/`"global"`) often get called from the template with the
full struct instead. Every call then hits the catch-all `_` clause and the UI
shows the default for EVERY row ("always says Global"). The tell: the
function's clauses only match strings, the template passes `ap`/`item`
directly, and no `case`/`scope_for` translation layer exists between them.

**Audit pattern:**
```bash
# Template calls passing a bare variable to a helper:
grep -n 'scope_badge(\|scope_label(\|badge_for(\|label_for(' lib/*/live/*_live.ex lib/*/live/*.heex
# Then read the helper — if no clause matches the struct shape, flag it.
```

**Fix:** add struct clauses to the helper that derive the discriminator from
the struct's real fields (usually FK presence), keeping the string clauses for
back-compat:
```elixir
def scope_badge(%ModelProvider{exclusive_to_team_member_id: id}) when not is_nil(id), do: "badge-warning"
def scope_badge(%ModelProvider{exclusive_to_team_id: id}) when not is_nil(id), do: "badge-info"
def scope_badge(%ModelProvider{}), do: "badge-ghost"
def scope_badge("member"), do: "badge-warning"
def scope_badge(_), do: "badge-ghost"
```
Rate Medium — it's a display lie, not an auth hole, but it hides real
scoping from admins (e.g. an exclusive model looks global).

### 5i. Strict `{:ok, ...}` pattern-match on calls backed by external services

`{:ok, results} = Context.search(...)` in a LiveView `handle_params` or
`handle_event` crashes the process with a `MatchError` when the backing
external service (embeddings, LLM, HTTP fetch) is down and the context
returns `{:error, _}`. The template doesn't matter — the match fails before
render. Verified MyApp 2026-08: `search_live.ex` matched `{:ok, results}` on
`Brain.search/1`; semantic/hybrid strategies hit the embeddings API, so an
outage turns every search into a LiveView crash.

**Audit grep:**
```bash
grep -n '{:ok, .*} = ' lib/*/live/*_live.ex
# per hit: can the right-hand call fail on an EXTERNAL dependency (network,
# LLM, embeddings)? DB-only calls failing is rarer; external ones are the flag.
```

**Fix:** `case` on the result with a graceful empty state / error flash, or
normalize in the context layer so external failure degrades to `{:ok, []}`.
Rate Medium (availability, not data exposure).

---

## Remediation Mode (when the user asks to fix, not just report)

This skill is read-only by default, but users often ask "audit AND fix what
you find". In remediation mode:

1. Fix findings in priority order (authorization/IDOR first, then secrets,
   then performance), one focused change per finding — no drive-by refactors.
2. Prefer SQL-level scoping over in-Elixir post-filtering when the fix touches
   a query module (post-filter still runs the org-wide query; acceptable only
   when row-level identity is needed, e.g. team tables for managers).
3. Delete helpers that become unused after the fix (compiler warnings fail
   `--warnings-as-errors`).
4. Verify with the project's own gate (`mix precommit`, or
   `mix compile --warnings-as-errors` + full `mix test`) before claiming done.
5. Commit only the files the fixes touched; separate any pre-existing WIP.
6. In the report, split "fixed" from "found but not fixed" (documented
   product decisions, migration-sized changes like encryption-at-rest) so the
   user can decide on the leftovers.
7. **Expect existing tests to assert the vulnerable behavior.** Fixes that
   change user-visible output (uniform login messages, scrubs, new error
   text) will break tests written against the old strings. When the gate
   fails on exactly the assertion your fix was supposed to change, update
   the test to assert the NEW behavior (plus the security invariant, e.g.
   `refute get_session(conn, :user_id)` after a rejected login) — don't
   revert the fix. Verified: the 8a uniform-message fix broke a
   `users_live_test.exs` test asserting `flash =~ "suspendida"`.

---

## Category 6 — OAuth Pitfalls (when applicable)

### 6a. Empty allowlist treated as "allow all"

Check domain allowlist logic:

```elixir
# DANGEROUS — nil/[] means "allow everyone"
case config()[:allowed_domains] do
  nil -> true      # ← anyone can auto-register
  [] -> true       # ← anyone can auto-register
  domains -> ...
end
```

Should be fail-closed: `nil` / `[]` = auto-registration disabled.

### 6b. Non-timing-safe state comparison

OAuth CSRF state should use `Plug.Crypto.secure_compare/2`, not `!=`:

```elixir
# DANGEROUS — timing attack
if state != stored_state do

# SAFE
if not Plug.Crypto.secure_compare(state, stored_state) do
```

---

## Category 7 — Session Management

### 7a. Session fixation — no session renewal after login / privilege change

Check every point where the session's identity changes: email/password login,
OAuth callback, impersonation start/stop, "switch account". Each must call
`Plug.Conn.configure_session(conn, renew: true)` so the session id rotates.
Without it, the pre-login session id (which an attacker may have planted via
XSS, a sibling subdomain, or cookie tossing) survives authentication — classic
session fixation.

**Pattern to flag:**
```elixir
# DANGEROUS — session id unchanged across login
conn
|> put_session(:user_id, user.id)
|> redirect(to: "/dashboard")
```

**Safe:**
```elixir
conn
|> configure_session(renew: true)
|> put_session(:user_id, user.id)
|> redirect(to: "/dashboard")
```

**Audit grep:**
```bash
# Identity changes can live in controllers AND in shared auth helpers
# (plugs/auth.ex, user_auth.ex) — grep the whole lib/, not just controllers.
# Verified MyApp 2026-08: the login helper was Plugs.Auth.login/3 and
# controllers-only greps missed it; zero configure_session in all of lib/.
grep -rn 'put_session' lib/ | grep -v 'delete_session\|get_session'
# Any identity-changing put_session must sit next to:
grep -rn 'configure_session' lib/
```
Apply the check to impersonation start AND stop (both swap `:user_id`), and to
the OAuth callback's session creation. Rate it high — exploitable without any
other vuln when combined with cookie planting, and the fix is one line.

### 7b. Session cookie hardening

Session fixation (7a) handles the identity-change case. The cookie itself
also needs hardening — defaults are minimal and Phoenix's `Plug.Session`
doesn't enable everything out of the box.

**Check `@session_options` in `endpoint.ex` and verify:**

- **`secure: true`** — cookie only sent over HTTPS. In prod, rely on
  Phoenix's `force_ssl` rewrite, but be explicit so a misconfigured deploy
  (e.g., `PHX_HOST=localhost` accidentally) doesn't send the session over
  plain HTTP.
- **`http_only: true`** — JS can't read the cookie (Phoenix's default, but
  write it explicitly).
- **`encryption_salt`** — sessions are signed but not encrypted by default,
  meaning the client can read (not tamper with) every session key. If the
  session ever holds anything more sensitive than a UUID (an OAuth state,
  a token, a role blob), add `encryption_salt:` with a distinct salt from
  `signing_salt`.
- **`same_site: "Lax"`** (or `"Strict"`) — defends against CSRF cross-site
  cookie tossing. `"Lax"` is the right default for browser apps.
- **`max_age:`** — bound the session lifetime. Eight hours is a common
  default for admin dashboards.

**Pattern to flag:**
```elixir
# MINIMAL — no encryption, no explicit secure, no max_age
@session_options [
  store: :cookie,
  key: "_my_app_key",
  signing_salt: "TwS/TtVu",
  same_site: "Lax"
]
```

**Hardened version:**
```elixir
@session_options [
  store: :cookie,
  key: "_my_app_key",
  signing_salt: System.get_env("SESSION_SIGNING_SALT", "..."),
  encryption_salt: System.get_env("SESSION_ENCRYPTION_SALT", "..."),
  same_site: "Lax",
  secure: true,
  http_only: true,
  max_age: 60 * 60 * 8
]
```

**Severity:** Low for the cookie attributes themselves (most Phoenix apps
ship this way and it works), Medium if the session actually carries
sensitive content (tokens, refresh data).

---

## Category 8 — Information Disclosure & Defaults

### 8a. Login error messages distinguish "user exists" from "user doesn't"

When `Accounts.authenticate_user/2` returns `{:error, :suspended}` for a
known-but-suspended user and `{:error, :unauthorized}` for an unknown
email, and the controller surfaces both distinctly, an unauthenticated
visitor can enumerate which email addresses are registered and which are
suspended.

**Pattern to flag:**
```elixir
# DANGEROUS — two different flashes for two different failure modes
case Accounts.authenticate_user(email, password) do
  {:ok, user} -> ...
  {:error, :suspended} -> put_flash(:error, "Tu cuenta está suspendida.") |> render(:new)
  {:error, :unauthorized} -> put_flash(:error, "Credenciales inválidas.") |> render(:new)
end
```

**Fix:** Uniform user-visible message; log the real reason server-side:
```elixir
case Accounts.authenticate_user(email, password) do
  {:ok, user} -> ...
  {:error, reason} ->
    Logger.warning("login_attempt status=#{reason} email_hash=#{hash(email)}")
    put_flash(:error, "Credenciales inválidas.") |> render(:new)
end
```

**Severity:** Low. Most apps accept this trade-off — but it's free to fix
and is a common "first recon step" for targeted attacks.

**Audit grep:**
```bash
grep -rn 'suspended\\|no_user\\|invalid_credentials\\|not_found' lib/ | grep -v test
```

**Timing variant — no `Bcrypt.no_user_verify` for unknown emails.** Even with
a perfectly uniform message, `authenticate_user/2` that returns early for an
unknown email leaks "user exists" via response timing: bcrypt verification
costs ~50–100ms, the miss branch returns in microseconds. Verified MyApp
2026-08: `authenticate_user` did `Bcrypt.verify_pass` for known users but
plain `{:error, :unauthorized}` for unknown ones.

```elixir
# DANGEROUS — timing oracle even though the message is uniform
case get_user_by_email(email) do
  %User{password_hash: hash} = user when is_binary(hash) ->
    if Bcrypt.verify_pass(password, hash), do: {:ok, user}, else: {:error, :unauthorized}
  _ ->
    {:error, :unauthorized}   # ← returns instantly
end

# SAFE — equalize the work in the miss branch
_ ->
  Bcrypt.no_user_verify()
  {:error, :unauthorized}
```

Also cover users whose `password_hash` is NULL (OAuth-only accounts) — the
`when is_binary(hash)` guard falls through to the fast branch for them too.
Rate Low (needs many samples to exploit) — but the fix is one line.

### 8b. Shared secret defaults (`Application.get_env/3` with string fallback)

Hardcoded fallback strings in production code paths are real defaults.
`Application.get_env(:MyApp, :webhook_secret, "MyApp-dev-secret")`
returns the hardcoded string whenever the env var is unset — an operator
who forgets to set the env var in prod silently signs every outgoing
webhook with a publicly-known string (the GitHub repo).

**Pattern to flag:**
```elixir
# DANGEROUS — silent fallback
secret = Application.get_env(:MyApp, :webhook_secret, "MyApp-dev-secret")
secret = System.get_env("GOOGLE_OAUTH_CLIENT_SECRET") || "fallback-secret"
```

**Fix:** Fail closed with `fetch_env!/2` or an explicit `raise`:
```elixir
secret = Application.fetch_env!(:MyApp, :webhook_secret)
# Or, for env vars:
secret = System.fetch_env!("GOOGLE_OAUTH_CLIENT_SECRET")
```

**Severity:** Medium (the secret is disclosed in the repo, so anyone
watching can forge signed payloads to a customer's endpoint). Comparable
to the `SECRET_KEY_BASE` pattern in `runtime.exs` — adopt that style for
every production secret.

**Audit grep:**
```bash
grep -rn 'Application\.get_env\|System\.get_env' lib/ | grep '"'
# Any literal string fallback in a get_env call = flag.
```

### 8c. `force_ssl` excluded for `localhost` in prod

`config :MyApp, MyappWeb.Endpoint, force_ssl: [rewrite_on: [:x_forwarded_proto], exclude: [hosts: ["localhost", "127.0.0.1"]]]`
is a documented Phoenix default. If the operator ever sets `PHX_HOST=localhost`
(e.g., a behind-the-proxy deployment) thinking it'll route around the
production TLS chain, TLS termination is bypassed silently.

**Fix:** Document in `prod.exs` that `PHX_HOST=localhost` is a deliberate
dev-mode choice and should not be used in real prod. Consider removing the
`exclude:` clause and forcing HSTS unconditionally for single-host
deployments.

**Severity:** Low.

### 8d. LIKE wildcard injection in search/autocomplete functions

Search helpers that wrap user input in `"%#{query}%"` for `ilike` without
escaping `%` and `_` let ANY user enumerate the full table by searching
`"%"` — and `%a%b%c%` patterns are expensive for Postgres. No SQL injection
(Ecto parameterizes), but it's user enumeration plus a perf footgun. Worked
example (MyApp 2026-08, NM1): `Accounts.search_users/2` feeding the
member-add autocomplete.

**Audit grep:**
```bash
grep -rn '"%#{' lib/ | grep -i 'ilike\|like'
# For each hit: does the code escape %, _, and \ before interpolating?
```

**Fix pattern (verified, MyApp):**
```elixir
escaped =
  query
  |> String.replace("\\", "\\\\")
  |> String.replace("%", "\\%")
  |> String.replace("_", "\\_")

pattern = "%#{String.downcase(escaped)}%"
```
Tests that prove it: `search("%")` must return `[]` unless a row literally
contains `%`, and a row storing `"50%"` must still match `"50%"`.
Rate Medium — the `limit` clause mitigates but doesn't fix.

**Stored-input variant — LIKE built from an unvalidated DB field.** The
wildcard can also come from a column, not request params. Verified MyApp
2026-08: `Page.changeset` validates `slug` only by length, and
`rename_slug/2` interpolates the stored slug into
`like(p.body, ^"%![[#{old_slug}%")` (brain.ex:2203). A slug containing
`%`/`_` (writable via API) over-selects rows for the rewrite cascade —
churn/DoS, not SQLi (parameterized; the body rewrite used `Regex.escape`).
Fix both ends: `validate_format(:slug, ~r/^[a-z0-9-]+$/)` on the schema AND
escape `%`/`_` when building LIKE patterns from any stored value.

### 8e. Session salts with hardcoded repo defaults (endpoint.ex variant of 8b)

Same class as 8b but for `@session_options` in `endpoint.ex`:
`signing_salt: System.get_env("SESSION_SIGNING_SALT", "TwS/TtVu")`. If prod
deploys forget the env vars, every deployment shares the salts committed to
the (possibly public) repo — session cookies become forgeable/decryptable
by anyone who read the source. **Fix (verified, MyApp):** keep the
fallback for dev/test, but add a `raise` in the `config_env() == :prod`
block of `runtime.exs` (same pattern as `SECRET_KEY_BASE`):

```elixir
for var <- ["SESSION_SIGNING_SALT", "SESSION_ENCRYPTION_SALT"] do
  System.get_env(var) || raise "environment variable #{var} is missing..."
end
```
Rate Low→Medium depending on repo visibility.

**Sibling gap — LiveView `signing_salt` in config.exs.** The runtime raise
pattern usually covers SECRET_KEY_BASE and SESSION_* salts but forgets
`live_view: [signing_salt: "..."]` in `config/config.exs`, which stays
hardcoded in prod (verified MyApp 2026-08, config.exs:23 — no override
anywhere). Limited blast radius (session is separately encrypted), but it's
a public signing secret: move it to runtime.exs with the same
`System.get_env || raise` pattern. Rate Low→Medium.

### 8f. `inspect(reason)` in client-facing error bodies leaks internal infra

Error branches that return `json(%{errors: %{detail: inspect(reason)}})` (or
interpolate `"Error: #{inspect(reason)}"` into MCP tool text) hand the client
raw Elixir error structs: Req/Mint/Finch errors carry the INTERNAL URL, host
and port of backing services (inference/embeddings servers); Postgrex errors
carry SQL detail. On admin-only endpoints it's noise; on endpoints reachable
by low-privilege tokens (MCP user tokens, scoped API keys) it's internal
topology disclosure. Verified MyApp 2026-08: `search_controller` 502s and
`dran_search` tool errors both surfaced `inspect(reason)` to non-admin
callers.

**Audit grep:**
```bash
grep -rn 'inspect(reason)\|inspect(reason)' lib/*/controllers/ lib/*/mcp.ex
# per hit: who can reach this endpoint — admin only, or any valid token?
```

**Fix:** generic client message ("search backend unavailable") +
`Logger.error(inspect(reason))` server-side. Rate Medium when reachable by
non-admin tokens; Low otherwise.

---

## Category 9 — Infrastructure & Transport (prod config)

### 9a. Database SSL without certificate verification

`config/runtime.exs` — the Repo config often defaults to
`ssl_opts: [verify: :verify_none]` because "managed DBs use self-signed
certs". That's a MITM hole between the app and Postgres (VPC peering,
DNS poisoning, compromised jump host).

**Pattern to flag:**
```elixir
# DANGEROUS — MITM-able DB connection
[ssl: true, ssl_opts: [verify: :verify_none]]
```

**Fix:** opt back into verification and point at the provider's CA:
```elixir
[ssl: true, ssl_opts: [verify: :verify_peer,
                       cacerts: :public_key.cacerts_get()]]
# or for managed DBs with their own CA:
[ssl: true, ssl_opts: [verify: :verify_peer,
                       cacertfile: "priv/certs/cloudsql-ca.pem"]]
```
The correct fix for self-signed managed certs is distributing the CA, not
disabling verification. Rate high — DB traffic carries every secret in the
app.

**Audit grep:**
```bash
grep -n 'verify_none\|verify: :verify' config/*.exs
```

### 9b. No request body size limit on public endpoints

`Plug.Parsers` without `:length`/`:read_length` lets a client POST a
multi-hundred-MB JSON body. The JSON decoder buffers the whole thing in
memory before any auth or validation runs — an unauthenticated memory-exhaustion
DoS on your most exposed route.

**Pattern to flag:**
```elixir
plug Plug.Parsers,
  parsers: [:urlencoded, :multipart, :json],
  pass: ["*/*"],
  json_decoder: Phoenix.json_library()
  # ← no length:, no read_length:
```

**Fix:** cap it (8MB covers chat payloads; embeddings/rerank batches may
need more):
```elixir
plug Plug.Parsers,
  parsers: [:urlencoded, :multipart, :json],
  pass: ["*/*"],
  json_decoder: Phoenix.json_library(),
  length: 8_000_000,
  read_length: 1_000_000
```
Rate high on any app with a public/proxy API; medium for browser-only apps.

**Audit grep:**
```bash
grep -A6 'plug Plug.Parsers' lib/*/endpoint.ex | grep -c 'length'
# 0 = unguarded
```

### 9c. Login endpoint without brute-force rate limiting

The session controller passes credentials straight to
`Accounts.authenticate_user/2`. Bcrypt makes each attempt expensive, but
nothing stops an attacker from trying thousands of passwords per minute
from one IP.

**First grep for ANY throttle/rate-limit dep:**
```bash
grep -rni 'hammer\|plug_attack\|throttle\|rate.limit' lib/ mix.exs
# 0 hits = no rate limiting anywhere — don't limit the finding to login.
```

**Rate-limiting absence as a finding of its own.** When the grep returns
zero, flag the whole app's public endpoints, not just login: `POST /session`
(brute-force bcrypt passwords), first-run `POST /setup` (creates the first
admin!), every API bearer endpoint (unbounded token enumeration), MCP/agent
endpoints. **Fix:** `PlugAttack` (lightest, no extra storage) or `Hammer` +
`hammer_plug`, throttling `/session` and `/api/*` by IP. Rate high on
internet-facing apps. Verified gap in MyApp 2026-08 — zero throttle anywhere.

**Re-audit pitfall — "login IS rate limited" ≠ "proxy API is rate limited."**
A naive re-audit sees the `LoginRateLimit` plug on `POST /login` and skips
the whole category. The login throttle protects ONLY the session-credential
endpoint. The proxy's `POST /v1/chat/completions` (and siblings) sit in a
DIFFERENT pipeline (`:proxy_api`) with only `ApiAuth` — no IP throttle. An
attacker brute-forcing API keys hits no rate limit on invalid tokens; only
the DB lookup cost gates them. When the login plug exists, grep for the
proxy pipeline specifically: `grep -A4 'pipeline :proxy_api' lib/*/router.ex`
— if the only plug is `ApiAuth` (auth, not throttle), flag the bearer
endpoints as unthrottled. Verified my_app_gateway 2026-08: login had
`LoginRateLimit`, proxy API had none.

---

## Category 10 — Atom Exhaustion & Compile-Time Secret Freezing

### 10a. `String.to_atom/1` on LiveView event input (atom table DoS)

`String.to_atom/1` on any value derived from client input mints a new atom
per call — the BEAM atom table is finite (~1M) and never GC'd, so a crafted
client exhausts it and the node crashes. The LiveView variant is subtle
because the dangerous call often sits one hop away from the event:

```elixir
# DANGEROUS — two-step leak (verified MyApp 2026-08, search_live.ex)
# 1. event handler stores UNVALIDATED client input in an assign:
def handle_event("set_mode", %{"mode" => mode}, socket) do
  {:noreply, assign(socket, search_mode: mode)}   # any string!
end
# 2. a later search converts the assign to an atom:
Brain.search(q, strategy: String.to_atom(socket.assigns.search_mode))
```

The template's `<select>` only offers valid modes, but a WebSocket client
sends `"set_mode"` with arbitrary strings — each search then mints a fresh
atom. Trace BOTH directions: (a) does any `handle_event` assign client data
without validating against a whitelist? (b) does that assign ever reach
`String.to_atom/1`?

**Audit grep:**
```bash
grep -rn 'String.to_atom' lib/
# per hit: literal / fixed local whitelist (safe — atoms already exist, e.g.
# converting keys of ~w(type tag status)) vs client-controlled data (flag).
```

**Variant — unvalidated client header → unbounded ETS key amplification
(cross-cuts performance).** When an HTTP header value (e.g. `X-Agent-Type`)
is persisted as an ETS key (`{:requests, {:agent, agent_type}}` in a metrics
table) without truncation or validation, every unique header value mints a
new ETS entry. An attacker sending `X-Agent-Type: unique-<random>` per
request inflates the metrics table unboundedly — memory exhaustion without
admin access. The fix is the same as 10a but for STRING keys: truncate to
a fixed length AND validate against a whitelist (or normalize unknown values
to `"unknown"`). Verified my_app_gateway 2026-08: `agent_type` was untruncated
while the sibling `client_agent` was truncated to 255 — the inconsistency
is the tell. Grep `get_req_header.*x-agent\|agent_type` and trace to the
ETS insert; if there's no `String.slice/3` or whitelist check, flag it.
Rate Medium (no admin needed, but requires sustained traffic).

**Fix:** validate the assign at the event boundary against the known list
(`if mode in @valid_modes`), or use `String.to_existing_atom/1`. Rate high —
DoS needing only a session, not admin.

### 10b. Module attribute freezes a secret at compile time

Distinct from 8b (hardcoded fallback string). Here the env var EXISTS in prod
but the module attribute bakes the value read at COMPILE time into the .beam:

```elixir
# DANGEROUS — changing DRAN_API_TOKEN at runtime does NOTHING (verified MyApp)
defmodule MyApp.Auth do
  @api_token System.get_env("DRAN_API_TOKEN", "MyApp-token")
  def api_token, do: @api_token
end
```

Two bugs in one: (1) the default means a deploy without the env var ships a
publicly-known admin credential; (2) rotating the env var requires a REBUILD,
not a restart — operators think they rotated and didn't. Worse: the Docker
build stage usually has NO secrets in env, so the value compiled into the
release is often the default even when runtime env is set correctly!

**Audit grep:**
```bash
grep -rn '@[a-z_]* System.get_env\|@[a-z_]* Application.get_env' lib/
# any module attribute reading env = flag. Endpoint @session_options reading
# salts at module level is the same class.
```

**Fix:** read at runtime — put it in `runtime.exs`
(`config :MyApp, :api_token, System.fetch_env!("DRAN_API_TOKEN")`) and read
`Application.get_env(:MyApp, :api_token)` inside the function body, or call
`System.get_env/1` in the body. Fail closed in prod per 8b. Rate high when
the value is an admin credential.

**Variant — the runtime `raise` that validates presence but never
configures: security theater.** The inverse failure mode of the frozen
attribute: `runtime.exs` does `System.get_env(var) || raise` for a value
consumed ONLY by a compile-time module attribute (e.g. endpoint
`@session_options`). The raise passes at boot, operators believe the value
is env-controlled, but the release still uses whatever was compiled in —
and rotating the env var at runtime is a SILENT no-op. Cross-check the
Dockerfile for build ARGs: no ARG = the repo default is what ships.
Severity calibration: if the actual crypto secret (`secret_key_base`) IS
runtime-configured, known frozen salts alone don't enable forgery — rate
Medium (dead/misleading control); rate High only when the frozen value is
itself the credential. Verified my_app_gateway 2026-08 (endpoint.ex
`@session_options` salts + runtime.exs presence-raise + Dockerfile without
SESSION_* ARGs).

**Check the comparison too.** The same module usually compares the token
with `==` (e.g. `def valid_token?(t), do: t == @api_token`) — a timing
oracle on top of the frozen secret. Fix with
`Plug.Crypto.secure_compare/2` (same pattern as 6b for OAuth state).
Verified MyApp 2026-08 (auth.ex:46). Also watch in-app documentation that
tells operators to "set the env var in production" — under compile-time
freezing that advice is actively misleading; flag it in the report.

### 10c. Missing Content-Security-Policy with inline scripts

`plug :put_secure_browser_headers` (Phoenix default) sets `x-frame-options`,
`x-content-type-options`, etc. but **NOT CSP**. Check `root.html.heex` for
inline `<script>` blocks (the stock Phoenix theme-switcher is one!) — without
a CSP, any stored/reflected XSS executes freely. Apps that render user
markdown (mdex/Earmark in second-brain/wiki apps) have a wide stored-XSS
surface, so CSP is the cheap backstop.

**Audit grep:**
```bash
grep -rn 'content-security' lib/ config/                 # empty = no CSP
grep -n '<script>' lib/*/components/layouts/*.heex       # inline blocks strict CSP
```

**Fix (easiest first):** move the inline script into `app.js` — zero inline
JS → a strict `default-src 'self'` works. If inline is unavoidable, emit a
per-request nonce and put it in both the CSP header and the
`<script nonce={...}>` tag. Rate medium — needs an XSS primitive to matter,
but it's free defense-in-depth.

---

The session controller passes credentials straight to
`Accounts.authenticate_user/2`. Bcrypt makes each attempt expensive, but
nothing stops an attacker from trying thousands of passwords per minute
from one IP.

**Audit grep:**
```bash
grep -rn 'plug_attack\|Hammer\|rate_limit' lib/*/router.ex lib/*/controllers/session_controller.ex
# No hits = unguarded
```

**Fix:** `plug_attack` (or Hammer) with a rule like 5 attempts per IP per
10 minutes on `POST /login`. Return a uniform 429, don't reveal which
factor tripped. Rate high.

### 9d. Google OAuth via legacy /userinfo instead of OIDC id_token

Exchanging the code for an `access_token` and then hitting
`https://www.googleapis.com/oauth2/v2/userinfo` trusts the email claim from
a bearer-token endpoint. The modern OIDC flow returns an `id_token` (a
signed JWT) that you verify locally against Google's JWKs — signature,
`iss`, `aud` (your client_id), `exp`, and the `hd` (hosted domain) claim.

**Why it matters:** with /userinfo, a stolen/replayed access token yields a
valid-looking email; with id_token, the token itself is cryptographically
bound to your client and to the Google Workspace domain. The `hd` check
also moves domain restriction from string-matching the email to a verified
IdP claim.

**Audit grep:**
```bash
grep -n 'userinfo\|id_token\|JOSE\|JWK' lib/*/oauth/*.ex
# userinfo without id_token verification = flag
```

**Fix:** request `id_token` in the token exchange, verify with `JOSE.JWT`
+ Google's published JWKs, assert `hd` when `allowed_domains` is set. Rate
medium (the email-domain post-check mitigates, but crypto-verified claims
are the right boundary).

**Adjacent gap — `verified_email` never asserted.** Whether using /userinfo
(`verified_email` field) or an id_token (`email_verified` claim), check the
app requires the flag before linking the Google identity onto an existing
account. Without it, an unverified Workspace email could be linked onto a
pre-existing account with the same address. Verified gap MyApp 2026-08:
`fetch_userinfo/1` mapped `email` but never read `verified_email`, and
`find_or_link_from_google/1` links by email alone. The invite-only model
(unknown users rejected) blunts it — rate Low — but it's a one-line hardening.

### 9e. Repo pool exhaustion — no statement timeout, small pool, no queue config

A slow query (CSV export, missing-index rollup) holds a DB connection.
With the Phoenix default `pool_size: 10` and no `statement_timeout`, a few
slow admin queries starve the proxy hot path of connections. No
`queue_target`/`queue_interval` means checkout waits pile up silently.

**Pattern to flag:**
```elixir
config :MyApp, MyApp.Repo,
  url: database_url,
  pool_size: String.to_integer(System.get_env("POOL_SIZE") || "10")
  # ← no queue_target, no queue_interval, no statement_timeout
```

**Fix:**
```elixir
config :MyApp, MyApp.Repo,
  url: database_url,
  pool_size: String.to_integer(System.get_env("POOL_SIZE") || "20"),
  queue_target: 500,
  queue_interval: 1_000,
  # plus at the DB level:
  # ALTER ROLE MyApp SET statement_timeout = '15s';
  # or per-connection: parameters: [statement_timeout: "15000"]
```
Rate high on apps mixing an admin dashboard with a latency-sensitive API
on the same Repo; medium otherwise.

**Audit grep:**
```bash
grep -n 'queue_target\|statement_timeout\|pool_size' config/runtime.exs
```

---

## Category 10 — Streaming / Upstream Resource Leaks

### 10a. Streaming task not killed on client-side timeout

When a proxy streams from an upstream provider with a "first token"
timeout, the typical pattern is `Task.start(fn -> Finch.stream_while(...) end)`.
If the timeout fires but nothing kills the Task, the upstream connection
stays open and the Finch process keeps buffering. Enough hung providers =
file-descriptor exhaustion.

**Pattern to flag:**
```elixir
{:ok, pid} = Task.start(fn ->
  Finch.stream_while(request, finch, acc, fn ... end, receive_timeout: t)
end)
# caller has a first_token_timeout, but never Task.shutdown(pid) on expiry
```

**Fix:** track the pid and on timeout call
`Task.shutdown(task, :brutal_kill)` (or use `Task.async` + `Task.yield/2`
which cancels the linked task). Verify the Finch request is tied to the
task's lifecycle so killing the task closes the socket. Rate high on
proxy/gateway apps.

**Audit grep:**
```bash
grep -n 'Task.start\|Task.async\|stream_while\|first_token' lib/*/proxy/*.ex
# then trace: does the timeout path kill the task?
```

---

## Category 11 — File Uploads (context + serving layer)

Uploads usually span three layers; audit all three.

### 11a. Active extensions served from the app origin → stored XSS

If the upload validator's extension/MIME allowlist includes `svg`, `html`,
`js`, `xml` (or a MIME→ext map like `ext_from_mime("image/svg+xml")`), and
files are served by `Plug.Static` from the SAME origin, an uploader gets
stored XSS with full same-origin power (http_only cookies don't help — the
XSS drives the app via authenticated fetch). Verified MyApp 2026-08:
`valid_extensions()` included `svg html js ts` and uploads were in
`static_paths` (uploads.ex:89-91 + dran_web.ex:20). Fix: drop active
extensions, serve `Content-Disposition: attachment` +
`X-Content-Type-Options: nosniff`, or serve from a separate origin.
Rate High.

**Also check:** is the file content itself validated (magic bytes), or does
the code trust the client-supplied filename extension and `client_type`
MIME hint? Trusting both = the allowlist is theater.

### 11b. Store function not self-defending

Context-layer `store/4`-style functions should validate size, path segments,
and MIME themselves instead of trusting every caller. Verified MyApp 2026-08:
`Uploads.store/4` had no size check (one LiveView caller checked
`byte_size > max_size`, but any future caller bypasses it) and interpolated
`context_id` into the filesystem path without validation (path traversal if
a caller ever passes a non-UUID). Fix: enforce size + UUID format + magic
bytes inside the store function. Rate Low→Medium.

### 11c. Public static serving with no authorization

`Plug.Static` runs BEFORE the router, so anything under its paths is public
— no auth, no per-context authz, no expiry. Unguessable names (sha256
content-addressing) are obscurity, not control: URL leaks (logs, referer,
sharing) are permanent, and removed members keep access to known URLs. If
content needs authz, serve via an authenticated controller that checks
membership. Rate Low→Medium depending on content sensitivity.

### 11d. Parser vs app-level size mismatch

Compare `Plug.Parsers multipart_length` against the app's own upload max
(e.g. `UPLOADS_MAX_SIZE`). Verified MyApp 2026-08: 200MB parser cap vs 100MB
app max — a 150MB body is fully buffered in memory before the app rejects
it, and the endpoint comment wrongly claimed the two matched. Align the
values (parser ≤ app max + form overhead) and fix misleading comments.
Rate Low.

**Audit grep:**
```bash
grep -rn 'valid_extensions\|ext_from_mime\|Plug.Static\|static_paths\|multipart_length\|max_size' lib/ config/
# then: served from same origin? active MIME types? who checks size/content?
```

---

## Report Format

Structure the final report as:

```
# 🔒 Security Audit Report — [Project Name]

## Executive Summary
- Files reviewed: [count]
- Findings: [total] ([critical], [high], [medium], [low])
- Top issues: [one-line summary of top 3]

## 🔴 CRITICAL
### C1 — [Title]
**File:** `path:line`
**Category:** [Authorization/IDOR/Secrets/etc.]
**Description:** ...
**Fix:** ...

## 🟠 HIGH
...

## 🟡 MEDIUM
...

## 🟢 LOW
...

## Summary Table
| Category | Critical | High | Medium | Low | Total |
|---|---|---|---|---|---|
| Authorization/IDOR | ... | ... | ... | ... | ... |
| Secrets-at-rest (4a) | ... | ... | ... | ... | ... |
| Secrets in assigns (4c) | ... | ... | ... | ... | ... |
| Secrets in logs (4d/e) | ... | ... | ... | ... | ... |
| OAuth (6a/6b) | ... | ... | ... | ... | ... |
| Session (7a/7b) | ... | ... | ... | ... | ... |
| Defaults / enumeration (8a/8b/8c) | ... | ... | ... | ... | ... |
| ... | ... | ... | ... | ... | ... |

## Remediation Priority
1. [Immediate items]
2. [Urgent items]
3. ...

**No files were edited during this audit.**
```

**Always include a "Verified-Good Patterns" section** alongside the
findings — for each domain you audited but did NOT find a problem, list
the file:line and why it's safe. This (a) prevents the user from re-asking
"did you check X?", (b) documents positive security decisions for future
audits, and (c) gives the next agent a worked example of the safe pattern.

---

## Delta Audit Workflow (changes since a previous audit)

When the user asks for a **delta audit** (auditing changes since a date or
commit), the workflow differs from a full audit:

### Phase 1 — Read the previous audit report
Read `SECURITY_AUDIT_REPORT.md` (or whatever file was used). Note:
- Every finding's ID, severity, and current status (fixed / not fixed / TBD).
- The "Verified-Good Patterns" section — these are areas you can skip unless
  touched by new commits.
- Any open questions or product decisions left pending.

### Phase 2 — Identify changed files
```bash
# Commits since the date:
git log --oneline --since="<date>" | head -50
# Changed files (deduplicated):
git log --oneline --since="<date>" --name-only | sort | uniq
# New files added:
git log --oneline --since="<date>" --diff-filter=A -- '*.ex' '*.exs'
```

### Phase 3 — Verify previous findings
For EACH previous finding:
1. Check if the relevant file was touched (`git log --since=... -- <file>`).
2. If touched, read the current code and determine: FIXED / PARTIALLY FIXED /
   STILL OPEN / WORSE.
3. **Don't assume a commit message is the truth.** A commit titled "security:
   fix session fixation" might have missed one code path. Verify the actual
   code change.
4. For FIXED findings: note the commit hash and what was done. For STILL OPEN:
   re-state the finding with current line numbers.

**Pitfall: security commits that fix one thing but break another.** Example:
commit `ca6b41d` unified login error messages (good) but the test that
asserted the old behavior (`flash =~ "suspendida"`) had to be updated. When
verifying fixes, check that the fix didn't introduce regressions in the
test suite or adjacent code.

### Phase 4 — Audit new code
Focus on:
1. **New LiveViews / controllers** — do they have the `attach_hook` pattern?
   Are they in the right `live_session`?
2. **New endpoints** (especially proxy/router changes) — new attack surface
   that didn't exist before. Check auth, input validation, error handling.
3. **New context functions** — do they have limits? Do they validate input?
   Do they scope queries to the requesting user?
4. **Config changes** — `runtime.exs`, `endpoint.ex`, `config.exs`. Security
   hardening OR accidental weakening.
5. **Security-specific commits** — verify each claim. A commit that "scrubs
   API key fragments" should be checked: does the regex cover all provider
   key formats? Does the scrub run before persistence?

**New vulnerability categories discovered in delta audits** (add to the
category list if the codebase exhibits them):
- **Search wildcard abuse (ilike with unescaped user input):** `search_users`
  builds `%#{query}%` without escaping `%` and `_` characters. While Ecto
  parameterizes (no SQL injection), the wildcards enable enumeration of all
  records and expensive pattern scans. Fix: escape `%` → `\%` and `_` → `\_`
  before interpolating.
- **Over-broad data loading in read-only views:** A read-only LiveView loads
  ALL records of a join table (e.g., `ServiceModelAlias`) into socket assigns
  without scoping to the user's resources. Even though the template filters
  what's displayed, the full data lives in the socket process. Fix: add
  `WHERE service_id IN ^service_ids` to the query.
- **Hardcoded salt defaults in env-var-configurable secrets:** When
  `signing_salt` / `encryption_salt` fall back to a string literal, every
  unconfigured deployment shares the same salts. Fix: fail-closed (`raise`)
  or generate random defaults per-boot.

### Phase 5 — Report (delta format)

The delta report should include:
1. **Executive summary** — how many previous findings resolved, how many
   persist, how many new findings.
2. **Previous findings status table** — ID, severity, status (✅ CORREGIDO /
   ⚠️ PERSISTE / 🔴 EMPEORADO), brief note on what was done (or not done).
3. **Proactive improvements table** — security improvements that were NOT
   audit findings but strengthen the codebase (e.g., filter_parameters,
   session hardening, login message uniformity). These are important because
   they show the team's security posture is improving even between audits.
4. **New findings** — same format as the full audit (ID, severity, file:line,
   category, description, fix).
5. **Remediation priority** — updated list considering both old and new.
6. **Explicit statement** that no files were edited.

---

See `references/delta-audit-MyApp-2026-08.md` for a worked delta audit
example (previous findings verification, new finding discovery, report format).

## Subagent Fan-Out Playbook (combined security + performance audits)

For a full audit (security + N+1 + pagination + PubSub), fan out 3 subagents
with **disjoint scopes** in one batch:

| Task | Scope | Files to read first |
|---|---|---|
| 1 | Authorization + IDOR (Categories 1a–1f) | `router.ex`, `plugs/`, `user_auth.ex`, all LiveViews |
| 2 | Secrets + Sessions + OAuth + proxy headers (4a–4e, 6, 7, 8) | schemas, `endpoint.ex`, controllers, adapters |
| 3 | Performance: N+1 + pagination + PubSub storms + indexes (2, 3, 5c) | contexts, LiveViews, migrations, PubSub broadcast sites |

Each subagent prompt must carry: read-only mandate, the category checklist,
"verify against the real function before reporting", and the report format.

**Dispatch mechanics (verified MyApp audit 2026-08):** write each scope's full
checklist as a spec file under `/tmp` (write_file) and dispatch a SHORT goal
that points at the file — multi-KB inline goals get truncated to
'...truncated...' and the child wanders without instructions. The spec file
should also carry the "already verified by the parent, don't re-audit" list
so children don't burn context re-reporting known findings. While the
children run, the parent reads and self-verifies the core auth files
first-hand (router, plugs, session controller, OAuth module, `endpoint.ex`,
`runtime.exs`) — those are usually the highest-severity findings, and the
parent needs first-hand knowledge to cross-check the children's self-reports
before consolidating the final report.

**Rate-limit pitfall (verified MyApp 2026-08):** if the app's own LLM
gateway is also the subagent provider, 3+ parallel subagents can 429 one of
the tasks — the dead task returns **empty** (5 retries, then a bare error
line, no partial work). Recovery ladder:

1. Let the surviving batch finish.
2. Re-dispatch ONLY the failed scope as its own single-task delegation.
3. If the re-dispatch also 429s (the shared gateway can have external
   traffic), **run that scope yourself with local tools** —
   `search_files`/`read_file` greps need no LLM API: the router map,
   attach_hook-vs-handle_event triage, and orphan-LiveView check (1f) are
   all doable in ~6 tool calls. Slower, but unblocked.

Never assume a 429'd subagent produced partial findings — treat its scope as
completely unaudited until redone.

## Pitfalls

- **Multi-project drift: confirm the target repo before auditing.** When the
  user names a project ("revisa MyApp..."), audit THAT repo — don't drift
  to the session's cwd or another repo you have context on. If the conversation
  evolves and you started reading a second repo (e.g. comparing configs),
  re-confirm scope before reporting; a mid-task "sobre MyApp" correction
  means you were drifting. Verify with `git -C <repo> rev-parse
  --show-toplevel` and match it against what the user asked for.
- **Don't report router guards as missing auth.** If a LiveView is behind
  `live_session :admin` with `on_mount: :require_admin`, the route IS
  protected. Note the defense-in-depth gap (mount doesn't re-check) as
  medium, not critical — unless the handler also lacks the check.
- **Don't report N+1 as critical.** N+1 is a performance issue, not a security
  hole. Rate it medium unless it enables a DOS (e.g., unbounded list with no
  limit).
- **Verify preloads before reporting missing ones.** The context function may
  preload in a different layer. Read the actual function before reporting.
- **Don't confuse `type="text"` for a secret field as critical** unless the
  field actually contains a plaintext secret. If it's encrypted at rest and
  only the masked version is sent to the template, it's medium.
- **Don't trust the `*_encrypted` field name.** Authors routinely name
  plaintext columns `*_encrypted` ("we'll encrypt it later"). The three-step
  verification in 4a (moduledoc, grep for encrypt/decrypt functions, migration
  column type) is the only way to confirm. A field named `api_key_encrypted`
  that is `:string` and has no schema-level encryption function is plaintext
  at rest — Critical.
- **Don't rate 4c (masked render) as low just because the HTML shows dots.**
  If the LiveView did `Repo.all(from(p in Provider, preload: [credentials: c]))`,
  the full secret is in the socket process state. Rate High. The fix (SQL
  projection) is what makes 4c truly safe.
- **`force_ssl` HSTS exclusion for `localhost` is not a finding on its own**
  unless the operator can plausibly set `PHX_HOST=localhost` in prod. Rate
  Low; document the pitfall.
- **Read the real code.** Never report based on filename or module name alone.
  The function might have guards you didn't see.
- **Dead-code sweeps: `mix compile --warnings-as-errors` only catches unused
  defp/vars/aliases — NOT unused public `def`s.** For orphaned public context
  functions (common when the audit includes a dead-code pass), grep callers per
  candidate: `grep -rn 'FnName\b' lib/ test/ | grep -v 'def FnName'`. Zero
  hits = orphan (but rule out `apply/3` dynamic dispatch first). In one
  MyApp pass this found 5 orphaned public functions
  (`list_api_keys/0`, `list_team_members/0`, `list_credentials/0`, …) that the
  clean compile never surfaced.
- **Elixir 1.20: drop redundant `var &&` truthiness when adding role assigns
  in remediation.** When a LiveView is behind `live_session :admin` (or any
  `require_*` on_mount), `current_user` is guaranteed non-nil in mount, so the
  defensive `user && user.global_role == "admin"` assign now fails
  `--warnings-as-errors` with an "always truthy / will always evaluate to"
  type warning. Write `user.global_role == "admin"` directly. Reserve the
  `user &&` guard for contexts where the user can genuinely be nil
  (e.g. `:default` on_mount).
- **DB SSL verification disabled is a common silent gap.** When the app
  connects to a cloud DB (AlloyDB, Cloud SQL, RDS) over SSL, the
  `runtime.exs` often ships with `ssl_opts: [verify: :verify_none]` as a
  quick fix for certificate chain issues. This disables MITM protection on
  the DB connection -- an attacker on the same network can intercept queries,
  credentials, and data. Check `config/runtime.exs` for `verify: :verify_none`
  in the Repo SSL config. Rate Medium. Fix: use `verify: :verify_peer` with
  the correct CA bundle for the provider. If tolerance is needed for local
  dev, condition the verify level by `config_env()`.
- **Remediation: `verify_peer` flip needs an operator escape hatch (verified
  MyApp Aug 2026).** Don't flip `verify_none` → `verify_peer` outright —
  managed/self-signed Postgres in private networks presents certs that fail
  verification and the app won't boot. Ship a three-way cond in runtime.exs:
  `ECTO_SSL=false` → no ssl; `ECTO_SSL_VERIFY=false` → `verify_none`
  (documented escape); default → `verify: :verify_peer, cacerts:
  :public_key.cacerts_get()`. Same pattern for session cookie hardening:
  salts and TTL as env vars with dev defaults
  (`SESSION_SIGNING_SALT`/`SESSION_ENCRYPTION_SALT`/`SESSION_MAX_AGE_SECONDS`);
  `secure: true` can be set unconditionally — Plug only enforces it on HTTPS
  requests, so local HTTP dev keeps working.
- **Nil-pinned Ecto queries crash LiveViews at render (`comparing field
  with nil is forbidden`).** Template helpers that build
  `where: x.assoc_id == ^param` from an assign that's nil until the user
  picks something (e.g. `provider_form_alias_id` before a model is selected)
  kill the LiveView process the moment the section renders. Verified in
  MyApp ModelsLive: clicking "Miembro" scope crashed with
  `ArgumentError` from `Ecto.Query.Builder.not_nil!/2`. Fix pattern: add a
  nil clause to the helper — `def items_with_access(_items, nil), do: []` —
  not an `is_nil` fragment. When a crash report lands mid-remediation, check
  whether the failing line is in YOUR diff: if not, it's a latent bug your
  change merely exposed — fix it with the targeted clause, don't revert.
- **Partial coalescing in one handler still storms the DB.** When a single
  `handle_info` carries multiple reload triggers (e.g. one for budget
  alerts, one for recent errors), coalescing only ONE of them leaves the
  other firing a query per broadcast. Verified: AlertsLive coalesced the
  budget reload but called `load_recent_errors/1` directly per 4xx/5xx log —
  an upstream 5xx burst = one DB query per error per connected admin. Audit
  EVERY `load_*`/query call inside a PubSub `handle_info` for its own
  `_scheduled` flag + timer, not just the handler as a whole.
- **A code line that looks syntactically impossible probably isn't — verify
  raw bytes before auditing around it.** Tool output pipelines can strip
  `#{}` interpolations: a line displayed as
  `email: "api-key:*** contexts: [key.context]}` (unclosed string — wouldn't
  compile) turned out to be `email: "api-key:#{key.name}", contexts: ...`
  on disk. When an audit finding depends on the exact content of one line
  (here: the shape of a synthetic auth identity), confirm with
  `sed -n '<n>p' <file> | od -c` instead of trusting the rendered output.
  Verified MyApp 2026-08.
- **Concurrent remediation shifts the code under the audit — re-verify
  before citing.** When a parent agent (or a parallel remediation wave)
  edits the repo while you audit, earlier reads go stale: line numbers
  drift and findings get fixed mid-report. The tell is a read-vs-grep
  discrepancy (a grep hit shows a line your earlier full-file read didn't
  have). On any discrepancy, re-check `git status --short` + `wc -l`/`md5`
  for the file, re-read the CURRENT disk state, and cite current line
  numbers; describe fixes that landed mid-audit as "fixed on disk
  (uncommitted WIP)" instead of reporting them as open findings. Verified
  my_app_gateway 2026-08 (endpoint.ex gained a Plug.Parsers cap and accounts.ex
  gained a suspended-branch timing fix DURING the scope-2 audit).

## References

- `references/MyApp-audit-example.md` — Full worked example: security audit
  of the MyApp LLM proxy gateway. Covers IDOR in a CSV export controller,
  LiveView handle_event without admin checks, plaintext API key storage, OAuth
  allowlist fail-open, N+1 in mount, and missing pagination. Includes the
  audit methodology, grep commands, and severity assignments used.
- `references/MyApp-audit-aug2026.md` — Third pass (Aug 2026): authorization
  & access control re-audit. Verified all previous findings fixed (attach_hook,
  secure_compare, session renewal, list_users limit). New findings: DB SSL
  verification disabled, upstream error messages with key fragments, session
  cookie hardening gaps, orphan LiveView module.
- `references/MyApp-api-mcp-audit-2026-08.md` — MyApp scope-2 audit (API REST +
  MCP + controllers, Aug 2026). Headline: CRITICAL MCP dispatch IDOR (1h) —
  HTTP-layer context check bypassed via JSON-RPC `arguments.context`; 14
  findings with file:line, plus the verified-good patterns list for that
  surface (hashed API keys, MCP attr whitelists, inference timeouts).
- `references/MyApp-contexts-config-audit-2026-08.md` — MyApp scope-3 audit
  (contexts, schemas, config, secrets, performance, Aug 2026). Headline:
  CRITICAL compile-time-frozen admin token (10b); uploads with active
  extensions served from app origin (11a); plaintext per-user token beside a
  hashed sibling table (4a variant); LIKE from unvalidated slug (8d variant);
  N+1 writes/excerpts (2d/2e); unbounded task fan-out and cascading
  side-effect amplification; verified-good patterns list for contexts.
- `references/my_app_gateway-secrets-audit-2026-08.md` — my_app_gateway scope-2 audit
  (secrets/sessions/OAuth/config, Aug 2026). Headline: CRITICAL plaintext
  upstream provider keys at rest (4a) + plaintext keys in LiveView assigns
  (4c). New variants: edit-form password-input DOM leak (4b), first-8-prefix
  display + persisted key fragments (4c/4d), runtime presence-raise that
  never configures compile-time salts (10b), and the concurrent-remediation
  mid-audit pitfall.
- `references/my_app_gateway-authz-audit-2026-08.md` — my_app_gateway scope-1 audit
  (authorization & IDOR, Aug 2026). Headline: HIGH status-revocation gap
  (1j — suspended users keep full proxy API access), mount-only and
  hardcoded-`is_admin: true` LiveViews (1b), org aggregates on the shared
  dashboard (1d render-layer variant), latent registration-changeset
  privesc (1i calibration), orphan LiveView (1f). Includes the verified-good
  list for the scoping architecture (fail-closed scope_member_ids,
  require_admin_hook fleet, routing alias-access checks).
