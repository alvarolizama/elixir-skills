# Search Picker Wiring — Autocomplete / Combobox

**Symptom:** a LiveView search-input + dropdown picker (single- or
multi-select) misbehaves: filter resets every keystroke, the dropdown
slams shut, Escape reopens it, the edit modal is born with the dropdown
open, picking an option doesn't close the list, or one of several
sibling pickers works while the others silently don't.

## The five traps

1. **Unnamed input + own `phx-change` inside a form ⇒ empty payload.**
   With an element-local change binding, LiveView serializes ONLY the
   changed input, keyed by its `name` attribute
   (`serializeForm(form, opts, [input.name])`). An input WITHOUT a name
   ships an empty value → every keystroke resets the filter to `""` →
   dropdown shuts. Legacy code used `phx-keyup` PRECISELY because it
   sends `%{"value"}` regardless of name — treat pre-existing keyup as
   load-bearing until proven otherwise; migrating to `phx-change`
   requires naming the inputs in the same commit.
2. **Escape reopen loop.** With keyup filters, Escape closes but
   RELEASING the key fires keyup → `q != ""` → reopens. Impossible once
   filtering runs on change. Never mix keyup-openers with keyboard
   closers — move the opener to `phx-focus`.
3. **Modal prefill forcing `open = true`** renders the dropdown
   born-open; users report a sticky zombie that never closes no matter
   how often they close/reopen the modal. Born-closed is the correct
   default; focus opens.
4. **Label attr missing on ONE variant's option buttons** (one picker
   yes, its sibling no): that variant's pick handler matches no clause
   and dead-ends with a `FunctionClauseError` — or, with no test driving
   the flow, stays silently green.
5. **Pick without reflect + close** leaves the list open and the raw
   query in the input.

## Handler set (complete)

| Event | Fired by | Effect |
|---|---|---|
| `<kind>_search` | input `phx-change` (+ `phx-debounce="200"`) | resolve query; `open = query != ""` |
| `open_picker` | input `phx-focus` + `phx-value-picker` discriminator | that `_open = true` |
| `pick_item` | dropdown button `phx-click` | store id + reflect label into input; `open = false` |
| `toggle_item` | multi-select variant | add/remove id; STAY open (chips below handle removal) |
| `close_pickers` | wrapper `phx-click-away` AND form-level `phx-window-keydown` + `phx-key="Escape"` | ALL `_open = false` |

Window-level Escape so it works wherever focus sits inside the form.

## Payload contract — cover BOTH wire shapes

```elixir
defp resolve_search(%{"value" => q}),                 do: q
defp resolve_search(%{"ns" => %{"value" => q}}),      do: q
defp resolve_search(%{"ns" => %{"thing_id_display" => q}}), do: q || ""
defp resolve_search(_),                               do: ""
```

Keys must match template `name="ns[thing_id_display]"` EXACTLY. A
missing clause falls through to the fallback silently and wipes the
query every keystroke.

## Template shape

```heex
<div class="relative" phx-click-away="close_pickers">
  <input
    type="text"
    name="model_provider[scope_member_id_display]"
    value={@search}
    placeholder="Search…"
    phx-focus="open_picker"
    phx-value-picker="member"
    phx-change="scope_search"
    phx-debounce="200"
    autocomplete="off"
  />
  <%= if @open and filtered != [] do %>
    <div class="absolute z-50 ... max-h-40 overflow-y-auto">
      <button
        :for={item <- Enum.take(filtered, 10)}
        type="button"
        phx-click="pick_item"
        phx-value-item_id={item.id}
        phx-value-item_label={item.label}
      >
        {item.label}
      </button>
    </div>
  <% end %>
</div>

<%!-- form-level Escape closer --%>
<.form ... phx-window-keydown="close_pickers" phx-key="Escape">
```

Key rules:

- **Name every searcher** (`model_provider[...]` even though nothing
  casts it) — unknown keys are dropped at cast time, but the name is
  what `phx-change` serializes from.
- Two inputs sharing one `name=` is safe when their branches are
  mutually exclusive in HEEx (`is_new? if/else`) — only one ever
  renders.
- Option buttons carry the FULL payload: `phx-value-item_id` AND
  `phx-value-item_label`. A handler clause requiring the label without
  the template sending it compiles fine and crashes at runtime — and
  suites without tests for that flow stay green.
- Never force `open = true` in an edit-opens-modal handler; rely on
  focus-to-open instead.

## Sibling Parity Audit (after ANY edit to a repeated pattern)

Before editing: enumerate every variant of the picker (kind × mode).
After editing, verify mechanically — green suites will NOT catch a
skipped sibling when no test drives that sibling's flow:

```bash
grep -c 'phx-click-away="close_pickers"' lib/**/*_live.ex  # == wrapper count (all variants)
grep -c 'phx-focus="open_picker"' ...                      # == searcher count (all variants)
grep -c 'phx-keyup="' ...                                  # == 0, no half-migrated stragglers
```

Delete orphaned handlers only AFTER grepping templates for their event
names (`phx-(click|focus|change)="name"`); comments lie — a "legacy"
handler marked as "used by the edit form" was found referenced by
nothing. Then encode parity in tests so the next refactor cannot regress
a sibling unnoticed.

## LiveViewTest traps for these controls

- **Selectors are not substrings**: `assert html =~ ~s(input[name="..."])`
  FAILS — serialized HTML contains no CSS-selector syntax. Use
  `has_element?(view, ~s(input[name="ns[...]"]))`.
- **Copy flash text EXACTLY** from source, including
  pluralization/casing: `"#{n} providers assigned."` does NOT contain
  `"Provider assigned"`. An assert written from memory fails while the
  feature works.
- Drive events with the EXACT wire payload shape (nested maps included)
  — that pins the payload contract in CI:

```elixir
view |> render_click("open_picker", %{"picker" => "team"})
assert render(view) =~ "(bound row visible)"
view |> render_click("pick_item", %{"item_id" => id, "item_label" => name})
assert render(view) =~ ~s(value="#{name}")   # reflected
refute render(view) =~ "(actual)"            # closed
view |> render_change("scope_search", %{"model_provider" => %{"scope_team_id_display" => q}})
```

- Born-closed is assertable: `refute render(view) =~ marker` right after
  opening the modal, then open → assert marker appears.
- **Multi-select creation stays multiplicative**: two toggles + one
  submit must produce two rows; pin with a test and assert the exact
  flash string with count/plural.

## Hook-owned picker variant (rows client-side, single server channel)

When the picker lives inside a JS-hook-managed editor (rows cloned from
`<template>`), do NOT use server assigns for the dropdown — single
channel: the hook serializes everything to a hidden textarea (real form
`name=`) inside a `phx-update="ignore"` container.

- **ALL** client-managed subtrees carry `id` + `phx-update="ignore"`,
  not just the textarea: without ignore, morphdom discards the hook's
  rows on every `phx-change` patch (lists empty as you type).
- Search via `pushEvent("event", %{q: q}, reply => render(reply))` +
  `handle_event` returning `{:reply, %{results: ...}, socket}` —
  replaces a `fetch()` to a custom endpoint; scope is resolved by the
  LiveView's assigns, never sent from the client. Debounce in the hook
  (250ms).
- Bind the dropdown pick to `mousedown` + `preventDefault` so the
  input's blur doesn't eat the click.
- The server renders EMPTY lists: tests assert the textarea (server-side
  source of state), never client-side DOM.
- New `defp` helpers: place them AFTER the last clause of their group
  (`handle_event`, ...) — interleaving triggers "clauses with the same
  name and arity should be grouped together".