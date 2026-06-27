import pytest
from daemon.runners import (
    AgentResult, RunnerSpec, RUNNERS, runnable_agents, run_stdout,
)


def test_runnable_agents_is_registry_keys():
    assert runnable_agents() == {
        "claude-code", "hermes", "codex", "gemini-cli", "copilot-cli", "aider",
    }
    assert "opencode" not in runnable_agents()


@pytest.mark.parametrize("agent, expected", [
    ("hermes", ["-z", "do X"]),
    ("codex", ["exec", "--dangerously-bypass-approvals-and-sandbox", "do X"]),
    ("gemini-cli", ["-p", "do X", "--approval-mode", "yolo"]),
    ("copilot-cli", ["-p", "do X", "--allow-all-tools"]),
    ("aider", ["--message", "do X", "--yes-always"]),
])
def test_build_argv_per_stdout_agent(agent, expected):
    assert RUNNERS[agent].build_argv("do X") == expected


def test_claude_is_stream_json_and_not_stdout_built():
    spec = RUNNERS["claude-code"]
    assert spec.mode == "stream-json"
    assert spec.build_argv is None  # claude argv is built in worker.run_claude


def test_run_stdout_success(tmp_path):
    spec = RunnerSpec(binary="printf", mode="stdout", build_argv=lambda p: [p])
    res = run_stdout(spec, "hello", str(tmp_path))
    assert res.text == "hello"
    assert res.is_error is False
    assert res.session_id is None


def test_run_stdout_nonzero_exit_is_error(tmp_path):
    spec = RunnerSpec(
        binary="sh", mode="stdout",
        build_argv=lambda p: ["-c", "echo oops >&2; exit 1"],
    )
    res = run_stdout(spec, "ignored", str(tmp_path))
    assert res.is_error is True
    assert "oops" in res.text
