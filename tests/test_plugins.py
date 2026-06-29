"""Tests for the plugin discovery system."""
import pytest
from daemon.plugins import discover, load_into_pipeline
from daemon.extractors import ExtractorPipeline, Extractor, ExtractedEntity


def test_discover_empty_when_no_dir(tmp_path):
    assert discover(str(tmp_path)) == []


def test_discover_finds_valid_plugin(tmp_path):
    plugins_dir = tmp_path / "plugins" / "extractors"
    plugins_dir.mkdir(parents=True)
    (plugins_dir / "my_plugin.py").write_text(
        "from daemon.extractors import Extractor, ExtractedEntity\n"
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
    import asyncio
    results = asyncio.run(pipeline.run("some text"))
    assert any(e.name == "TODO" for e in results)


def test_discover_skips_underscore_files(tmp_path):
    plugins_dir = tmp_path / "plugins" / "extractors"
    plugins_dir.mkdir(parents=True)
    (plugins_dir / "__init__.py").write_text("")
    (plugins_dir / "_helper.py").write_text("")
    assert discover(str(tmp_path)) == []
