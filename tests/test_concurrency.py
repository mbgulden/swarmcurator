"""tests/test_concurrency.py — Concurrent admission and dispatch race tests."""

import concurrent.futures
from pathlib import Path
from swarmcurator.models import CuratorTask
from swarmcurator.queue import SwarmCuratorQueue


def test_concurrent_admit_and_pop(tmp_path: Path) -> None:
    queue_file = tmp_path / "queue_concurrent.json"
    queue = SwarmCuratorQueue(path=queue_file)

    # 1. Concurrently admit 20 tasks
    def worker_admit(i: int) -> bool:
        t = CuratorTask(
            task_id=f"task-{i}",
            provider="generic",
            external_id=str(i),
            title=f"Concurrent Task {i}",
            base_priority=i % 4,
            lane_id=f"lane-{i % 5}",  # 5 distinct lanes
        )
        return queue.admit(t)

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(worker_admit, range(20)))

    assert all(results)
    assert len(queue.list_tasks()) == 20

    # 2. Concurrently pop tasks across 5 workers
    def worker_pop(worker_id: int):
        return queue.pop_next(agent_id=f"worker-{worker_id}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        popped_tasks = list(executor.map(worker_pop, range(5)))

    # Filter non-None
    valid_popped = [t for t in popped_tasks if t is not None]

    # Every popped task MUST have a distinct lane_id (no two workers in same lane!)
    popped_lanes = [t.lane_id for t in valid_popped]
    assert len(popped_lanes) == len(set(popped_lanes))

    # All popped task IDs must be unique (no double-leases!)
    popped_ids = [t.task_id for t in valid_popped]
    assert len(popped_ids) == len(set(popped_ids))
