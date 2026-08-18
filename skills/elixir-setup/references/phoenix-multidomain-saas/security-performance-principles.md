# Security & Performance Principles — distilled from my_app_gateway & my_app

These are the lessons already paid for in Álvaro's real projects. Bake them
into ANY new Elixir/Phoenix app from day 1 — they are not optional
refactors. Commit hashes are the receipts.

## Security

### Fail closed (my_app 09bb76a, SEC-001..SEC-012)
- Deleted/missing user → NOT admin (`nil` → denied), never the reverse.
- Failed context/tenant lookup → error/denied, never default-open.
- Mass assignment: whitelist of allowed fields on update; reject the rest.
- Admin-only plugs on Settings, Context CRUD, Export, Relation delete.
- Search resolve_context_id fails closed.
- **Rule:** nil/error/unknown → denied. In multi-tenant code, fail-open is a
  data leak.

### Rate limiting (my_app_gateway 885ca0c)
- Login POST per IP: ETS fixed-window, 10/min default.
- Counter cleared on successful login (don't punish the legitimate user).
- API keys: rate limit per token hash; webhooks: per source IP + signature.
- Invalid/missing keys are NEVER cached long — else the table becomes a
  brute-force growth vector.

### Session & secrets hygiene (my_app_gateway 19fcbf4, my_app SEC-005/008)
- Sliding expiration (`renew: true`) + 4h max_age (not 8h absolute).
- Session cookie: secure + httpOnly + SameSite lax.
- API token NEVER reaches the DOM: prefix-only + `push_event` copy.
- Mask credential names/key suffix for non-admins.
- Filter sensitive params from Phoenix logs (`filter_parameters`).
- Rotate/revoke keys with immediate ETS cache invalidation.

### Web hardening (my_app_gateway 885ca0c / 19fcbf4)
- CSP without `unsafe-inline` in script-src.
- Permissions-Policy header on browser pipeline.
- Plug.Parsers body caps: 10MB length, 1MB read_length.
- CSV formula injection: prefix `'` on values starting `= + - @` in exports.
- Audit log for sensitive admin actions (user create/update/delete, password
  reset, status toggle, credential create/update/toggle, resets).
- `mix_audit` in precommit — catches transitive CVEs (e.g. hackney < 4.0.1
  via tzdata).
- Kill upstream stream task on first-token timeout (prevents fd leak).

## Performance

### Hot path (my_app_gateway acd7491)
- ETS auth cache: token → identity + effective limits, 60s TTL. Postgres
  untouched on authenticated hot-path hits. Invalidate on key
  rotation/revocation and member/team/service edits. Invalid keys never
  cached.
- Batch queries: one `WHERE id IN (^ids) GROUP BY id` → map `{id => value}`,
  lookup in memory. Never per-item queries in a loop.
- Accumulate as iodata (list of binaries), not `binary <> acc` (O(n²)).
- SSE fast-path: forward chunks without Jason.decode unless the chunk
  contains a specific field; binary scan.
- `compress: true` on the endpoint — big JSON completions compress 5-10x.
- Finch pools: size 32 × count 2, conn_max_idle 60s, HTTP/2 preferred with
  HTTP/1.1 fallback.
- Composite indexes on log tables: `(foreign_key, inserted_at DESC)`.

### Routing / dashboard cache (my_app_gateway 19fcbf4)
- Routing.Cache ETS: per (alias, team) with 60s TTL + disabled-credentials
  set; invalidate on credential/model_provider writes.
- Metrics: fixed-bucket latency histogram with atomic `update_counter`
  (replaces racy read-modify-write lists).
- Debounce enqueues via ETS `insert_new` mark (1 job per burst, worker
  clears mark before sync).

### N+1 (my_app 09bb76a P-01..P-06; `n-plus-one-cookbook` concept in my_app)
- Fix by changing the helper SIGNATURE (receive data, not struct), not by
  adding preloads.
- `maybe_preload` with `Ecto.assoc_loaded?/1` in shared helpers.
- Search excerpt in the main query select (kills N+1 ts_headline).
- Pass preloaded %Context{} to avoid extra queries in list endpoints.
- Caps as defense: kanban 500 todos, wiki index 1000 pages.

### ETS cache — the critical lesson (my_app_gateway 31be8a7, memory)
- Named ETS tables of NEW GenServers do NOT exist on already-running nodes:
  the code_reloader does NOT restart the supervision tree.
- Modules touching named tables must degrade graceful: `whereis` guard +
  `rescue ArgumentError`.
- Cache = optimization, NEVER a hard dependency. An ApiKeyCache without a
  guard took down the whole proxy (31be8a7).
- `:public` + `read_concurrency: true`; reads go direct to ETS, only the
  miss constructs.
- Cache the cheap misses (`:not_found`) so repeated misses are cheap — but
  with short TTL and never for invalid-auth keys.

## Resilience

### Circuit breaker on every external integration
- States: closed → open (after N consecutive failures) → half-open (probe)
  → closed/open.
- In Elixir: GenServer per integration with atomic counters or ETS; or the
  `Fuse` / `FancyFlow` hex libs.
- Applies to: GHL, Systeme.io, WhatsApp/Telegram connectors, LLM providers.
- Timeout + kill stream task on first-token timeout (fd leak prevention).

## Source commits

- my_app_gateway `885ca0c` — security audit hardening (rate limiting, CSV, audit,
  masking, body caps, CSP).
- my_app_gateway `acd7491` — proxy hot path (ETS auth cache, Finch pools, SSE
  fast-path, compress).
- my_app_gateway `19fcbf4` — harden security + hot-path (sliding session, CSP,
  Routing.Cache, metrics, debounce, indexes, mix_audit).
- my_app_gateway `31be8a7` — never crash when ETS table missing (graceful).
- my_app `09bb76a` — security hardening SEC-001..012 + performance P-01..P-06.