"""Ensure coding_agent stays extractable (no daemon dependency)."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import zipfile
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


def test_wheel_packages_coding_agent_and_family_yaml(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[1]
    wheel_dir = tmp_path / "wheels"
    wheel_dir.mkdir()
    built = subprocess.run(
        [
            sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
            "-w", str(wheel_dir), str(repo),
        ],
        capture_output=True,
        text=True,
    )
    assert built.returncode == 0, built.stderr
    wheels = list(wheel_dir.glob("*.whl"))
    assert len(wheels) == 1
    names = zipfile.ZipFile(wheels[0]).namelist()
    assert any(name.startswith("coding_agent/") and name.endswith("__init__.py") for name in names)
    assert any(name.endswith("patterns/families/react.yaml") for name in names)
    assert any(name.startswith("daemon/") and name.endswith("__init__.py") for name in names)


def test_installed_import_ignores_repo_pythonpath() -> None:
    """Import both packages from /tmp with PYTHONPATH cleared (editable install)."""
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    probe = (
        "import coding_agent, daemon.agent_run\n"
        "from importlib.resources import files\n"
        "yaml_path = files('coding_agent') / 'patterns' / 'families' / 'react.yaml'\n"
        "text = yaml_path.read_text(encoding='utf-8')\n"
        "assert 'id: react' in text, text\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd="/tmp",
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr