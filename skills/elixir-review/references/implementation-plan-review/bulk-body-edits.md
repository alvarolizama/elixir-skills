# Bulk body edits en my_app vía REST (método probado)

Para aplicar fixes de 3+ páginas del plan/todos: edición por anchors sobre el body exacto vía REST, en vez de reconstruir bodies a mano o editar página por página con `dran_update_page`.

## Por qué no MCP tool calls

- `dran_update_page` REEMPLAZA el body entero — con 5+ páginas es lento y cada call es un riesgo de perder contenido.
- Pasar meta+body juntos: TipTap re-parsea y strippea bloques mermaid.
- El PUT REST con solo `body` preserva meta (whitelist del controller: title/body/tags/meta/summary/archived/kb_*) y evita el re-parseo del editor.

## Receta paso a paso

### 1. Auth

Token del MCP en `~/.hermes/config.yaml` → `mcp_servers.my_app.headers.Authorization` (valor `Bearer <token>`). Base URL: la url del MCP sin `/api/mcp` (ej `http://local-apps.vpn.cloud:4000`).

### 2. Fetch exacto de bodies

`GET /api/pages/:slug?context=<ctx>&include=body` — sin `include=body` el GET devuelve `body: null` (metadata only). Guardar cada body a disco (`bodies/<slug>.md`). El sha256 local debe coincidir con el `body_hash` del response (sanity).

### 3. Ediciones por anchor

Estructura: `EDITS = { slug: [(old, new), ...] }`. Reglas:

- `old` debe aparecer **EXACTAMENTE 1 vez** en el body o la página se skippea entera — nunca PUT parcial (dejaría la página a medias).
- Los bodies reales difieren de lo que `get_page` muestra:
  - mermaid: el rendering de get_page muestra `\n` literal pero el body guardado puede tener newlines reales (o viceversa según el editor que la creó).
  - texto exacto de snippets: verificar SIEMPRE contra los bytes del body fetchado (grep/sed) antes de escribir el anchor.
- Ante mismatch, diagnóstico: búsqueda binaria del prefijo más largo de `old` que SÍ está en el body → el byte siguiente revela la diferencia.

### 4. PUT body-only

`PUT /api/pages/:slug?context=<ctx>` con JSON `{"body": "<nuevo>"}`. El controller hace `Map.take` de campos whitelist — meta NO se toca.

### 5. Verificación

- Tras cada PUT: GET metadata y comprobar `sha256(body_enviado) == body_hash` devuelto.
- Ronda final: por página, fetch de nuevo y confirmar needles de cada fix (strings que DEBEN estar presentes) + count de bloques ` ```mermaid ` intacto vs original.

## Resultados reales (sesión my_app)

- 11 páginas, 48 ediciones aplicadas; 9/11 pasaron a la primera, 2 fallaron por anchors con formato distinto (`IF NOT EXISTS` vs `IF EXISTS`, `\n` literal vs newline real) y se resolvieron con anchors corregidos. Cero contenido perdido, cero mermaid dañado, meta intacta (verificado por hash + versión).
