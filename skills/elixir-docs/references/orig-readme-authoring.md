---
name: readme-authoring
description: "Use when writing/updating READMEs or user-facing docs."
version: 1.0.0
author: Álvaro Lizama
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [readme, documentation, verification, docs, user-facing]
    related_skills: [architecture-specs, grounded-citations]
---

# README Authoring (codebase-verified)

## When to use

- "Revisa el codebase y haz un README resaltando features" / "highlight the features"
- "Simplifica el README" / "rewrite the README"
- "Update the docs / install guide" for a project
- Any user-facing feature list, landing doc, or configuration guide that must match shipped code

This is NOT `architecture-specs` (which produces reimplementation/porting specs) and NOT `grounded-citations` (which grounds research in external sources). This skill grounds **user-facing docs in the codebase itself**.

## Core rule (Álvaro's standing requirement)

**Every claimed feature must exist in the codebase, and every UI claim must have real UI (a route/page/component).** No invented features, no aspirational roadmap items presented as shipped, no marketing claims the code can't back. When the user says "resalta features" they mean *verified* features.

## Workflow

```
confirm project → read existing doc claims → enumerate ground truth →
verify each claim individually → separate user-facing from internals →
write doc → report discrepancies found
```

1. **Confirm the project first.** Don't assume from stack markers (Elixir/Phoenix ≠ automatically MyApp — the user has multiple projects). Check the cwd / git remote, or ask.

2. **Read the existing doc** (if any) and extract its claims as a checklist: each feature bullet, each env var + default, each endpoint, each "X is persisted/audited/exported" statement.

3. **Enumerate ground truth from code, not from the old doc:**
   - Routes/pages: the router file is the page inventory (Phoenix: `router.ex`; JS: route definitions; Python: urlconf/blueprints).
   - Each page's purpose: read the module doc / top of each LiveView/controller/component — batched reads, 5+ per turn.
   - Config: read the runtime config source for env vars WITH their real defaults (Phoenix: `config/runtime.exs` — read the actual `System.get_env("VAR", "default")` lines; don't copy defaults from the old README).
   - Install/deploy facts: seeds file (default credentials + override env vars), Dockerfile (ports, entrypoint behavior, build args), package manifest (versions, setup aliases/scripts).

4. **Verify each claim individually with grep** — never carry a claim from the old doc into the new one without a code hit:
   - Claimed mechanism (auditing, signing, headers): grep all call sites. If `Audit.log(...)` is only called from one controller, the feature is that one controller's scope — write it that precisely.
   - Claimed response headers: grep the actual `put_resp_header`/`setHeader` site, not just mentions in comments or moduledocs.
   - Claimed endpoints: confirm method + path in the router.

5. **Separate user-facing features from internals.** Proxy internals (adapters, estimators, normalizers), ETS/Postgres topology, and worker names belong in a short "Platform" section at most — the features section is for things a user can touch via UI or API.

6. **Write the doc**, then **report discrepancies back to the user explicitly**: which old claims were removed or corrected because the code didn't support them, and which verified features were added. This report is part of the deliverable — the user wants to know what was wrong in the old doc.

## Pitfalls (all from real sessions)

- **Framework boilerplate comments are not config.** Phoenix's `runtime.exs` ships commented-out mailer/SSL blocks with `SOME_APP_*` placeholder env vars. Grepping `System.get_env` finds them — but they're inert comments. Read the surrounding lines before listing a var.
- **Orphan modules exist.** A LiveView/controller can exist in `lib/` with no route mounting it (dead or legacy code). The router is the truth for "does this page exist" — a module in the tree is not a feature.
- **Doc comments can promise what code doesn't do.** A `@moduledoc` mentioning a response header / behavior that the code never sets (found via grep of the set-site) means the comment is stale, not that the feature exists. Verify the implementation, not the documentation.
- **Scope overstatement is common.** "Admin actions are audited" may mean exactly one audited action. Find ALL call sites of the claimed mechanism and write the real scope.
- **Missing moduledoc doesn't mean missing feature.** `@moduledoc false` modules still render pages — check the render/functions.
- **Don't trust old-doc defaults.** Env var defaults drift. Read each default from the config source at write time.
- **Screenshots can outlive pages.** A `docs/screenshots/foo.png` existing doesn't prove the page still exists — cross-check the router before referencing it.
- **UI language matters.** If the UI strings are hardcoded in a non-English language (check page titles/labels in templates), note it in the README — an English README for a Spanish UI surprises users otherwise.

## Output conventions (Álvaro's prefs)

- English for the README unless told otherwise; note the UI language prominently if it differs.
- Env vars as a table: `Var | Default | What it tunes` — required-in-prod vars in their own table first.
- Quick start = clone → setup command → run → seeded credentials (with their override env vars) → first milestone ("proxy a request in ~5 minutes").
- Keep one hero screenshot; verify the referenced file exists in the repo.
- Compact sections; no verbose architecture narrative — compress internals into a short Platform/Stack section.

## References

- `references/phoenix-readme-verification.md` — Phoenix/Elixir-specific verification recipe (router.ex → LiveView moduledocs → runtime.exs → seeds/Dockerfile/mix.exs) with a worked example from a real README rewrite, including the exact greps and the discrepancies caught.
