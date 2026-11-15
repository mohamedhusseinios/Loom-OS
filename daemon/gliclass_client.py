"""Knowledgator GLiClass filter client.

Talks to a separate Knowledgator serve process over HTTP (``POST /gliclass``).
The daemon does not load PyTorch or that package. Phase 1 ``judge`` is skipped
with reason ``unsupported``.

The serve process drops labels below ``threshold``. This client sends
``threshold=0`` so the relevant score is still returned; band cutoffs stay in
the decision layer.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

logger = logging.getLogger("loom.gliclass")

GLICLASS_PATH = "/gliclass"
RELEVANT_LABEL = "relevant"
OTHER_LABEL = "not_relevant"
DEFAULT_THRESHOLD = 0.0
DEFAULT_TIMEOUT_SEC = 5.0
MAX_FILTER_WORKERS = 8
_SKIP_REASONS = frozenset({"error", "timeout", "bad_payload", "unsupported"})


class _WireError(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason if reason in _SKIP_REASONS else "error"


def resolve_gliclass_url(base_url: str | None) -> str:
    """Append ``/gliclass`` unless ``base_url`` already ends with that path."""
    url = (base_url or "").strip().rstrip("/")
    if not url:
        return ""
    if url.endswith(GLICLASS_PATH):
        return url
    return f"{url}{GLICLASS_PATH}"


def _is_timeout(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    reason = getattr(exc, "reason", None)
    return isinstance(reason, TimeoutError)


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0


def _clamp_unit(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number < 0.0:
        return 0.0
    if number > 1.0:
        return 1.0
    return number


def _status_text(status: Any) -> str:
    if hasattr(status, "value"):
        status = status.value
    if status is None:
        return ""
    return str(status)


def _task_view(task: Any) -> dict[str, str]:
    if isinstance(task, dict):
        title = task.get("title") or ""
        instruction = task.get("instruction") or ""
        status = task.get("status")
    elif task is None:
        title, instruction, status = "", "", ""
    else:
        title = getattr(task, "title", "") or ""
        instruction = getattr(task, "instruction", "") or ""
        status = getattr(task, "status", "")
    return {"title": str(title), "instruction": str(instruction), "status": _status_text(status)}


def _hit_text(task: Any, hit: dict, index: int) -> str:
    view = _task_view(task)
    nid = hit.get("id") or hit.get("name") or f"hit-{index}"
    label = hit.get("label") or hit.get("text") or hit.get("type") or ""
    return f"Task: {view['title']}\n{view['instruction']}\nNode {nid}: {label}"


def _prediction_rows(payload: Any) -> list:
    if isinstance(payload, list) and payload and all(isinstance(item, list) for item in payload):
        return list(payload[0])
    if isinstance(payload, list):
        return payload
    raise _WireError("bad_payload")


def _relevant_score(payload: Any) -> float | None:
    for item in _prediction_rows(payload):
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip().lower()
        if label != RELEVANT_LABEL:
            continue
        return _clamp_unit(item.get("score"))
    return None


class GLiClassClient:
    """Filter-only client for Knowledgator ``POST /gliclass``."""

    def __init__(self, base_url: str = "", model: str = "", timeout: float = DEFAULT_TIMEOUT_SEC, threshold: float = DEFAULT_THRESHOLD):
        self.base_url = (base_url or "").strip().rstrip("/")
        self.model = model or ""
        self.timeout = timeout
        self.threshold = threshold

    @property
    def available(self) -> bool:
        return bool(self.base_url)

    def filter_relevance(self, *, pack: str, task: Any, catalog: list[dict], hits: list[dict], **kwargs: Any) -> DecisionResult:
        del pack, catalog, kwargs
        from daemon.decision import DecisionResult

        started = time.perf_counter()
        if not self.base_url:
            return self._skipped("error", started)
        jobs = [(index, hit) for index, hit in enumerate((hits or [])[:12]) if isinstance(hit, dict)]
        if not jobs:
            return DecisionResult(scores={}, provider="gliclass", model=self.model, skipped=False, skip_reason=None, latency_ms=_elapsed_ms(started))
        scores: dict[str, float] = {}
        workers = min(MAX_FILTER_WORKERS, len(jobs))
        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(self._score_hit, task, hit, index): index for index, hit in jobs}
                try:
                    for fut in as_completed(futures):
                        index, score = fut.result()
                        if score is not None:
                            scores[f"rel_{index}"] = score
                except _WireError:
                    for pending in futures:
                        pending.cancel()
                    raise
        except _WireError as exc:
            return self._skipped(exc.reason, started)
        return DecisionResult(scores=scores, provider="gliclass", model=self.model, skipped=False, skip_reason=None, latency_ms=_elapsed_ms(started))

    def _score_hit(self, task: Any, hit: dict, index: int) -> tuple[int, float | None]:
        payload = self._post(_hit_text(task, hit, index))
        return index, _relevant_score(payload)

    def judge(self, *, pack: str, task: Any, catalog: list[dict], candidates: list[dict], **kwargs: Any) -> DecisionResult:
        del pack, task, catalog, candidates, kwargs
        from daemon.decision import DecisionResult

        started = time.perf_counter()
        logger.info("GLiClass judge is unsupported in Phase 1")
        return DecisionResult(provider="gliclass", model=self.model, skipped=True, skip_reason="unsupported", latency_ms=_elapsed_ms(started))

    def _post(self, text: str) -> Any:
        url = resolve_gliclass_url(self.base_url)
        body = json.dumps({"texts": [text], "labels": [RELEVANT_LABEL, OTHER_LABEL], "threshold": self.threshold}).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode()
        except urllib.error.HTTPError as exc:
            logger.warning("GLiClass HTTP %s", getattr(exc, "code", 0))
            raise _WireError("error") from exc
        except Exception as exc:
            reason = "timeout" if _is_timeout(exc) else "error"
            logger.warning("GLiClass request failed reason=%s", reason)
            raise _WireError(reason) from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise _WireError("bad_payload") from exc

    def _skipped(self, reason: str, started: float) -> DecisionResult:
        from daemon.decision import DecisionResult

        skip_reason = reason if reason in _SKIP_REASONS else "error"
        logger.warning("GLiClass decision skipped reason=%s", skip_reason)
        return DecisionResult(provider="gliclass", model=self.model, skipped=True, skip_reason=skip_reason, latency_ms=_elapsed_ms(started))
