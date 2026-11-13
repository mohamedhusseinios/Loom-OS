"""Orchestration loop: graph → Jev filter → main LLM → Jev choice → suggestion."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from daemon.jev_client import JevClient, JevError
from daemon.llm_client import LlmClient, LlmError
from daemon.models import AgentTaskRecord, AgentTaskStatus

logger = logging.getLogger("loom.orchestrator")

# Loom actions allowed per current task status.
LOOM_ACTIONS: dict[str, list[tuple[str, str]]] = {
    AgentTaskStatus.TODO.value: [
        ("loom.move_ready", "Move task to Ready"),
        ("loom.move_blocked", "Move task to Blocked"),
    ],
    AgentTaskStatus.READY.value: [
        ("loom.move_running", "Move task to Running (ready to implement)"),
        ("loom.move_blocked", "Move task to Blocked"),
    ],
    AgentTaskStatus.RUNNING.value: [
        ("loom.move_blocked", "Move task to Blocked"),
        ("loom.move_done", "Mark task Done"),
    ],
    AgentTaskStatus.BLOCKED.value: [
        ("loom.move_ready", "Unblock — move to Ready"),
        ("loom.move_todo", "Move task back to Todo"),
    ],
    AgentTaskStatus.DONE.value: [
        ("loom.move_archived", "Archive task"),
    ],
    AgentTaskStatus.TRIAGE.value: [
        ("loom.move_todo", "Move task to Todo"),
        ("loom.move_ready", "Move task to Ready"),
    ],
}

STATUS_FOR_ACTION = {
    "loom.move_todo": AgentTaskStatus.TODO,
    "loom.move_ready": AgentTaskStatus.READY,
    "loom.move_running": AgentTaskStatus.RUNNING,
    "loom.move_blocked": AgentTaskStatus.BLOCKED,
    "loom.move_done": AgentTaskStatus.DONE,
    "loom.move_archived": AgentTaskStatus.ARCHIVED,
}


@dataclass
class SuggestResult:
    action_id: str
    action_label: str
    confidence: float
    prose: str
    catalog: list[dict] = field(default_factory=list)
    reply: str = ""
    jev_skipped: bool = False
    graph_empty: bool = False


def load_playbook(project_path: str) -> list[dict]:
    path = Path(project_path) / "loom-playbook.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    steps = data.get("steps") if isinstance(data, dict) else data
    if not isinstance(steps, list):
        return []
    out = []
    for s in steps:
        if isinstance(s, dict) and s.get("id") and s.get("label"):
            out.append({"id": s["id"], "label": s["label"], "when": s.get("when") or []})
    return out


def loom_catalog_for_status(status: str) -> list[dict]:
    return [{"id": aid, "label": label, "source": "loom"} for aid, label in LOOM_ACTIONS.get(status, [])]


def playbook_for_status(steps: list[dict], status: str) -> list[dict]:
    out = []
    for s in steps:
        when = s.get("when") or []
        if when and status not in when:
            continue
        out.append({"id": s["id"], "label": s["label"], "source": "playbook"})
    return out


def merge_catalog(loom: list[dict], playbook: list[dict], candidates: list[dict]) -> list[dict]:
    """Dedupe by id; drop candidates without a graph citation."""
    seen: set[str] = set()
    merged: list[dict] = []
    for item in loom + playbook:
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        merged.append(item)
    for c in candidates:
        cid = c.get("id")
        if not cid or cid in seen:
            continue
        if not c.get("graph_ids"):
            continue
        seen.add(cid)
        merged.append({
            "id": cid,
            "label": c.get("label") or cid,
            "source": "llm",
            "graph_ids": c.get("graph_ids") or [],
        })
    return merged


def _node_snippet(hit: dict) -> str:
    nid = hit.get("id") or hit.get("name") or "?"
    label = hit.get("label") or hit.get("text") or hit.get("type") or ""
    return f"{nid}: {label}"[:200]


class Orchestrator:
    """Runs one suggest/chat cycle against graph memory + Jev + main LLM."""

    def __init__(self, graph_engine, jev: JevClient | None = None, llm: LlmClient | None = None):
        self.graph_engine = graph_engine
        self.jev = jev or JevClient()
        self.llm = llm or LlmClient()

    async def run_suggest_cycle(
        self,
        project_path: str,
        project: str,
        task: AgentTaskRecord,
        chat_messages: list[dict[str, str]] | None = None,
        user_message: str | None = None,
        model: str | None = None,
    ) -> SuggestResult:
        question = f"{task.title}\n{task.instruction}"
        if user_message:
            question = f"{question}\n{user_message}"

        hits = await self._retrieve(project_path, project, question)
        graph_path = Path(project_path) / "graphify-out" / "graph.json"
        if not hits and not graph_path.exists():
            return SuggestResult(
                action_id="loom.refresh_graph",
                action_label="Build or refresh the project graph",
                confidence=1.0,
                prose="No graph memory found for this project. Build the knowledge graph first, then ask again.",
                catalog=[{"id": "loom.refresh_graph", "label": "Build or refresh the project graph", "source": "loom"}],
                reply="I don't have graph memory for this project yet. Please build/refresh the graph, then we can plan the next step.",
                graph_empty=True,
            )

        jev_skipped = False
        filtered = hits[:8]
        if hits and self.jev.available:
            try:
                filtered = self._jev_filter(hits, task)
            except JevError:
                logger.warning("Jev filter failed; using top hybrid hits", exc_info=True)
                jev_skipped = True
                filtered = hits[:5]
        elif hits:
            jev_skipped = True

        pack = "\n".join(_node_snippet(h) for h in filtered) or "(no graph hits)"
        playbook = load_playbook(project_path)
        loom = loom_catalog_for_status(task.status.value)
        pb = playbook_for_status(playbook, task.status.value)

        reply = ""
        candidates: list[dict] = []
        if self.llm.available:
            try:
                reply, candidates = self._llm_propose(pack, task, chat_messages, user_message, model)
            except LlmError as e:
                reply = f"(Main model unavailable: {e})"
        else:
            reply = "Add a DeepSeek (or other) API key in Agent settings to enable chat."

        catalog = merge_catalog(loom, pb, candidates)
        if not catalog:
            catalog = loom or [{"id": "loom.move_ready", "label": "Move task to Ready", "source": "loom"}]

        action_id = catalog[0]["id"]
        action_label = catalog[0]["label"]
        confidence = 0.5
        if self.jev.available and not jev_skipped:
            try:
                action_id, action_label, confidence = self._jev_choose(pack, task, catalog)
            except JevError:
                logger.warning("Jev choice failed; using first catalog option", exc_info=True)
                jev_skipped = True

        prose = reply
        if user_message is None and reply:
            prose = reply
        elif not prose:
            prose = f"Suggested next step: {action_label}"

        return SuggestResult(
            action_id=action_id,
            action_label=action_label,
            confidence=confidence,
            prose=prose,
            catalog=catalog,
            reply=reply or prose,
            jev_skipped=jev_skipped,
        )

    async def _retrieve(self, project_path: str, project: str, question: str) -> list[dict]:
        if self.graph_engine is None:
            return []
        try:
            return await self.graph_engine.hybrid_query(project_path, project, question, top_k=12)
        except Exception:
            logger.warning("hybrid_query failed", exc_info=True)
            return []

    def _jev_filter(self, hits: list[dict], task: AgentTaskRecord) -> list[dict]:
        questions = {}
        for i, h in enumerate(hits[:12]):
            nid = h.get("id") or h.get("name") or f"hit-{i}"
            questions[f"rel_{i}"] = {
                "type": "noul",
                "instructions": (
                    f"Is graph node `{nid}` relevant to the task "
                    f"\"{task.title}\": {task.instruction[:300]}?"
                ),
            }
        state = {
            "task": {"title": task.title, "instruction": task.instruction, "status": task.status.value},
            "nodes": [_node_snippet(h) for h in hits[:12]],
        }
        answers = self.jev.ask(state, questions)
        scored: list[tuple[float, dict]] = []
        for i, h in enumerate(hits[:12]):
            ans = answers.get(f"rel_{i}") or {}
            score = float(ans.get("noul") if ans.get("type") == "noul" else ans.get("score") or 0)
            scored.append((score, h))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [h for s, h in scored if s >= 0.35][:6] or [h for _, h in scored[:4]]

    def _llm_propose(
        self,
        pack: str,
        task: AgentTaskRecord,
        chat_messages: list[dict[str, str]] | None,
        user_message: str | None,
        model: str | None,
    ) -> tuple[str, list[dict]]:
        system = (
            "You are the Loom agent. Use ONLY the provided graph context. "
            "Respond with JSON: {\"reply\": \"human language\", "
            "\"candidates\": [{\"id\": \"custom.step\", \"label\": \"...\", \"graph_ids\": [\"node-id\"]}]}. "
            "Candidates without graph_ids are invalid. Keep reply to 2-4 sentences."
        )
        messages = [{"role": "system", "content": system}]
        if chat_messages:
            messages.extend(chat_messages[-20:])
        user = (
            f"Task status={task.status.value}\nTitle: {task.title}\n"
            f"Instruction: {task.instruction}\n\nGraph context:\n{pack}"
        )
        if user_message:
            user += f"\n\nUser message: {user_message}"
        messages.append({"role": "user", "content": user})
        data = self.llm.chat_json(messages, model=model or "deepseek-chat")
        reply = data.get("reply") or ""
        candidates = data.get("candidates") or []
        if not isinstance(candidates, list):
            candidates = []
        return reply, [c for c in candidates if isinstance(c, dict)]

    def _jev_choose(self, pack: str, task: AgentTaskRecord, catalog: list[dict]) -> tuple[str, str, float]:
        options = {c["id"]: c["label"] for c in catalog}
        state = {
            "task": {"title": task.title, "instruction": task.instruction, "status": task.status.value},
            "graph": pack,
            "options": options,
        }
        answers = self.jev.ask(state, {
            "next_step": {
                "type": "choice",
                "instructions": "Which next step should the human take for this task?",
                "options": list(options.keys()),
            },
        })
        ans = answers.get("next_step") or {}
        choice = ans.get("choice") or catalog[0]["id"]
        conf = float(ans.get("confidence") or 0.5)
        label = options.get(choice) or choice
        for c in catalog:
            if c["id"] == choice:
                label = c["label"]
                break
        return choice, label, conf
