"""tests/test_concurrency.py — Concurrent admission and dispatch race tests."""

import concurrent.futures
from pathlib import Path
from swarmcurator.models import CuratorTask
from swarmcurator.queue import SwarmCuratorQueue


def _make_unique_task(i: int) -> CuratorTask:
    return CuratorTask(
        task_id=f"task-{i}",
        provider="generic",
        external_id=f"EXT-{i:04d}",  # Zero-padded to ensure unique fingerprints
        title=f"Concurrent Task {i:04d}",
        base_priority=i % 4,
        lane_id=f"lane-unique-{i}",
    )


def test_concurrent_admit_no_corruption(tmp_path: Path) -> None:
    """Concurrent admit calls must not corrupt the queue (atomic file locking)."""
    queue_file = tmp_path / "queue_concurrent.json"
    queue = SwarmCuratorQueue(path=queue_file)

    # 1. Concurrently admit 20 tasks
    def worker_admit(i: int) -> bool:
        return queue.admit(_make_unique_task(i))

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(worker_admit, range(20)))

    admitted_count = sum(1 for r in results if r)
    all_tasks = queue.list_tasks()

    # All tasks must be admitted (file lock must prevent writes from being lost)
    assert len(all_tasks) == 20, f"Expected 20 tasks, admitted_count={admitted_count}, actually_in_queue={len(all_tasks)}"
    assert all(results), f"Some admits returned False unexpectedly: {[i for i, r in enumerate(results) if not r]}"

    # All task_ids must be unique — no two tasks clobbered each other
    task_ids = {t.task_id for t in all_tasks}
    assert len(task_ids) == 20, f"Duplicate task_ids found: {20 - len(task_ids)} duplicates"


def test_concurrent_pop_no_double_lease(tmp_path: Path) -> None:
    """Concurrent pop_next calls from multiple agents must never double-lease the same lane."""
    queue_file = tmp_path / "queue_pop_concurrent.json"
    queue = SwarmCuratorQueue(path=queue_file)

    # Admit 20 tasks sequentially first (testing pop concurrency, not admit concurrency)
    for i in range(20):
        queue.admit(_make_unique_task(i))

    # 2. Concurrently pop tasks across 10 workers
    def worker_pop(worker_id: int):
        return queue.pop_next(agent_id=f"worker-{worker_id}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        popped_tasks = list(executor.map(worker_pop, range(10)))

    valid_popped = [t for t in popped_tasks if t is not None]

    # Each worker gets at most 1 task, lanes must be distinct (no double-leases)
    popped_lanes = [t.lane_id for t in valid_popped]
    assert len(popped_lanes) == len(set(popped_lanes)), f"Double-lease detected! Lanes: {popped_lanes}"

    # All popped task IDs must be unique (no double-leases!)
    popped_ids = [t.task_id for t in valid_popped]
    assert len(popped_ids) == len(set(popped_ids)), f"Duplicate task_ids popped: {popped_ids}"
