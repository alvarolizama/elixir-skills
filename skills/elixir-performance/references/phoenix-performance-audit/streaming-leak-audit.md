# Streaming-leak audit — SSE / Finch.stream_while proxy paths

LLM-proxy apps stream upstream SSE through the request process. The
spawn-and-forward plumbing has four distinct leak shapes; all four were
verified in a production audit (2026-08). This is the checklist for
auditing them.

## The reference shape (what you'll see)

```elixir
# adapter.ex
{:ok, pid} = Task.start(fn ->                # <-- shape A: spawn
  Finch.stream_while(request, finch, acc, fn ... end,
    receive_timeout: timeout)                # <-- per-RECV idle timeout
  # on exit: send(caller, {:sse_error, ...})
end)
{:ok, pid}

# controller.ex
{:ok, pid} = Adapter.stream_chat_completion(...)
ref = Process.monitor(pid)                   # caller → task only
case await_first_chunk(pid, ref) do ... end  # first-token timeout
stream_loop(conn, pid, ref, ...)             # receive without 'after'?
```

## Leak 1 — Unlinked upstream task outlives the request process (medium)

`Task.start/1` is UNLINKED. The controller's `Process.monitor(pid)` is
one-directional: the caller learns when the task dies, but nothing kills
the task when the CALLER dies. If the request process dies mid-stream by
any path other than the handled client-disconnect (downstream crash,
Cowboy/LB teardown, untrappable `:kill`), the task keeps:

- the upstream HTTP connection + Finch pool slot,
- sending `{:sse_chunk, ...}` to a dead pid (harmless but wasteful),
- alive until stream end or the per-recv idle timeout fires (60–180s).

**Check:** grep `Task.start(` in the adapter; then enumerate every death
path of the request process and confirm each one kills the task
(`Process.exit(pid, :kill)`). The handled paths are usually
client-disconnect (`Plug.Conn.chunk` error → kill) and first-token
timeout (`after` → kill + `demonitor([:flush])`). The residual gap is
caller-death propagation. **Fix:** `Task.start_link/1`, or have the task
`Process.monitor(caller)` and self-terminate on `:DOWN`.

## Leak 2 — `receive` loop without `after`: no idle or total cap (medium)

```elixir
defp stream_loop(conn, pid, ref, acc) do
  receive do
    {:sse_chunk, c} -> stream_loop(...)
    {:sse_done}     -> finish_stream(...)
    {:DOWN, ...}    -> finish_stream(...)
    # no 'after' — bounded only by the upstream task eventually messaging
  end
end
```

Termination depends entirely on the adapter task sending something or
dying. Finch's `receive_timeout` is a PER-RECV idle timeout, not a total
cap: a provider trickling one SSE event (or heartbeat comment) per
sub-timeout window holds the request process, the credential concurrency
slot, and the per-user slot FOREVER. Retry budgets (`@max_attempts`)
only bound the pre-first-chunk phase. **Fix:** add an `after` idle guard
or a monotonic deadline check per iteration.

## Leak 3 — First-token timeout that doesn't kill the upstream (critical if missing)

The GOOD shape (verified present in the audited repo — keep as the
reference): `await_first_chunk` has an `after timeout` and the error
branch does `Process.exit(pid, :kill)` + `Process.demonitor(ref, [:flush])`
BEFORE any fallback work. Killing the task closes the Mint socket
(sockets are owned by the process), freeing the fd and the credential's
concurrency slot immediately. If the kill is missing, every hung
provider holds a connection until the full `receive_timeout` per
fallback attempt (attempts × timeout of leaked fds).

## Leak 4 — Spawn-result match that assumes `{:ok, pid}` (low)

`case Adapter.stream_chat_completion(...) do {:ok, pid} -> ... end` with
a single clause crashes with `CaseClauseError` if the adapter can ever
return an error tuple. Verify what the adapter actually returns on
connection failure — if the Task is spawned before the HTTP request is
made (usual), `{:ok, pid}` is the only return and the match is safe
today; note it as fragile-but-OK, not a finding.

## Audit recipe

```bash
# 1. Find the streaming spawn
grep -rn 'Task.start\|Task.start_link' lib/*/proxy/ lib/*/proxy*.ex

# 2. Monitor direction + kill paths
grep -n 'Process.monitor\|Process.exit\|demonitor' \
  lib/<app>_web/controllers/proxy_controller.ex
# Expect: monitor after spawn; :kill on (a) first-token timeout,
# (b) client disconnect. Missing either = finding.

# 3. The receive loop
grep -n 'receive do' lib/<app>_web/controllers/proxy_controller.ex
# Read each one: is there an 'after'? Per-recv timeout is NOT a total cap.

# 4. Timeouts actually in force
grep -rn 'receive_timeout\|first_token_timeout' lib/ config/
# Distinguish: first-token (controller 'after'), per-recv idle (Finch
# receive_timeout), total (usually MISSING — that's leak 2).

# 5. Fire-and-forget error-path tasks
grep -rn 'Task.start' lib/<app>_web/controllers/
# e.g. disable-credential-on-401 tasks: unbounded until the DB write
# lands; each one typically also broadcasts → feeds the PubSub storm
# checks in references/pubsub-storm-detection.md.
```

## Severity guide

- Missing kill on first-token timeout → high (fd/connection leak per attempt).
- Unlinked task (caller-death gap only) → medium (bounded by idle timeout).
- `receive` without `after` → medium (slot exhaustion via slow-drip).
- Single-clause `{:ok, pid}` match when adapter always returns ok → low/informational.
- Unlinked fire-and-forget task per UI click with long HTTP timeout (e.g.
  admin "fetch models" with 180s `receive_timeout`) → low (admin-only).