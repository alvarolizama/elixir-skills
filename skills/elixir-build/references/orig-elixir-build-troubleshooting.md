---
name: elixir-build-troubleshooting
description: "Diagnose and recover from Elixir/Phoenix build failures without making things worse."
version: 1.2.0
author: Álvaro Lizama
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [elixir, phoenix, build, troubleshooting, mix, umbrella]
    related_skills: [elixir-mix-build, phoenix-umbrella-project-setup]
---

# Elixir Build Troubleshooting

Recover from broken `mix compile`, `mix test`, and `mix ecto.migrate` states in Elixir/Phoenix umbrella projects.

## Core rule

Do NOT delete individual app directories inside `_build`.

```bash
# BAD — syncs back to source and deletes priv files
rm -rf _build/test/lib/core/priv

# GOOD — clean the whole build or use mix
rm -rf _build
mix deps.get
mix compile

# OR
mix clean
mix deps.clean --all
mix deps.get
mix compile
```

Phoenix/Ecto copies each app's `priv` directory into `_build/<env>/lib/<app>/priv` and keeps them in sync. Deleting a subdirectory inside `_build` can propagate the deletion back to the source tree, wiping migrations, static assets, gettext, and other `priv` contents.

## When to reset the build tree

Reset the whole `_build` directory when you see:

- Stale `.beam` files after a dependency change
- `UndefinedFunctionError` for modules that should exist
- `** (CaseClauseError)` during compile after switching branches
- Asset or migration files that exist in source but are reported missing

Steps:

```bash
cd /path/to/umbrella
rm -rf _build deps
mix deps.get
mix compile
```

## When to reset the database

Use `MIX_ENV=test mix ecto.reset` (or `MIX_ENV=dev`) when:

- Migrations fail mid-flight and leave the schema in a half-applied state
- You renamed or deleted migrations already recorded in `schema_migrations`
- You changed a migration file that was already executed
- Duplicate module errors like `migration name X is duplicated`

Steps:

```bash
MIX_ENV=test mix ecto.reset
```

This runs `ecto.drop`, `ecto.create`, and `ecto.migrate` in one go.

## Editing migrations that failed in production (in-place edit)

**When:** a migration was deployed to production but **failed mid-execution** (e.g. a `create unique_index` hit a duplicate-key violation). Ecto's migration runner wraps each migration in a transaction, so a failure rolls back the DDL — the migration is NOT recorded in `schema_migrations` and the schema is clean. The next `mix ecto.migrate` in prod will re-attempt it.

**the user's rule (explicit):** do NOT create a new "fix" migration. Edit the original migration file IN-PLACE so the corrected version runs when prod retries. This avoids leaving broken/orphaned migration files and keeps history clean. This is safe because the failed migration was never recorded in `schema_migrations`.

