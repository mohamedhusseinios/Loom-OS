"""Family pattern documents and YAML validation."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = ("id", "name", "kind", "schema_version", "version", "status", "description")

KNOWN_FIELDS = frozenset(
    {
        *REQUIRED_FIELDS,
        "when_to_use",
        "anti_criteria",
        "steps",
        "graph",
        "allowed_tools",
        "required_capabilities",
        "expected_cost_class",
        "expected_steps",
        "runner",
    }
)

_STATUSES = ("active", "planned")
_COST_CLASSES = ("Low", "Med", "High")

FamilyStatus = Literal["active", "planned"]
CostClass = Literal["Low", "Med", "High"]


class PatternSchemaError(ValueError):
    """A pattern YAML document failed validation."""


@dataclass(frozen=True)
class PatternDoc:
    id: str
    name: str
    kind: Literal["family"]
    schema_version: int
    version: str | int
    status: FamilyStatus
    description: str
    when_to_use: list[str] = field(default_factory=list)
    anti_criteria: list[str] = field(default_factory=list)
    steps: list[Any] | None = None
    graph: dict[str, Any] | None = None
    allowed_tools: list[str] = field(default_factory=list)
    required_capabilities: list[str] = field(default_factory=list)
    expected_cost_class: CostClass | None = None
    expected_steps: str | int | None = None
    runner: str | None = None


def parse_family_doc(data: object, *, source: str) -> PatternDoc:
    if not isinstance(data, dict):
        raise PatternSchemaError(f"{source}: pattern document must be a mapping")

    for key in sorted(set(data) - KNOWN_FIELDS):
        logger.warning("%s: ignoring unknown field %r", source, key)

    missing = [name for name in REQUIRED_FIELDS if name not in data or data[name] is None]
    if missing:
        joined = ", ".join(missing)
        raise PatternSchemaError(f"{source}: missing required field(s): {joined}")

    schema_version = data["schema_version"]
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise PatternSchemaError(f"{source}: schema_version must be an int")

    kind = data["kind"]
    if kind != "family":
        raise PatternSchemaError(f"{source}: kind must be 'family'")

    status = data["status"]
    if status not in _STATUSES:
        raise PatternSchemaError(f"{source}: status must be 'active' or 'planned'")

    version = data["version"]
    if isinstance(version, bool) or not isinstance(version, (str, int)):
        raise PatternSchemaError(f"{source}: version must be a string or int")
    if isinstance(version, str) and not version.strip():
        raise PatternSchemaError(f"{source}: version must be a non-empty string")

    expected_cost_class = data.get("expected_cost_class")
    if expected_cost_class is not None and expected_cost_class not in _COST_CLASSES:
        raise PatternSchemaError(f"{source}: expected_cost_class must be Low, Med, or High")

    expected_steps = data.get("expected_steps")
    if expected_steps is not None and (isinstance(expected_steps, bool) or not isinstance(expected_steps, (str, int))):
        raise PatternSchemaError(f"{source}: expected_steps must be a string or int")

    steps = data.get("steps")
    if steps is not None and not isinstance(steps, list):
        raise PatternSchemaError(f"{source}: steps must be a list")

    graph = data.get("graph")
    if graph is not None and not isinstance(graph, dict):
        raise PatternSchemaError(f"{source}: graph must be a mapping")

    runner = data.get("runner")
    if runner is not None and not isinstance(runner, str):
        raise PatternSchemaError(f"{source}: runner must be a string")

    return PatternDoc(
        id=_require_text(data, "id", source),
        name=_require_text(data, "name", source),
        kind="family",
        schema_version=schema_version,
        version=version,
        status=status,
        description=_require_text(data, "description", source),
        when_to_use=_string_list(data, "when_to_use", source),
        anti_criteria=_string_list(data, "anti_criteria", source),
        steps=steps,
        graph=graph,
        allowed_tools=_string_list(data, "allowed_tools", source),
        required_capabilities=_string_list(data, "required_capabilities", source),
        expected_cost_class=expected_cost_class,
        expected_steps=expected_steps,
        runner=runner,
    )


def _require_text(data: dict, key: str, source: str) -> str:
    value = data[key]
    if not isinstance(value, str) or not value.strip():
        raise PatternSchemaError(f"{source}: {key} must be a non-empty string")
    return value


def _string_list(data: dict, key: str, source: str) -> list[str]:
    if key not in data or data[key] is None:
        return []
    value = data[key]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise PatternSchemaError(f"{source}: {key} must be a list of strings")
    return list(value)
