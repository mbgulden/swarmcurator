"""tests/test_queue.py — Unit tests for atomic queue operations and deduplication."""

from pathlib import Path
from swarmcurator.models import CuratorTask
from swarmcurator.queue import SwarmCuratorQueue


def test_queue_deduplication(tmp_path: Path) -> None:
    queue_file = tmp_path / "queue.json"
    queue = SwarmCuratorQueue(path=queue_file)

    task = CuratorTask(task_id="t1", provider="linear", external_id="GRO-100", title="Unique Task", base_priority=1)

    # First admission succeeds
    assert queue.admit(task) is True

    # Duplicate admission rejected
    duplicate_task = CuratorTask(task_id="t2", provider="linear", external_id="GRO-100", title="Unique Task", base_priority=1)
    assert queue.admit(duplicate_task) is False

    assert len(queue.list_tasks()) == 1


def test_queue_purge(tmp_path: Path) -> None:
    queue_file = tmp_path / "queue.json"
    queue = SwarmCuratorQueue(path=queue_file)

    t1 = CuratorTask(task_id="t1", provider="linear", external_id="1", title="Task 1", base_priority=1)
    t2 = CuratorTask(task_id="t2", provider="linear", external_id="2", title="Task 2", base_priority=1)

    queue.admit(t1)
    queue.admit(t2)

    popped = queue.pop_next(agent_id="agent-1")
    assert popped is not None
    queue.release_lane(lane_id=popped.lane_id, task_id=popped.task_id, final_status="completed")

    assert len(queue.list_tasks()) == 2
    purged = queue.purge()
    assert purged == 1
    assert len(queue.list_tasks()) == 1
    assert queue.list_tasks()[0].status == "pending"
