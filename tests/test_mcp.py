"""Tests for the MCP server tools.

Calls the tool functions directly (not through MCP transport).
"""
import json
import pytest
from pathlib import Path

from daemon.mcp_server import (
    list_projects,
    search_knowledge_graph,
    add_to_memory,
    get_project_graph,
    query_graph,
)


def test_list_projects_empty_when_no_state_db(tmp_path):
    """list_projects returns empty when no state.db exists."""
    result = list_projects(loom_dir=str(tmp_path))
    assert result == []


def test_list_projects_with_state_db(tmp_path):
    """list_projects reads projects from state.db."""
    import sqlite3
    db_path = tmp_path / "state.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            project_id TEXT PRIMARY KEY, project_name TEXT, project_path TEXT,
            node_count INTEGER DEFAULT 0, edge_count INTEGER DEFAULT 0,
            community_count INTEGER DEFAULT 0, last_graph_update TEXT,
            total_findings INTEGER DEFAULT 0
        )
    """)
    conn.execute("INSERT INTO projects VALUES ('proj-a', 'Project A', '/tmp/a', 5, 3, 1, NULL, 0)")
    conn.execute("INSERT INTO projects VALUES ('proj-b', 'Project B', '/tmp/b', 0, 0, 0, NULL, 2)")
    conn.commit()
    conn.close()

    result = list_projects(loom_dir=str(tmp_path))
    assert len(result) == 2
    names = [p["project_name"] for p in result]
    assert "Project A" in names


def test_get_project_graph_empty_when_no_state_db(tmp_path):
    """get_project_graph returns error when project not found."""
    result = get_project_graph(project="no-exist", loom_dir=str(tmp_path))
    assert "error" in result
    assert result["nodes"] == []


def test_get_project_graph_with_state_and_graph(tmp_path):
    """get_project_graph reads graph.json via state.db project_path."""
    import sqlite3
    db_path = tmp_path / "state.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            project_id TEXT PRIMARY KEY, project_name TEXT, project_path TEXT,
            node_count INTEGER DEFAULT 0, edge_count INTEGER DEFAULT 0,
            community_count INTEGER DEFAULT 0, last_graph_update TEXT,
            total_findings INTEGER DEFAULT 0
        )
    """)
    conn.execute("INSERT INTO projects VALUES ('test', 'Test', ?, 0, 0, 0, NULL, 0)", (str(tmp_path),))
    conn.commit()
    conn.close()

    # Create graph.json
    graph_dir = tmp_path / "graphify-out"
    graph_dir.mkdir()
    graph = {
        "nodes": [{"id": "n1", "name": "auth.py", "kind": "Module"}],
        "edges": [{"source": "n1", "target": "n2", "kind": "contains"}],
    }
    (graph_dir / "graph.json").write_text(json.dumps(graph))

    result = get_project_graph(project="test", loom_dir=str(tmp_path))
    assert len(result["nodes"]) == 1
    assert result["nodes"][0]["label"] == "auth.py"


def test_search_knowledge_graph_matches_inbox_findings(tmp_path):
    """Search finds findings in the inbox."""
    inbox = tmp_path / "inbox" / "proj"
    inbox.mkdir(parents=True)
    (inbox / "finding-001.md").write_text("""---
agent: agent-a
project: proj
---
PATTERN: auth.py always uses bcrypt for password hashing
""")

    results = search_knowledge_graph(
        query="password hashing",
        project="proj",
        loom_dir=str(tmp_path),
    )
    assert len(results) > 0
    assert any("bcrypt" in r.get("text", "") for r in results)


def test_search_knowledge_graph_no_match(tmp_path):
    """Search returns empty when nothing matches."""
    results = search_knowledge_graph(
        query="nonexistent",
        project="nonexistent",
        loom_dir=str(tmp_path),
    )
    assert results == []


def test_add_to_memory_writes_finding(tmp_path):
    """add_to_memory writes a finding file to the inbox."""
    result = add_to_memory(
        finding="PATTERN: discovered circular dependency",
        project="proj",
        agent="agent-1",
        loom_dir=str(tmp_path),
    )
    assert result["status"] == "stored"

    inbox = tmp_path / "inbox" / "proj"
    files = list(inbox.glob("finding-*.md"))
    assert len(files) == 1
    assert "circular dependency" in files[0].read_text()


def test_add_to_memory_with_type(tmp_path):
    """add_to_memory accepts FOUND/PATTERN/DECISION type hints."""
    result = add_to_memory(
        finding="Hardcoded secret in auth.py",
        project="proj",
        agent="agent-1",
        finding_type="FOUND",
        loom_dir=str(tmp_path),
    )
    assert result["status"] == "stored"
    inbox = tmp_path / "inbox" / "proj"
    finding = list(inbox.glob("finding-*.md"))[0].read_text()
    assert "FOUND:" in finding


def test_query_graph_finds_node(tmp_path):
    """query_graph returns matching nodes from graph.json."""
    import sqlite3
    db_path = tmp_path / "state.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            project_id TEXT PRIMARY KEY, project_name TEXT, project_path TEXT,
            node_count INTEGER DEFAULT 0, edge_count INTEGER DEFAULT 0,
            community_count INTEGER DEFAULT 0, last_graph_update TEXT,
            total_findings INTEGER DEFAULT 0
        )
    """)
    conn.execute("INSERT INTO projects VALUES ('test', 'Test', ?, 0, 0, 0, NULL, 0)", (str(tmp_path),))
    conn.commit()
    conn.close()

    graph_dir = tmp_path / "graphify-out"
    graph_dir.mkdir()
    graph = {
        "nodes": [
            {"id": "n1", "name": "AuthService", "kind": "Class"},
            {"id": "n2", "name": "utils.py", "kind": "Module"},
        ],
    }
    (graph_dir / "graph.json").write_text(json.dumps(graph))

    result = query_graph(question="auth", project="test", loom_dir=str(tmp_path))
    nodes = result.get("results", [])
    assert len(nodes) > 0
    assert any("AuthService" in r["name"] for r in nodes)
