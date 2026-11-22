"""Built-in pattern families."""

from coding_agent.patterns.registry import PatternRegistry, load_patterns
from coding_agent.patterns.schema import PatternDoc, PatternSchemaError

__all__ = [
    "PatternDoc",
    "PatternRegistry",
    "PatternSchemaError",
    "load_patterns",
]
