"""Tests for the family pattern schema loader."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from coding_agent.patterns import PatternDoc, PatternSchemaError, load_patterns

FAMILIES = Path(__file__).resolve().parents[1] / "coding_agent" / "patterns" / "families"

_REQUIRED = """\
id: {id}
name: {name}
kind: family
schema_version: {schema_version}
version: 1
status: {status}
description: {description}
"""


def _write(directory: Path, name: str, body: str) -> None:
    (directory / name).write_text(body, encoding="utf-8")


def _minimal(directory: Path, filename: str, **overrides: str) -> None:
    fields = {
        "id": "bare",
        "name": "Bare",
        "schema_version": "1",
        "status": "active",
        "description": "minimal family",
    }
    fields.update(overrides)
    _write(directory, filename, _REQUIRED.format(**fields))


def test_builtin_react_loads_as_active_family() -> None:
    registry = load_patterns(FAMILIES)
    doc = registry.get("react")

    assert isinstance(doc, PatternDoc)
    assert doc.id == "react"
    assert doc.name == "ReAct"
    assert doc.kind == "family"
    assert doc.schema_version == 1
    assert doc.version == 1
    assert doc.status == "active"
    assert doc.description
    assert doc.when_to_use
    assert doc.anti_criteria
    assert doc.steps
    assert doc.allowed_tools == [
        "read_file", "edit", "search", "shell", "git", "run_tests", "run_lint",
    ]
    assert doc.expected_cost_class == "Med"
    assert doc.runner == "react"


_LAUNCH_ACTIVE_IDS = frozenset({
    "react",
    "plan_then_execute",
    "tdd",
    "debug",
    "review_only",
})


def test_launch_catalog_has_five_active_families() -> None:
    registry = load_patterns(FAMILIES)
    active_ids = frozenset(doc.id for doc in registry.active_families())

    assert active_ids == _LAUNCH_ACTIVE_IDS
    planned = registry.get("orchestrator_workers")
    assert planned.status == "planned"
    assert "orchestrator_workers" not in active_ids
    assert "edit" not in registry.get("review_only").allowed_tools


def test_planned_family_excluded_from_active_families() -> None:
    registry = load_patterns(FAMILIES)
    planned = registry.get("orchestrator_workers")

    assert planned.status == "planned"
    assert planned.schema_version == 1
    active = registry.active_families()
    active_ids = {doc.id for doc in active}
    assert "orchestrator_workers" not in active_ids
    assert active_ids == _LAUNCH_ACTIVE_IDS
    assert all(doc.status == "active" for doc in active)


def test_missing_schema_version_raises(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "bad.yaml",
        """\
id: react
name: ReAct
kind: family
version: 1
status: active
description: loop without a schema version
""",
    )

    with pytest.raises(PatternSchemaError, match="schema_version"):
        load_patterns(tmp_path)


def test_schema_version_must_be_int(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "quoted.yaml",
        """\
id: quoted
name: Quoted
kind: family
schema_version: "1"
version: 1
status: active
description: schema version is a string
""",
    )

    with pytest.raises(PatternSchemaError, match="schema_version"):
        load_patterns(tmp_path)


def test_unknown_field_warns_and_loads(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    _write(
        tmp_path,
        "extra.yaml",
        """\
id: extra
name: Extra
kind: family
schema_version: 1
version: 1
status: active
description: has a future key
future_field: 1
""",
    )

    with caplog.at_level(logging.WARNING):
        registry = load_patterns(tmp_path)

    assert registry.get("extra").id == "extra"
    assert any("future_field" in record.message for record in caplog.records)


def test_missing_required_field_raises(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "noname.yaml",
        """\
id: noname
kind: family
schema_version: 1
version: 1
status: active
description: missing name
""",
    )

    with pytest.raises(PatternSchemaError, match="name"):
        load_patterns(tmp_path)


def test_optional_fields_default_when_absent(tmp_path: Path) -> None:
    _minimal(tmp_path, "bare.yaml")
    doc = load_patterns(tmp_path).get("bare")

    assert doc.when_to_use == []
    assert doc.anti_criteria == []
    assert doc.steps is None
    assert doc.graph is None
    assert doc.allowed_tools == []
    assert doc.required_capabilities == []
    assert doc.expected_cost_class is None
    assert doc.expected_steps is None
    assert doc.runner is None


def test_load_patterns_is_not_recursive_and_yaml_only(tmp_path: Path) -> None:
    _minimal(tmp_path, "top.yaml", id="top", name="Top", description="top level")
    nested = tmp_path / "nested"
    nested.mkdir()
    _minimal(nested, "hidden.yaml", id="hidden", name="Hidden", description="nested")
    _minimal(tmp_path, "skip.yml", id="yml", name="Yml", description="wrong suffix")
    _write(tmp_path, "notes.txt", "not a pattern\n")

    registry = load_patterns(tmp_path)

    assert registry.get("top").id == "top"
    with pytest.raises(KeyError):
        registry.get("hidden")
    with pytest.raises(KeyError):
        registry.get("yml")
