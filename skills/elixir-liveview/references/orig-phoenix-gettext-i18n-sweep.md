---
name: phoenix-gettext-i18n-sweep
description: "Sweep a Phoenix/LiveView app for untranslated strings when the default locale is not English (e.g. Spanish-first): gettext wrapping, po-file workflow, model label localization, test assertion patterns, and subagent pitfalls."
version: 1.0.0
author: Álvaro Lizama
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [phoenix, elixir, gettext, i18n, localization, liveview]
    related_skills: [elixir-umbrella-feature-build, elixir-build-troubleshooting]
---

# Phoenix Gettext i18n Sweep (non-English default locale)

Systematically bring a Phoenix/LiveView app to full translation when the default locale is NOT English (e.g. a Spanish-first app where msgids are English source strings and the UI renders Spanish).

## Core model

- **msgid = English source string** in code: `gettext("Archive")`.
- **msgstr = the rendered UI text** in the default locale: `msgstr "Archivar"`.
- An **empty msgstr renders the msgid verbatim** — i.e. untranslated English leaks into the UI. So "untranslated string in the UI" = "empty msgstr in the default-locale .po", not "missing gettext() call" (though those exist too).
- Find all leaks in one command:
  ```bash
  awk '/^msgid/{id=$0} /^msgstr ""$/{print id}' priv/gettext/es/LC_MESSAGES/default.po
  ```

## Sweep order (each step independently verifiable)

1. **Wrap UI literals** in `gettext/1` across LiveViews/components: headers, buttons, labels, flash messages, empty states, table chrome. Leave data values (page titles, tags, user content) alone. Don't touch code samples / technical docs content.
2. **Re-extract and merge** (compiles too — do it with the dev server killed):
   ```bash
   mix gettext.extract --merge
   ```
   This rewrites ALL locale .po files and reports `N new messages` per locale.
3. **Fill msgstrs in the default-locale .po** for every new/empty msgid. Natural, concise, informal-neutral voice; preserve `%{var}` tokens verbatim.
4. **Verify visually**, not just by grep: boot the dev server, log in, and screenshot the swept pages. Grep misses strings rendered from module attributes, model label helpers, and JS.

## Model label localization (the biggest blind spot)

UI chrome is easy; **labels that come from the data/model layer are what actually leaks**. If a central module maps type keys to display labels:

```elixir
@types %{"note" => %{label: "Note", plural: "Notes"}, ...}

def label(type), do: Gettext.gettext(MyAppWeb.Gettext, @types[type].label)
def plural(type), do: Gettext.gettext(MyAppWeb.Gettext, @types[type].plural)
```

Localizing at the single source fixes every badge, list header, page title, and "New X" header at once — much better than wrapping dozens of call sites.

**Watch out for singular/plural msgid collisions.** If `"Notes"` (plural label) and `"Note"` (singular) are separate msgids, a previous partial translation may have set `"Note"` → `"Notas"` (translated as if plural). Audit both after wiring the helper:
- `msgid "Note"` → `msgstr "Nota"` (singular!)
- `msgid "Notes"` → `msgstr "Notas"`
Same class of bug: `msgid "All"` translated as `"Todas"` when the UI context is masculine (`"Todos"`). Check each msgid's actual render context before writing the msgstr.

## Fuzzy merge can corrupt EXISTING msgstrs (not just msgids)

`mix gettext.extract --merge` fuzzy-matches msgids, and when a new msgid is "close enough" to an existing one it can stamp the OLD msgid's msgstr onto the NEW entry — silently, no warning. Seen in production: `msgid "None"` (prompt for "no goal selected") ended up with `msgstr "Hecho"` because the merge fuzzy-matched it against `msgid "Done"` → `msgstr "Hecho"`. Every Goal/Project/Plan select then showed "Hecho" as its empty option.

**Sweep for this after every merge:**
```bash
git diff priv/gettext/es/LC_MESSAGES/default.po | grep -E '^[-+]msgstr'
```
Any msgstr that changed without its msgid changing is suspect. Verify each against the msgid's render context (open the page, look at the select).

**Fix:** replace ambiguous shared msgids with context-specific ones. Instead of one `gettext("None")` for all select prompts, use per-type prompts — `gettext("Sin objetivo")` / `gettext("Sin proyecto")` / `gettext("Sin plan")` — so each gets its own correct msgstr and fuzzy merge has nothing to collide with. This is also what the USER prefers (the user explicitly asked for "Sin goal o el goal listado" over a generic prompt) — link pickers read naturally; plain selects get `gettext("Ninguno")`.

## Proactive fuzzy audit — the `fuzzy` flag is a standing defect signal

