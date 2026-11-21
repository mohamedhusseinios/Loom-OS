"""daemon.agent_run --manifest drives the coding_agent ReAct loop."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from daemon.agent_run import main


def _done_action() -> str:
    return json.dumps({"thought": "finish", "tool": None, "args": {}, "done": True})


def _patch_chat(monkeypatch, content: str) -> None:
    def fake_chat(self, messages, model="deepseek-chat"):
        self.last_usage = {"prompt_tokens": 3, "completion_tokens": 2}
        return content

    monkeypatch.setattr("daemon.llm_client.LlmClient.chat", fake_chat)


def _write_manifest(tmp_path: Path, **extra: object) -> tuple[Path, Path, Path]:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "hello.txt").write_text("hello\n", encoding="utf-8")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    manifest = {
        "prompt": "say done",
        "run_dir": str(run_dir),
        "worktree": str(worktree),
        "model": "fake",
        "step_limit": 4,
    }
    manifest.update(extra)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path, run_dir, worktree


def test_manifest_loop_exits_0_and_events_end_succeeded(tmp_path: Path, monkeypatch) -> None:
    manifest_path, run_dir, _worktree = _write_manifest(tmp_path)
    _patch_chat(monkeypatch, _done_action())

    code = main(["--manifest", str(manifest_path)])

    assert code == 0
    lines = (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[-1]) == {"type": "run.succeeded", "stop_reason": "done"}


def test_manifest_events_path_override(tmp_path: Path, monkeypatch) -> None:
    events_path = tmp_path / "custom" / "events.jsonl"
    manifest_path, _run_dir, _worktree = _write_manifest(tmp_path, events_path=str(events_path))
    _patch_chat(monkeypatch, _done_action())

    code = main(["--manifest", str(manifest_path)])

    assert code == 0
    lines = events_path.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[-1])["type"] == "run.succeeded"


def test_prompt_alone_stays_single_shot(capsys, monkeypatch) -> None:
    seen: list[str] = []

    def fake_chat(self, messages, model="deepseek-chat"):
        seen.append(messages[-1]["content"])
        return "single-shot reply"

    monkeypatch.setattr("daemon.llm_client.LlmClient.chat", fake_chat)

    code = main(["--prompt", "fix the bug"])

    assert code == 0
    assert seen == ["fix the bug"]
    assert capsys.readouterr().out.strip() == "single-shot reply"


def test_missing_prompt_and_manifest_errors() -> None:
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


def test_manifest_and_prompt_runs_loop(tmp_path: Path, monkeypatch) -> None:
    manifest_path, run_dir, _worktree = _write_manifest(tmp_path, prompt="")
    seen: list[str] = []

    def fake_chat(self, messages, model="deepseek-chat"):
        seen.append(messages[-1]["content"])
        self.last_usage = {"prompt_tokens": 1, "completion_tokens": 1}
        return _done_action()

    monkeypatch.setattr("daemon.llm_client.LlmClient.chat", fake_chat)

    code = main(["--manifest", str(manifest_path), "--prompt", "from cli"])

    assert code == 0
    assert seen == ["from cli"]
    lines = (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[-1])["type"] == "run.succeeded"
