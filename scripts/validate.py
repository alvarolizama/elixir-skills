#!/usr/bin/env python3
"""Structural validator for the elixir-skills repo.

Python stdlib only — no third-party dependencies. Run from the repo root:

    python3 scripts/validate.py

Checks, per SKILL.md (root router + every skills/<category>/SKILL.md):

  1. Frontmatter exists and carries the required keys:
     name, description, version, author, license, metadata (all non-empty).
  2. A decision DAG is present: a fenced ```mermaid flowchart block with
     at least one `-->` edge.
  3. Every category SKILL.md has an exact `## VERIFY` heading (case-sensitive;
     a case-mismatched variant such as `## Verify` is reported), declares
     `platforms: [linux, macos]`, and stays within 150-350 lines.

Per category (skills/<category>/):

  4. Every references/*.md file is indexed in that SKILL.md's reference
     index, every indexed entry resolves to a real file, the category keeps
     5-10 references, and each reference is 60-250 lines (no exemptions).
  5. Relative Markdown links/images across all repo .md files resolve to
     real files. Link extraction ignores fenced code blocks and inline code
     spans, so GATE/VERIFY shell commands are never misclassified as links,
     and it understands nested badge image links like
     [![License: MIT](https://...)](LICENSE) — the LICENSE target is
     resolved even though the badge image is a remote URL.

Output: one line per failure (`path:line — problem`) plus a summary.
Exit code 0 when clean, 1 when any failure was found.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

REQUIRED_FRONTMATTER_KEYS = (
    "name",
    "description",
    "version",
    "author",
    "license",
    "metadata",
)

REF_MIN = 5
REF_MAX = 10
REF_MIN_LINES = 60
REF_MAX_LINES = 250

FENCE_RE = re.compile(r"^\s*(```|~~~)")
MERMAID_FENCE_RE = re.compile(r"^\s*```mermaid\s*$")
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
TOP_LEVEL_KEY_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
VERIFY_HEADING_EXACT_RE = re.compile(r"^##\s*VERIFY\s*$")
VERIFY_HEADING_ANY_CASE_RE = re.compile(r"^##\s*verify\s*$", re.IGNORECASE)
# Capture path prefixes so cross-category pointers are not mistaken for an
# index entry owned by this category.
REF_MENTION_RE = re.compile(
    r"(?P<prefix>(?:[A-Za-z0-9_.-]+/)*)references/(?P<name>[A-Za-z0-9._-]+\.md)"
)
# Markdown link or image; link text may contain one level of nested brackets
# (covers [![badge](remote)](LICENSE)).
MD_LINK_RE = re.compile(
    r"\[((?:[^\[\]]|\[[^\[\]]*\])*)\]\(([^()\s]+)(?:\s+\"[^\"]*\")?\)"
)
INLINE_CODE_RE = re.compile(r"`[^`]+`")
REMOTE_RE = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//|#)", re.IGNORECASE)


class Failure:
    def __init__(self, path: Path, line: int, message: str) -> None:
        self.path = path
        self.line = line
        self.message = message

    def __str__(self) -> str:
        try:
            display = self.path.relative_to(REPO_ROOT)
        except ValueError:
            display = self.path
        return f"{display}:{self.line} — {self.message}"


def strip_code_spans(line: str) -> str:
    """Blank out inline code spans so their content is never link-parsed."""
    return INLINE_CODE_RE.sub(lambda m: "`" + " " * (len(m.group(0)) - 2) + "`", line)


def prose_lines(path: Path) -> list[tuple[int, str]]:
    """Return (line_number, text) for lines OUTSIDE fenced code blocks, with
    inline code spans blanked. This is what link extraction runs on — shell
    GATE commands inside fences can never be mistaken for Markdown links."""
    out: list[tuple[int, str]] = []
    fence: str | None = None
    for idx, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        fence_match = FENCE_RE.match(raw)
        if fence_match:
            marker = fence_match.group(1)
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
            continue
        if fence is not None:
            continue
        out.append((idx, strip_code_spans(raw)))
    return out


def mermaid_blocks(path: Path) -> list[str]:
    blocks: list[str] = []
    current: list[str] | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        if MERMAID_FENCE_RE.match(raw):
            current = []
        elif current is not None:
            if FENCE_RE.match(raw):
                blocks.append("\n".join(current))
                current = None
            else:
                current.append(raw)
    return blocks


def parse_frontmatter(path: Path) -> tuple[dict[str, str] | None, int]:
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        return None, 1
    body = match.group(1)
    keys: dict[str, str] = {}
    for line in body.splitlines():
        key_match = TOP_LEVEL_KEY_RE.match(line)
        if key_match:
            keys[key_match.group(1)] = line.split(":", 1)[1].strip()
    return keys, 1


def reference_index_entries(skill_path: Path) -> set[str]:
    """Filenames mentioned under the SKILL.md's `## References` heading."""
    entries: set[str] = set()
    in_refs = False
    for raw in skill_path.read_text(encoding="utf-8").splitlines():
        heading = HEADING_RE.match(raw)
        if heading:
            in_refs = heading.group(2).strip().lower() == "references"
            continue
        if in_refs:
            entries.update(
                match.group("name")
                for match in REF_MENTION_RE.finditer(raw)
                if not match.group("prefix")
            )
    return entries


