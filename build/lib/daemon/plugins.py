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
