# my_app security audit — Scope 2: API REST + MCP + controllers (Aug 2026)

Read-only audit of `lib/dran_web/controllers/api/*.ex`, `lib/my_app/mcp.ex`
(1746 lines), `controller_helpers.ex`, `graph_json/page/locale/health`
controllers, and `accounts/api_key.ex`, cross-verified against `router.ex`,
`plugs/auth.ex`, `accounts.ex`, schemas, and `brain.ex`. Executed as subagent
2 of 3 per the skill's fan-out playbook (spec file in /tmp, parent-verified
context excluded). Repo: `my_app` (Phoenix 1.8, LiveView, Ecto, pgvector).

## Headline finding — API-1 CRITICAL: MCP dispatch IDOR (skill category 1h)

Chain, all verified against real code:

1. `api/mcp_controller.ex:59-67` — `validate_context_access` reads only
   `conn.params["context"]` (top-level HTTP param). A standard JSON-RPC POST
   has no top-level "context", so the check falls back to the caller's
   default context → always `:ok`.
2. `mcp.ex:908-928` — `inject_user_context` only injects the default context
   when `arguments` LACKS "context"; a caller-supplied value is honored.
3. `mcp.ex:837-840` — `execute_tool(tool_name, args)`; the authenticated
   `user` is NEVER passed to any of the 18 tools. None revalidate.

Exploit: low-priv user token (contexts: [personal]) or single-context API
key → `tools/call dran_delete_page {"context":"work","slug":"x"}` deletes
cross-context. Also `resources/read` on `page://work/secret` (mcp.ex:1591).
The router comment "enforces per-user context access" was false.

Fix direction given: thread `user` into dispatch, validate effective context
per call, centralize in `process_message`; regression tests: user-A token +
arguments.context=B → error; key-A + `page://B/x` → error.

## Remaining findings (ID — severity — file:line — one-liner)

- API-2 high — `mcp.ex:1487-1509` — `dran_get_agent_session` takes only a
  session UUID; any token polls any session (input/summary/steps of another
  context). Not covered by a generic context-fix (no context in args) —
  must check `session.context_id ∈ user.contexts`.
- API-3 medium — `accounts/user.ex:11`, `accounts.ex:34-36` —
  `users.api_token` stored PLAINTEXT (DB lookup by token), while `ApiKey`
  in the same codebase does SHA-256 hash + prefix + never-persist-plaintext
  (`api_key.ex:48-55`). Migrate user tokens to the hash scheme.
- API-4 medium — `api/page_controller.ex:85` + `brain/page.ex:113-130` —
  REST update drops only `["slug","context"]`; changeset casts
  `:context_id, :owner, :created_by, :updated_by` → move pages across
  contexts, forge provenance (admin token only). MCP whitelists (clean).
- API-5 medium — zero rate limiting (`grep -ri 'hammer|plug_attack|throttle'`
  = 0 hits in mix.exs+lib). Unbounded token attempts on `/api/mcp`;
  unbounded LLM-cost endpoints (`dran_start_agent`, community summaries,
  semantic search) for any valid token.
- API-6 medium — `api/search_controller.ex:28,47,80`, `mcp.ex:1001,1480,1541`
  — `inspect(reason)` in client error bodies leaks internal inference-server
  URLs / Req-Mint structs / Postgrex detail to non-admin MCP callers (8f).
- API-7 low — `log_controller.ex:12`, `page_controller.ex:19`,
  `search_controller.ex:12,43,63` — `String.to_integer(params["limit"])` →
  ArgumentError → 500 on `?limit=abc` (should be 400).
- API-8 low — `todo_controller.ex:51`, `relation_controller.ex:65,68`,
  `exporter.ex:72` — `Repo.get` on `:binary_id` with non-UUID →
  `Ecto.Query.CastError` → 500. The correct `Ecto.UUID.cast` guard already
  exists elsewhere (`mcp.ex:1488`, `page_controller.ex:216`).
- API-9 low — `brain.ex:127-128` (list_pages no max), `brain.ex:2058`
  (list_log no max/offset), `exporter.ex:103-152` (full export = whole
  context + all versions in one in-memory JSON), negative limit/offset →
  Postgrex error even in MCP (`min(limit,500)` has no floor).
- API-10 low — `mcp.ex:837-839,857-858,876-878` — JSON-RPC `params` not a
  map → Access on binary/list raises → 500 instead of `-32602`.
- API-11 low — `relation_controller.ex:39-51` → `brain.ex:754-758` —
  create-by-IDs path doesn't check source/target share a context →
  cross-context relations break silo isolation (slug path is safe:
  `brain.ex:864-882`).
- API-12 low — `brain/page.ex` changeset lacks
  `foreign_key_constraint(:context_id)`; `page_controller.ex:202-228`
  passes through an unresolvable-but-valid UUID → FK violation → 500.
- API-13 info — `health_controller.ex:5-17` — public status+db+timestamp,
  no version. Acceptable; document.
- API-14 observation — `Accounts.valid_api_key?/1` is ONLY wired into the
  MCP controller (`mcp_controller.ex:46-48`); REST `:api_auth`
  (`router.ex:80-92`) accepts only the legacy admin token. Context-scoped
  keys don't exist for REST (and by API-1 don't scope in MCP either).

## Verified-good patterns (for future delta audits — skip unless touched)

- REST API rejects non-admin tokens: `require_api_token` legacy-only
  (`router.ex:80-92`). User tokens/API keys get 401 on `/api/*` REST.
- API keys: SHA-256 hash storage, prefix-only display, revocation honored,
  plaintext never persisted (`api_key.ex:9-16,48-58`; `accounts.ex:197-205`).
- MCP create/update whitelist attrs explicitly; `context_id` not updatable
  via MCP (`mcp.ex:1022-1035, 1059-1074`).
- Page changeset does NOT cast id/inserted_at/version/body_hash/embedding.
- FTS uses bound params with `plainto_tsquery` — no SQLi (`brain.ex:1642+`).
- Inference client has 30s `receive_timeout` + `auto` strategy degrades to
  FTS when backend down (`inference/client.ex:151`; `brain.ex:1597-1601`).
- MCP limit caps: `min(limit,100)` search / `min(limit,500)` list.
- `report` page type not creatable via MCP (`page_types.ex:30-38`).
- Locale whitelist `["en","es"]`; redirect uses parsed path only (no open
  redirect). `graph_json` takes context from session only, behind
  `[:browser, :auth]` — depends on `POST /context` validating membership
  (other subagent's scope).
- `Plug.Parsers length: 2_000_000` body cap (`endpoint.ex:61-69`).
- `User` schema has no `@derive Jason.Encoder` — api_token never serialized.

## Session notes

- The fan-out spec-file playbook worked as documented: parent supplied
  /tmp spec with "already verified, don't re-audit" list (router pipeline
  facts, non-timing-safe admin token comparison, admin-token-full-access
  design decision). Zero duplicated work.
- `od -c` was needed once: rendered output stripped a `#{key.name}`
  interpolation in `mcp_controller.ex:48`, making the synthetic API-key
  identity look syntactically impossible; raw bytes confirmed the real
  shape (`%{is_admin: false, email: "api-key:#{key.name}", contexts: [key.context]}`).
