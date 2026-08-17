"""tests/test_multi_input.py — Unit tests for multi-input streams, batch admissions, and composite tasks."""

import json
from pathlib import Path
from swarmcurator.models import CuratorTask
from swarmcurator.adapters import AutoAdapter, CompositeTaskBuilder, MultiInputAggregator
from swarmcurator.queue import SwarmCuratorQueue
from swarmcurator.cli import main

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from swarmcurator.fastapi_router import create_router
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


def test_auto_adapter_detection() -> None:
    # 1. Linear detection
    t_lin = AutoAdapter.from_any({"identifier": "GRO-100", "title": "Linear Issue", "priority": 1})
    assert t_lin.provider == "linear"
    assert t_lin.external_id == "GRO-100"

    # 2. GitHub detection
    t_gh = AutoAdapter.from_any({"number": 88, "title": "GitHub Bug", "body": "details", "repo": "core-repo"})
    assert t_gh.provider == "github"
    assert t_gh.external_id == "GH-88"
    assert t_gh.lane_id == "core-repo"

    # 3. Kanban detection
    t_kb = AutoAdapter.from_any({"id": "KB-5", "title": "Kanban Card", "column": "Doing"})
    assert t_kb.provider == "kanban"
    assert t_kb.external_id == "KB-5"

    # 4. Generic detection
    t_gen = AutoAdapter.from_any({"task_id": "gen-1", "title": "Generic Task", "priority": 2})
    assert t_gen.title == "Generic Task"


def test_composite_task_builder() -> None:
    builder = CompositeTaskBuilder(task_id="comp-1", title="Resolve Gateway Flakiness", lane_id="gateway")
    builder.add_linear_issue({"identifier": "GRO-400", "description": "High 502 rates on deploy"})
    builder.add_github_pr_or_issue({"number": 210, "body": "PR adding connection pool retries", "html_url": "https://github.com/org/repo/pull/210"}, repo="gateway")
    builder.add_context("ci_log", "job-449", "Exit code 1: Connection reset by peer")

    task = builder.build()
    assert task.provider == "composite"
    assert task.lane_id == "gateway"
    assert len(task.inputs) == 3
    assert "Linear Context (GRO-400)" in task.description
    assert "GitHub Context (GH-210)" in task.description
    assert "CI_LOG Context (job-449)" in task.description


def test_queue_admit_batch(tmp_path: Path) -> None:
    queue_file = tmp_path / "queue_batch.json"
    queue = SwarmCuratorQueue(path=queue_file)

    items = [
        {"identifier": "GRO-1", "title": "Task 1", "priority": 1},
        {"number": 2, "title": "Task 2", "body": "Issue 2"},
        {"id": "KB-3", "title": "Task 3", "column": "Todo"},
        {"identifier": "GRO-1", "title": "Task 1", "priority": 1},  # Duplicate
    ]

    result = queue.admit_batch(items)
    assert result.total_admitted == 3
    assert result.total_duplicates == 1
    assert len(queue.list_tasks()) == 3


def test_cli_admit_batch(tmp_path: Path, capsys) -> None:
    queue_file = tmp_path / "cli_batch.json"
    batch_file = tmp_path / "incoming.json"
    batch_file.write_text(json.dumps([
        {"identifier": "GRO-10", "title": "Batch Linear Task", "priority": 2},
        {"number": 20, "title": "Batch GitHub Task", "body": "Desc"},
    ]))

    ret = main([
        "--store", str(queue_file),
        "admit-batch",
        "--file", str(batch_file),
    ])
    assert ret == 0
    data = json.loads(capsys.readouterr().out)
    assert data["total_admitted"] == 2


def test_fastapi_admit_batch(tmp_path: Path) -> None:
    if not HAS_FASTAPI:
        return
    queue_file = tmp_path / "api_batch.json"
    queue = SwarmCuratorQueue(path=queue_file)

    app = FastAPI()
    app.include_router(create_router(queue))
    client = TestClient(app)

    res = client.post("/curator/admit/batch", json={
        "items": [
            {"identifier": "GRO-77", "title": "Task A"},
            {"number": 88, "title": "Task B"},
        ]
    })
    assert res.status_code == 200
    assert res.json()["total_admitted"] == 2
    assert len(res.json()["admitted_ids"]) == 2
