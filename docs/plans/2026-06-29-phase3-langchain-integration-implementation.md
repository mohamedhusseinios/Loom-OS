# Loom OS Phase 3 — LangChain Integration — Implementation Plan

> **Source spec:** Feature #10. Wraps #5's SDK (already shipped).

**Goal:** Discoverability in the LangChain ecosystem via a `langchain-loom` package implementing `BaseMemory`.

**Architecture:** Thin wrapper over `loom-client`. `langchain-loom` implements LangChain's `BaseMemory` interface (`load_memory_variables`, `save_context`, `clear`). No daemon changes.

## Task 10.1: `langchain-loom` package

**Files:**
- Create `integrations/langchain-loom/pyproject.toml`
- Create `integrations/langchain-loom/langchain_loom/__init__.py`
- Create `integrations/langchain-loom/langchain_loom/memory.py`
- Create `integrations/langchain-loom/tests/test_memory.py`
- Create `integrations/langchain-loom/README.md`
- Create `integrations/langchain-loom/examples/basic_usage.py`

```python
# integrations/langchain-loom/langchain_loom/memory.py
"""LangChain BaseMemory implementation backed by Loom OS.

Writes agent findings and decisions to the Loom inbox so they're shared
across the multi-agent fabric. Reads the shared context back as memory
variables.
"""
from __future__ import annotations

from typing import Any, Dict, List
from langchain_core.memory import BaseMemory
from pydantic import Field

from loom_client import LoomClient


class LoomMemory(BaseMemory):
    """LangChain memory backed by Loom OS.
    
    Each save_context writes a finding to the Loom inbox.
    load_memory_variables returns the project's shared context.
    """

    loom_client: LoomClient = Field(default_factory=LoomClient)
    project: str = ""
    agent: str = "langchain-agent"
    project_path: str = "."

    class Config:
        arbitrary_types_allowed = True

    @property
    def memory_variables(self) -> List[str]:
        return ["loom_context"]

    def load_memory_variables(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Return the shared context as a memory variable."""
        # Read the SHARED_CONTEXT.md if it exists
        from pathlib import Path
        context_path = Path(self.project_path) / ".loom" / "SHARED_CONTEXT.md"
        if context_path.exists():
            return {"loom_context": context_path.read_text()[:4000]}
        return {"loom_context": ""}

    def save_context(self, inputs: Dict[str, Any], outputs: Dict[str, str]) -> None:
        """Write the interaction as a finding to the Loom inbox."""
        input_text = inputs.get("input", str(inputs))
        output_text = outputs.get("output", str(outputs))
        self.loom_client.finding(
            project=self.project,
            agent=self.agent,
            title=f"Interaction: {input_text[:60]}",
            body=f"**Input:** {input_text[:500]}\n\n**Output:** {output_text[:500]}",
            type="general",
        )

    def clear(self) -> None:
        """Clear is a no-op — Loom findings are durable."""
        pass
```

**Test:**
```python
# integrations/langchain-loom/tests/test_memory.py
import pytest
from pathlib import Path
from langchain_loom.memory import LoomMemory


def test_loom_memory_load_returns_empty_when_no_context(tmp_path):
    mem = LoomMemory(project="p", project_path=str(tmp_path))
    result = mem.load_memory_variables({})
    assert "loom_context" in result
    assert result["loom_context"] == ""


def test_loom_memory_load_reads_shared_context(tmp_path):
    loom_dir = tmp_path / ".loom"
    loom_dir.mkdir()
    (loom_dir / "SHARED_CONTEXT.md").write_text("# Shared Context\nTest data")
    mem = LoomMemory(project="p", project_path=str(tmp_path))
    result = mem.load_memory_variables({})
    assert "Test data" in result["loom_context"]


def test_loom_memory_save_writes_finding(tmp_path):
    from langchain_loom.memory import LoomMemory
    from loom_client import LoomClient
    
    client = LoomClient(loom_dir=str(tmp_path / "loom"))
    mem = LoomMemory(
        loom_client=client,
        project="p",
        agent="test-agent",
        project_path=str(tmp_path),
    )
    mem.save_context(
        inputs={"input": "What is the auth module?"},
        outputs={"output": "AuthService handles login."},
    )
    # Verify a finding was written
    inbox = tmp_path / "loom" / "inbox" / "p"
    findings = list(inbox.glob("finding-*.md"))
    assert len(findings) == 1
    content = findings[0].read_text()
    assert "auth module" in content
    assert "AuthService" in content


def test_loom_memory_clear_is_noop():
    mem = LoomMemory(project="p")
    mem.clear()  # should not raise
```

**pyproject.toml:**
```toml
[project]
name = "langchain-loom"
version = "0.1.0"
description = "LangChain memory integration for Loom OS"
requires-python = ">=3.11"
license = { text = "MIT" }
dependencies = ["loom-client", "langchain-core>=0.3.0"]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.24.0"]

[build-system]
requires = ["setuptools>=75.0"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["langchain_loom*"]
```
