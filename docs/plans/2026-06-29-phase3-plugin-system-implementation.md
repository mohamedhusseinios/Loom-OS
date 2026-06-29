# Loom OS Phase 3 — Plugin System for Extractors — Implementation Plan

> **Source spec:** Feature #9. Builds on Phase 1's matured `ExtractorPipeline`.

**Goal:** Let the community contribute extractors via the existing `Extractor` ABC, discovered automatically from `~/.loom/plugins/extractors/`.

**Architecture:** `daemon/plugins.py` discovers `.py` files in the plugins directory on startup. Each file exposes `def register() -> Extractor`. Discovered extractors are added to the `ExtractorPipeline` after the built-ins. Broken plugins are skipped with a warning (pipeline already swallows exceptions). Dashboard lists discovered plugins.

## Task 9.1: `daemon/plugins.py` — discovery + loader

**Files:** Create `daemon/plugins.py`, Test: `tests/test_plugins.py`

```python
# daemon/plugins.py
"""Plugin discovery for community-contributed extractors.

Scans ``~/.loom/plugins/extractors/`` on startup for ``.py`` files that
expose a ``register() -> Extractor`` function. Broken plugins are skipped
with a warning — the pipeline already swallows per-extractor exceptions.
"""
from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def discover(loom_dir: str | None = None) -> list[dict]:
    """Discover extractor plugins in ``~/.loom/plugins/extractors/``.

    Returns a list of ``{"name": str, "extractor": Extractor | None, "error": str | None}``.
    Plugins that fail to load have ``extractor=None`` and an ``error`` message.
    """
    base = Path(loom_dir or os.path.expanduser("~/.loom")) / "plugins" / "extractors"
    if not base.exists():
        return []

    results: list[dict] = []
    for py_file in sorted(base.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        name = py_file.stem
        try:
            spec = importlib.util.spec_from_file_location(f"loom_plugin.{name}", py_file)
            if spec is None or spec.loader is None:
                raise ImportError(f"Cannot load {py_file}")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if not hasattr(mod, "register"):
                raise AttributeError(f"Plugin {name} has no register() function")
            extractor = mod.register()
            results.append({"name": name, "extractor": extractor, "error": None})
            logger.info("Plugin discovered: %s", name)
        except Exception as exc:
            logger.warning("Plugin %s failed to load: %s", name, exc)
            results.append({"name": name, "extractor": None, "error": str(exc)})
    return results


def load_into_pipeline(pipeline, loom_dir: str | None = None) -> list[str]:
    """Discover plugins and add working ones to an ExtractorPipeline.

    Returns the names of successfully loaded plugins.
    """
    loaded: list[str] = []
    for entry in discover(loom_dir):
        if entry["extractor"] is not None:
            pipeline.add(entry["extractor"])
            loaded.append(entry["name"])
    return loaded
```

**Tests:**
```python
# tests/test_plugins.py
import pytest
from pathlib import Path
from daemon.plugins import discover, load_into_pipeline
from daemon.extractors import ExtractorPipeline, Extractor, ExtractedEntity


def test_discover_empty_when_no_dir(tmp_path):
    assert discover(str(tmp_path)) == []


def test_discover_finds_valid_plugin(tmp_path):
    plugins_dir = tmp_path / "plugins" / "extractors"
    plugins_dir.mkdir(parents=True)
    (plugins_dir / "my_plugin.py").write_text(
        "from daemon.extractors import Extractor, ExtractedEntity\n"
        "import asyncio\n"
        "class MyExtractor(Extractor):\n"
        "    async def extract(self, text):\n"
        "        return [ExtractedEntity(name='test', kind='function')]\n"
        "def register():\n"
        "    return MyExtractor()\n"
    )
    results = discover(str(tmp_path))
    assert len(results) == 1
    assert results[0]["name"] == "my_plugin"
    assert results[0]["extractor"] is not None
    assert results[0]["error"] is None


def test_discover_skips_broken_plugin(tmp_path):
    plugins_dir = tmp_path / "plugins" / "extractors"
    plugins_dir.mkdir(parents=True)
    (plugins_dir / "broken.py").write_text("raise RuntimeError('boom')")
    results = discover(str(tmp_path))
    assert len(results) == 1
    assert results[0]["name"] == "broken"
    assert results[0]["extractor"] is None
    assert "boom" in results[0]["error"]


def test_discover_skips_missing_register(tmp_path):
    plugins_dir = tmp_path / "plugins" / "extractors"
    plugins_dir.mkdir(parents=True)
    (plugins_dir / "no_register.py").write_text("x = 1\n")
    results = discover(str(tmp_path))
    assert results[0]["extractor"] is None
    assert "register" in results[0]["error"]


def test_load_into_pipeline_adds_working_plugins(tmp_path):
    plugins_dir = tmp_path / "plugins" / "extractors"
    plugins_dir.mkdir(parents=True)
    (plugins_dir / "todo_scanner.py").write_text(
        "from daemon.extractors import Extractor, ExtractedEntity\n"
        "class TodoScanner(Extractor):\n"
        "    async def extract(self, text):\n"
        "        return [ExtractedEntity(name='TODO', kind='pattern')]\n"
        "def register():\n"
        "    return TodoScanner()\n"
    )
    pipeline = ExtractorPipeline()
    loaded = load_into_pipeline(pipeline, str(tmp_path))
    assert "todo_scanner" in loaded
    # Verify the pipeline actually runs the plugin
    import asyncio
    results = asyncio.get_event_loop().run_until_complete(pipeline.run("some text"))
    assert any(e.name == "TODO" for e in results)


def test_discover_skips_underscore_files(tmp_path):
    plugins_dir = tmp_path / "plugins" / "extractors"
    plugins_dir.mkdir(parents=True)
    (plugins_dir / "__init__.py").write_text("")
    (plugins_dir / "_helper.py").write_text("")
    assert discover(str(tmp_path)) == []
```

## Task 9.2: Wire plugin loading into daemon lifespan

**Files:** Modify `daemon/api.py` lifespan, Modify `daemon/api.py` (add plugins endpoint)

In `api.py` lifespan, after building the built-in pipeline, call `load_into_pipeline`:
```python
from daemon.plugins import load_into_pipeline
loaded_plugins = load_into_pipeline(_pipeline)
logger.info("Loaded %d extractor plugins", len(loaded_plugins))
```

Add endpoint:
```python
@app.get("/api/plugins")
async def list_plugins():
    """List discovered extractor plugins."""
    from daemon.plugins import discover
    plugins = discover()
    return {"plugins": [
        {"name": p["name"], "loaded": p["extractor"] is not None, "error": p["error"]}
        for p in plugins
    ]}
```

Add test:
```python
def test_plugins_endpoint_empty(client):
    resp = client.get("/api/plugins")
    assert resp.status_code == 200
    assert resp.json() == {"plugins": []}
```

## Task 9.3: Example plugins + dashboard surface

**Files:**
- Create `examples/plugins/todo_scanner.py`, `examples/plugins/git_history.py`, `examples/plugins/python_patterns.py`
- Create `dashboard/components/plugin-list.tsx`
- Modify `dashboard/lib/api.ts`, `dashboard/messages/en.json`, `dashboard/messages/ar.json`

Each example plugin:
```python
# examples/plugins/todo_scanner.py
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

Dashboard: `plugin-list.tsx` showing discovered plugins with loaded/error status.