def check_skill_file(path: Path, is_category: bool, failures: list[Failure]) -> None:
    keys, line = parse_frontmatter(path)
    if keys is None:
        failures.append(Failure(path, 1, "missing YAML frontmatter block (--- ... ---)"))
        keys = {}
    for key in REQUIRED_FRONTMATTER_KEYS:
        if key not in keys:
            failures.append(Failure(path, line, f"frontmatter missing required key: {key}"))
        elif key != "metadata" and not keys[key]:
            # `metadata` is a nested mapping (its own line carries no value);
            # scalar keys must have a non-empty value on the key line.
            failures.append(Failure(path, line, f"frontmatter key has empty value: {key}"))

    dags = [b for b in mermaid_blocks(path) if "flowchart" in b and "-->" in b]
    if not dags:
        failures.append(
            Failure(path, 1, "no decision DAG found: expected a ```mermaid flowchart with --> edges")
        )

    if is_category:
        if path.read_text(encoding="utf-8").count("platforms: [linux, macos]") != 1:
            failures.append(
                Failure(path, 1, "category frontmatter must declare platforms: [linux, macos]")
            )
        n_lines = len(path.read_text(encoding="utf-8").splitlines())
        if not 150 <= n_lines <= 350:
            failures.append(
                Failure(path, 1, f"category SKILL.md is {n_lines} lines, outside 150-350")
            )
        text_lines = path.read_text(encoding="utf-8").splitlines()
        has_exact = any(VERIFY_HEADING_EXACT_RE.match(l) for l in text_lines)
        if not has_exact:
            wrong = [
                (i, l.strip())
                for i, l in enumerate(text_lines, start=1)
                if VERIFY_HEADING_ANY_CASE_RE.match(l) and not VERIFY_HEADING_EXACT_RE.match(l)
            ]
            if wrong:
                for lineno, heading in wrong:
                    failures.append(
                        Failure(path, lineno, f"VERIFY heading must be exactly `## VERIFY` (found `{heading}`)")
                    )
            else:
                failures.append(Failure(path, 1, "missing exact `## VERIFY` section heading"))


def check_category_references(
    category_dir: Path, skill_path: Path, failures: list[Failure]
) -> None:
    refs_dir = category_dir / "references"
    actual = sorted(p.name for p in refs_dir.glob("*.md")) if refs_dir.is_dir() else []
    if not refs_dir.is_dir():
        failures.append(Failure(category_dir, 1, "missing references/ directory"))
    if not REF_MIN <= len(actual) <= REF_MAX:
        failures.append(
            Failure(
                skill_path,
                1,
                f"reference count {len(actual)} outside {REF_MIN}-{REF_MAX}",
            )
        )
    indexed = reference_index_entries(skill_path)
    for name in actual:
        if name not in indexed:
            failures.append(
                Failure(skill_path, 1, f"reference file not indexed under `## References`: references/{name}")
            )
    for name in sorted(indexed):
        if name not in actual:
            failures.append(
                Failure(skill_path, 1, f"indexed reference does not exist on disk: references/{name}")
            )
    for name in actual:
        ref_path = refs_dir / name
        n_lines = len(ref_path.read_text(encoding="utf-8").splitlines())
        if not REF_MIN_LINES <= n_lines <= REF_MAX_LINES:
            failures.append(
                Failure(
                    ref_path,
                    1,
                    f"reference is {n_lines} lines, outside {REF_MIN_LINES}-{REF_MAX_LINES} "
                    "(split or expand with real content — no padding)",
                )
            )


def check_links(path: Path, failures: list[Failure]) -> None:
    base = path.parent
    for lineno, text in prose_lines(path):
        for match in MD_LINK_RE.finditer(text):
            link_text, target = match.group(1), match.group(2)
            if REMOTE_RE.match(target):
                continue
            clean = target.split("#", 1)[0].split("?", 1)[0]
            if not clean:
                continue
            resolved = (base / clean).resolve()
            if not resolved.exists():
                label = link_text.strip() or target
                failures.append(
                    Failure(path, lineno, f"broken relative link `{target}` (text: {label[:60]!r})")
                )


def main() -> int:
    failures: list[Failure] = []

    md_files = sorted(p for p in REPO_ROOT.rglob("*.md") if ".git" not in p.parts)
    root_skill = REPO_ROOT / "SKILL.md"
    category_skills = sorted((REPO_ROOT / "skills").glob("*/SKILL.md"))

    for skill in [root_skill, *category_skills]:
        if not skill.is_file():
            failures.append(Failure(skill, 1, "SKILL.md missing"))
            continue
        check_skill_file(skill, is_category=skill.parent != REPO_ROOT, failures=failures)

    for skill in category_skills:
        check_category_references(skill.parent, skill, failures)

    for md in md_files:
        check_links(md, failures)

    readme = REPO_ROOT / "README.md"
    if readme.is_file():
        if "scripts/validate.py" not in readme.read_text(encoding="utf-8"):
            failures.append(
                Failure(readme, 1, "README does not document running `python3 scripts/validate.py`")
            )
    else:
        failures.append(Failure(readme, 1, "README.md missing"))

    license_path = REPO_ROOT / "LICENSE"
    if not license_path.is_file():
        failures.append(Failure(license_path, 1, "LICENSE file missing"))
    else:
        license_text = license_path.read_text(encoding="utf-8")
        if "MIT License" not in license_text or "Permission is hereby granted" not in license_text:
            failures.append(Failure(license_path, 1, "LICENSE does not look like the standard MIT text"))
        if "Alvaro Lizama" not in license_text:
            failures.append(Failure(license_path, 1, "LICENSE copyright line missing 'Alvaro Lizama'"))

    for failure in failures:
        print(failure)
    print(
        f"\n{len(md_files)} markdown files checked, "
        f"{len(category_skills)} categories, "
        f"{len(failures)} failure(s)."
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