**When NOT to edit in-place:** if the migration **succeeded partially** (some DDL statements committed before the failure — possible in MySQL or when a migration uses `execute` without a transaction, or when the DB doesn't support transactional DDL), you must account for the partial state. Check with `psql` what actually exists (columns, indexes) before editing. You may need `drop_if_exists` / `alter` statements to clean up partial artifacts in the `up` direction.

**The `drop_if_exists` index-name gotcha (common trap):**

When you edit a migration to fix an index that was wrong (e.g. changing from a single-column unique index to a composite one), you'll rename the index. But if the OLD index was already created in some environment (dev, staging), the `down` direction's `drop_if_exists` uses the NEW name and won't clean up the old one. Both indexes coexist, and the old one still enforces the wrong constraint silently.

```elixir
# BAD — only drops the new index name; old index survives in envs where it was applied
def up do
  create unique_index(:model_providers, [:credential_id, :model_alias_id],
           name: :model_providers_credential_model_alias_unique_index)
end

def down do
  drop_if_exists unique_index(:model_providers, [:credential_id, :model_alias_id],
                   name: :model_providers_credential_model_alias_unique_index)
end

# GOOD — explicitly drop the OLD index by its original name before creating the new one
def up do
  # Drop the old single-column index if it was applied by a previous version
  # of this migration (it has a different name, so drop_if_exists on the new
  # name won't catch it).
  drop_if_exists unique_index(:model_providers, [:credential_id],
                   name: :model_providers_credential_id_unique_index)

  create unique_index(:model_providers, [:credential_id, :model_alias_id],
           name: :model_providers_credential_model_alias_unique_index)
end
```

**Rule:** when renaming ANY database object (index, constraint) in an in-place migration edit, add an explicit `drop_if_exists` for the OLD name in the `up` direction. The `down` direction should drop the NEW name. Don't assume the old version was never applied — dev and staging may have the old artifact while prod doesn't.

**Verification pattern:** after editing, rollback + migrate locally to confirm both directions work:

```bash
mix ecto.rollback -n 1   # runs the edited `down`
mix ecto.migrate          # runs the edited `up`
psql -d <db> -c "\d <table>" | grep -i unique   # verify only the correct index exists
```

Then run the full test suite to confirm the schema change doesn't break anything.

## Migration duplicate name errors

Error example:

```text
** (Ecto.MigrationError) migrations can't be executed, migration name X is duplicated
```

This means two migration files define the same module name. Either:

1. Rename the duplicated migration module to match its filename, or
2. Delete the redundant migration if it is superseded by another one.

Rule: a migration module name should match the file base minus the timestamp and use PascalCase. File `20260629002000_create_widgets.exs` → module `CreateWidgets`.

## Recovering deleted migrations

If migrations were accidentally deleted from source, recover from git:

```bash
git checkout -- apps/<app>/priv/repo/migrations/
```

If the migrations were untracked and lost, inspect the current database schema with `\d` in `psql`, read the existing Ecto schemas, and recreate the migration files. Then re-run:

```bash
mix ecto.reset
```

## `mix run -e` fails with `:eaddrinuse` in dev — probe the DB with `psql` instead

During pairing sessions the user usually has `mix phx.server` running, so any
`mix run -e "..."` that boots the full app dies with `:eaddrinuse` on the
endpoint port.

**Don't fight it.** When you only need to inspect data (row counts, key
formats, verify a query's result), go straight to `psql` with the credentials
from `config/dev.exs`:

```bash
# creds live in config/dev.exs — e.g. user brain, db my_app_dev
psql -U my_user -d my_app_dev -c "
SELECT c.name, c.id, COUNT(p.id) AS page_count
FROM contexts c
LEFT JOIN pages p ON p.context_id = c.id
GROUP BY c.id, c.name;
"
```

This answers most "is the data there / what does the query return" questions in
one shot, no app boot required.

### Running Ecto queries in dev WITHOUT colliding with the running server

**Prefer `psql` first** — but when you need to test the *actual Ecto query
shape* (type coercion, `binary_id` UUID → string mapping, schema defaults,
`Map` key types), you need Ecto. The clean, collision-free pattern is
`mix run --no-start` + manual app startup:

```bash
mix run --no-start -e '
Application.ensure_all_started(:postgrex)
Application.ensure_all_started(:ecto_sql)
{:ok, _} = MyApp.Repo.start_link()

r = MyApp.Context.page_counts_by_context()
IO.inspect(r, label: "counts")
k = Map.keys(r) |> List.first()
IO.inspect(k, label: "first key")
IO.inspect(is_binary(k), label: "is_binary")
'
```

**Why this is better than `PORT=4001 mix run -e`:**

- `--no-start` skips the full OTP supervision tree, so the Phoenix Endpoint
  never starts → no port binding → **zero collision risk**, even with a
  dev server running on 4000.
- `Application.ensure_all_started(:postgrex)` / `:ecto_sql` brings up just the
  DB driver and Ecto pools — no Endpoint, no PubSub, no watchers.
- `Repo.start_link()` manually starts the Repo pool. The earlier skill advice
  said "starting it bare hits Ownership/pool errors" — that is **wrong**:
  `Repo.start_link()` works fine under `--no-start` as long as `postgrex` and
  `ecto_sql` are started first. Ownership errors only happen when the full
  app is running and a sandbox checkout is required.

**Key use case — verifying `binary_id` type coercion in `group_by` queries:**
Ecto's `:binary_id` primary key is returned as a **string** in query results
(e.g. `"962037b8-..."`), and `Repo.all(from p in Page, group_by: p.context_id,
select: {p.context_id, count(p.id)}) |> Map.new()` produces
`%{"962037b8-..." => 36}` — string keys. A `Map.get(map, ctx.id, 0)` lookup
where `ctx.id` is also a binary string **will** match. So if the UI shows `0`
but the DB shows 36, and this Ecto probe returns 36 with matching string keys,
the bug is **upstream of the data layer** — in the assigns → template →
component attr forwarding chain. See the reference file below.

See `references/ui-shows-zero-data-flow-tracing.md` for the full
data-flow tracing methodology that found the "Personal context shows 0
pages" root cause.

## Redundant re-verification loops — the probe-exhaustion trap

**Anti-pattern from real session:** two different probes returned the SAME
answer (`psql` LEFT JOIN says 36 pages; the equivalent GROUP BY also says 36),
and instead of switching layers the agent re-ran the *same* `psql` command 20+
times until the tool budget died. Zero new information, zero progress.

**Rule:** once a probe's answer is confirmed, the next probe MUST be
information-different — change the layer (Ecto vs raw SQL), change the
interface (HTTP response / rendered HTML vs DB), or change the mechanism
(inspect the assigns in a LiveView test instead of re-querying). If your next
command is a paraphrase of the previous one, STOP and re-plan. One clean
falsification beats twenty confirmations.

Concrete example — debugging "context dropdown shows (0) but DB has 36 pages":
1. `psql` confirms data exists ✓ (probe exhausted — do NOT re-run)
2. Next probe: what does `page_counts_by_context/0` actually return? → needs
   Ecto, so use the `mix run --no-start` + `ensure_all_started` pattern (see
   "Running Ecto queries in dev WITHOUT colliding" above).
3. Next probe: is the key type the problem? → compare `Map.keys()` output vs
   `ctx.id` type in the template (`binary_id` UUID vs string).
4. If Ecto returns 36 with matching string keys, STOP probing the data layer —
   the bug is upstream in the UI rendering chain (plug assigns → LiveView
   render → component attr forwarding). See
   `references/ui-shows-zero-data-flow-tracing.md`.
Each step answers a different question. That's the pattern.

## Runtime credentials silently stale — `System.get_env` in module attributes is compile-time

**Symptom:** an API endpoint that checks a bearer token (or any config value read from an env var) keeps returning `invalid token` even though the running OS process has the correct env var set (`ps eww <pid>` confirms it) and you restarted the server.

**Cause:** the value was read at **compile time**, not runtime. This pattern bakes the env var into the `.beam` at compile:

```elixir
defmodule MyApp.Auth do
  @api_token System.get_env("MYAPP_API_TOKEN", "default-token")   # ← compile-time!
  def valid_token?(token), do: token == @api_token
end
```

`System.get_env` inside a module attribute (`@attr`) is evaluated when the module is compiled. Changing the env var and restarting the server does nothing unless the module is **recompiled** — and even then, only if the env var is set in the shell that runs the compile. Two traps seen in one session:

1. Server compiled with no env var set → default value (`"default-token"`) baked in. Real token in `.env` never takes effect, even after restart.
2. `mise` auto-loads `.env` for interactive shells but a background/CI shell may compile without it, producing a beam with a different value than the running process's env.

**Diagnosis:** hash the running process's env var and compare with what the server actually accepts:

```bash
ps eww <beam_pid> | tr ' ' '\n' | grep '^MYAPP_API_TOKEN=' | shasum
# vs the token the endpoint actually accepts (try the default too)
```

If the process env is correct but the endpoint rejects the token, the module was compiled with a different value.

**Fix:** recompile with the env var present, then restart:

```bash
# ensure the env is loaded for the compile (mise does this automatically in interactive shells)
eval "$(mise env)"            # or: set -a; source .env; set +a
mix compile --force           # --force so the stale beam is rebuilt
mix phx.server
```

**Proper fix (avoid the footgun):** don't read env vars in module attributes for values that can change between deploys. Read them in `runtime.exs` or at call time:

```elixir
# GOOD — read at runtime
def valid_token?(token) when is_binary(token),
  do: token == Application.get_env(:MyApp, :api_token)

# config/runtime.exs
config :MyApp, api_token: System.get_env("MYAPP_API_TOKEN", "default-token")
```

Module attributes are fine for constants; they are wrong for secrets/tokens/paths that vary per environment.

## Flaky precommit: different test fails each run while dev server runs

**Symptom**: `mix test` alone passes 100%, but `mix precommit` fails 1-2 tests — and EACH precommit run fails a DIFFERENT test (e.g. an ingest ASR test one run, a curation_agent E2E the next). The failure is usually `DBConnection.ConnectionError: client #PID<...> exited` mid-checkout, NOT an assertion failure.

**Cause**: a running `mix phx.server` holds connections against the same Postgres; under precommit's heavier load the test sandbox loses its checkout. It is NOT a code regression.

**Diagnosis rule (two probes, then stop)**:
1. Run the failing test alone: `mix test path/to/test.exs:LINE` — passes.
2. Kill the dev server (`ps aux | grep beam.smp | grep -v grep | awk '{print $2}' | xargs kill; sleep 2`) and run plain `mix test` — green.

If both pass, the flake is environmental — do NOT "fix" the test or the code under test. Distinct from the seed/order-dependence flake in the previous section: that one fails deterministically under the same seed; this one fails a different test every run and always with a DB checkout error.

## Test-count drift between `mix test` and `mix precommit`

**Symptom:** `mix test` reports N/N passed but `mix precommit` immediately
after reports N-1/N with one failure — or vice versa.

**Cheap cause first:** `mix precommit` runs the suite with a different seed
(and possibly different env). A test that depends on execution order, on a
DB row left by a *previous* test in seed order, or on a background process
started by an earlier test can flip between runs. Before suspecting the
alias, re-run precommit twice with the SAME seed as the passing run:

```bash
mix test --seed <seed_from_passing_run>
PORT=4099 mix precommit   # compare
```

If the same test flips across seeds, it's an order-dependence bug in the
test (missing setup, leaked `Application.put_env`, a row the test assumed
wouldn't exist), not a precommit problem. Find it with
`mix test --seed <failing_seed> --failed` and make the test hermetic.

## Piped verification commands mask the real exit code — capture `$?` yourself

**Symptom (2026-08-07, MyApp):** `mix precommit` "passed" — the terminal
reported `exit_code: 0` — but the precommit had actually FAILED at
`deps.audit` (hackney advisories). The lie came from the shell pipeline:

```bash
mix precommit 2>&1 | tail -25   # pipeline exit = tail's exit = 0, always
```

The exit code of a pipeline is the LAST command, so `tail`/`grep`/`head`
swallow mix's real failure. The terminal tool echoes the pipeline's exit, not
mix's.

**Fix:** never judge a verification command by pipeline-exit. Either:

```bash
mix precommit > /tmp/verify.log 2>&1; echo "EXIT: $?"   # real exit, full log preserved
# or
set -o pipefail; mix precommit 2>&1 | tee /tmp/verify.log
```

Then read the log. In Hermes, prefer redirecting to a file and `echo "EXIT: $?"`
— you get the log for `read_file` AND the true exit code.

**Related: an alias stops at the first failing step.** `mix precommit` is
`compile --warnings-as-errors → deps.unlock --unused → deps.audit → format →
test`. When `deps.audit` fails (outdated transitive deps like hackney), the
later steps NEVER run — so "precommit failed" does NOT mean "code failed".
Run `mix format --check-formatted` and `mix test` explicitly to verify the
actual code. The audit failure itself is environment state (fixable by
`mix deps.update hackney` or a lockfile bump), not a code regression — don't
chase it mid-task unless the user asks.

## Docker build OOM during Erlang/rebar3 dep compilation (Coolify, small VPS)

**Symptom:** `docker build` fails at `mix deps.compile` with exit code 255. The log
shows ~11 mix deps compiled successfully, then `===> Compiling idna` (rebar3 output)
and silence — the Erlang compiler hangs and the build container is killed. Local
`mix deps.compile` passes fine; only the Docker build on the CI/CD host fails.

**Cause:** The default Erlang VM uses one scheduler per CPU core. On a Docker
build container with tight memory limits (512 MB-1 GB, common on Coolify and
budget VPS), the Erlang compiler run by rebar3 can OOM. The `idna`, `telemetry`,
and `telemetry_poller` hex packages are pure Erlang and compiled via rebar3,
which boots a full Erlang VM for compilation — each scheduler adds ~100-200 MB.

**Diagnosis:** check the build log for the last successful step before the hang.
If it's `===> Compiling idna` (or `telemetry`/`telemetry_poller`) and the build
exits with code 255 or a generic "command execution failed", memory is the
prime suspect — especially when the same `mix deps.compile` passes on a dev
machine with 16+ GB RAM.

**Fix:** compile the rebar3 deps first with a single-scheduler Erlang VM, then
compile the remaining mix deps normally:

```dockerfile
# BEFORE (OOM on Coolify / small VPS)
RUN mix deps.get --only prod
RUN mix deps.compile

# AFTER — scope ERL_AFLAGS to the rebar3 deps only
RUN mix deps.get --only prod

# +S 1:1  → single scheduler (~60-70% less memory than default multi-scheduler)
# +MBas busy_wait → avoids busy-waiting on the single scheduler
RUN ERL_AFLAGS="+S 1:1 +MBas busy_wait" mix deps.compile idna telemetry telemetry_poller
RUN mix deps.compile
```

**Why scoped to just those three deps:** `idna`, `telemetry`, and `telemetry_poller`
are the only common transitive deps that use rebar3 (not mix) and boot a full
Erlang VM. The remaining deps (phoenix, ecto, oban, etc.) compile via mix's
Elixir compiler which is less memory-hungry. Scoping the env var inline keeps
the later `mix compile` and `mix release` steps — which also use the Erlang VM
— at full speed.

**If it still fails:** the VPS/Docker host genuinely doesn't have enough RAM.
Options (in order):
1. Add swap on the VPS: `fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile`
2. Increase the Coolify build container memory limit in the service settings
3. Reduce total deps (unlikely for a Phoenix app)

## `DateTime.beginning_of_day/1` is undefined — use `DateTime.new!/3`

**Symptom:** `mix compile` fails with:
```text
warning: DateTime.beginning_of_day/1 is undefined or private
```

**Cause:** `DateTime.beginning_of_day/1` does NOT exist in Elixir's stdlib. The `beginning_of_day` function is only on `NaiveDateTime`.

**Fix:** construct the beginning of day explicitly:
```elixir
# WRONG — will not compile
today_start = DateTime.utc_now() |> DateTime.beginning_of_day()

# CORRECT
today_start = DateTime.new!(Date.utc_today(), ~T[00:00:00], "Etc/UTC")
```

**Generalizable rule:** Elixir's `DateTime` module has fewer convenience functions than `NaiveDateTime`. When you need date/time truncation or rounding, check which module has the function — `NaiveDateTime` has `beginning_of_day/1`, `beginning_of_hour/1`, etc.; `DateTime` does not.

## `from(p in Module)` without body doesn't expand — add `select: p`

**Symptom:** `mix compile` fails with:
```text
error: undefined variable "p"
     │
 210 │       from(p in Provider)
     │            ^
```

**Cause:** `Ecto.Query.from/2` requires a body (either a keyword query or a `do...end` block). The bare `from(p in Module)` without a select or where clause doesn't expand the macro, so the variable `p` is never bound.

**Fix:** add an explicit `select` or full query:
```elixir
# WRONG — will not compile
from(p in Provider) |> Repo.all()

# CORRECT — with select
from(p in Provider, select: p) |> Repo.all()

# ALSO CORRECT — with where
from(p in Provider, where: p.status == "active") |> Repo.all()
```

**Generalizable rule:** `from` in Ecto.Query always needs a body. Even if you want all columns, write `from(p in Module, select: p)` — the bare form doesn't work.

## `field :X_id` + `belongs_to :X` — duplicate field compile error

**Symptom:** `mix compile` fails with:

```text
** (ArgumentError) field/association :provider_id already exists on schema,
you must either remove the duplication or choose a different name
```

**Example:**

```elixir
schema "request_logs" do
  field :id, :binary_id, primary_key: true
  field :provider_id, :binary_id            # ← explicit field
  # ...
  belongs_to :provider, MyApp.Providers.Provider,
    references: :id,
    foreign_key: :provider_id,
    type: :binary_id
end
```

**Cause:** `belongs_to :provider` already generates a `:provider_id` field. Adding a `field :provider_id` on top creates a duplicate — Ecto rejects it.

**Fix:** remove the explicit `field :provider_id` — let `belongs_to` create it:

```elixir
schema "request_logs" do
  field :id, :binary_id, primary_key: true
  # field :provider_id, :binary_id   ← DELETE this line
  field :model_provider_id, :binary_id
  # ...
  belongs_to :provider, MyApp.Providers.Provider,
    references: :id,
    foreign_key: :provider_id,
    type: :binary_id
end
```

**Rule:** for associations, declare only the `belongs_to` — never add a raw `field` for the foreign key column as well.

## `mix compile` hangs at 0% CPU — dev server `.beam` lock or zombie compile process

**Symptom:** `mix compile` (or `mix compile --warnings-as-errors`) never finishes and prints nothing. It does NOT error — it just sits there. This is distinct from the `:eaddrinuse` failure modes above: the compile never gets far enough to boot the app.

**Diagnosis:**

```bash
# 1. Find the compile process and check its state
ps aux | grep -E "mix|beam" | grep -v grep

# 2. Is it actually doing anything? 0% CPU = hung, not slow
ps -p <pid> -o pid,etime,%cpu,stat
```

Two common causes, both seen in the same session:

1. **A `mix phx.server` beam is running.** The dev server holds file locks on the `.beam` files in `_build/<env>/lib/*/ebin/`. On macOS this blocks the compiler from overwriting them — the compile hangs silently instead of erroring. Check with `ps aux | grep phx.server | grep -v grep`.
2. **A zombie `mix compile` from a timed-out subagent.** A subagent that hit its 600s timeout mid-compile leaves an orphaned beam process behind. A second compile then hangs waiting on the same lock. Check `ps -p <pid> -o etime` — a compile with `ELAPSED` of 10+ minutes at 0% CPU is a zombie.

**Recovery (in order):**

```bash
# 1. Kill zombie compile processes first
kill -9 <compile_beam_pid> <compile_shell_pid>

# 2. Kill the dev server (it re-locks beams on every code reload)
kill <phx_server_pid>   # then kill -9 if it survives

# 3. Compile clean
mix compile --warnings-as-errors
```

**If the first compile after the kill fails with `redefining module ... (current version loaded from _build/...)` warnings under `--warnings-as-errors`:** those warnings are spurious leftovers — the dying server still had modules loaded in memory when the compile started. Do NOT chase them. Just re-run:

```bash
mix compile --force --warnings-as-errors
```

`--force` recompiles everything from source, so no stale in-memory module can "redefine" anything. After it succeeds once, plain `mix compile --warnings-as-errors` works again.

**Do NOT try `MIX_BUILD_PATH=/tmp/...` to dodge the lock.** It breaks deps like `phoenix_live_reload` that read `phoenix/priv/static/phoenix.js` from the shared build path at compile time (`could not read file .../phoenix.js: no such file or directory`). Killing the locker is the fix, not sandboxing the build.

**Prevention:** before running `mix compile` / `mix test` / `mix precommit` during pairing sessions, check `ps aux | grep phx.server` and kill any running server first — or expect the hang. After the work is done, restart the server for the user (or tell them to).

**Alternative when the server must stay up (2026-07-19):** during a long edit → test → visually-verify-in-browser loop, killing and rebooting the dev server every cycle is slow and logs out the browser session each time. Two lighter options:
- `PORT=4077 mix test` — runtime.exs reads `System.get_env("PORT")`, so the test endpoint binds elsewhere and the suite runs alongside the live server on :4000. (Works when the test env boots its own endpoint; if runtime.exs's `server: true` is prod-guarded and test.exs sets `server: false`, there's no collision anyway and plain `mix test` is fine as long as nothing else binds the port.)
- For quick intermediate checks skip compile entirely: edit files, let the dev server hot-reload, verify in the browser. Save `mix compile --force --warnings-as-errors` + the full suite for the final gate, killing the server only once at the end.

## Ecto mixed FK types — `belongs_to` + `field` when one side is `:binary_id` and the other `:id`

**Symptom:** `mix ecto.migrate` (or the test sandbox running migrations) fails with:

```text
** (Postgrex.Error) ERROR 42804 (datatype_mismatch) foreign key constraint "user_contexts_context_id_fkey" cannot be implemented

Key columns "context_id" of the referencing table and "id" of the referenced table are of incompatible types: bigint and uuid.
```

**Cause:** a join schema links two tables whose primary keys have different types — e.g. `users.id` is `bigint` (default) but `contexts.id` is `:binary_id` (uuid). Plain `references(:contexts)` in the migration defaults to `bigint`, which doesn't match the referenced `uuid` column. And in the schema, plain `belongs_to :context, MyApp.Context` generates a `context_id` field typed `:id` (integer), so casting a uuid string fails with `{"is invalid", [type: :id, validation: :cast]}`.

**Fix — both files must agree:**

```elixir
# migration — type the reference explicitly
add :context_id, references(:contexts, type: :binary_id, on_delete: :delete_all), null: false

# schema — declare the field manually with the right type, and tell belongs_to NOT to redefine it
schema "user_contexts" do
  belongs_to :user, MyApp.Accounts.User          # user.id is bigint — plain belongs_to is fine
  field :context_id, :binary_id                  # explicit field with uuid type
  belongs_to :context, MyApp.Brain.Context, define_field: false

  timestamps()
end
```

**Rule:** when a schema has `belongs_to` associations to tables with DIFFERENT PK types (one `:id`, one `:binary_id`), declare the non-default FK as an explicit `field :x_id, :binary_id` and pass `define_field: false` to its `belongs_to`. The migration's `references/2` must carry the matching `type:` option. A compile that passes but a migration/test that blows up with `datatype_mismatch` or a cast `is invalid` error is this mismatch — check the referenced table's `@primary_key` type before writing the join.

## `redirect(to:)` crashes with full URL from the Referer header — extract the path

**Symptom (2026-08-02):** a POST action that redirects back to where the user came from crashes with:

```text
** (ArgumentError) the :to option in redirect expects a path but was "http://localhost:4000/"
```

**Cause:** `get_req_header(conn, "referer")` returns the FULL URL (`http://host/path?query`), but `Phoenix.Controller.redirect(to:)` only accepts a local path (`/path`). Passing the raw referer string to `redirect(to:)` raises.

**Fix:** parse the referer with `URI.parse/1` and keep only path + query:

```elixir
defp referer_path(conn) do
  case get_req_header(conn, "referer") |> List.first() do
    nil -> ~p"/fallback"
    url ->
      case URI.parse(url) do
        %URI{path: path} when is_binary(path) and path != "" ->
          case URI.parse(url).query do
            nil -> path
            query -> path <> "?" <> query
          end
        _ -> ~p"/fallback"
      end
  end
end

# usage
conn |> redirect(to: referer_path(conn))
```

**Rule:** any redirect built from request headers (referer, forwarded URLs) must be sanitized through `URI.parse` — never trust that a header contains a path. Also validate the target belongs to your app if the header can come from external clients (open-redirect risk).

## Multi-clause `defp` with default args — declare the default ONCE, not per clause

**Symptom:** `mix compile --warnings-as-errors` fails with:

```text
error: defp execute_tool/3 defines defaults multiple times. Elixir allows
defaults to be declared once per definition. Instead of:

    def foo(:first_clause, b \ :default) do ... end
    def foo(:second_clause, b \ :default) do ... end

one should write:

    def foo(a, b \ :default)
    def foo(:first_clause, b) do ... end
    def foo(:second_clause, b) do ... end
```

**Cause:** you added `\\nil` (or any default) to EVERY clause head of a multi-clause function. Elixir requires defaults in a single headless declaration clause, followed by clause heads WITHOUT the default.

**Fix (two options):**

Option A — declare once, then clauses without default:
```elixir
defp execute_tool(name, args, user \\nil)  # headless — declares the default
defp execute_tool("dran_search", %{"query" => q} = args, user) do ... end
defp execute_tool("dran_create_page", %{"page_type" => t} = args, user) do ... end
defp execute_tool(tool_name, _args, _user), do: "Error: unknown tool"
```

Option B — if the caller ALWAYS passes the arg explicitly, drop the default entirely:
```elixir
defp execute_tool("dran_search", %{"query" => q} = args, _user) do ... end
defp execute_tool("dran_create_page", %{"page_type" => t} = args, user) do ... end
```

Option B is cleaner when there's a single call site that always passes the value — no headless declaration, no "default never used" warning.

**`\\nil` syntax gotcha:** the backslash operator for default args must be `\\nil` (two backslash bytes `0x5c 0x5c`, no space before nil). When bulk-editing with Python, `b'user \\\\nil'` matches two actual backslash bytes — `b'user \\nil'` (one backslash) will NOT match and silently misses every occurrence. Always verify with `xxd` or `hexdump` before attempting byte-level replacements. The display `user \\nil` in grep output IS the two-backslash byte sequence.

**Unused-variable warnings after removing defaults:** clauses that receive `user` but don't use it will warn. Prefix with underscore: `_user`. Only clauses that actually reference the variable keep it without the underscore. A catch-all clause at the end (`defp execute_tool(tool_name, _args, _user)`) both catches unknown tools and marks the variable unused.

**Don't forget the catch-all removal:** if the function had a catch-all clause with `\\nil`, removing the default from all clauses also requires removing it from the catch-all. If a headless default declaration is placed before the first real clause, the old catch-all at the end of the function that also had a default must have its default removed too.

## `@deprecated` + `@compile {:nowarn_deprecated}` doesn't suppress warnings in Elixir 1.20+

**Symptom:** You add `@deprecated "Use X instead"` to a function, then add `@compile {:nowarn_deprecated, ...}` at call sites to suppress the warnings — but `mix compile --warnings-as-errors` STILL fails with deprecation warnings. The suppression syntax has no effect.

**Cause:** In Elixir 1.20+, the `@compile {:nowarn_deprecated, ...}` attribute is either broken or its syntax changed silently. None of these forms work:

```elixir
@compile {:nowarn_deprecated, {Mod, :fun, 1}}
@compile {:nowarn_deprecated, [{Mod, :fun, 1}]}
@compile {:nowarn_deprecated, [Mod: [fun: 1]]}
```

The warning is still emitted at every call site, and `--warnings-as-errors` turns it into a compile failure.

**Fix:** don't use `@deprecated` on functions that still have active call sites in the same codebase. Instead:

1. **Keep the function working** (no behavior change).
2. **Document deprecation in `@moduledoc` and `@doc`** — prose warnings, not compiler attributes:

```elixir
defmodule MyApp.Auth do
  @moduledoc """
  **Deprecated legacy single-user authentication.**

  Use `MyApp.Accounts` for multi-user auth instead. This module is kept for
  backward compatibility with existing deployments.
  """

  @doc "Deprecated: use `MyApp.Accounts.valid_token?/1` instead."
  def valid_token?(token), do: # ...
end
```

3. **Migrate call sites incrementally** — once all callers use the new API, you can safely add `@deprecated` (or just delete the module).

**Rule:** `@deprecated` is only safe when the function has ZERO callers in the same repo. If any module in the project still calls it, the compile breaks. Use doc comments for soft deprecation during migration.

## `mix phx.server` hangs on "Waiting for lock on the build directory" — wedged previous server

**Symptom:** starting `mix phx.server` prints `Waiting for lock on the build directory (held by process <pid>)` and never boots. The holder is a previous `beam.smp` running `mix phx.server` that is still alive — `lsof -i :4000 -sTCP:LISTEN` shows it bound — but it does NOT answer HTTP: `curl -m 5 http://localhost:4000/` times out (returns `000`) and `ps` shows 0% CPU. This is a wedged/zombie server (TCP listen socket open, acceptor pool dead), distinct from the healthy-server `:eaddrinuse` cases.

**Diagnosis (fast path):**
1. The holder PID is printed right in the lock message — confirm it: `ps -p <pid> -o pid,stat,%cpu,etime,command`.
2. Probe responsiveness, not just the port: `curl -s -m 5 -o /dev/null -w "%{http_code}" http://localhost:4000/`. `000`/timeout + `Ss` state + 0% CPU = wedged. **A listening port that answers `000` is NOT "server already running, all good"** — when asked to "start the server" and one is already up, always curl before declaring done. If it answers 200, just report that; no restart needed.

**Recovery:**
```bash
kill <pid>          # SIGTERM — beam may release the port but linger in ps
sleep 5
kill -9 <pid>       # only if it survives the TERM
mix phx.server      # fresh start
curl -s -m 10 -o /dev/null -w "%{http_code}\n" http://localhost:4000/   # expect 200
```
Kill YOUR duplicate too — the `mix phx.server` you just started is still sitting on the lock queue (in Hermes: `process(action='kill')` on its background session).

**Hermes tip:** start dev servers with `terminal(background=true)` + `watch_patterns: ["Access <App>Web.Endpoint at"]` instead of sleep-polling — you get notified exactly once when the endpoint is ready, and a boot that hangs on the lock message is visible immediately (no match after a few seconds = go diagnose).

**watch_patterns pitfall (2026-07-27):** do NOT add generic words like `"error"` as extra watch patterns on a Phoenix dev server. The server logs Ecto queries verbatim (`WHERE status = 'error'`), router 404s, and transient code-reload compile errors — a generic pattern fires on benign lines, and the 1-per-15s rate limit then SUPPRESSES later matches, so a real boot error can be hidden behind noise. Watch only the exact ready string; treat the absence of a match after a few seconds as the hang signal, and poll the log if you suspect trouble.

**Harmless log noise (the user's env):** `POST /api/some-plugin → Phoenix.Router.NoRouteError` 404s in a fresh server log are the hermes-extools MCP client probing the app — benign in projects that don't host that route (e.g. your app). Not an app bug; don't "fix" it.

## "undefined function" in the dev-server log but `mix compile` is clean — transient mid-edit reload

**Symptom (2026-07-27):** the running dev server logs a hard compile error (e.g. `error: undefined function to_float!/1 (expected MyApp.Mod to define such a function or for it to be imported...)`), but the current source clearly defines/imports that function and `mix compile --force --warnings-as-errors` passes clean.

**Cause:** Phoenix's code reloader compiles on file-change events. While a file is being written incrementally (a subagent streaming an edit, a multi-hunk patch landing in stages), the reloader compiles a half-written snapshot — e.g. a call site already saved while the helper `defp` further down hasn't been written yet. The error is real *for that intermediate state* and never exists in the final file.

**Rule:** a compile error that lives ONLY in the dev-server log is not actionable until verified against current source. Grep the file for the "missing" function, then run `mix compile --force --warnings-as-errors` and the module's test file. If clean, report it as transient and move on — do NOT "fix" working code and do NOT re-dispatch the subagent that wrote the file. (Inverse of the "broken syntax after subagent batch" section below: that one persists in `mix compile`; this one vanishes.)

## HEEX `not @assign` crashes with ArgumentError — use `is_nil/1`

**Symptom:** a LiveView renders a 500 on mount. The log shows:

```text
** (ArgumentError) argument error
    (MyApp 0.1.0) lib/myapp_web/live/something_live.html.heex:162
```

**Cause:** `not` in Elixir requires a strict boolean argument. When an assign is `nil` (the default for many assigns in `mount/3`), `not nil` raises `ArgumentError` — it does NOT return `true`.

```heex
<!-- WRONG — crashes when @selected_provider_id is nil -->
disabled={not @selected_provider_id}
```

**Fix — use `is_nil/1` which handles nil safely:**

```heex
disabled={is_nil(@selected_provider_id)}
```

For compound expressions:

```heex
<!-- WRONG -->
disabled={not @a or not @b or not @c}

<!-- CORRECT -->
disabled={is_nil(@a) or is_nil(@b) or is_nil(@c)}
```

**Rule:** in HEEX templates, never use `not @assign` for nil-checking. Always use `is_nil(@assign)`. The `not` operator is only safe when the value is guaranteed to be a boolean (e.g. `@running` initialized to `false`).

## LiveView `phx-value-*` sends flat params, not nested — normalize in handler

**Symptom:** a `phx-click` button with `phx-value-*` attributes crashes the `handle_event` callback because it pattern-matches `%{"target" => params}` but receives flat params.

```heex
<!-- Button sends: %{"provider_id" => "x", "credential_id" => "y", "model" => "z"} -->
<button phx-click="add_target" phx-value-provider_id={@p} phx-value-credential_id={@c} phx-value-model={@m}>
```

```elixir
# WRONG — crashes, params are flat, not nested under "target"
def handle_event("add_target", %{"target" => params}, socket) do
```

**Cause:** `phx-value-*` attributes on a `phx-click` button produce **flat** params (each `phx-value-key` becomes a top-level `"key"` in the params map). A `<.form phx-submit="add_target">` with `name="target[key]"` inputs produces **nested** params (`%{"target" => %{"key" => val}}`). When you use both a form AND a button for the same event, the handler must accept both shapes.

**Fix — normalize with `Map.get(params, "target", params)`:**

```elixir
def handle_event("add_target", params, socket) do
  # Flat from phx-value-* button, nested from form submit — normalize
  target = Map.get(params, "target", params)
  provider_id = target["provider_id"] || ""
  credential_id = target["credential_id"] || ""
  model = String.trim(target["model"] || "")
  # ...
end
```

**Rule:** when a LiveView event can be triggered by both a `phx-click` button (flat params) and a `phx-submit` form (nested params), always normalize at the top of the handler. Never pattern-match a specific nested shape.

## `mix precommit` leaves a dirty tree (format sweep side effect)

**Symptom (2026-08, MyApp):** after a clean series of refactor commits, you run `mix precommit` as the final gate — it passes — but `git status` now shows uncommitted modifications in files your work never touched (a prior migration, unrelated modules).

**Cause:** the `precommit` alias includes `mix format` (write mode, not `--check-formatted`). It re-formats the WHOLE project, including files committed earlier in non-canonical format. The formatter's edits land in the working tree AFTER your last commit, leaving the repo dirty even though everything "passed".

**Rule:** commit all refactor/feature work FIRST, run `mix precommit` LAST, then sweep the format leftovers into a separate `style: mix format sweep` commit. Never amend them into a refactor commit, and check `git diff` first — if the sweep re-formatted a file you didn't author (e.g. a prior migration), say so in the style commit message so archaeology stays clear.

## `mix precommit` fails with `:eaddrinuse` — kill dev server first

`mix precommit` (which runs `mix test` + `mix credo` + `mix format`) starts a
test endpoint on the configured port. If a dev server (`mix phx.server`) is
already running on that port, the alias fails with:

```text
** (Mix) Could not start application MyApp: MyApp.Application.start(:normal, []) returned an error: shutdown: failed to start child: MyAppWeb.Endpoint
    ** (EXIT) :eaddrinuse
```

**Fix:** kill the dev server before running precommit, or use a different port:

```bash
# Option 1: kill stale server
lsof -ti :4000 | xargs kill -9 2>/dev/null; sleep 1; mix precommit

# Option 2: use different port for test endpoint
PORT=4199 mix precommit
```

**Why this happens:** `runtime.exs` sets `server: true` and reads `PORT` env
var. The test env inherits this unless `test.exs` explicitly sets
`server: false` or `config_env() != :test` guards the runtime config. See
the `runtime.exs` overrides section above for the full diagnosis.

## `mix test` fails with `:eaddrinuse` — check the cheap cause first

Before anything else: a stale dev server may just be holding the port. Check
and kill, then re-run:

```bash
lsof -ti :4000 | xargs kill -9 2>/dev/null; sleep 1; mix test
```

If the suite runs green after the kill, it was just a leftover `mix phx.server`
— no config bug. This is the common case when the failing port matches your
normal dev/test port AND you recently had a server running.

If the port still collides after killing (or the error names a port that does
NOT match `test.exs`, e.g. 4000 when test uses 4002), then it's the config
problem below.

### `runtime.exs` overrides `test.exs`

`config/runtime.exs` runs in **all** environments, including `:test`, and is applied **after** `config/test.exs`. Any `config :app, AppWeb.Endpoint, server: true` or `http: [port: ...]` line written *outside* a `if config_env() == :prod do` block in `runtime.exs` will silently override `test.exs`'s `server: false`, causing `mix test` to start the HTTP endpoint and collide with a running dev server on the same port.

Symptom:

```text
** (Mix) Could not start application app: App.Application.start(:normal, []) returned an error: shutdown: failed to start child: AppWeb.Endpoint
    ** (EXIT) :eaddrinuse
```

The `:eaddrinuse` target port is the one from `runtime.exs` (default 4000), NOT the `4002` set in `test.exs` — that mismatch is the tell-tale sign `runtime.exs` is winning over `test.exs`.

Quick workaround to unblock a test run without editing config:

```bash
PORT=4099 mix test   # or any free port — overrides runtime.exs's System.get_env("PORT", "4000")
```

Proper fix: gate endpoint `server:`/`http:` config in `runtime.exs` behind a prod (or `config_env() != :test`) guard so `test.exs` wins in `:test`:

```elixir
# config/runtime.exs — BAD (runs in :test too, overrides test.exs)
config :app, AppWeb.Endpoint, server: true
config :app, AppWeb.Endpoint, http: [port: String.to_integer(System.get_env("PORT", "4000"))]

# GOOD — only applies in prod
if config_env() == :prod do
  config :app, AppWeb.Endpoint, server: true
  config :app, AppWeb.Endpoint, http: [port: String.to_integer(System.get_env("PORT", "4000"))]
  # ... rest of prod config
end
```

See `references/runtime-exs-overrides-test-exs.md` for the full reproduction and diagnosis path.
See `references/subagent-parallel-pitfalls.md` for real-world issues from parallel subagent execution (commit bundling §1/§12, timeouts §2/§11, syntax errors §3, test hangs §4, gettext fuzzy pollution §13, dynamic msgid extraction §14).

## `mix test` hangs forever — subagent tests trigger external HTTP calls

**Symptom:** `mix test` hangs forever. Individual test files pass quickly, but the full suite never finishes. `lsof -ti:PORT` shows no server running.

**Cause:** Subagent-written tests call `Brain.create_page/1` (or similar) which triggers `PageAugmenter.schedule/1`. When test config sets `schedule_async: false` but leaves `base_url` pointing to a non-existent server, each `create_page` call blocks for the full retry timeout (3 retries × ~7s = ~21s per page). With 25+ tests, the suite hangs for minutes.

**Diagnosis:** Run `mix test --trace` — you'll see tests completing but with 14+ second delays and `Req.TransportError: connection refused` warnings from `PageAugmenter`.

**Fix:** In the test setup, set `base_url: nil` to disable inference entirely:

```elixir
setup do
  original = Application.get_env(:MyApp, :inference)

  Application.put_env(:MyApp, :inference,
    base_url: nil,  # ← this makes Inference.enabled?() return false
    api_key: nil,
    timeout: 100,
    schedule_async: false
  )

  on_exit(fn ->
    if original, do: Application.put_env(:MyApp, :inference, original),
      else: Application.delete_env(:MyApp, :inference)
  end)

  # ... rest of setup
end
```

The key is `base_url: nil` — this makes `MyApp.Inference.Config.enabled?()` return `false`, which short-circuits `PageAugmenter.schedule/1` to `:ignored` before any HTTP call is attempted.

## Flaky suite failures from env-injected inference — async tasks race `Req.Test` stubs

**Symptom:** 2-4 tests fail when running the full suite (different ones each run — an E2E agent test, a search controller test, a curation_agent test), but every one of them **passes when run in isolation**. The failing assertion is often a scripted-response desync, e.g. the E2E expected tool call #2 `get_page` but received `done` (script response #4).

**Cause (the deterministic version):** `runtime.exs` loads inference config in **all** envs (`config :MyApp, :inference, MyApp.Inference.Config.load_from_env()` unguarded). A dev shell with the inference env vars set — e.g. `eval "$(mise env)"` auto-loading `.env` with `MYAPP_INFERENCE_API_URL` — means inference is **enabled at test boot**. Tests that create pages *before* their own `Application.put_env(:MyApp, :inference, ...)` setup assume `PageAugmenter.schedule/1` returns `:ignored`, but with inference enabled it spawns a real async `Task`. That task wakes up *after* the test installs its `Req.Test` stub and consumes scripted responses, desyncing the script.

**Diagnosis (do this before blaming the tests):**

1. Run one failing file alone: `PORT=4099 mix test test/path/file_test.exs` — if it passes, it's a suite-level race, not a broken test.
2. Confirm the suite goes green with inference stripped from the environment:
   ```bash
   env -u MYAPP_INFERENCE_API_URL -u MYAPP_INFERENCE_API_KEY PORT=4099 mix test
   ```
   If this is green, the failures are env leakage, not your code.
3. To find the thief inside a scripted E2E test, temporarily add `IO.inspect({idx, raw_body}, label: "STUB CALL")` inside the `Req.Test.stub` function. The surprise calls are unmistakable — e.g. augmenter payloads (`"Analyze the given page and return a single JSON object..."`) wedged between the script's own steps.

**Fix (make the test hermetic — don't rely on the shell being clean):** explicitly delete inference config **before** creating any pages, then install the stub config:

```elixir
test "E2E flow with scripted stub" do
  # runtime.exs loads inference in all envs — kill it before page creation
  # so PageAugmenter.schedule returns :ignored (no async task racing the stub)
  original = Application.get_env(:MyApp, :inference)
  Application.delete_env(:MyApp, :inference)

  ctx = create_context!()
  page = create_page!(ctx, %{...})          # safe now — no augmenter spawned

  Application.put_env(:MyApp, :inference, base_url: "...", req_plug: {Req.Test, ...})
  on_exit(fn -> restore original end)
  # ...
end
```

**Distinction from the "hangs forever" section above:** that one is `base_url` pointing at a dead server with `schedule_async: false` (sync 21s-per-page stall). This one is inference *enabled from the shell env* with async tasks stealing stub responses. Same family (env-leaked inference in tests), different mechanism and symptom.

## Keyword list ordering gotcha — `[key: val, :atom]` is invalid

**Symptom:** `mix compile` fails with:

```text
error: unexpected expression after keyword list. Keyword lists must always come
last in lists and maps. Therefore, this is not allowed:

    [some: :value, :another]
    %{some: :value, another => value}

Instead, reorder it to be the last entry:

    [:another, some: :value]
    %{another => value, some: :value}
```

**Example from a real deployment failure:**

```elixir
# BROKEN — keyword pair before atom in list
request_log = MyApp.Repo.preload(request_log, [team_member: [:user, :team], :provider])

# FIX — atoms before keyword pairs
request_log = MyApp.Repo.preload(request_log, [:provider, team_member: [:user, :team]])
```

**Cause:** In Elixir, when a list contains both keyword pairs (`key: value`) and bare atoms/terms, the keyword pairs **must come last**. This applies whether the list is explicit (`[...]`) or implicit via function-call last-argument syntax (`f(arg, key: val, :atom)`).

**Both of these are equally invalid:**

```elixir
# Explicit list — keyword pair before atom
Repo.preload(request_log, [team_member: [:user, :team], :provider])

# Implicit keyword-list last arg (same parse result)
Repo.preload(request_log, team_member: [:user, :team], :provider)
```

**The `team_member: [:user, :team], :provider` function-call form** is parsed as `[team_member: [:user, :team], :provider]` internally — the same invalid list. There is no compiler leniency for the bracket-less form.

**Why this slips through local development:** Local `mix compile` may use a different Elixir version (e.g. 1.18) that has a different parser, or the file was never actually recompiled (cached `.beam`). The Docker build with the exact target Elixir version (e.g. 1.20.2 in the Dockerfile) catches it.

**Rule of thumb:** in any list that mixes keyword pairs and bare elements, always write atoms/terms first, keyword pairs last:

```elixir
# VALID
[:provider, team_member: [:user, :team]]
```

This is valid because `[:provider, team_member: [:user, :team]]` is syntactic sugar for `[:provider, {:team_member, [:user, :team]}]` — a list with an atom followed by a two-tuple.

**How to prevent:** when calling Ecto.Repo.preload/3 (or any function that takes a mixed list of assocs), always write bare atom associations first, then keyword pairs:

```elixir
# GOOD — atoms first, keyword pairs last
Repo.preload(request_log, [:provider, team_member: [:user, :team]])

# ALSO GOOD — separate into positional args if preload/2 accepts multiple
Repo.preload(request_log, :provider, team_member: [:user, :team])
```

The three-argument form `Repo.preload(struct_or_structs, assocs, opts \\\\ [])` accepts a list as the second arg, so `Repo.preload(log, [:provider, team_member: [:user, :team]])` is the idiomatic fix.

## `mix compile --warnings-as-errors` fails after subagent batch — broken syntax

**Symptom:** After a batch of subagents returns, compilation fails with `TokenMissingError`, `undefined function sigil_p/2`, or `Gettext macros expect message keys to expand to strings`.

**Cause:** Parallel subagents edit overlapping files or generate code with unescaped quotes, missing imports, or invalid HEEx/Gettext syntax.

## Patching heredoc strings in module attributes (`@moduledoc`, `@tools`)

**Symptom:** After a targeted find-and-replace inside a `@moduledoc """..."""` or
a `%{"description" => """..."""}` string in an `@tools` list, `mix compile`
fails with `TokenMissingError` / `unexpected token` / `syntax error before`.

**Cause:** The closing `"""` of a heredoc sits at the end of a line that is
*also* followed by trailing punctuation (`,`, `=>`, etc.). A find-and-replace
that includes the closing `"""` plus the trailing comma in its match can
accidentally produce:

- `""""` (four quotes) — the replacement re-appends the comma's quote,
  turning the heredoc terminator into a four-quote run that Elixir reads as
  an empty heredoc + a stray `"`.
- `""",,` (double comma) — when the `old_string` captured `"""` but the
  `new_string` re-added a comma, and the original already had one.

**Detection:** the error line number points at the `"""` line, and the diff
shows the terminator line was touched. Read the actual file (not just the diff)
around the quoted heredoc terminator before re-patching.

**Recovery pattern:**
1. `read_file` the lines around the heredoc terminator (offset ±5).
2. If you see `""""` or `""",,`, patch **just those characters** back to `"""` +
   the single correct trailing punctuation.
3. Re-run `mix compile --warnings-as-errors` — it will now pass or reveal the
   next error (if any).

**Prevention:** when patching inside a heredoc body, make the `old_string`
start and end on **content lines**, never on the terminator `"""` line itself.
If you must touch the terminator, include it with enough unique context and
make sure the `new_string` reproduces exactly one `"""` plus the original
trailing punctuation — no more.

**Common fixes:**

| Error | Fix |
|-------|-----|
| `missing terminator: " (for sigil ~p"` | Remove nested quotes: `~p"/path?key=value"` not `~p"/path?#{%{key: "value"}}"` |
| `undefined function sigil_p/2` | Component doesn't `use Phoenix.VerifiedRoutes` — use plain string `"/path"` instead of `~p"/path"` |
| `Gettext macros expect message keys to expand to strings` | `gettext(dynamic_var)` is invalid — use `dynamic_var` directly, or `Gettext.gettext(MyAppWeb.Gettext, dynamic_var)` |
| `attribute "phx-hook" requires the "id" attribute` | Add `id="hook-name"` to the element |

**Recovery workflow:**
1. `git diff --stat` to see the blast radius
2. `mix compile --warnings-as-errors 2>&1 | head -30` to find the first error
3. Read the broken file, fix the syntax yourself
4. Re-compile, fix next error, repeat
5. Only commit after compile + test pass

## Subagent timeout — work is often already committed (or NOT — check mtimes)

**Symptom:** Subagent reports `status=timeout` after 600s, but `git log` shows a commit with the task's message and the working tree contains the expected files.

**Cause:** The subagent completed the work and committed, but the summary/report step exceeded the time limit. The timeout is on the report, not the work.

**Recovery:** Don't re-dispatch. Verify the commit exists (`git log --oneline -3`), run `mix compile --warnings-as-errors && mix test`, and move on. The work is done.

**Inverse case (2026-07-19):** a subagent that burns 600s re-searching the same CSS patterns in a discovery loop and reports "task NOT completed — file was not modified" produced NOTHING. Check file mtimes (`stat -f "%Sm %N" <files>`) before assuming either way. For small well-specified tasks, the parent should just do the edit directly rather than re-dispatching the same prompt to the same looping model. See `references/subagent-parallel-pitfalls.md` §11.

**Commit bundling — subagent sweeps parent's uncommitted work (2026-07-19):** a subagent that fills `.po` files can run `git add -A` and commit everything in the working tree, including the parent's own uncommitted edits (e.g. kanban button fixes, page_new gender labels). The parent then finds `git status` clean and assumes their work was "already committed by someone else" — when actually the subagent's commit bundled both scopes. **Prevention:** always check `git log --oneline -2` after a subagent batch completes to see if the commit message covers multiple scopes; if it does, verify your own edits are inside before moving on. See `references/subagent-parallel-pitfalls.md` §12.

## Gettext fuzzy pollution — existing msgstr corrupted by merge (2026-07-19)

**Symptom:** After `mix gettext.extract --merge`, a msgid that had a correct translation suddenly shows a completely wrong msgstr — e.g. `msgid "None"` (used for select prompts) renders as `"Hecho"` in the UI instead of `"Ninguno"`.

**Cause:** The gettext fuzzy matcher maps a new msgid to the *closest* existing one when it can't find an exact match. A msgid that was previously `msgstr ""` (empty) gets "helpfully" filled with the nearest non-empty msgstr during merge. This happens silently — no warning, no error.

**Diagnosis:**
1. `grep -B1 -A2 'msgid "<wrong_string>"' priv/gettext/es/LC_MESSAGES/default.po` — find the msgid with the wrong msgstr.
2. Check the `#, fuzzy` flag on the entry — fuzzy entries were auto-matched.
3. `git diff priv/gettext/` to see which msgstrs changed in the last merge.

**Fix:** manually correct the msgstr, remove the `#, fuzzy` flag, and re-run `mix gettext.extract --merge` to confirm it stays. If the same msgid is used in multiple contexts (e.g. "None" for both "no goal" and "no project"), replace it with context-specific msgids (`"Sin objetivo"`, `"Sin proyecto"`) so each gets its own correct translation.

**Prevention:** after any `mix gettext.extract --merge`, run `git diff priv/gettext/es/LC_MESSAGES/default.po | grep "^+msgstr"` and scan for msgstrs that don't match their msgid. Never trust the merge to preserve existing translations — fuzzy matching is a heuristic, not a guarantee.

## Gettext extraction markers for dynamic msgids (2026-07-19)

**Symptom:** Page type labels (Note, Concept, Entity, Todo, etc.) are translated correctly in the `.po` file but the UI still shows the English string — or the msgstr disappears after every `mix gettext.extract --merge`.

**Cause:** The labels are looked up dynamically at runtime via `Gettext.gettext(MyAppWeb.Gettext, label_string)` where `label_string` comes from a map (`%{"note" => %{label: "Note"}}`). The gettext extractor never sees these msgids because they're not inside `gettext("...")` calls in the source. During merge, msgids not found in source are removed.

**Fix:** add a no-op extraction block at the end of the module that lists all dynamic msgids:

```elixir
# At the end of page_types.ex (or any module with dynamic gettext lookups)
if false do
  gettext("Note")
  gettext("Concept")
  gettext("Entity")
  # ... etc
end
```

**Why this works:** the extractor scans for `gettext("literal")` calls and adds them to the `.pot`/`.po`. The `if false` guard means the code never executes but the extractor sees the msgids and preserves them through merges.

## Async delegation batch — verify before re-dispatching

**Symptom:** A background delegation batch completes, but when you check `git status` the working tree is clean and `git log` shows the changes were already committed in a previous wave.

**Cause:** Async subagents run in the same repo. If a previous synchronous wave already committed the same changes (e.g., i18n wrappers, empty states, micro-interactions), the async batch's work is redundant — the files were already modified and committed before the async agents started.

**Recovery:**
1. `git status --short` — if clean, changes are already committed
2. `git log --oneline -5` — check if the async task's scope matches recent commits
3. `git show --stat HEAD` — verify the files match what the subagents claimed to modify
4. Run `mix compile --warnings-as-errors && mix test` to confirm everything still passes
5. Do NOT re-dispatch or re-commit — the work is already integrated

**Prevention:** When dispatching async subagents for UI polish (i18n, empty states, micro-interactions), note in the task prompt which files were already modified in previous waves. This prevents redundant work and merge conflicts.

## Verifying CSS independently when `.ex` compilation fails

When `mix assets.build` fails due to an unrelated Elixir compilation error
(e.g., Gettext dynamic msgid, broken HEEx syntax in a `.ex` file), you can
still verify that your CSS changes compile correctly by running only the
Tailwind step:

```bash
mix tailwind default
```

This runs the Tailwind v4 compiler against `assets/css/app.css` and writes
to `priv/static/assets/css/app.css`. If it prints "Done in Xms" without
errors, the CSS is valid — the `mix assets.build` failure is purely from
the Elixir compilation phase. Useful when you only changed CSS and need to
confirm Tailwind syntax is correct without fixing unrelated `.ex` issues.

## `rescue _ ->` does NOT catch `:exit` from `GenServer.call` — use `catch :exit`

**Symptom:** A function has a `rescue _ -> :ignored` clause intended to swallow any failure from a `Task.Supervisor.start_child/3` or `GenServer.call/3`, but it still crashes with:

```text
** (exit) exited in: GenServer.call(MyApp.Embeddings.TaskSupervisor, {:start_task, ...}, :infinity)
    ** (EXIT) no process: the process is not alive or there's no process currently associated with the given name
```

This happens when the supervisor isn't running — e.g. during `mix run priv/repo/seeds.exs`, `bin/app eval`, or release tasks where only `Repo` is started, not the full supervision tree.

**Cause:** `rescue` only catches **exceptions** (raised via `raise` or `throw`). A `GenServer.call` against a dead/no-process named supervisor **exits** the calling process with `{:noproc, _}` (or `{:noproc, _}` wrapped in `:EXIT`). Exits are not exceptions — they propagate as OTP exit signals, which `rescue` cannot intercept.

**Fix:** add a `catch` clause alongside the `rescue`:

```elixir
def schedule(%Page{} = page) do
  cond do
    not Inference.enabled?() -> :ignored
    not needs_embedding?(page) -> :ignored
    schedule_async?() ->
      Task.Supervisor.start_child(
        MyApp.Embeddings.TaskSupervisor,
        fn -> generate(page) end,
        restart: :transient
      )
      :ok
    true ->
      generate(page)
      :ok
  end
rescue
  _ -> :ignored      # catches raises (e.g. FunctionClauseError)
catch
  :exit, _ -> :ignored   # ← catches {:noproc, _} and other OTP exits
end
```

**General rule:** any time you call `GenServer.call`, `Task.Supervisor.start_child`, `Supervisor.start_child`, or `:gen_server.call` against a process that *might not be alive* (background tasks during seeds, release eval, partial app boot), a bare `rescue` will let the exit propagate and crash the caller. You need `catch :exit, _ -> ...` to swallow it. This is the Elixir/OTP equivalent of "exceptions vs. signals" — exits are signals, not exceptions.

**Diagnosis trick:** if you're unsure whether a failure is an exit or an exception, wrap the call in a `try` with both clauses and log which one fires:

```elixir
try do
  Task.Supervisor.start_child(MySup, fn -> :ok end)
catch
  kind, reason -> IO.inspect({kind, reason}, label: "caught")
  # :exit, {:noproc, _}  → supervisor not running
  # :error, %RuntimeError{} → a raise inside start_child
end
```

## Partitioned table migrations — raw SQL `ALTER TABLE` only

**Symptom:** `mix ecto.migrate` fails with:
```text
** (Postgrex.Error) ERROR 42P16 (feature_not_supported) cannot alter partitioned table "request_logs"
```

**Cause:** Postgres partitioned tables (RANGE, LIST, HASH) do not support standard DDL inside transactions. `alter table(:request_logs) do ... end` generates transactional DDL, which Postgres rejects for partitioned tables.

**Fix:** use `execute/1` with raw SQL and disable transaction/lock wrappers:

```elixir
defmodule MyApp.Repo.Migrations.AddColumnToPartitionedTable do
  use Ecto.Migration

  @disable_ddl_transaction true
  @disable_migration_lock true

  def up do
    execute "ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS client_agent VARCHAR(255)"
  end

  def down do
    execute "ALTER TABLE request_logs DROP COLUMN IF EXISTS client_agent"
  end
end
```

**Why `IF NOT EXISTS` / `IF EXISTS`:** partitioned table DDL runs outside a transaction, so there's no rollback on partial failure. Idempotent guards prevent duplicate-column errors on re-runs.

**Rule:** any `ALTER TABLE` on a partitioned table MUST use `execute "ALTER TABLE ..."` with `@disable_ddl_transaction true` and `@disable_migration_lock true`. Never use `alter table(:name) do ... end` for partitioned tables.

## `cond` does NOT support `<-` pattern matching — use `with` + helper

**Symptom:** `mix compile` fails with:
```text
error: expected one argument for "do" clauses (->) in "cond"
```

**Cause:** Elixir's `cond` evaluates clauses as boolean expressions (`condition -> result`). The `<-` operator is pattern matching, which only works in `case`, `with`, and `receive` — NOT in `cond`.

```elixir
# BROKEN — cond does not support <-
cond do
  [value | _] <- get_req_header(conn, "x-title"), byte_size(value) > 0 ->
    value
  true ->
    "default"
end

# FIX — use with + helper function
defp first_header(conn, name) do
  case get_req_header(conn, name) do
    [value | _] when byte_size(value) > 0 -> String.slice(value, 0, 255)
    _ -> :error
  end
end

def client_agent(conn) do
  with :error <- first_header(conn, "x-title"),
       :error <- first_header(conn, "user-agent"),
       :error <- first_header(conn, "x-agent-type") do
    "unknown"
  end
end
```

**Rule:** when you need pattern matching with fallback in a chain of attempts, use `with` + a helper that returns `:error` on miss. `cond` is for boolean guards only.

## Common signs you touched the wrong `priv`

- `relation "X" does not exist` after a successful-looking migration run
- `** (FileError) could not read file` for templates, migrations, or assets
- `priv/repo/migrations` is empty or missing files you know were there

Fix: restore `priv` from git, then reset the build tree:

```bash
git checkout -- apps/*/priv/
rm -rf _build
mix deps.get
mix compile
```

## Reference

See `references/phoenix-umbrella-priv-sync.md` for the mechanics of `_build` / `priv` synchronization.
See `references/ui-shows-zero-data-flow-tracing.md` for the data-flow tracing methodology when the UI shows 0/empty but the DB has data (assigns → component attr → template forwarding chain).
See `references/ecto-analytics-query-pitfalls.md` for Postgres rollup/aggregate query pitfalls: `fragment(^str)` compile error, `date_trunc` parameterized-unit grouping_error 42803, AVG/percentile_cont type instability (Decimal vs float), `Ecto.UUID.dump!` in raw SQL test inserts, time-truncated test fixtures (never `Map.put(:minute)` on raw `utc_now()`), and the sweep-line peak-concurrency estimation pattern.
