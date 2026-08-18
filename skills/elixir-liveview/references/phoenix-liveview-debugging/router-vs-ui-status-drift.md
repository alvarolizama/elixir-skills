# Router-vs-UI status drift on join tables

## Symptom

An admin disables a child entity in one LiveView (e.g. flips a
`credential.status` to `"disabled"` in `/dashboard/providers`) but
another LiveView (e.g. `/dashboard/models`) still shows the row as
**active** — wrong badge, wrong toggle icon, no error message — even
though the proxy/router **already filters the row out of routing
correctly**. The user thinks the toggle is broken.

The router respects the change because it filters at the candidate list;
the UI didn't reflect it because the template only read the join-row's
own field, not the child's status.

This is distinct from `references/stale-beam-code-reload.md` (server
hasn't picked up the new code) and from `references/form-select-traps.md`
(UI not picking up submit). Both those feel similar on the surface but
have different diagnoses.

## Diagnosis (3-line check)

Before touching the UI, confirm the routing side is correct:

```bash
grep -n "child.status\|child_field.status\|credential.status" \
  lib/<app>/routing/router.ex lib/<app>/routing/priority.ex
```

If the routing code filters by the child's status, then **the bug is
in the UI display**, not in routing. Skip the routing audit and go to
the fix.

If the routing code does NOT filter by the child's status, you have a
**larger problem** (traffic still flows) — fix the router first, then
this pitfall's UI fix won't matter anyway.

## Root cause pattern

The join table (e.g. `ModelProvider`, which pairs a `Model` with a
`Credential`) carries its own boolean state (`enabled`), AND the
referenced child carries its own state (`status = "active" |
"disabled" | "error"`). The UI was checking only one of them:

```heex
<span class={badge(enabled_badge(ap.enabled))}>
  {enabled_label(ap.enabled)}     # WRONG — ignores credential.status
</span>
```

`router.ex` correctly filters by **both**, but the UI didn't learn
from the router. The user sees a green "Activo" row for a credential
that's actually disabled, with a `hero-pause` icon suggesting "click
to disable" when the click would do nothing useful.

## Fix: hoist the predicate

Define the effective predicate on the join row once, and use it in
every UI surface that touches it — badge, label, toggle icon, toggle
tooltip, badge title:

```elixir
def provider_active?(%{enabled: false}), do: false
def provider_active?(%{credential: nil}), do: false
def provider_active?(%{credential: %{status: s}}) when is_binary(s),
  do: s == "active"
def provider_active?(_), do: true

def credential_status_label(%{credential: %{status: "active"}}), do: nil
def credential_status_label(%{credential: %{status: "disabled"}}), do: "credential desactivada"
def credential_status_label(%{credential: nil}), do: "sin credential"
def credential_status_label(_), do: nil

def toggle_title(%{enabled: false}), do: "Activar"
def toggle_title(ap) do
  if provider_active?(ap),
    do: "Desactivar",
    else: "Credential desactivada — activa en /dashboard/providers"
end
```

Then in the template:

```heex
<span class={["badge", enabled_badge(provider_active?(ap))]}
      title={credential_status_label(ap)}>
  {enabled_label(provider_active?(ap))}
</span>

<button title={toggle_title(ap)}>
  <.icon name={if provider_active?(ap), do: "hero-pause", else: "hero-play"} />
</button>
```

## Verification

1. Write a LiveView test that creates a join-row + its child,
   toggles the child to `"disabled"` in the DB, mounts the LiveView,
   and asserts the badge / icon / title reflect the effective state.
   Without this test, the next refactor will silently re-introduce
   the drift.
2. `mix precommit` (or the project's full-suite alias) still green.
3. Manual: open the LiveView in the browser, hover the badge — the
   tooltip should explain *why* the row is inactive when the cause
   is the referenced child, not a generic "Inactivo".

## Pitfall: keep the tooltip actionable

When the badge says "Inactivo" because the **child** is the cause,
the toggle tooltip should NOT say "Activar" — the toggle doesn't
actually re-enable the child. Point the admin to the correct page:

```elixir
def toggle_title(_), do: "Credential desactivada — activa en /dashboard/providers"
```

Otherwise the admin clicks the pause/play toggle, nothing happens,
and they think the app is broken.

## Pitfall: tile every UI surface that touches the predicate

A partial fix leaves the bug looking fixed from one angle but
present from another. Audit each place that reads the join-row's
state:

- Status badge (label, class, tooltip)
- Toggle icon (pause/play) + tooltip
- Edit-mode prefill (the form should also reflect the child's state)
- Empty-state messages (e.g. "0 enabled" vs "all paused because of X")
- Flash messages after toggle (the current row's state may be stale;
  mention the child if relevant)

The user only finds the missed surface via a different request later.

## Related

- `phoenix-liveview-crud-forms` — pitfall "Virtual mirror field for unit
  conversion" uses the same attach-predicates-once pattern when the field
  is on the same row.
- `phoenix-feature-removal` — same trap class (UI surfaces keep reading
  fields from a removed feature); always grep `lib/<app>_web/live/` for
  references to a field before removing it.
- `references/form-select-traps.md` — UI not picking up server state
  (different mechanism: select dropdown stale vs status drift).
- `references/stale-beam-code-reload.md` — restart the BEAM after
  schema changes; the new helper compiles but the running process
  still uses the old one.
