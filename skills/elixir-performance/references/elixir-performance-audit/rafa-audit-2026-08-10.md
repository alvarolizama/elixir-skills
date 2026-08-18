# Rafa Audit — 2026-08-10 (against my_app `engineering` glosario)

Repo: `/Users/alvaro/Workspace/Repos/my_org/rafa` (Elixir/Phoenix, NOT umbrella)
Baseline: `glosario-performance-y-seguridad-elixir-phoenix` + 6 sub-pages in my_app `engineering` context
Status: **read-only audit** — no tracks created yet, user deciding on track split

## Findings mapped to glosario rules

### 🔴 Critical — Security

| # | Finding | Glosario rule | Evidence |
|---|---------|---------------|----------|
| 1 | Admin LiveViews without auth | seguridad #6 | `lib/rafa_web/router.ex:57-67` — `live_session :admin` uses only `pipe_through :browser`, no `:require_auth` / `:require_admin`. Routes: `/admin/agents`, `/admin/skills`, `/admin/objectives`, `/admin/chat/:agent_id` |
| 2 | ApiAuth timing + no scope enforcement | seguridad #4 | `lib/rafa/api_keys.ex:18-32` — `Repo.get_by(key_hash: hash)` timing-leaks valid hashes; `ApiKey.scopes` column exists but never read; `lib/rafa_web/plugs/api_auth.ex` has no scope check. No `read < write < admin` hierarchy. |
| 3 | RateLimiter ETS without GenServer + race | cache anti-patrón #4 | `lib/rafa/rate_limiter.ex:10-24` — `:ets.new` called from `Rafa.Application.start/2` (orphan risk). `check/1` does `lookup` then `insert` non-atomically → double-count under concurrency. Fix: `:ets.update_counter/4`. |
| 4 | OutputScanner phone regex false positives | web-hardening | `lib/rafa/security/output_scanner.ex:10` — `@phone_regex ~r/\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b/` matches version strings, IDs, CC fragments. Will mask non-PII and train operators to ignore alerts. |

### 🟠 High — Performance

| # | Finding | Glosario rule | Evidence |
|---|---------|---------------|----------|
| 5 | `ApiKeys.validate` 2 queries/request | hot-path | `lib/rafa/api_keys.ex:20-32` — SELECT + `update_last_used` UPDATE per request. Should use ETS cache (TTL 60s) like Hub's `Contexts.ApiTokens.Cache` (TRACKER-TRAC-170560), async write for `last_used_at`. |
| 6 | SystemPromptCache ETS without GenServer / no graceful degradation | cache regla oro #1, anti-patrón #4 | `lib/rafa/runtime/system_prompt_cache.ex:32` — `:ets.lookup(@table, ...)` raises `ArgumentError` if table missing (hot-reload, test). No `whereis` guard. Table created in `Application.start`, not GenServer. |
| 7 | ReAct loop re-fetches history every step | n+1 cookbook | `lib/rafa/runtime/llm_runtime.ex:178` — `Rafa.Agents.list_messages_for_llm(session_id)` inside `do_run_loop`; with `max_steps: 10` that's 10 queries per chat. Needs `(session_id, inserted_at DESC)` index + consider incremental fetch. |
| 8 | Canary generated but never checked | sesiones/secretos | `lib/rafa/runtime/prompt_builder.ex:99-100` — `Canary.generate()` + `prompt_clause/1` inject canary into prompt, but `Rafa.Security.Canary.check/2` never called on response path. Token is decoration. |

### 🟡 Medium — Web hardening

| # | Finding | Glosario rule | Evidence |
|---|---------|---------------|----------|
| 9 | No body caps on Plug.Parsers | web-hardening | `lib/rafa_web/endpoint.ex:50-53` — `plug Plug.Parsers, parsers: [:urlencoded, :multipart, :json]` without `length:` / `read_length:`. One-line fix: `length: 10_000_000, read_length: 1_000_000`. |
| 10 | No CSP header | web-hardening | Router has `put_secure_browser_headers` only. Admin LiveViews serve user content; need explicit CSP without `unsafe-inline`. |
| 11 | `mix_audit` not in precommit | web-hardening | `mix.exs` aliases — verify `precommit` includes `mix audit`. |

## Track split recommendation (proposed to user)

- **Track A (security)**: findings 1, 2, 4 (+ optionally 9, 10, 11 as checklist)
- **Track B (performance)**: findings 3, 5, 6, 7, 8

Quick wins (1-2h each): #3 (GenServer + `update_counter`), #5 (ETS cache), #8 (wire canary check), #9 (one-line config).

## Repo structure notes (for future audits)

- `lib/rafa/` — contexts: `agents`, `api_keys`, `memory`, `objectives`, `observability`, `runtime`, `security`, `skills`, `tools`, `integrations`
- `lib/rafa_web/` — `api/`, `controllers/`, `live/{agent,chat,objective,skill}_live/`, `plugs/{api_auth,rate_limiter}.ex`
- Runtime: `Rafa.Runtime.LlmRuntime` (ReAct loop), `Rafa.Runtime.PromptBuilder` (3-tier prompt: stable/context/volatile + canary), `Rafa.Runtime.SystemPromptCache` (ETS)
- Security: `Rafa.Security.{ApprovalRequest, Canary, OutputScanner, PermissionGate, PromptScanner}`
- Auth: API key (SHA-256 hashed) → `RafaWeb.Plugs.ApiAuth` → `RafaWeb.Plugs.RateLimiter` (ETS sliding window, 60 req/min default)
- LLM client: `Rafa.Integrations.my_app_gateway` (configurable via `Application.get_env(:rafa, :llm_client, ...)`)
- Recent perf work: TRACKER-TRAC-876660 (parallel tools, DB indexes, ETS cleanup) merged 2026-08; LLM layers switched to `deepseek-v4-flash` (commit `17d6f34`)
