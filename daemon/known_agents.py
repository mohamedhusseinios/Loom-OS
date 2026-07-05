"""Known agent types and auto-detection for Loom OS.

Defines the canonical set of coding agents that Loom OS knows about,
and provides detection of which agents are installed on the current machine.
"""

import shutil
import subprocess
from pathlib import Path


KNOWN_AGENTS = [
    {
        "name": "claude-code",
        "display": "Claude Code",
        "detect_cmd": "claude",
        "description": "Anthropic's CLI coding agent",
        "default_version": "2.0",
        "default_capabilities": ["code-analysis", "refactoring", "debugging"],
    },
    {
        "name": "codex",
        "display": "OpenAI Codex",
        "detect_cmd": "codex",
        "description": "OpenAI's CLI coding agent",
        "default_version": "0.135.0",
        "default_capabilities": ["code-analysis", "refactoring"],
    },
    {
        "name": "hermes",
        "display": "Hermes Agent",
        "detect_cmd": "hermes",
        "description": "Nous Research's universal agent",
        "default_version": "1.0",
        "default_capabilities": ["code-analysis", "research", "automation"],
    },
    {
        "name": "gemini-cli",
        "display": "Gemini CLI",
        "detect_cmd": "gemini",
        "description": "Google's Gemini CLI coding agent",
        "default_version": "1.0",
        "default_capabilities": ["code-analysis", "generation"],
    },
    {
        "name": "copilot-cli",
        "display": "GitHub Copilot CLI",
        "detect_cmd": "copilot",
        "description": "GitHub Copilot's CLI agent",
        "default_version": "1.0",
        "default_capabilities": ["code-analysis", "completion"],
    },
    {
        "name": "aider",
        "display": "Aider",
        "detect_cmd": "aider",
        "description": "AI pair programming in your terminal",
        "default_version": "0.60",
        "default_capabilities": ["code-analysis", "refactoring"],
    },
    {
        "name": "opencode",
        "display": "OpenCode",
        "detect_cmd": "opencode",
        "description": "Terminal-based AI coding agent",
        "default_version": "1.0",
        "default_capabilities": ["code-analysis"],
    },
    {
        "name": "cursor",
        "display": "Cursor",
        "detect_cmd": None,  # Not a CLI tool — detect via app bundle on macOS
        "description": "AI-first code editor",
        "default_version": "1.0",
        "default_capabilities": ["code-analysis", "editing"],
    },
    {
        "name": "kimi-code",
        "display": "Kimi Code",
        "detect_cmd": "kimi",
        "description": "Moonshot AI's Kimi Code CLI agent",
        "default_version": "1.0",
        "default_capabilities": ["code-analysis", "generation", "refactoring"],
    },
    {
        "name": "zcode",
        "display": "ZCode",
        "detect_cmd": None,
        "description": "Zhipu AI's ZCode agentic development environment",
        "default_version": "1.0",
        "default_capabilities": ["code-analysis", "generation", "long-context", "review"],
    },
]


def _find_binary(name: str) -> str | None:
    """Check if a binary is on PATH. Returns path string or None."""
    found = shutil.which(name)
    return found


def _detect_app_bundle(name: str) -> str | None:
    """Detect an macOS .app bundle by name in /Applications or ~/Applications."""
    app_path = Path(f"/Applications/{name}.app")
    if app_path.exists():
        return str(app_path)
    user_app = Path.home() / "Applications" / f"{name}.app"
    if user_app.exists():
        return str(user_app)
    return None


def _detect_cursor() -> str | None:
    """Detect Cursor editor via its macOS app bundle."""
    return _detect_app_bundle("Cursor")


def _detect_zcode() -> str | None:
    """Detect ZCode via its macOS app bundle."""
    return _detect_app_bundle("ZCode")


def detect_installed() -> dict[str, str]:
    """Return a dict of {canonical_name: detected_path} for installed agents.

    Only agents whose detection command succeeds are included.
    """
    installed: dict[str, str] = {}
    for agent in KNOWN_AGENTS:
        cmd = agent.get("detect_cmd")
        if cmd:
            path = _find_binary(cmd)
            if path:
                installed[agent["name"]] = path
        else:
            # Special-case detection handlers
            if agent["name"] == "cursor":
                path = _detect_cursor()
                if path:
                    installed[agent["name"]] = path
            elif agent["name"] == "zcode":
                path = _detect_zcode()
                if path:
                    installed[agent["name"]] = path
    return installed


def get_known_agents() -> list[dict]:
    """Return the full list of known agent definitions (without installed flag).

    Callers should merge with ``detect_installed()`` to add the installed
    field. This separation keeps the data pure and cachable.
    """
    return [dict(a) for a in KNOWN_AGENTS]
