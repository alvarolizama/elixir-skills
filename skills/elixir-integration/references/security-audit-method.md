# Phoenix Security Audit Method

A repeatable read-only audit workflow, then the highest-value vulnerability
categories with fixes, then remediation discipline. Intended to be applied
to existing code — scope is EXPLICIT: no files are edited during the audit.

## Method

1. **Map the attack surface.** Router pipelines, plugs, `on_mount` hooks,
   controllers, LiveViews, deploy config (secrets, ports). Anything that
   accepts input or carries identity is in scope.
2. **Check each category** below, recording file, line, severity, fix —
   without editing.
3. **Verify every finding** against the real code before reporting. A false
   positive destroys trust in the real ones — check the line, the plug
   order, the actual branch.
4. **Report** prioritized (critical → cosmetic, each with repro steps),
   and state explicitly "no files edited".

## Highest-value categories

### 1. `handle_event` without permission check — the #1 LiveView hole

**Symptom.** Templates hide the admin button, but a crafted client session
triggers the destroy event and succeeds.

**Mechanism.** LiveView events ride the authenticated WebSocket; hiding the
UI is not enforcement. Elevation checks inside each handler are easy to
forget.

**Fix.** One hook in `mount/3` halts EVERY event:

```elixir
:ok = Phoenix.LiveView.attach_hook(socket, :require_admin, :handle_event,
  fn _event, _params, socket -> {:halt, socket} end)
```

(plus the roles check for `{:cont, socket}`). New handlers cannot bypass
it by omission.

**Verification.** Test: a non-admin user's socket sends the event →
`{:halt, socket}` and the mutation did not run.

### 2. IDOR (insecure direct object reference)

**Symptom.** `{:ok, record} = MyApp.get_record(params["id"])` — any team,
any model, any id.

**Fix.** Validate the id against the caller's scope in the controller
BEFORE the query, or scope the query itself. Fail closed: unvalidated id →
`{:error, :not_found}`-style empty result, never cross-scope data.

### 3. Fail-open identity defaults

**Symptom.** `case user do nil -> true; ...` — a deleted (or not-yet-created)
user ESCALATES into full access.

**Mechanism.** Defaults written as "missing = permissive" to make early
testing convenient, then never revisited.

**Fix.** Missing user/context → deny. Delete the "convenient" branch; add a
test for the missing-user path.

```bash
grep -rn 'nil -> true\|nil -> :all' lib/
```

### 4. Suspension that never reaches the data plane

**Symptom.** Suspending a user works in the web UI; their API tokens keep
working.

**Mechanism.** Suspension writes the users table, but the API key plug /
bearer plug / WebSocket auth never re-check `user.status`.

**Fix.** Trace what a suspend writes, then re-check `user.status` in EVERY
non-session auth path (API key plug, bearer token, WS connect).

**Verification.** Test: suspend user → web AND API calls 401/403.

### 5. Session renewal / rate limiting / mass assignment

- **Renewal:** `configure_session(conn, renew: true)` on every identity
  change (fixation). See `oauth-social-login.md`.
- **Rate limiting:** auth plugs are not throttles. Login/register/reset
  endpoints need real throttling (per-IP and per-account). Check the API
  pipeline too, not just `:browser`.
- **Mass assignment:** diff controller param filters vs changeset `cast`.
  Scrub tools are not a cast allowlist.

## Admin route protection

Layered (strongest first):

1. Router: `live_session :admin` + `on_mount` guard (admin-only pages).
2. Mount-level guard — data-dependent checks.
3. Template `@is_admin` — cosmetic only.

Never leave a template-only control: the WebSocket fires events anyway.

## Remediation discipline

- One focused change per finding — no refactor merges.
- Prefer SQL-level scoping over in-controller filtering.
- Existing tests will assert the OLD vulnerable behavior. That is normal:
  update them to assert the NEW contract; do NOT revert the fix to satisfy
  them.
- After each fix: `mix compile --warnings-as-errors && mix test`.
- Re-run the audit's verification commands; findings whose repro no longer
  fires are done, findings that still fire are not.

## Verification commands

```bash
mix compile --warnings-as-errors && mix test

# no fail-open identity defaults
grep -rn 'nil -> true\|nil -> :all' lib/ | wc -l          # expect 0

# session renewed on every identity change
grep -rn "configure_session(conn, renew: true)" lib/ | wc -l

# no direct (unscoped) get by client id in controllers
grep -rn "get_.*params\[" lib/my_app_web/ | wc -l          # expect 0
```