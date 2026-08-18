# Concept pages LLM Proxy/Gateway — ejemplo MyApp (2026)

Resultado de documentar los conceptos técnicos de MyApp como concept pages
en my_app (context `personal`): 14 concept pages, todas `part_of` al project
`MyApp` y a su plan, + 20 relations `related` a todos existentes y entre
concepts. Reutilizable para re-crear, extender, o documentar otro gateway.

## Workflow (lecciones de Álvaro)

- **Conceptos GENERALES del dominio, no app-specific.** Álvaro lo corrigió
  explícitamente: "hay conceptos muy de las apps me refiero a los generales".
  Los concept pages son conocimiento reutilizable (circuit breaker, sticky
  routing, OTLP, OAuth), NO detalles de implementación (model_type, timezone
  periods, buckets ETS) — esos van como notas dentro de los todos.
- **Escanear TODOS los todos del project**, no solo el código core: features
  tipo embeddings/rerank u OAuth se escapan si solo miras los módulos de
  routing. Cada todo existente es un candidato a concept page.
- **Presentar la tabla antes de crear** (bajada, 3 columnas: concepto / para
  qué / plan) y clarificar alcance — Álvaro decide el set final.
- **Verificar con `dran_get_links` en el project** (inbound `part_of` de todos
  los concepts) antes de reportar.

## Los 14 concept pages (slug → plan)

| Slug | Plan |
|------|------|
| api-gateway-openai-compatible | MyApp-core-proxy |
| multi-provider-routing-fallback | MyApp-core-proxy |
| sticky-routing | MyApp-core-proxy |
| circuit-breaker | MyApp-core-proxy |
| prompt-caching | MyApp-core-proxy |
| streaming-sse | MyApp-core-proxy |
| rate-limiting | MyApp-core-proxy |
| embeddings-rerank-apis | MyApp-core-proxy |
| cost-accounting | MyApp-multitenant-budgets |
| budgets-quotas | MyApp-multitenant-budgets |
| multi-tenancy-rbac | MyApp-multitenant-budgets |
| model-abstraction-aliases | MyApp-multitenant-budgets |
| oauth-google | MyApp-multitenant-budgets |
| observabilidad-otlp | MyApp-observabilidad-dashboard |

## Meta de cada concept page

`page_type: "concept"`, `context: "personal"`, `owner: "alvaro"`,
`created_by: "agent"`, `meta: {kind, domain, project_slug, plan_slug}`.
Los `project_slug`/`plan_slug` en meta materializan `part_of` automáticamente.

## Body estándar

`## Qué es` / `## Cómo se aplica en <proyecto>` (módulos reales del repo) /
`## Por qué importa` / `## Fuentes` (2-3 URLs primarias).

## Fuentes primarias clave

- OpenRouter docs: prompt caching + provider sticky routing + broadcast OTLP webhook
- Azure Architecture Center: circuit-breaker pattern
- OpenAI developers: streaming responses (SSE)
- arXiv 2601.06007 "Don't Break the Cache": prompt caching en tareas agentic
- WorkOS + medium: multi-tenant RBAC
- Google Cloud: ranking/rerank API; Google OAuth 2.0 + OIDC
- Lunar.dev / runcycles: API consumption/quota management
- TrueFoundry "AI Gateway Series": routing, model coverage, fallback chains
