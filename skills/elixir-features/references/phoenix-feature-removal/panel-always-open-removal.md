# Panel-Always-Open Removal (toggle → always-on)

Variante de feature-removal donde un sub-panel dentro de una fila se renderiza
bajo un `:if={@some_id == X}` y un botón toggle. El usuario quiere eliminar el
toggle y dejar el panel siempre visible. Es más liviano que borrar un feature
entero pero sigue siendo multi-archivo (LiveView + handler + assign + test).

Caso real: `providers_live.ex` con un panel `<div id="credentials-panel-#{id}">`
que mostraba las credenciales de cada provider. Inicialmente gated por
`@credential_provider_id == provider.id` y un botón "Credenciales" con
`phx-click="manage_credentials"`.

## Blast radius (más pequeño que feature-removal completo)

| Capa | Qué buscar | Acción |
|------|------------|--------|
| **Template** | `<div :if={@some_id == ...}>` envolviendo el panel | Quitar el `:if` (panel siempre renderizado) |
| **Template** | Botón con `phx-click="toggle_X"` / `phx-click="manage_X"` que hacía toggle del panel | Quitar el botón completo (icono + texto + phx-click + phx-value-id + class + id) |
| **Mount** | `assign(:some_id, nil)` en el pipe de mount | Quitar la línea |
| **handle_event** | `def handle_event("manage_X", ...)` o `def handle_event("toggle_X", ...)` | Borrar el handler entero |
| **Tests** | Pasos que hacen `render_click` sobre el botón toggle antes de interactuar con el panel | Quitar el clic, reemplazar `assert has_element?` por la misma aserción directa sobre el id del panel |

**NO** requiere migración (no se toca la DB). **NO** requiere gettext sweep (no
se renombran strings). Es casi siempre < 30 líneas tocadas.

## Receta de ejecución (orden importa)

1. **Identificar el anchor**: la línea con el `:if` (en el template) o el
   handler. Sin anchor claro, escanear el módulo con `search_files` por los
   nombres del assign.
2. **Quitar el botón toggle** del template (incluyendo su icono).
3. **Quitar el `:if`** del panel (panel siempre abierto).
4. **Quitar el handler** correspondiente.
5. **Quitar el assign** de mount.
6. **Quitar la línea de `assign(:some_id, ...)`** del handler si quedó alguna.
7. **Actualizar tests**: donde antes había un `render_click` para abrir el
   panel, ahora `assert has_element?(view, "#panel-...")` directo.
8. Verificar con `search_files` que no quedan referencias al assign/handler
   removidos: `grep -rn "@some_id\|handle_X\|#toggle-X\|#manage-X" lib/ test/`.
9. `mix compile --warnings-as-errors` + test del LiveView + `mix precommit`.

## Pitfalls

- **Handler huérfano que llama a un módulo separado**: si el handler era
  `def handle_event("manage_X", p, s), do: SomeModule.handle_event(p, s)`,
  también necesitas quitar el `alias SomeModule` si no se usa en otro lado.
- **Test asertaba el id del botón**: `assert has_element?(view, "#toggle-X")`
  o `"#manage-X"` — esas aserciones se rompen. Reemplazar por el id del panel.
- **Orden importa para no romper el diff del LiveView**: si quitas el handler
  antes de quitar el botón, el compile pasa (handlers no referenciados no
  truenan). Pero al revés también. Sin embargo, si haces todo en un solo commit
  grande, deja el archivo en estado de "no compila" brevemente entre patches.
  Por eso: **un commit limpio por concern** — un commit que quita el botón +
  otro que limpia el handler, **o** un solo commit que toque los 4 puntos
  juntos si están todos en el mismo archivo.
- **Hay otro toggle similar en otro LiveView**: usa `search_files` global antes
  de empezar para no dejar inconsistencias (ej: 2 tablas con toggle, sólo
  quitamos 1). Si hay que replicar el cambio en N sitios, considera
  `execute_code` con regex en lugar de patch manual.

## Anti-pattern: NO capturar como "remove dead feature"

Panel-always-open **no es** dead feature removal — el panel sigue existiendo y
siendo interactivo. Es una transformación de UX: gated → always-on. El SKILL.md
de `phoenix-feature-removal` describe borrado completo; este variant es para
cuando el contenido sobrevive pero el toggle muere.

## Caso MyApp (referencia)

Commit `491b48d feat(providers): open credentials panel by default`:
- Quitado botón `<button phx-click="manage_credentials" id="credentials-#{id}">`
  (8 líneas con icono `hero-key` + texto).
- Quitado `:if={@credential_provider_id == provider.id}` del panel.
- Quitado handler `manage_credentials` (5 líneas).
- Quitado `assign(:credential_provider_id, nil)` del mount.
- Test actualizado: 1 línea cambió (clic → assert directo).
- Total: 2 archivos, 23 líneas, sin migración, sin gettext.
