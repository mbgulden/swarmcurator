"""tests/test_fastapi.py — Unit tests for SwarmCurator FastAPI router endpoints."""

import pytest
from pathlib import Path
from swarmcurator.queue import SwarmCuratorQueue

try:
    from fastapi import FastAPI, Header, HTTPException
    from fastapi.testclient import TestClient
    from swarmcurator.fastapi_router import create_router
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


@pytest.mark.skipif(not HAS_FASTAPI, reason="FastAPI not installed")
def test_fastapi_router_endpoints(tmp_path: Path) -> None:
    queue_file = tmp_path / "queue.json"
    queue = SwarmCuratorQueue(path=queue_file)

    app = FastAPI()
    app.include_router(create_router(queue))
    client = TestClient(app)

    # 1. Admit task
    res_admit = client.post("/curator/admit", json={
        "task_id": "t-api-1",
        "provider": "linear",
        "external_id": "GRO-500",
        "title": "API Test Task",
        "base_priority": 1,
        "lane_id": "lane-fastapi",
    })
    assert res_admit.status_code == 200
    assert res_admit.json()["ok"] is True

    # 2. Get queue
    res_q = client.get("/curator/queue")
    assert res_q.status_code == 200
    assert len(res_q.json()["tasks"]) == 1

    # 3. Pop task
    res_pop = client.post("/curator/pop", json={"agent_id": "agent-agy"})
    assert res_pop.status_code == 200
    assert res_pop.json()["task"]["external_id"] == "GRO-500"

    # 4. Check active lanes
    res_lanes = client.get("/curator/lanes")
    assert res_lanes.status_code == 200
    assert "lane-fastapi" in res_lanes.json()["lanes"]

    # 5. Release lane
    res_rel = client.post("/curator/release", json={"lane_id": "lane-fastapi", "status": "completed"})
    assert res_rel.status_code == 200
    assert res_rel.json()["ok"] is True
