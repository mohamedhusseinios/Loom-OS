"""Ensure coding_agent stays extractable (no daemon dependency)."""

from __future__ import annotations

import ast
from pathlib import Path


def _collect_import_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test_coding_agent_tree_does_not_import_daemon():
    package_root = Path(__file__).resolve().parent.parent / "coding_agent"
    py_files = sorted(package_root.rglob("*.py"))
    assert py_files, f"no Python files under {package_root}"

    violations: list[tuple[Path, str]] = []
    for path in py_files:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        if "daemon" in _collect_import_roots(tree):
            violations.append((path, "daemon"))

    assert not violations, "daemon imports found: " + ", ".join(f"{p.relative_to(package_root.parent)}" for p, _ in violations)