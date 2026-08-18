# Tool Catalog — Elixir Dev Bridge

67 tools across 6 categories, organized by the 3-layer architecture.

## Layer 1 — Mix & Build (13 tools)

Tidewave has NONE of these. These work via the `mix` CLI, don't need
the app running, and are always available.

| Tool | What it does | Implementation |
|------|-------------|----------------|
| `elixir_compile` | Compile with `--warnings-as-errors`, parse warnings to `{file, line, msg}` | `mix compile --warnings-as-errors` |
| `elixir_test` | Run all tests, parse ExUnit output to `{module, test, status, time, file:line}` | `mix test --trace` |
| `elixir_test_file` | Run tests of a specific file or `module:test` | `mix test path/to/file_test.exs` |
| `elixir_test_line` | Run a specific test by `path:line` | `mix test path/to/file_test.exs:42` |
| `elixir_mix_task` | Run any mix task, capture stdout/stderr | `mix task_name args` |
| `elixir_format` | Run `mix format`, return diff of changes | `mix format --check-formatted` |
| `elixir_deps_tree` | Dependency tree from `mix.lock` | `mix deps.tree` or parse mix.lock |
| `elixir_deps_outdated` | `mix deps.outdated` parsed | `mix deps.outdated --format=json` |
| `elixir_credo` | Run Credo linter, parse suggestions | `mix credo --strict` |
| `elixir_dialyzer` | Run Dialyzer, parse type warnings | `mix dialyzer` |
| `elixir_sobelow` | Security audit of deps, parse vulnerabilities | `mix sobelow` |
| `elixir_coverage` | Run tests with `--cover`, parse report | `mix test --cover` |
| `elixir_release` | `mix release`, capture output | `mix release` |

## Layer 2 — BEAM Runtime (21 tools)

These need a connection to the running BEAM (remsh or MCP HTTP).
Tidewave has ~7 of these; the rest are new.

### Core (shared with Tidewave)

| Tool | Tidewave | Extools |
|------|----------|---------|
| `elixir_eval` | ✅ `project_eval` | ✅ |
| `elixir_execute_sql` | ✅ `execute_sql_query` | ✅ |
| `elixir_get_docs` | ✅ `get_docs` | ✅ |
| `elixir_get_logs` | ✅ `get_logs` | ✅ |
| `elixir_source_location` | ✅ `get_source_location` | ✅ |
| `elixir_get_schemas` | ✅ `get_ecto_schemas` | ✅ |
| `elixir_process_info` | ✅ `get_process_info` | ✅ |

### New runtime tools (Tidewave doesn't have)

| Tool | What it does | Implementation |
|------|-------------|----------------|
| `elixir_ets_inspect` | List ETS tables, see content, size | `:ets.all()` + `:ets.info/1` |
| `elixir_supervision_tree` | Full supervision tree with states | `Supervisor.which_children/1` recursive |
| `elixir_app_state` | `:sys.get_state` of named processes | `:sys.get_state/1` |
| `elixir_named_processes` | All registered processes (Registry, :gproc, atoms) | `Process.registered/0` + Registry |
| `elixir_memory_report` | Memory by process, ETS, binary heap | `:erlang.process_info/2` |
| `elixir_scheduler_utilization` | `:scheduler.utilization()` — BEAM load | `:scheduler.utilization/1` |
| `elixir_trace_function` | Trace calls to a function with `:dbg` | `:dbg.tp/2` |
| `elixir_trace_pattern` | Trace with pattern matching on args | `:dbg.tp/3` with match spec |
| `elixir_crash_history` | Processes that crashed recently | `:error_logger` history |
| `elixir_message_queue` | Message queue of a process — detect bottlenecks | `Process.info(pid, :message_queue_len)` |
| `elixir_port_info` | Inspect ports (external connections, FDs) | `Port.list()` + `:erlang.port_info/1` |
| `elixir_code_reload` | Reload a specific module without full restart | `:code.purge/1` + `:code.load_file/1` |
| `elixir_config_dump` | Runtime config of the app | `Application.get_all_env/1` |
| `elixir_running_apps` | `Application.started_applications()` | `Application.started_applications/0` |

