# Ejemplo trabajado: revisión del plan my_app (fundación umbrella)

Revisión del plan `my_app-fundacion-umbrella` (9 todos originales + 5 gaps) contra las decisiones D1-D20. Sirve como checklist concreto de cómo se ve cada clase de drift.

## Fuentes de verdad leídas

- Project `my_app` + plan + todos (get_page de cada uno)
- Conceptos vinculados: `my_app-arquitectura-decisiones` (D1-D20 + esquemas), `my_app-seguridad-inicio`, `my_app-performance-inicio`, `feature-flags`

## Hallazgos por clase de drift

| Clase | Ejemplo concreto | Fix |
|---|---|---|
| Hashing | auth-portal usaba `Bcrypt.verify_pass`/`no_user_verify`; auth-communities usaba `Comeonin.Argon2.hashpwd`; D7 = Argon2 | Unificar en `Argon2` (`hash_pwd_salt`/`verify_pass`/`no_user_verify`) |
| Campo schema vs código | schema `Member.community_role` vs código `role` | Usar `community_role` |
| Status padre vs hijo | resolucion-dominios ramificaba `%Domain{status: :suspended...}` — pero Domain es solo active/blocked; suspended/deleted/maintenance/draft son del RECURSO community/landing | Ramificar por status del recurso resuelto vía `target_id` |
| Tipo de ID | `is_integer(member_id)` vs binary_id (UUID string) | `is_binary` + validar por binary_id |
| Artefacto duplicado | `feature_flags` creada en modelo-datos (010) Y re-creada en feature-flags-i18n con schema distinto (`scope` vs D17 `target_type/target_id/meta`) | No re-crear; usar la del modelo de datos |
| otp_app inexistente | Gettext `otp_app: :my_app` — no existe app `:my_app` (raíz del umbrella) | `otp_app: :core` |
| Namespace | Mezcla `my_app.*` (core), `AceleraWeb.*` (dominios/flags) y `PortalWeb.*` (auth-portal); D11 = plugs en core | Plugs en `my_app.Plugs.*`; routers por app (CommunitiesWeb/LandingsWeb) |
| Prerrequisito faltante | `MIX_ENV=prod mix release` en verificacion sin sección `releases:` en mix.exs | Todo `my_app-release-infra` |
| Umbral inconsistente | Rate limit 10/min (seguridad) vs ">100 requests" en verificacion | 10/min |
| Flags sensibles a env | `secure: true` en cookie rompe localhost dev | `secure: config_env() == :prod` |
| Roles mal mapeados | `RequireRole` matcheaba `org_role in [:manager, :admin]` — pero org_role es (owner/collaborator); manager/admin son platform_role | Separar platform_role vs org_role |

## Gaps (decisión referenciada, sin todo)

- D19 telemetría — en deliverable y gotcha, sin todo → `my_app-telemetria` (nuevo)
- Email/confirmación/password reset (`confirmed_at` existe, sin mailer) → `my_app-email-flows` (nuevo)
- D20 sesiones concurrentes (schema `sessions` existe, sin lógica) → `my_app-sesiones-concurrentes` (nuevo)
- D15 bin/migrate → `my_app-release-infra` (nuevo)
- D16 seeds prod → `my_app-seeds-prod` (nuevo)

## Higiene

- 9 todos estaban en `in_progress` a la vez (auto-move al crear) con plan "pendiente de aprobación" → reset a `backlog`.

## Quirks de herramientas my_app (descubiertos)

- `dran_create_todo` requiere `slug` (la recipe del skill my_app no lo lista).
- `dran_list_pages` con `project_slug` + `status` combinados devolvió TODOS los todos para `status: done` (filtro ignorado en combinación); sin project_slug el filtro de status sí funcionó. Verificar con query sin project_slug.
- get_page añade footer `--- Type: ... | Tags: ... | Version: N` que NO es parte del body — no incluirlo al reconstruir.
- Contexto del perfil default: `personal` (los contextos alvaro/engineering/my_business son del perfil my_business-cto).
