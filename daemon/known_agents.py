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
]


def _find_binary(name: str) -> str | None:
    """Check if a binary is on PATH. Returns path string or None."""
    found = shutil.which(name)
    return found


def _detect_cursor() -> str | None:
    """Detect Cursor editor via its macOS app bundle."""
    cursor_app = Path("/Applications/Cursor.app")
    if cursor_app.exists():
        return str(cursor_app)
    # Also check user Applications
    user_cursor = Path.home() / "Applications" / "Cursor.app"
    if user_cursor.exists():
        return str(user_cursor)
    return None


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
    return installed


def get_known_agents() -> list[dict]:
    """Return the full list of known agent definitions (without installed flag).

    Callers should merge with ``detect_installed()`` to add the installed
    field. This separation keeps the data pure and cachable.
    """
    return [dict(a) for a in KNOWN_AGENTS]
