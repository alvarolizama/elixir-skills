# my_app Page Ownership and Type Correction

Session-learned patterns for managing my_app page ownership fields, fixing wrong
page types, and preserving mermaid during recreate operations.

## 1. Ownership fields — only settable at creation time

`dran_create_page` and `dran_create_todo` accept `owner`, `created_by`, and
`assignee` parameters. `dran_update_page` and `dran_update_todo` do NOT.

**Defaults for Álvaro's brain:**
- `owner`: always `"alvaro"`
- `created_by`: always `"agent"`
- `assignee` (todos only): ALWAYS ask via `clarify` before creating.
  Choices: `alvaro`, `agent`, or Other (type a name).

If you forget to set these at creation, the only fix is delete + recreate.
The fields default to `"agent"` for both owner and created_by when omitted.

## 2. Page type cannot be changed after creation

`dran_update_page` cannot change `page_type`. If a page was created with the
wrong type (e.g. `entity` when it should be `concept`), the only fix is:

1. Read the full body with `dran_get_page`
2. Read all relations with `dran_get_links`
3. Delete the page with `dran_delete_page`
4. Recreate with correct `page_type` and `meta.kind`
5. Recreate explicit relations (`related`, `part_of`) with `dran_create_relation`
   - `semantic` relations auto-regenerate via the augmenter
   - `embeds` relations auto-regenerate from `![[slug]]` in the body

## 3. Entity vs Concept — the most common misclassification

| Question | Entity | Concept |
|----------|--------|---------|
| Does it have a proper name in the world? | Yes | No |
| Is it a person, company, product, tool, place, or event? | Yes | No |
| Is it abstract knowledge (technique, pattern, discipline, theory)? | No | Yes |

**Examples from real corrections:**
- Yungdrung Bön (religion/tradition) → **concept** (discipline), NOT entity
- Qigong (practice) → **concept** (discipline), NOT entity
- Tsa Lung / Trul Khor (yoga system) → **concept** (discipline), NOT entity
- Mantra OM BOM NAMAHA → **concept** (technique), NOT entity
- Mantra SO MA MA RA YO DZA → **concept** (technique), NOT entity
- Yeshe Walmo (deity with a name) → **entity** (person) ✅ — deities have names
- Tönpa Shenrap Miwoché (founder) → **entity** (person) ✅

**Anti-pattern**: using `entity` with `meta.kind: "concept"`. Entity kinds
are: person, company, product, tool, place, event. If the kind you want is
"concept", "technique", "pattern", "discipline", or "theory", the page type
is `concept`, not `entity`.

**Rule of thumb**: A mantra is a TECHNIQUE. A religion is a DISCIPLINE.
A practice system is a DISCIPLINE. A deity IS an entity (person) — it has
a proper name.

## 4. Mermaid blocks can be stripped on recreate

When you delete a page and recreate it, the body text survives but mermaid
code fences may be emptied: ` ```mermaid\n\n``` ` with no content.

**Prevention:**
- After any delete + recreate, ALWAYS read the page back with `dran_get_page`
- Verify that all `mermaid` code fences still contain their diagram content
- If they're empty, re-update the body with `dran_update_page` to restore
- This has been observed on long pages with many mermaid blocks (7+)

## 5. Delete + recreate workflow for fixing ownership/type

```
1. dran_get_page(slug)           → save full body
2. dran_get_links(slug)          → save all explicit relations (related, part_of)
   (embeds and semantic are auto-regenerated, don't save those)
3. dran_delete_page(slug)        → cascades all relations
4. dran_create_page/create_todo  → recreate with correct type, meta, owner, etc.
5. dran_create_relation(...)     → recreate each saved relation
6. dran_get_page(slug)           → verify body + mermaid survived
```

For batch operations (many pages), read all pages first, then delete all,
then recreate all. Parallel reads are safe; parallel deletes are safe;
parallel creates may hit slug conflicts if not careful.

## 6. Pre-creation checklist

Before calling `dran_create_page` or `dran_create_todo`, verify ALL of:
- [ ] Correct `page_type` (note, concept, entity, reference, project, goal, plan, todo, comparison, query)
- [ ] Correct `meta.kind` for the type (see §8 of SKILL.md)
- [ ] `owner: "alvaro"`
- [ ] `created_by: "agent"`
- [ ] `assignee` (todos only) — asked via `clarify`
- [ ] Relations planned: which `related` and `part_of` to create after
- [ ] `![[slug]]` embeds in body for pages that should auto-link
- [ ] Tags are kebab-case, 2-5 items
