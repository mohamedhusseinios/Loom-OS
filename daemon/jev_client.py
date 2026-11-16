"""TypeSafe Jev (System One) client — typed decisions, not chat.

One client serves ``typesafe`` (cloud, API key required) and ``ollama`` (local,
API key optional). ``ask`` still returns the raw payload. ``filter_relevance``
and ``judge`` normalize that payload to ``DecisionResult`` and never raise.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any, Callable

logger = logging.getLogger("loom.jev")

DEFAULT_SYSTEMONE_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"
SYSTEMONE_PATH = "/v1/systemone"
MAX_ATTEMPTS = 4
MAX_RETRY_SLEEP_SEC = 8.0
INITIAL_BACKOFF_SEC = 0.5
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
CLOUD_TIMEOUT_SEC = 10.0
LOCAL_TIMEOUT_SEC = 5.0
_SKIP_REASONS = frozenset({"error", "timeout", "bad_payload"})


class JevError(Exception):
    """Raised when ``ask`` cannot return a SystemOne payload."""

    def __init__(self, message: str, *, reason: str = "error"):
        super().__init__(message)
        self.reason = reason if reason in _SKIP_REASONS else "error"


def resolve_systemone_url(base_url: str | None = None) -> str:
    """Return a POST URL for ``/v1/systemone``.

    A bare host such as ``http://localhost:11434`` gets the path appended.
    A URL that already ends with ``/v1/systemone`` is kept (trailing slash stripped).
    """
    raw = base_url if base_url is not None else os.environ.get("TYPESAFE_BASE_URL", DEFAULT_SYSTEMONE_URL)
    url = (raw or DEFAULT_SYSTEMONE_URL).strip()
    if not url:
        url = DEFAULT_SYSTEMONE_URL
    url = url.rstrip("/")
    if url.endswith(SYSTEMONE_PATH):
        return url
    return f"{url}{SYSTEMONE_PATH}"


def _retry_delay(attempt: int, headers: Any | None) -> float:
    """Seconds to wait after a failed attempt (0-based). Caps at MAX_RETRY_SLEEP_SEC."""
    backoff = min(MAX_RETRY_SLEEP_SEC, INITIAL_BACKOFF_SEC * (2 ** attempt))
    if headers is None:
        return backoff
    raw = None
    try:
        raw = headers.get("Retry-After") or headers.get("retry-after")
    except Exception:
        raw = None
    if raw is None:
        return backoff
    try:
        return min(MAX_RETRY_SLEEP_SEC, max(0.0, float(raw)))
    except (TypeError, ValueError):
        return backoff


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


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


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


def _node_line(hit: dict, index: int) -> tuple[str, str]:
    nid = str(hit.get("id") or hit.get("name") or f"hit-{index}")
    label = hit.get("label") or hit.get("text") or hit.get("type") or ""
    return nid, f"{nid}: {label}"[:160]


class JevClient:
    """SystemOne HTTP client for TypeSafe cloud and local Ollama."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None, timeout: float | None = None, sleep: Callable[[float], None] | None = None, max_attempts: int = MAX_ATTEMPTS, provider: str = "typesafe", model: str = DEFAULT_MODEL):
        self.provider = provider if provider in ("typesafe", "ollama") else "typesafe"
        self.api_key = api_key if api_key is not None else os.environ.get("TYPESAFE_API_KEY", "")
        self.base_url = resolve_systemone_url(base_url)
        self.model = model or ("" if self.provider == "ollama" else DEFAULT_MODEL)
        if timeout is None:
            timeout = LOCAL_TIMEOUT_SEC if self.provider == "ollama" else CLOUD_TIMEOUT_SEC
        self.timeout = timeout
        self._sleep = sleep if sleep is not None else time.sleep
        self.max_attempts = max(1, max_attempts)

    @property
    def available(self) -> bool:
        if self.provider == "ollama":
            return True
        return bool(self.api_key)

    def ask(self, state: Any, questions: dict[str, dict], model: str = DEFAULT_MODEL) -> dict[str, Any]:
        """Send state + questions; return the full SystemOne response.

        The payload includes ``answers``, ``usage``, and ``model`` when the API
        provides them. ``questions`` values are primitives:
        ``{"type": "noul"|"choice"|"score", "instructions": ..., "criteria": ...}``.
        Cloud calls require an API key. Local Ollama does not.
        """
        if self.provider != "ollama" and not self.api_key:
            raise JevError("TYPESAFE_API_KEY not configured")
        body = json.dumps({"model": model, "state": state, "questions": questions}).encode()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        last_error: Exception | None = None
        for attempt in range(self.max_attempts):
            req = urllib.request.Request(self.base_url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode()
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError as e:
                    raise JevError("TypeSafe returned invalid JSON", reason="bad_payload") from e
                if not isinstance(payload, dict):
                    raise JevError("TypeSafe returned a non-object payload", reason="bad_payload")
                payload.setdefault("answers", {})
                payload.setdefault("usage", {})
                return payload
            except JevError:
                raise
            except urllib.error.HTTPError as e:
                status = getattr(e, "code", 0)
                detail = e.read().decode() if e.fp else str(e)
                headers_in = getattr(e, "headers", None)
                last_error = JevError(f"TypeSafe HTTP {status}: {detail}")
                if status in RETRYABLE_STATUS and attempt + 1 < self.max_attempts:
                    delay = _retry_delay(attempt, headers_in)
                    logger.warning("Jev HTTP %s, retrying in %.2fs (attempt %s/%s)", status, delay, attempt + 1, self.max_attempts)
                    self._sleep(delay)
                    continue
                raise last_error from e
            except Exception as e:
                reason = "timeout" if _is_timeout(e) else "error"
                raise JevError(str(e), reason=reason) from e
        raise last_error or JevError("TypeSafe request failed")

    def filter_relevance(self, *, pack: str, task: Any, catalog: list[dict], hits: list[dict], **kwargs: Any) -> DecisionResult:
        del catalog, kwargs
        started = time.perf_counter()
        questions, state = _filter_request(task, hits, pack)
        return self._decide(questions, state, started)

    def judge(self, *, pack: str, task: Any, catalog: list[dict], candidates: list[dict], **kwargs: Any) -> DecisionResult:
        del kwargs
        started = time.perf_counter()
        questions, state = _judge_request(task, pack, catalog, candidates)
        return self._decide(questions, state, started)

    def _decide(self, questions: dict[str, dict], state: dict, started: float) -> DecisionResult:
        from daemon.decision import DecisionResult, DecisionUsage

        if not self.available:
            return self._skipped("error", started)
        if not questions:
            return DecisionResult(provider=self.provider, model=self.model, skipped=False, latency_ms=_elapsed_ms(started))
        try:
            payload = self.ask(state, questions, model=self.model or DEFAULT_MODEL)
        except JevError as exc:
            return self._skipped(exc.reason, started)
        answers = payload.get("answers") if isinstance(payload.get("answers"), dict) else {}
        scores: dict[str, float] = {}
        for key in questions:
            score = _clamp_unit((answers.get(key) or {}).get("noul") if isinstance(answers.get(key), dict) else None)
            if score is None and isinstance(answers.get(key), dict):
                score = _clamp_unit(answers[key].get("score"))
            if score is not None:
                scores[key] = score
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        reported_model = payload.get("model")
        model = reported_model if isinstance(reported_model, str) and reported_model else self.model
        return DecisionResult(scores=scores, usage=DecisionUsage(input_tokens=_optional_int(usage.get("input_tokens")), output_tokens=_optional_int(usage.get("output_tokens"))), provider=self.provider, model=model, skipped=False, skip_reason=None, latency_ms=_elapsed_ms(started))

    def _skipped(self, reason: str, started: float) -> DecisionResult:
        from daemon.decision import DecisionResult

        skip_reason = reason if reason in _SKIP_REASONS else "error"
        logger.warning("Jev decision skipped provider=%s reason=%s", self.provider, skip_reason)
        return DecisionResult(provider=self.provider, model=self.model, skipped=True, skip_reason=skip_reason, latency_ms=_elapsed_ms(started))


def _filter_request(task: Any, hits: list[dict], pack: str) -> tuple[dict[str, dict], dict]:
    questions: dict[str, dict] = {}
    nodes: list[str] = []
    for i, hit in enumerate((hits or [])[:12]):
        if not isinstance(hit, dict):
            continue
        nid, line = _node_line(hit, i)
        nodes.append(line)
        questions[f"rel_{i}"] = {"type": "noul", "instructions": f"Is graph node `{nid}` relevant to the task described in `task`?", "criteria": {"true": "The node is needed to understand or implement the task.", "false": "The node is unrelated to the task."}}
    state = {"task": _task_view(task), "pack": pack or "", "nodes": nodes}
    return questions, state


def _judge_request(task: Any, pack: str, catalog: list[dict], candidates: list[dict]) -> tuple[dict[str, dict], dict]:
    questions: dict[str, dict] = {
        "complete": {"type": "noul", "instructions": "Is the work on this task already complete?", "criteria": {"true": "The graph context and task description show the work is finished.", "false": "The work is not finished, or there is not enough evidence it is done."}},
        "blocked": {"type": "noul", "instructions": "Is this task blocked?", "criteria": {"true": "The task cannot proceed because of a missing dependency, decision, or obstacle.", "false": "The task can proceed."}},
        "ready_to_implement": {"type": "noul", "instructions": "Is this task ready to implement?", "criteria": {"true": "The task is clear enough to start implementation now.", "false": "The task still needs planning, unblocking, or more definition."}},
    }
    cited = [c for c in (candidates or []) if isinstance(c, dict) and c.get("id") and c.get("graph_ids")]
    for i, cand in enumerate(cited):
        nid = ", ".join(str(g) for g in (cand.get("graph_ids") or [])[:4])
        questions[f"grounded_{i}"] = {"type": "noul", "instructions": f"Is proposed step `{cand['id']}` ({cand.get('label') or cand['id']}) grounded in the cited graph node(s) `{nid}`?", "criteria": {"true": "The cited graph node actually supports this step.", "false": "The citation is missing, unrelated, or does not support the step."}}
    labels: dict[str, str] = {}
    for item in catalog or []:
        if isinstance(item, dict) and item.get("id"):
            labels[str(item["id"])] = str(item.get("label") or item["id"])
    state = {"task": _task_view(task), "graph": pack or "", "catalog": labels}
    return questions, state
