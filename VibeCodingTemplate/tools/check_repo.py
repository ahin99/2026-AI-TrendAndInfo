"""Dependency-free repository checks used locally and in tests."""

from __future__ import annotations

import ast
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    errors: list[str] = []
    paths = sorted((ROOT / "src").rglob("*.py")) + sorted(
        (ROOT / "tests").rglob("*.py")
    )
    for path in paths:
        text = path.read_text(encoding="utf-8")
        try:
            ast.parse(text, filename=str(path))
        except SyntaxError as exc:
            errors.append(f"{path.relative_to(ROOT)}:{exc.lineno}: {exc.msg}")
        for number, line in enumerate(text.splitlines(), start=1):
            if line.rstrip() != line:
                errors.append(f"{path.relative_to(ROOT)}:{number}: trailing whitespace")

    for name, command in (
        ("sync-notion.yml", "bash tools/commit_session.sh sync"),
        ("generate-quiz.yml", "bash tools/commit_session.sh quiz"),
    ):
        path = ROOT / ".github" / "workflows" / name
        if not path.is_file():
            errors.append(f"missing workflow: {name}")
            continue
        text = path.read_text(encoding="utf-8")
        required = (
            "workflow_dispatch:",
            "contents: write",
            "group: study-quiz-${{ github.ref }}",
            "python -m study_quiz",
            command,
        )
        for marker in required:
            if marker not in text:
                errors.append(f"{name}: missing {marker!r}")
        if text.count("env:") != len(set(_duplicate_mapping_lines(text, "env:"))):
            errors.append(f"{name}: duplicate env mapping at one indentation level")

    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"repository checks passed ({len(paths)} Python files)")
    return 0


def _duplicate_mapping_lines(text: str, key: str) -> list[tuple[int, int]]:
    """Return unique (indent, nearest step line) occurrences for a YAML key."""
    groups: list[tuple[int, int]] = []
    step = -1
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("- name:"):
            step = number
        if stripped == key:
            groups.append((len(line) - len(stripped), step))
    return groups


if __name__ == "__main__":
    raise SystemExit(main())
