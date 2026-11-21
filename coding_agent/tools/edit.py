"""SEARCH/REPLACE apply: exact match, then one unique fuzzy line-window."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from coding_agent.ports import Sandbox

# Fuzzy runs only after exact search fails. A candidate is a contiguous
# line window with the same line count as `search`. difflib.SequenceMatcher
# ratio >= 0.9 (default autojunk). Overlapping windows collapse to the
# highest ratio; more than one remaining window is ambiguous.
FUZZY_RATIO_MIN = 0.9


@dataclass(frozen=True)
class ApplyResult:
    ok: bool
    reason: str | None


def apply_search_replace(path: Path, search: str, replace: str) -> ApplyResult:
    try:
        original = path.read_text(encoding="utf-8", newline="")
    except (OSError, UnicodeError):
        return ApplyResult(ok=False, reason="not_found")
    updated, result = _replace_text(original, search, replace)
    if result.ok and updated is not None:
        path.write_text(updated, encoding="utf-8", newline="")
    return result


def edit(sandbox: Sandbox, path: str, search: str, replace: str) -> dict:
    try:
        original = sandbox.read_text(path)
    except UnicodeDecodeError:
        return {"ok": False, "reason": "not_found"}
    except ValueError:
        return {"ok": False, "reason": "path_escape"}
    except OSError:
        return {"ok": False, "reason": "not_found"}
    updated, result = _replace_text(original, search, replace)
    if not result.ok or updated is None:
        return {"ok": False, "reason": result.reason}
    try:
        sandbox.write_text(path, updated)
    except ValueError:
        return {"ok": False, "reason": "path_escape"}
    return {"ok": True, "reason": None}


def _replace_text(text: str, search: str, replace: str) -> tuple[str | None, ApplyResult]:
    if search == "":
        return None, ApplyResult(ok=False, reason="not_found")
    count = text.count(search)
    if count > 1:
        return None, ApplyResult(ok=False, reason="multiple_matches")
    if count == 1:
        return text.replace(search, replace, 1), ApplyResult(ok=True, reason=None)
    spans = _fuzzy_spans(text, search)
    if not spans:
        return None, ApplyResult(ok=False, reason="not_found")
    if len(spans) > 1:
        return None, ApplyResult(ok=False, reason="ambiguous_fuzzy")
    start, end = spans[0]
    return text[:start] + replace + text[end:], ApplyResult(ok=True, reason=None)


def _strip_one_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return line[:-2]
    if line.endswith(("\n", "\r")):
        return line[:-1]
    return line


def _line_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    for line in text.splitlines(keepends=True):
        end = start + len(line)
        spans.append((start, end))
        start = end
    return spans


def _fuzzy_spans(text: str, search: str) -> list[tuple[int, int]]:
    search_lines = search.splitlines(keepends=True)
    window = len(search_lines)
    if window == 0:
        return []
    lines = _line_spans(text)
    if len(lines) < window:
        return []
    # Search without a final newline must not take the file line's ending,
    # or the splice eats that newline and merges the following line.
    search_keeps_end = search.endswith(("\n", "\r"))
    candidates: list[tuple[float, int, int]] = []
    for index in range(len(lines) - window + 1):
        start = lines[index][0]
        last_start, end = lines[index + window - 1]
        if not search_keeps_end:
            end = last_start + len(_strip_one_ending(text[last_start:end]))
        ratio = SequenceMatcher(a=text[start:end], b=search).ratio()
        if ratio >= FUZZY_RATIO_MIN:
            candidates.append((ratio, start, end))
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    chosen: list[tuple[int, int]] = []
    for _, start, end in candidates:
        if any(start < other_end and other_start < end for other_start, other_end in chosen):
            continue
        chosen.append((start, end))
    return chosen
