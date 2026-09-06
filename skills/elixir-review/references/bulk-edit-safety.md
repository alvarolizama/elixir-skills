# Bulk Edit Safety

Apply review fixes to 3+ document pages safely: anchor-based edits over the
exact body via REST, instead of reconstructing bodies by hand or editing
page by page.

## Why not the specialized API calls

- The page update tool REPLACES the entire body — with 5+ pages it is slow
  and every call risks losing content.
- Passing meta+body together makes the rich editor re-parse and strip
  mermaid blocks.
- A REST `PUT` with ONLY `body` preserves meta (controller field whitelist:
  title/body/tags/meta/summary/archived/kb_*) and avoids editor re-parsing.

## Recipe

### 1. Auth

Read the token from the tool config (`mcp_servers.<name>.headers.Authorization`,
value `Bearer <token>`). Base URL = the MCP URL without the `/api/mcp`
suffix.

### 2. Fetch exact bodies

`GET /api/pages/:slug?context=<ctx>&include=body` — WITHOUT `include=body`
the GET returns `body: null` (metadata only). Save each body to disk
(`bodies/<slug>.md`). Sanity check: local `sha256` must match the
`body_hash` from the response.

### 3. Anchor edits

Structure: `EDITS = { slug: [(old, new), ...] }`. Rules:

- `old` must appear EXACTLY once in the body, or skip the whole page —
  never do a partial PUT (it leaves the page half-edited).
- Stored bodies differ from what the read UI displays:
  - Mermaid: the read rendering shows literal `\n` text where the stored
    body may have real newlines (or vice versa, depending on the editor
    that created it).
  - Exact snippet text: ALWAYS verify against the fetched body's bytes
    (grep/sed) before writing the anchor.
- On mismatch, diagnose with binary search: find the longest prefix of
  `old` that IS in the body — the next byte reveals the difference (e.g.
  `IF NOT EXISTS` vs `IF EXISTS`, literal `\n` vs real newline).

### 4. PUT body-only

`PUT /api/pages/:slug?context=<ctx>` with JSON `{"body": "<new>"}`. The
controller does a field whitelist take — meta is NOT touched.

### 5. Verification

- After each PUT: GET metadata and check `sha256(body_sent) ==
  body_hash` returned.
- Final round: per page, re-fetch and confirm the needles of each fix
  (strings that MUST be present) + count of ```mermaid blocks intact vs
  original.

## Results

11 pages, 48 edits applied; 9/11 passed first try, 2 failed on differently
formatted anchors (`IF NOT EXISTS` vs `IF EXISTS`, literal `\n` vs real
newline) and were resolved with corrected anchors. Zero content lost, zero
mermaid damaged, meta intact (verified by hash + version).

## When to fall back to full-function rewrite

If 2+ anchor edits on the SAME region fail (anchor can't be matched, or
fixes keep interacting), stop patching: rewrite the whole function/file
body in one pass. Repeated partial edits on one region compound risk; a
single clean rewrite of the region is easier to verify than a stack of
tweaks.