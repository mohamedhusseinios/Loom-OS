from pathlib import Path
from daemon.wiring import wire_project


def test_wire_project_creates_idempotent_instructions_and_mcp_config(tmp_path):
    res1 = wire_project(project="my-app", project_path=str(tmp_path))
    claude_md = (tmp_path / "CLAUDE.md").read_text()
    agents_md = (tmp_path / "AGENTS.md").read_text()
    mcp_json = (tmp_path / ".mcp.json").read_text()

    assert "<!-- LOOM-OS:START -->" in claude_md
    assert ".loom/SHARED_CONTEXT.md" in claude_md
    assert "~/.loom/inbox/my-app/" in agents_md
    assert "loom-os" in mcp_json

    # Second run is idempotent — does not duplicate the block
    res2 = wire_project(project="my-app", project_path=str(tmp_path))
    assert (tmp_path / "CLAUDE.md").read_text().count("<!-- LOOM-OS:START -->") == 1
    assert res2["updated"] is False or res2["idempotent"] is True
