# Graph query pitfalls — my_app (2026-12 session)

Detailed code comparisons behind fixes 6-8 in `liveview-data-performance`.

## 6. Cap edges: problema y fix

**Problema:** `Brain.graph_data/2` capa nodos (`max_nodes: 400`) pero NO edges. 400 nodos en un cluster denso pueden generar 4000-8000 edges → JSON payload inflado (800KB+) + 3D render lento.

**Fix:** `order_by: [desc: r.weight]` + `limit: @max_graph_edges` (2500). Las relaciones estructurales (`part_of` 1.0, `embeds` 0.8) sobreviven; las semánticas (`semantic` 0.1) se van primero.

```elixir
# BEFORE — sin cap
edges = Repo.all(
  from r in Relation,
    where: r.source_id in ^node_ids and r.target_id in ^node_ids,
    select: %{source: r.source_id, target: r.target_id, type: r.relation_type, weight: r.weight}
)

# AFTER — cap por weight
@max_graph_edges 2500

edges = Repo.all(
  from r in Relation,
    where: r.source_id in ^node_ids and r.target_id in ^node_ids,
    order_by: [desc: r.weight],
    limit: @max_graph_edges,
    select: %{source: r.source_id, target: r.target_id, type: r.relation_type, weight: r.weight}
)
```

Archivo: `lib/my_app/brain.ex` → `graph_data/2`, ~line 1415

---

## 7. top_connected_ids: problema y fix

**Problema:** `top_connected_ids/3` carga TODOS los pares `(source_id, target_id)` del contexto en RAM con `Repo.all(pairs)`, luego `Enum.frequencies()`, `Enum.sort_by()`, y `Enum.take(limit)`. Con 50k relaciones es ~800KB en RAM y ~50ms. Con 500k es ~8MB y ~400ms, bloqueando el controller.

**Fix:** Dos queries con `GROUP BY` + `count` que devuelven solo per-page degree, combinados en Elixir con `Map.merge`. El filtro `exclude_types` se aplica en ambos queries — solo relaciones cuyos AMBOS endpoints son non-excluded cuentan para el degree, igual que el código original. Alternativa: SQL puro con UNION ALL (más eficiente pero más complejo de leer).

```elixir
# BEFORE — carga todos los pares source-target en RAM
defp top_connected_ids(context_id, exclude_types, limit) do
  pairs = from r in Relation,
    join: s in assoc(r, :source), join: t in assoc(r, :target),
    where: s.context_id == ^context_id and t.context_id == ^context_id,
    select: {r.source_id, r.target_id}

  pairs = if exclude_types == [], do: pairs,
    else: from([r, s, t] in pairs,
      where: s.page_type not in ^exclude_types and t.page_type not in ^exclude_types)

  relations = Repo.all(pairs)  # ← TODOS los pares en RAM

  (Enum.map(relations, &elem(&1, 0)) ++ Enum.map(relations, &elem(&1, 1)))
  |> Enum.frequencies()
  |> Enum.sort_by(fn {_id, degree} -> degree end, :desc)
  |> Enum.take(limit)
  |> Enum.map(&elem(&1, 0))
end

# AFTER — GROUP BY en SQL, solo per-page degree en RAM
# El filtro exclude_types se aplica en AMBOS queries (outbound + inbound)
defp top_connected_ids(context_id, exclude_types, limit) do
  out_base = from r in Relation,
    join: s in assoc(r, :source), join: t in assoc(r, :target),
    where: s.context_id == ^context_id and t.context_id == ^context_id

  out_base = if exclude_types == [], do: out_base,
    else: from([r, s, t] in out_base,
      where: s.page_type not in ^exclude_types and t.page_type not in ^exclude_types)

  in_base = from r in Relation,
    join: s in assoc(r, :source), join: t in assoc(r, :target),
    where: s.context_id == ^context_id and t.context_id == ^context_id

  in_base = if exclude_types == [], do: in_base,
    else: from([r, s, t] in in_base,
      where: s.page_type not in ^exclude_types and t.page_type not in ^exclude_types)

  out_degree = from [r, s, t] in out_base,
    group_by: r.source_id, select: {r.source_id, count(r.id)}

  in_degree = from [r, s, t] in in_base,
    group_by: r.target_id, select: {r.target_id, count(r.id)}

  out = Map.new(Repo.all(out_degree))
  in_ = Map.new(Repo.all(in_degree))

  Map.merge(out, in_, fn _k, v1, v2 -> v1 + v2 end)
  |> Enum.sort_by(fn {_id, degree} -> degree end, :desc)
  |> Enum.take(limit)
  |> Enum.map(&elem(&1, 0))
end
```

**Ganancia:**

| Métrica | Antes | Después |
|---------|-------|---------|
| Filas en RAM | #relaciones × 2 | #páginas únicas × 2 |
| Memoria (50k rels) | ~1.6MB | ~320KB |
| Memoria (500k rels) | ~16MB | ~1MB |
| Tiempo (50k rels) | ~50ms | ~30ms |
| Tiempo (500k rels) | ~400ms | ~200ms |

Archivo: `lib/my_app/brain.ex` → `top_connected_ids/3`, ~line 1475

---

## 8. PubSub filter en :show subgraph

**Problema:** `handle_info({:page_changed, ...})` recarga el subgrafo en CADA cambio del contexto, aunque la página modificada no tenga nada que ver con el subgrafo actual. 3 queries + serialización + re-render 3D cada vez.

**Fix:** Solo recargar si la página cambiada es el centro del subgrafo O uno de los vecinos actualmente visibles.

```elixir
# BEFORE — recarga incondicional
def handle_info({:page_changed, _action, _page}, socket) do
  {:noreply, load_graph_data(socket)}
end

# AFTER — solo si afecta el subgrafo visible
def handle_info({:page_changed, _action, changed_page}, socket) do
  case socket.assigns.live_action do
    :index ->
      {:noreply, load_index_graph(socket)}

    :show ->
      page = socket.assigns.page
      if page && affected_subgraph?(page, changed_page, socket) do
        {:noreply, load_show_graph(socket, page)}
      else
        {:noreply, socket}
      end
  end
end

defp affected_subgraph?(center_page, changed_page, socket) do
  center_page.id == changed_page.id
  || Enum.any?(socket.assigns.nodes, &(&1.id == changed_page.id))
end
```

Archivo: `lib/dran_web/live/graph_live.ex` → `handle_info/2`, ~line 167

---

## Orden de implementación recomendado

1. **Cap edges** (`brain.ex`): más ganancia inmediata, menos riesgo. Un `order_by` + `limit`.
2. **PubSub filter** (`graph_live.ex`): condicional simple, arregla recargas innecesarias.
3. **Degree ranking a SQL** (`brain.ex`): solo se nota con brains >10k páginas. Más queries pero mucho menos RAM.