The `fuzzy` flag doesn't just appear right after a merge — **it accumulates over time** across multiple merges and partial fixes. An entry stamped `fuzzy` months ago will still render its (wrong) msgstr in the UI today, because gettext serves fuzzy msgstrs at runtime (it does NOT fall back to the msgid). The UI shows *something* — just the wrong word — so the bug is invisible until a user notices a jarring mistranslation.

**Audit command (run periodically, not just post-merge):**
```bash
grep -c 'fuzzy' priv/gettext/es/LC_MESSAGES/default.po
```
If the count is > 0, every fuzzy entry is suspect. List them with context:
```bash
grep -B2 -A2 'fuzzy' priv/gettext/es/LC_MESSAGES/default.po
```

**Bulk-fix pattern:** parse the .po into blocks (split on blank lines), extract every block containing `fuzzy`, pull out the `msgid`/`msgstr` pair, review each against the msgid's render context, then batch-apply: (1) remove the `fuzzy` flag from the `#,` comment line, (2) replace the `msgstr` with the correct translation. A Python script with `re.split(r'\n\n+', content)` + `re.search` per block handles this cleanly for 50-100 entries in one pass.

**Real-world example (MyApp, 2026-07):** a proactive audit found 66 fuzzy entries accumulated over months. Many had completely wrong words — `msgid "Active"` → `msgstr "Archivar"` (should be "Activo"), `msgid "Author"` → `msgstr "Autenticación"` (should be "Autor"), `msgid "Company"` → `msgstr "Comparación"` (should be "Empresa"), `msgid "Person"` → `msgstr "Versión"` (should be "Persona"). The `msgid "Active"` bug was even documented in a test comment as a known example, but never fixed until the proactive sweep. Lesson: **don't wait for a user to report a wrong word — grep for `fuzzy` and clear them all.**

**Plural entries get fuzzy too:** `msgid "page"` / `msgid_plural "pages"` with `msgstr[0] "páginas"` (plural form in the singular slot) is a common fuzzy artifact. Fix both `msgstr[0]` (singular) and `msgstr[1]` (plural), and remove the `fuzzy` flag.

**Bulk-fix script:** `scripts/audit_fuzzy.py` lists all fuzzy entries, and with a `--corrections fixes.json` map (`{"msgid": "correct msgstr"}`) can apply fixes in place (`--apply`) or dry-run (`--dry-run`). Plurals use `"singular|plural"` format in the JSON. Run it whenever the `grep -c fuzzy` count is non-zero.

## Manually-appended .po entries vanish if the msgid isn't in source

`mix gettext.extract --merge` REBUILDS the .po from extraction: any entry appended by hand whose msgid has no `gettext("...")` call in source gets dropped (reported as "N removed"). If msgids are looked up dynamically (e.g. `Gettext.gettext(Gettext, @types[type].label)` where the label literals live in a module attribute map), the extractor never sees them. Add an extraction-marker function so the literals exist as real macro calls:

```elixir
# Extraction markers — these msgids are looked up dynamically in label/1
# via Gettext.gettext/2, so the extractor never sees them.
defp _extraction_markers do
  [gettext("Todo"), gettext("Concept"), gettext("Todos"), gettext("Concepts")]
end
```

Never called; exists only so `mix gettext.extract` registers the msgids. Note: `import MyAppWeb.Gettext, only: [gettext: 1]` FAILS ("undefined macro") — Gettext is a backend, not a macro module. Use `use Gettext, backend: MyAppWeb.Gettext` at module top.

## After a subagent regenerates the .po, your hand-filled msgstrs are gone

If a subagent's task includes `mix gettext.extract --merge` and commits the result, it silently overwrites msgstrs you filled manually earlier in the session (the merge rewrites the whole file). After any subagent i18n wave: `git diff HEAD -- priv/gettext/es/.../default.po` and re-fill anything reverted to `msgstr ""`. Fill msgstrs as the LAST step before commit, and tell translation subagents to leave .po writes to you.

## PITFALL: the `patch` tool's fuzzy matching destroys .po file entries

The `patch` tool uses fuzzy matching (9 strategies) to find `old_string` in the file. **.po files are extremely dangerous to patch** because entries are alphabetically sorted, structurally identical (every entry has the same `#: comment` / `#, flags` / `msgid` / `msgstr` shape), and adjacent entries often share similar msgids (e.g. "Todas las páginas" near "Total páginas"). The fuzzy matcher will find the WRONG entry and silently replace it — the diff shows success but the replaced block was an unrelated msgid.

