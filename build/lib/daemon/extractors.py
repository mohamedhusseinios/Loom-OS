"""Knowledge extraction pipeline — extracts entities and patterns from text.

Design:
- ``Extractor`` is an abstract base that defines the contract every extractor
  must fulfill.
- ``RegexExtractor`` is a zero-dependency fallback that uses regex to find
  CamelCase identifiers, function patterns, and architectural keywords.
  It always works (no LLM required).
- ``LLMExtractor`` (future) wraps an Ollama/OpenAI/Claude call with
  structured prompt templates inspired by Graphiti.
- ``ExtractorPipeline`` chains multiple extractors together, deduplicates
  results, and normalizes confidence scores.
"""

from __future__ import annotations

import abc
import json as _json
import logging
import os
import re
from typing import TYPE_CHECKING, Awaitable, Callable

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------

class ExtractedEntity:
    """A single entity or relationship found in text."""

    def __init__(
        self,
        name: str,
        kind: str,
        confidence: float = 0.5,
        context: str = "",
        relationships: list[tuple[str, str]] | None = None,
    ):
        self.name = name
        self.kind = kind        # e.g. "class", "function", "pattern", "module"
        self.confidence = min(max(confidence, 0.0), 1.0)
        self.context = context
        self.relationships = relationships or []

    def __repr__(self) -> str:
        return f"<ExtractedEntity {self.kind}={self.name!r} conf={self.confidence:.2f}>"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "confidence": self.confidence,
            "context": self.context,
            "relationships": self.relationships,
        }


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class Extractor(abc.ABC):
    """Contract for an entity extractor."""

    @abc.abstractmethod
    async def extract(self, text: str) -> list[ExtractedEntity]:
        """Return a list of entities found in *text*."""
        ...


# ---------------------------------------------------------------------------
# Regex-based extractor (always-on fallback)
# ---------------------------------------------------------------------------

# CamelCase or PascalCase identifiers
_CAMEL_PATTERN = re.compile(r"\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\b")

# snake_case function names (word_word)
_SNAKE_FUNC = re.compile(r"\b([a-z]+(?:_[a-z]+)+)\s*\(")

# Architecture / pattern keywords
_PATTERN_KEYWORDS = {
    "factory": "Factory Pattern",
    "singleton": "Singleton Pattern",
    "observer": "Observer Pattern",
    "strategy": "Strategy Pattern",
    "adapter": "Adapter Pattern",
    "decorator": "Decorator Pattern",
    "repository": "Repository Pattern",
    "dependency injection": "Dependency Injection",
    "middleware": "Middleware",
    "service": "Service",
    "controller": "Controller",
    "module": "Module",
    "pipeline": "Pipeline",
}

# Entity type keywords
_TYPE_HINTS = {
    "class": "class",
    "function": "function",
    "module": "module",
    "interface": "interface",
    "enum": "enum",
}


