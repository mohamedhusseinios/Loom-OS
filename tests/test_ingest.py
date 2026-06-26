"""Tests for the DocumentIngestor."""
import json
import pytest
from pathlib import Path
from daemon.ingest import DocumentIngestor


@pytest.fixture
def ingestor(tmp_path):
    return DocumentIngestor(loom_dir=str(tmp_path))


@pytest.mark.asyncio
async def test_ingest_text_file(ingestor, tmp_path):
    """Plain text files are ingested and written as findings."""
    txt_file = tmp_path / "notes.txt"
    txt_file.write_text("Important: the database uses PostgreSQL 16.")

    result = await ingestor.ingest_file(str(txt_file), project="proj")
    assert result["status"] == "ingested"
    assert result["finding_id"]

    # Check that a finding was written
    inbox = tmp_path / "inbox" / "proj"
    findings = list(inbox.glob("finding-*.md"))
    assert len(findings) == 1
    content = findings[0].read_text()
    assert "PostgreSQL" in content


@pytest.mark.asyncio
async def test_ingest_markdown_file(ingestor, tmp_path):
    """Markdown files are ingested."""
    md_file = tmp_path / "docs.md"
    md_file.write_text("# Architecture\nUses hexagonal architecture.")

    result = await ingestor.ingest_file(str(md_file), project="proj")
    assert result["status"] == "ingested"


@pytest.mark.asyncio
async def test_ingest_json_file(ingestor, tmp_path):
    """JSON files are ingested with structure description."""
    json_file = tmp_path / "config.json"
    json_file.write_text(json.dumps({
        "database": "postgres",
        "host": "localhost",
        "port": 5432,
    }))

    result = await ingestor.ingest_file(str(json_file), project="proj")
    assert result["status"] == "ingested"

    inbox = tmp_path / "inbox" / "proj"
    finding = list(inbox.glob("finding-*.md"))[0].read_text()
    assert "database: postgres" in finding


@pytest.mark.asyncio
async def test_ingest_unsupported_format(ingestor, tmp_path):
    """Unsupported formats return an error."""
    bin_file = tmp_path / "image.png"
    bin_file.write_bytes(b"\x89PNG")

    result = await ingestor.ingest_file(str(bin_file), project="proj")
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_ingest_nonexistent_file(ingestor):
    """Nonexistent files return an error."""
    result = await ingestor.ingest_file("/nonexistent/file.txt", project="proj")
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_ingest_directory(ingestor, tmp_path):
    """Directory ingestion processes all supported files."""
    proj_dir = tmp_path / "docs"
    proj_dir.mkdir()
    (proj_dir / "readme.md").write_text("# Project")
    (proj_dir / "notes.txt").write_text("Notes")
    (proj_dir / "image.png").write_bytes(b"\x89PNG")

    results = await ingestor.ingest_directory(str(proj_dir), project="proj")
    assert len(results) == 3
    ingested = [r for r in results if r["status"] == "ingested"]
    assert len(ingested) == 2  # skip png
