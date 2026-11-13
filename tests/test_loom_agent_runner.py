"""loom-agent known agent + runner registration."""
import sys

from daemon.known_agents import detect_installed, get_known_agents
from daemon.runners import RUNNERS, runnable_agents


def test_loom_agent_in_known_agents():
    names = {a["name"] for a in get_known_agents()}
    assert "loom-agent" in names


def test_loom_agent_always_detected():
    installed = detect_installed()
    assert installed.get("loom-agent") == "builtin"


def test_loom_agent_in_runners():
    assert "loom-agent" in runnable_agents()
    spec = RUNNERS["loom-agent"]
    assert spec.mode == "stdout"
    assert spec.binary == sys.executable
    argv = spec.build_argv("do the thing")
    assert "-m" in argv and "daemon.agent_run" in argv
    assert "--prompt" in argv
