"""LangChain memory implementation backed by Loom OS.

Writes agent findings and decisions to the Loom inbox so they're shared
across the multi-agent fabric. Reads the shared context back as memory
variables.

Compatible with both LangChain v0.3+ (where BaseMemory was in langchain.memory)
and the newer langchain-core-only setup. Falls back to a local Protocol if
neither is available.
"""
from __future__ import annotations

from typing import Any, Dict, List, Protocol, runtime_checkable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from loom_client import LoomClient


# Try to import BaseMemory from the available LangChain package.
# In langchain v0.3 it's in langchain.memory; in older versions langchain_core.memory.
# If neither is installed, we define a compatible Protocol.
_BaseMemoryBase = None

try:
    from langchain.memory import BaseMemory as _BaseMemoryBase
except ImportError:
    try:
        from langchain_core.memory import BaseMemory as _BaseMemoryBase
    except ImportError:
        # No LangChain installed — use a minimal Protocol so the class
        # still works standalone and passes isinstance checks.
        @runtime_checkable
        class _BaseMemoryBase(Protocol):
            @property
            def memory_variables(self) -> List[str]: ...
            def load_memory_variables(self, inputs: Dict[str, Any]) -> Dict[str, Any]: ...
            def save_context(self, inputs: Dict[str, Any], outputs: Dict[str, str]) -> None: ...
            def clear(self) -> None: ...


class LoomMemory(BaseModel if _BaseMemoryBase is Protocol else _BaseMemoryBase):
    """Loom OS memory backend for LangChain agents.

    Each ``save_context`` writes a finding to the Loom inbox so the daemon
    processes it, runs extractors, and regenerates the shared context.
    ``load_memory_variables`` reads ``SHARED_CONTEXT.md`` from the project,
    giving the agent the full knowledge graph overview, recent findings,
    and the agent roster.

    Usage::

        from langchain_loom import LoomMemory

        memory = LoomMemory(
            project="my-app",
            agent="langchain-agent",
            project_path="/path/to/project",
        )
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