class RegexExtractor(Extractor):
    """Extract entities using regex patterns (zero LLM dependency).

    Finds:
    - CamelCase identifiers (likely class/type names) with medium confidence.
    - snake_case function names with lower confidence.
    - Architectural pattern keywords from a curated dictionary.
    """

    def __init__(self):
        pass

    async def extract(self, text: str) -> list[ExtractedEntity]:
        entities: list[ExtractedEntity] = []
        seen: set[str] = set()

        # --- CamelCase identifiers ---
        for match in _CAMEL_PATTERN.finditer(text):
            name = match.group(1)
            if name in seen:
                continue
            seen.add(name)
            # Try to infer type from surrounding context
            kind = self._infer_type(text, match.start(), name)
            entities.append(ExtractedEntity(
                name=name,
                kind=kind,
                confidence=0.65,
                context=self._snippet(text, match.start(), 80),
            ))

        # --- snake_case function calls ---
        for match in _SNAKE_FUNC.finditer(text):
            name = match.group(1)
            if name in seen:
                continue
            seen.add(name)
            entities.append(ExtractedEntity(
                name=name,
                kind="function",
                confidence=0.55,
                context=self._snippet(text, match.start(), 80),
            ))

        # --- Pattern keywords ---
        text_lower = text.lower()
        for keyword, label in _PATTERN_KEYWORDS.items():
            if keyword in text_lower and label not in seen:
                seen.add(label)
                entities.append(ExtractedEntity(
                    name=label,
                    kind="pattern",
                    confidence=0.70,
                    context=keyword,
                ))

        return entities

    @staticmethod
    def _infer_type(text: str, pos: int, name: str) -> str:
        """Guess the entity type from surrounding words."""
        window_start = max(0, pos - 40)
        before = text[window_start:pos].lower()
        for hint, kind in _TYPE_HINTS.items():
            if hint in before:
                return kind
        return "class"  # default for CamelCase

    @staticmethod
    def _snippet(text: str, pos: int, width: int) -> str:
        """Return a short context window around position."""
        start = max(0, pos - width // 2)
        end = min(len(text), pos + width // 2)
        return text[start:end].replace("\n", " ").strip()


# ---------------------------------------------------------------------------
# LLM-backed extractor (Ollama / OpenAI / Claude)
# ---------------------------------------------------------------------------

_LLM_PROMPT = """You extract code/architecture entities from an engineering note.
Return ONLY minified JSON: {"entities": [{"name","kind","confidence","context","relationships"}]}
- kind is one of: class, function, module, pattern, interface, enum.
- confidence is 0.0-1.0.
- relationships is a list of [verb, target] pairs (may be empty).
NOTE:
%s
"""


class LLMExtractor(Extractor):
    """Extract entities via a configurable LLM backend (Ollama/OpenAI/Claude).

    The backend call is injectable (`call_fn`) so tests run with no live model.
    Any failure (no backend, network error, bad JSON) degrades to an empty list;
    ExtractorPipeline already swallows extractor exceptions, so extraction never
    blocks finding ingestion.
    """

    def __init__(
        self,
        backend: str = "ollama",
        model: str | None = None,
        call_fn: Callable[[str], Awaitable[str]] | None = None,
    ):
        self.backend = os.getenv("LOOM_LLM_BACKEND", backend)
        self.model = os.getenv("LOOM_LLM_MODEL", model or "")
        self._call_fn = call_fn  # injected in tests; real backends wired in Task 1.2

    async def extract(self, text: str) -> list[ExtractedEntity]:
        call = self._call_fn or self._default_call
        try:
            raw = await call(_LLM_PROMPT % text[:4000])
            data = _json.loads(raw)
        except Exception as exc:
            logger.debug("LLMExtractor degraded (%s): %s", self.backend, exc)
            return []
        return self._to_entities(data)

    async def _default_call(self, prompt: str) -> str:
        """Call the configured backend. All client imports are lazy/optional."""
        if self.backend == "ollama":
            import httpx  # part of dev deps; ollama exposes HTTP on 11434
            model = self.model or "llama3.1"
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "http://127.0.0.1:11434/api/generate",
                    json={"model": model, "prompt": prompt, "format": "json", "stream": False},
                )
                resp.raise_for_status()
                return resp.json().get("response", "")
        if self.backend == "openai":
            from openai import AsyncOpenAI  # optional dep
            client = AsyncOpenAI()
            r = await client.chat.completions.create(
                model=self.model or "gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
            return r.choices[0].message.content or ""
        if self.backend in ("claude", "anthropic"):
            from anthropic import AsyncAnthropic  # optional dep
            client = AsyncAnthropic()
            r = await client.messages.create(
                model=self.model or "claude-haiku-4-5-20251001",
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            return "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
        raise RuntimeError(f"unknown LLM backend: {self.backend}")

    @staticmethod
    def _to_entities(data: dict) -> list[ExtractedEntity]:
        out: list[ExtractedEntity] = []
        for item in data.get("entities", []):
            if not item.get("name") or not item.get("kind"):
                continue
            rels = [tuple(r) for r in item.get("relationships", []) if len(r) == 2]
            out.append(ExtractedEntity(
                name=str(item["name"]),
                kind=str(item["kind"]),
                confidence=float(item.get("confidence", 0.5)),
                context=str(item.get("context", "")),
                relationships=rels,
            ))
        return out


# ---------------------------------------------------------------------------
# Extractor pipeline
# ---------------------------------------------------------------------------

class ExtractorPipeline:
    """Run multiple extractors in sequence and merge results.

    Deduplication is based on (name, kind) tuples; the first occurrence
    wins (extractors earlier in the chain have priority).
    """

    def __init__(self):
        self._extractors: list[Extractor] = []

    def add(self, extractor: Extractor):
        """Append an extractor to the pipeline."""
        self._extractors.append(extractor)

    async def run(self, text: str) -> list[ExtractedEntity]:
        """Run all registered extractors and return deduplicated results."""
        seen: set[tuple[str, str]] = set()
        results: list[ExtractedEntity] = []

        for extractor in self._extractors:
            try:
                entities = await extractor.extract(text)
            except Exception as exc:
                logger.warning(
                    "Extractor %s failed: %s", type(extractor).__name__, exc
                )
                continue

            for entity in entities:
                key = (entity.name, entity.kind)
                if key not in seen:
                    seen.add(key)
                    results.append(entity)

        return results
