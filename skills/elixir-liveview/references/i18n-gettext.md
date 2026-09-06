# i18n / Gettext Sweep for a Non-English Default Locale

**Symptom:** English leaks into the UI, or after a merge the wrong
language shows. Core model: **msgid = English source string** in code
(`gettext("Archive")`); **msgstr = rendered UI text** in the default
locale (`msgstr "Archivar"`). An EMPTY msgstr renders the msgid verbatim
(English leaks into the UI).

## Sweep order (each step independently verifiable)

1. Wrap UI literals in `gettext/1` across LiveViews/components.
2. Re-extract and merge: `mix gettext.extract --merge` (kill the dev
   server first).
3. Fill msgstrs in the default-locale `.po` for every new/empty entry.
4. Verify visually — grep misses strings from module attributes, JS,
   and model helpers.

## Wrap rules (where literals hide)

- **Module attributes** (compile-time): wrap the literal in the
  attribute definition, then `Gettext.gettext(MyAppWeb.Gettext, @attr)`
  at use sites.
- **HEEx visible text**: `{gettext("Visible")}` between tags.
- **HEEx attributes** (`label`, `placeholder`): wrap there — attr
  values are strings, not compiled templates.
- **Interpolated strings** (counts, version history): `gettext("...")`
  with `%{count}` interpolation and proper pluralization.
- **Flash messages** (context modules): wrap at the source of truth.
- **`page_title` assignments**: separate msgids — easy to miss
  gender/number mismatches.
- **`phx-disable-with`**: wrap the label too.

## Model label localization — the biggest blind spot

Wrap labels at the SINGLE source (model helper), not at dozens of call
sites:

```elixir
def label(type), do: Gettext.gettext(MyAppWeb.Gettext, @types[type].label)
def plural(type), do: Gettext.gettext(MyAppWeb.Gettext, @types[type].plural)
```

Dynamic msgids are invisible to the extractor — add extraction-marker
functions:

```elixir
defp _extraction_markers do
  [gettext("Todo"), gettext("Concept"), gettext("Todos"), gettext("Concepts")]
end
```

## Fuzzy merge can corrupt EXISTING msgstrs

`mix gettext.extract --merge` can fuzzy-match a new msgid to an existing
one and stamp the wrong msgstr. After EVERY merge:

```bash
git diff priv/gettext/<locale>/LC_MESSAGES/default.po | grep -E '^[-+]msgstr'
```

Any msgstr that changed without its msgid changing is suspect.
**Never use the `patch` tool for `.po` files** — fuzzy matching in a
patch destroys entries by merging lines across contexts; use
`mix gettext` / `msgmerge` / manual editor instead.

## Proactive fuzzy audit

```bash
grep -c 'fuzzy' priv/gettext/<locale>/LC_MESSAGES/default.po
```

Fuzzy entries render their (wrong) msgstr at runtime. Grep periodically
and clear them all. After a subagent regenerates the `.po`, your
hand-filled msgstrs are gone — re-check and re-fill.

## Manually-appended .po entries vanish

If a msgid isn't in source, `extract --merge` drops it. Use
`Gettext.gettext/2` for runtime-built strings (they survive extraction
only via marker functions).

## Select option labels leak too

Option tuples in model/context modules bypass component-level
gettext — wrap the LABEL but keep the VALUE raw (DB enum):

```elixir
{gettext("Backlog"), "backlog"}
```

## Test assertions must expect translated strings

Default locale means `assert html =~ "Archive"` FAILS — the HTML has
the translated string. Two robust patterns:

1. Translate in the test:
   `defp t(msgid), do: Gettext.gettext(MyAppWeb.Gettext, msgid)`
2. Assert structure, not text:
   `assert has_element?(view, ~s([data-testid="row-#{slug}"]))`

## Subagent pitfalls

- Subagents may "translate" an already-translated msgid. Instruct: wrap
  English literals, never rewrite existing msgids.
- Subagents may skip `mix gettext.extract --merge` + msgstr filling.
- Subagents don't verify visually — always do a visual pass yourself.

## Post-sweep checklist

1. `awk` empties check → 0 empty msgstrs in the default locale.
2. `mix test` green.
3. Visual pass on every swept page.
4. Check `page_title` assigns (separate msgids, gender mismatches).