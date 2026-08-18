# my_app scope-3 audit (Aug 2026) — Contextos, schemas, config, secretos y performance

Third and final scope of the combined my_app audit (subagent 3 of 3, read-only).
Scope: `lib/my_app/**` contexts + schemas, `priv/repo/migrations/`,
`config/{config,prod,dev}.exs`, `mix.exs`. Web layer (LiveViews/controllers)
was scopes 1-2. 19 findings (1 crítico, 2 altos, 8 medios, 8 bajos), report
delivered in Spanish with CTX-N IDs.

## Headline findings (verified against code)

### CTX-1 CRÍTICO — `@api_token System.get_env("DRAN_API_TOKEN", "my_app-token")` (auth.ex:18)
Compile-time module attribute: release baked without the env var ships the
public default admin bearer, and setting the var at RUNTIME does nothing
(runtime.exs never references DRAN_API_TOKEN — verified). Same class as
SKILL.md 10b (already documented); the new wrinkles: `valid_token?` compares
with `==` (timing oracle → `Plug.Crypto.secure_compare/2`), and the in-app
docs (`docs_live.ex:833`) tell operators to "change DRAN_API_TOKEN in
production", which is actively misleading under compile-time freezing.

### CTX-2 ALTO — Uploads served from app origin with active extensions (uploads.ex:89-91 + dran_web.ex:20)
`valid_extensions()` includes `svg, html, js, ts`; `ext_from_mime/1` also maps
`image/svg+xml`. Files are content-addressed (sha256 path) but served by
`Plug.Static` BEFORE the router → no auth/authz at all, and with real MIME
(`text/html`, `image/svg+xml`) from the SAME origin → stored XSS that can
drive the whole app via authenticated fetch (http_only cookie doesn't help).
No magic-byte sniffing; extension and `client_type` are client-controlled.
Fix: drop active extensions, validate magic bytes, serve
`Content-Disposition: attachment` + `nosniff` or from a separate origin.

### CTX-3 ALTO — `users.api_token` plaintext (user.ex:11, accounts.ex:34-36)
Full-access per-user token stored raw (`Repo.get_by(User, api_token: token)`)
while the sibling `api_keys` table does it right (SHA-256 `token_hash` +
`token_prefix` + virtual token, api_key.ex:24-58). The coexistence of both
models in one codebase is the tell — the secure pattern was already invented
there, just not applied to users.

### CTX-4 MEDIO — LIKE built from an unvalidated slug (page.ex:131-133 + brain.ex:2203)
`Page.changeset` validates slug only by length. `rename_slug/2` interpolates
the stored slug into `like(p.body, ^"%![[#{old_slug}%")`. A slug containing
`%`/`_` (writable via API/MCP) over-selects pages for the rewrite cascade
(version bump + snapshot + log + broadcast + re-embed on unrelated pages).
The rewrite itself is safe (`Regex.escape` at brain.ex:2252) — impact is
churn/DoS, not SQLi. Stored-input variant of 8d: the wildcard vector is a DB
field lacking `validate_format`, not request params.

### CTX-5 MEDIO — privileged fields in changeset cast (user.ex:26-38)
`User.changeset` casts `:is_admin` and `:api_token`. All CURRENT callers pass
fixed maps (settings_live.ex:127, session_controller.ex:49, accounts.ex:90-94 —
verified), so it's latent, not live: one future caller passing raw params =
priv-esc. Fix: strip from cast, set via `Ecto.Changeset.change/2` or an
admin-only changeset.

### CTX-7 MEDIO — N+1 excerpts in FTS (brain.ex:1662-1676)
`Enum.map(results, fn page -> Repo.one(ts_headline...) end)` = 1+N queries
per search (21 default, 51 via hybrid limit 50). Aggravates the parent's
pool finding (pool_size 10, no `queue_target`/`statement_timeout`): search
bursts starve the pool. Fix: `ts_headline` in the main query's `select`.

### CTX-8 MEDIO — unbounded task fan-out (embeddings.ex:157-175)
Backfill spawns one `Task.Supervisor.start_child` per page in `Enum.each` —
no `Task.async_stream`/`max_concurrency`. Same pattern per save:
`Embeddings.schedule/1` + `PageAugmenter.schedule/1` fire 2 tasks per
create/update (brain.ex:506-507, 604-605) → import of N pages = 2N tasks
hitting the inference queue and DB.

### CTX-11 MEDIO — cascading side-effect amplification (brain.ex:1148-1331)
One todo status change → `update_page` (snapshot+log+broadcast+embed) →
`sync_todo_links` → `recompute_goal_progress` → ANOTHER full `update_page`
on the goal → `recompute_project_health` → TWO more `update_page_meta_field`
calls (brain.ex:1245-1246). 3-4 full write cycles + full-struct PubSub
broadcasts per single user edit. The codebase already knows the fix pattern:
`Graph.refresh_pagerank` uses `Repo.update_all` + jsonb merge precisely to
avoid these side effects (graph.ex:150-167).

### CTX-6/9 MEDIO — unbounded loads
`brain_log` is append-only with zero retention; `Journey.timeline/1` loads
ALL `page.create` rows into memory (journey.ex:34-41). `graph_data/2` with
`max_nodes: nil` (the DEFAULT) loads every page; only the one real caller
(GraphCache, graph_cache.ex:186) passes 400. `list_tags/1` flattens all tags
in memory.

### CTX-10 MEDIO — LiveView `signing_salt: "kfcD1Wtl"` (config.exs:23)
Hardcoded, committed, and NOT overridden anywhere (runtime.exs enforces
SECRET_KEY_BASE + SESSION_* salts but not this one). Sibling gap to 8e.

## Verified-good patterns (worth citing in future audits)
- Inference provider API key ONLY in env (`DRAN_INFERENCE_API_KEY`), never in
  DB; Settings UI renders it as a boolean mask (`if Config.api_key(), do:
  "••••••••"` — settings_live.ex:813); `settings` table holds no secrets.
- `api_keys`: SHA-256 hash + prefix + virtual plaintext field; unique index
  on `token_hash` (migration 20260805034223).
- All fragments/params parameterized; recursive CTE via `$1::uuid` +
  `Ecto.UUID.dump!` (brain.ex:1103).
- Agents: `execute_tool` whitelists with `{:error, :unknown_tool}` fallback,
  hard per-session caps (curation_agent 20, gardener 10 + relation-type whitelist,
  graph_rag_agent 10/5/3/1), no shell/eval anywhere (only `Code.eval_file` of the
  app's own seeds in release.ex:99).
- `String.to_atom(key)` in smart_collection.ex:95 is SAFE: iterates a fixed
  module-level list `~w(type tag status owner created_by due_before
  due_after)` (line 89) — matches the safe arm of SKILL.md 10a.
- No SSRF: the only outbound HTTP is the inference client against env-config
  `base_url`; page `source_url` fields are stored, never fetched.
- Migrations: unique indexes on users(email/google_id/api_token),
  pages(context_id,slug), relations(source,target,type), page_versions
  (page_id,version); concurrent expression indexes on hot JSONB meta keys.
- runtime.exs raises in prod when SECRET_KEY_BASE / SESSION_*_SALT missing.
