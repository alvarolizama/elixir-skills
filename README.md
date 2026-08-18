# elixir-skills — Elixir/Phoenix Development Framework

A living framework of development skills for Elixir/Phoenix work. One router
skill defines the core development rules and routes to category sub-skills via
DAGs. Built to grow: add a sub-skill, register it in the router, done.

## Structure

```
elixir-skills/
├── SKILL.md              ← router: core development rules + DAG routing + Quick Nav
├── README.md
└── skills/
    ├── elixir-setup/         umbrella scaffold, local bootstrap, multi-domain SaaS
    ├── elixir-build/         build troubleshooting, mix/deps, hex publishing
    ├── elixir-ecto/          query pitfalls, JSONB, cascades, tracing, data models
    ├── elixir-liveview/      LiveView debugging, HEEx design, forms, analytics, i18n
    ├── elixir-auth-security/ OAuth/social login, impersonation, security audit
    ├── elixir-performance/   read-only perf audits, redundancy audits
    ├── elixir-features/      end-to-end feature build, feature removal, runtime config
    ├── elixir-deploy/        mix release, PaaS/Docker, SSL/CSRF edge cases
    ├── elixir-bridges/       agent↔Elixir bridges, MCP servers/proxies, LLM gateways
    ├── elixir-testing/       pure Elixir + ExUnit, flaky tests, SSR components
    ├── elixir-git/           commit hygiene, history surgery, signing
    ├── elixir-docs/          READMEs, user docs, UI screenshots
    └── elixir-review/        architecture specs, plan review
```

Each sub-skill has its own `SKILL.md` (DAG + consolidated patterns) and a
`references/` directory (absorbed originals + detail).

## Installation

### 1. Clone

```bash
git clone git@github.com:alvarolizama/elixir-skills.git
```

### 2. Install into Hermes

```bash
REPO=/path/to/elixir-skills
mkdir -p ~/.hermes/skills/software-development
cp -R "$REPO/skills/"* ~/.hermes/skills/software-development/
cp "$REPO/SKILL.md" ~/.hermes/skills/software-development/elixir-skills/SKILL.md
```

Or use symlinks to stay on the repo's bleeding edge:

```bash
for s in "$REPO/skills/"*/; do
  ln -sfn "$s" ~/.hermes/skills/software-development/$(basename "$s")
done
ln -sfn "$REPO" ~/.hermes/skills/software-development/elixir-skills
```

### 3. Verify

```bash
ls ~/.hermes/skills/software-development/ | grep elixir-
```

The router (`elixir-skills`) is the entry point. It routes to the category
sub-skills based on the task.

## Usage

Load the router skill first: `elixir-skills`. It contains:

1. **Core Development Rules** — investigation-before-conclusion, codebase
   first, reuse over rewrite, verify before done.
2. **Workflow Rules** — shaping, planning (DAG phases ending in VERIFY),
   codebase review, reuse.
3. **Router DAG** — routes the task to the right category sub-skill.
4. **Quick Navigation** — one-row-per-sub-skill table.

Each sub-skill then handles its own territory with a DAG and consolidated
patterns, backed by `references/` for depth.

## How to Grow This Framework

The point is that it keeps growing cleanly:

1. **New topic fits an existing category** → add a section to that category's
   `SKILL.md` (and a reference file if it has depth).
2. **New category** → create `skills/<name>/SKILL.md` with frontmatter + DAG,
   add `references/`, and register one row in the router's Quick Navigation
   table.
3. **New depth on an existing pattern** → add a file under that category's
   `references/` and link it from its `SKILL.md`.

Rules for contributions:

- **English only.** All SKILL.md files, DAGs, and references are in English.
- **Generic, no project/brand references.** Skills must be reusable across
  projects. Real project names (product names, org names, brand names) do not
  belong in a class-level skill — use `MyApp` as the placeholder.
- **Every skill has a DAG.** The mermaid flow at the top of each `SKILL.md`
  routes "what task → which section".
- **Every flow ends in VERIFY.** No phase is done until it is verified with
  real tool output.

## License

MIT.
