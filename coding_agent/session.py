"""Run session: budgets, cancel, and tool dispatch."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from coding_agent.ports import ContextSource, EventSink, LlmPort, Sandbox, UsageMeter
from coding_agent.tools.edit import edit
from coding_agent.tools.fs import read_file, search

DEFAULT_STEP_LIMIT = 40
DEFAULT_TOKEN_LIMIT = 100_000
DEFAULT_COST_LIMIT_USD = 1.0


class BudgetExceeded(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class RunCancelled(Exception):
    def __init__(self, reason: str = "cancelled") -> None:
        self.reason = reason
        super().__init__(reason)


class RunSession:
    def __init__(self, manifest: dict[str, Any], sandbox: Sandbox, events: EventSink, llm: LlmPort, meter: UsageMeter, context: ContextSource) -> None:
        self.manifest = manifest
        self.sandbox = sandbox
        self.events = events
        self.llm = llm
        self.meter = meter
        self.context = context
        self.step_limit = int(manifest.get("step_limit", DEFAULT_STEP_LIMIT))
        self.token_limit = int(manifest.get("token_limit", DEFAULT_TOKEN_LIMIT))
        self.cost_limit_usd = float(manifest.get("cost_limit_usd", DEFAULT_COST_LIMIT_USD))
        self.steps_used = 0
        self._cancel_requested = False

    def record_step(self) -> None:
        self.steps_used += 1

    def request_cancel(self) -> None:
        self._cancel_requested = True

    def _cancel_flag_path(self) -> Path | None:
        if "cancel_path" in self.manifest and self.manifest["cancel_path"] not in (None, ""):
            return Path(self.manifest["cancel_path"])
        run_dir = self.manifest.get("run_dir")
        if run_dir:
            return Path(run_dir) / "cancel"
        return None

    def poll_cancel_file(self) -> bool:
        path = self._cancel_flag_path()
        if path is None:
            return False
        return path.is_file()

    def check_can_continue(self) -> None:
        if self._cancel_requested or self.poll_cancel_file():
            raise RunCancelled("cancelled")
        if self.steps_used >= self.step_limit:
            raise BudgetExceeded("step")
        if self.meter.tokens_used() >= self.token_limit:
            raise BudgetExceeded("token")
        if self.meter.cost_usd() >= self.cost_limit_usd:
            raise BudgetExceeded("cost")

    def dispatch_tool(self, name: str, args: dict) -> dict:
        if name == "read_file":
            return read_file(self.sandbox, args.get("path", ""))
        if name == "edit":
            return edit(self.sandbox, args.get("path", ""), args.get("search", ""), args.get("replace", ""))
        if name == "search":
            return search(self.sandbox, args.get("query", ""), args.get("path", "."))
        return {"ok": False, "reason": "not_implemented"}