## Ecto / DB (9 tools)

| Tool | What it does |
|------|-------------|
| `elixir_execute_sql` | Direct SQL (like Tidewave) |
| `elixir_get_schemas` | List schemas (like Tidewave) |
| `elixir_migration_status` | `mix ecto.migrations` parsed — which migrations applied |
| `elixir_migration_list` | List migration files with timestamps |
| `elixir_repo_config` | Repo config (pool size, timeout, DB url) |
| `elixir_query_plan` | `EXPLAIN ANALYZE` of a query — execution plan |
| `elixir_table_structure` | `\d table_name` — table structure |
| `elixir_foreign_keys` | Map of foreign keys between tables |
| `elixir_schema_assocs` | Map of schema associations (has_many, belongs_to, etc.) |

## Phoenix (6 tools, if present)

| Tool | What it does |
|------|-------------|
| `elixir_get_routes` | All Phoenix routes via `Phoenix.Router.routes()` |
| `elixir_get_liveview_routes` | LiveView routes with module and action |
| `elixir_liveview_state` | State of an active LiveView (assigns) |
| `elixir_socket_handlers` | List of channel/socket handlers |
| `elixir_plug_pipeline` | Plug pipeline of an endpoint |
| `elixir_endpoint_info` | Endpoint config (port, host, debug?) |

## Integrations (7 tools, auto-detected if dep exists)

| Tool | Dep | What it does |
|------|-----|-------------|
| `elixir_oban_jobs` | `oban` | Queue state, in-progress jobs, failed jobs |
| `elixir_oban_retry` | `oban` | Retry a failed job |
| `elixir_absinthe_schema` | `absinthe` | List queries/mutations/subscriptions |
| `elixir_ash_resources` | `ash` | List Ash resources (Tidewave has this) |
| `elixir_broadway_pipeline` | `broadway` | State of Broadway pipelines |
| `elixir_gen_stage` | `gen_stage` | State of GenStage producers/consumers |
| `elixir_horde_members` | `horde` | Members of Horde cluster |
| `elixir_fly_regions` | `fly` | Active regions (if running on Fly.io) |

## Layer 3 — Filesystem & Git (11 tools)

Only the Hermes plugin can do these — the MCP server inside the BEAM
can't see the filesystem.

| Tool | What it does | Implementation |
|------|-------------|----------------|
| `elixir_project_info` | Structure: umbrella?, apps, deps, moduledocs | Parse mix.exs + mix.lock |
| `elixir_git_blame` | `git blame` of a file, parsed | `git blame --line-porcelain` |
| `elixir_git_diff` | `git diff` of project, formatted | `git diff` |
| `elixir_git_log` | Commit history affecting Elixir files | `git log --oneline -- '*.ex*'` |
| `elixir_changed_modules` | Modules changed since last commit | `git diff --name-only` → map to modules |
| `elixir_diff_tests` | Run only tests for changed files | git diff → test file mapping → `mix test` |
| `elixir_module_graph` | Module dependency graph (who imports whom) | `mix xref` or parse compile graph |
| `elixir_behaviours` | List behaviours and implementations | `:beam_lib.chunks/2` |
| `elixir_protocols` | List protocols and implementations | `@derive`, `defimpl` scan |
| `elixir_macros` | List macros exported by a module | `Module.__info__(:macros)` |
| `elixir_module_functions` | All functions of a module with arities | `module.__info__(:functions)` |

## Summary

| Layer | Count |
|-------|-------|
| Layer 1 — Mix/Build | 13 |
| Layer 2 — BEAM Runtime | 21 |
| Ecto/DB | 9 |
| Phoenix | 6 |
| Integrations | 7 |
| Layer 3 — FS/Git/Static | 11 |
| **Total** | **67** |

Tidewave has ~10 tools. This architecture provides 67 across 6 categories,
covering static analysis, build, runtime introspection, and git history.
