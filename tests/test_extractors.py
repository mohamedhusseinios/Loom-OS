"""Tests for the LLM knowledge extractor pipeline."""
import pytest
from daemon.extractors import RegexExtractor, ExtractorPipeline, ExtractedEntity


@pytest.mark.asyncio
async def test_regex_extractor_finds_code_entities():
    """RegexExtractor finds class/function/module names from text."""
    extractor = RegexExtractor()
    text = """
    The AuthService class handles user authentication.
    It calls the authenticate_user function and uses the bcrypt library.
    """
    entities = await extractor.extract(text)
    assert len(entities) >= 2
    names = [e.name for e in entities]
    assert "AuthService" in names


@pytest.mark.asyncio
async def test_regex_extractor_finds_pattern_keywords():
    """RegexExtractor detects architectural pattern keywords."""
    extractor = RegexExtractor()
    text = "We use a Factory pattern for creating database connections and a Singleton for the config."
    entities = await extractor.extract(text)
    names = [e.name for e in entities]
    assert any("Factory" in n for n in names) or any("Singleton" in n for n in names)


@pytest.mark.asyncio
async def test_regex_extractor_empty_for_plain_text():
    """RegexExtractor returns empty list for text without code entities."""
    extractor = RegexExtractor()
    entities = await extractor.extract("Just a simple sentence without any code references.")
    assert entities == []


@pytest.mark.asyncio
async def test_extractor_pipeline_runs_all_extractors():
    """Pipeline aggregates results from all registered extractors."""
    pipeline = ExtractorPipeline()
    pipeline.add(RegexExtractor())

    text = "AuthService class handles authentication. We use the Factory pattern."
    entities = await pipeline.run(text)

    assert len(entities) > 0
    # Each entity should have the required fields
    for e in entities:
        assert e.name
        assert e.kind
        assert 0 <= e.confidence <= 1


@pytest.mark.asyncio
async def test_extractor_pipeline_empty_on_no_extractors():
    """Pipeline with no extractors returns empty list."""
    pipeline = ExtractorPipeline()
    entities = await pipeline.run("some text")
    assert entities == []
