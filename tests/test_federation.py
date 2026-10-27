import json
import pytest
from daemon.federation import FederatedIndex


@pytest.mark.asyncio
async def test_federated_index_queries_across_multiple_projects(tmp_path):
    p1 = tmp_path / "auth-service"
    p2 = tmp_path / "billing-service"
    for p, nodes, links in [
        (p1, [
            {"id": "auth.verify_jwt", "label": "verify_jwt", "kind": "function", "source_file": "auth/jwt.py"},
            {"id": "auth.TokenError", "label": "TokenError", "kind": "class", "source_file": "auth/jwt.py"},
        ], [{"source": "auth.verify_jwt", "target": "auth.TokenError", "relation": "raises"}]),
        (p2, [
            {"id": "billing.charge", "label": "charge", "kind": "function", "source_file": "billing/pay.py"},
            {"id": "billing.verify_jwt", "label": "verify_jwt", "kind": "function", "source_file": "billing/middleware.py"},
        ], [{"source": "billing.charge", "target": "billing.verify_jwt", "relation": "calls"}]),
    ]:
        gdir = p / "graphify-out"
        gdir.mkdir(parents=True)
        (gdir / "graph.json").write_text(json.dumps({"nodes": nodes, "links": links}))

    projects = [
        {"project_id": "auth-service", "project_path": str(p1)},
        {"project_id": "billing-service", "project_path": str(p2)},
    ]

    idx = FederatedIndex()
    summary = await idx.build_index(projects)
    assert summary["projects_indexed"] == 2
    assert summary["total_nodes"] == 4

    refs = await idx.cross_project_references("verify_jwt")
    assert {r["project"] for r in refs} == {"auth-service", "billing-service"}

    q_res = await idx.query("verify_jwt", top_k=5)
    assert len(q_res) >= 2
    assert {r["project"] for r in q_res} == {"auth-service", "billing-service"}