**What happens in practice (seen 2026-08 editing `default.po` for a new LiveView):**
1. Patching `msgid "Todas las páginas"` fuzzy-matched to the nearby `msgid "Total páginas"` (different entry, different context) — the original "Total páginas" entry was REPLACED, losing its source reference (`journey_live.ex:90`).
2. A later patch for `msgid "Regenerar"` produced a DUPLICATE entry instead of merging into the existing one — two entries with the same msgid.
3. Net result: one msgid deleted, one duplicated, gettext extraction metadata wrong, and the .po diff looks huge.

**Safe pattern for editing .po files:**
1. **NEVER use the `patch` tool for .po files** — the fuzzy matching is too aggressive for the uniform structure.
2. Use `terminal` with a Python script that parses blocks (split on blank lines) and matches by EXACT `msgid` content — never fuzzy string matching.
3. For removing fuzzy flags: rewrite the whole block in Python, don't patch the single `#, ... fuzzy` line.
4. After ANY .po edit, verify: `grep -c 'msgid "X"'` returns exactly 1 for every edited msgid (catches duplicates), and run `mix compile --warnings-as-errors`.

**Recovery if you already corrupted the .po:** `git checkout priv/gettext/` then re-apply with Python.

## Select OPTION LABELS in model/embedded-schema modules leak too

Not just field labels — the **option tuples** of `:select` fields defined in context/model modules (e.g. `{:select, "kanban_status", "Status", [{"Backlog", "backlog"}, ...]}`) bypass every component-level gettext wrap because they're built in the model layer. Wrap each option label, never the value: `{gettext("Backlog"), "backlog"}`. Values must stay raw — they're the DB enum.

In a non-web module, `import MyAppWeb.Gettext` may not bring the macro; use `use Gettext, backend: MyAppWeb.Gettext` at module top, or fully-qualified `Gettext.gettext(MyAppWeb.Gettext, "Backlog")`.

**Testing this:** asserting `pot_has?(label)` against labels returned by the model function fails confusingly when the app default locale is non-English — the function returns *translated* labels ("Pendientes"), and the .pot only contains English msgids. Pin the process locale inside the collection helper:

```elixir
defp with_en_locale(fun) do
  Gettext.put_locale(MyAppWeb.Gettext, "en")
  result = fun.()
  Gettext.put_locale(MyAppWeb.Gettext, "es")
  result
end
```

Also mark that test module `async: false` — locale is per-process but parallel suites share the backend.

## Runtime Gettext for dynamic strings

`gettext(dynamic_var)` does NOT compile ("Gettext macros expect message keys to expand to strings"). For values known only at runtime:

```elixir
Gettext.gettext(MyAppWeb.Gettext, dynamic_var)
```

The msgid still gets extracted if the literal appears somewhere as `gettext("Literal")`; otherwise add the entry to the .po manually with a `#: lib/...` comment reference.

## Test assertions must expect translated strings

The app default locale means `assert html =~ "Archive"` fails even when the feature works — the HTML contains "Archivar". Two robust patterns:

1. **Translate in the test** (mirrors what the user sees):
   ```elixir
   defp t(msgid), do: Gettext.gettext(MyAppWeb.Gettext, msgid)
   assert html =~ t("Archive")
   ```
2. **Assert structure, not text** (immune to locale entirely):
   ```elixir
   assert has_element?(view, ~s([data-testid="todo-row-#{todo.slug}"]))
   assert html =~ "hero-archive-box"
   ```
   Prefer this for anything you'd otherwise have to keep in sync with translators. Add `data-testid` attrs to templates when missing.

## Subagent pitfalls (seen in production sweeps)

- **A subagent "translated" an already-Spanish msgid into English** (`gettext("Más opciones")` → `gettext("More options")`), breaking the po entry and the test. In Spanish-first apps, some msgids are legitimately Spanish literals — instruct subagents explicitly: "msgids stay as they are; you wrap English literals, never rewrite existing non-English msgids."
- **Subagents skip `mix gettext.extract --merge` + msgstr filling**, leaving dozens of empty msgstrs = English UI. Always re-run the awk empties check after a subagent i18n wave and fill the gaps yourself (or dispatch a dedicated translation subagent with the awk command in its prompt).
- **Subagents don't verify visually.** They grep for literals and call it done; strings in module attributes (`@kanban_columns [{"backlog", "Backlog", ...}]`) get missed. Include "boot the server and check the page" in the acceptance criteria, or do the visual pass yourself.

## Post-sweep verification checklist

1. `awk` empties check on the default-locale .po → 0 results.
2. `mix test` green (with dev server killed — see elixir-build-troubleshooting for the beam-lock hang).
3. Visual pass on every swept page: sidebar groups, board columns, filter dropdowns, empty states, form labels, flash messages.
4. Check tab titles (`page_title` assigns) too — they use separate msgids and are easy to miss (e.g. "Nuevo Nota" vs "Nueva Nota" gender mismatches live there).
