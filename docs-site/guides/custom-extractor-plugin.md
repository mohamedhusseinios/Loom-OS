# Custom extractor plugin

The knowledge-extraction pipeline that runs over every `finding-*.md` and `decision-*.md` body is extensible: drop a Python file into `~/.loom/plugins/extractors/`, and the daemon auto-discovers and loads it at startup.

## The `Extractor` contract

Every extractor — built-in or third-party — implements the same abstract base class (`daemon/extractors.py`):

```python
import abc

class Extractor(abc.ABC):
    """Contract for an entity extractor."""

    @abc.abstractmethod
    async def extract(self, text: str) -> list[ExtractedEntity]:
        """Return a list of entities found in *text*."""
        ...
```

`ExtractedEntity` carries a `name`, `kind` (e.g. `"class"`, `"function"`, `"pattern"`), a `confidence` score clamped to `[0.0, 1.0]`, optional `context`, and optional `relationships` (a list of `(verb, target)` tuples).

## Writing a plugin

A plugin is a single `.py` file that defines an `Extractor` subclass and a module-level `register() -> Extractor` function. Here's the bundled example that scans for TODO/FIXME/HACK comments (`examples/plugins/todo_scanner.py`):

```python
"""Example Loom extractor plugin: scans for TODO/FIXME/HACK comments."""
import re
from daemon.extractors import Extractor, ExtractedEntity

_TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX|BUG)\b", re.IGNORECASE)

class TodoScanner(Extractor):
    async def extract(self, text: str) -> list[ExtractedEntity]:
        entities = []
        seen = set()
        for m in _TODO_RE.finditer(text):
            tag = m.group(1).upper()
            if tag not in seen:
                seen.add(tag)
                entities.append(ExtractedEntity(
                    name=tag, kind="pattern", confidence=0.8,
                    context="code annotation",
                ))
        return entities

def register():
    return TodoScanner()
```

Two more examples ship in `examples/plugins/`: `git_history.py` (extracts entities from git commit messages) and `python_patterns.py` (detects Python design patterns).

## Installing it

Drop the file into the plugins directory for your project-agnostic Loom install:

```bash
mkdir -p ~/.loom/plugins/extractors
cp examples/plugins/todo_scanner.py ~/.loom/plugins/extractors/todo_scanner.py
```

## Auto-discovery

On startup (and whenever the pipeline is rebuilt), `daemon/plugins.py`'s `discover()` scans `~/.loom/plugins/extractors/*.py`:

- Files starting with `_` are skipped.
- Each remaining file is imported dynamically via `importlib.util`.
- The module must expose a `register()` function; its return value is treated as an `Extractor` instance.
- A plugin that fails to import, has no `register()`, or errors during `register()` is **skipped with a warning** — it doesn't crash the daemon or the rest of the pipeline. `discover()` returns `{"name", "extractor", "error"}` for every file found, so failures are inspectable.

`load_into_pipeline(pipeline)` wraps `discover()` and appends every successfully-loaded extractor onto an `ExtractorPipeline` via its `.add()` method, returning the names of plugins that loaded. The pipeline already swallows per-extractor exceptions raised during `.extract()` at runtime, so one bad extractor can't take down extraction for the others.

## See also

- [The knowledge graph](../concepts/knowledge-graph.md) — how extracted entities become sidecar edges queried by [hybrid search](hybrid-search.md).
- `examples/plugins/` in the repo — `git_history.py` and `python_patterns.py` for two more worked examples.
