"""tests/test_retry_dlq.py — Unit tests for failure retry limit and Dead-Letter Queue (DLQ) transitions."""

from pathlib import Path
from swarmcurator.models import CuratorTask
from swarmcurator.queue import SwarmCuratorQueue


def test_retry_and_dead_letter_queue(tmp_path: Path) -> None:
    queue_file = tmp_path / "queue_dlq.json"
    queue = SwarmCuratorQueue(path=queue_file)

    task = CuratorTask(
        task_id="t-flaky",
        provider="linear",
        external_id="GRO-FLAKY",
        title="Flaky network test",
        base_priority=1,
        lane_id="lane-flaky",
        max_retries=2,
    )
    queue.admit(task)

    # Attempt 1: Pop and fail
    p1 = queue.pop_next(agent_id="worker-1")
    assert p1 is not None
    queue.release_lane(lane_id="lane-flaky", task_id="t-flaky", final_status="failed", error_message="Network 503")

    tasks = queue.list_tasks()
    assert tasks[0].status == "pending"
    assert tasks[0].retry_count == 1
    assert tasks[0].error_message == "Network 503"

    # Attempt 2: Pop and fail again
    p2 = queue.pop_next(agent_id="worker-2")
    assert p2 is not None
    queue.release_lane(lane_id="lane-flaky", task_id="t-flaky", final_status="failed", error_message="Network 504")

    tasks = queue.list_tasks()
    assert tasks[0].status == "pending"
    assert tasks[0].retry_count == 2

    # Attempt 3: Pop and fail (exceeds max_retries=2 -> must transition to dead_letter!)
    p3 = queue.pop_next(agent_id="worker-3")
    assert p3 is not None
    queue.release_lane(lane_id="lane-flaky", task_id="t-flaky", final_status="failed", error_message="Permanent 500")

    tasks = queue.list_tasks()
    assert tasks[0].status == "dead_letter"
    assert tasks[0].retry_count == 3

    # Attempt 4: Should be no pending tasks left!
    p4 = queue.pop_next(agent_id="worker-4")
    assert p4 is None

    # Check DLQ listing
    dlq_tasks = queue.list_tasks(status="dead_letter")
    assert len(dlq_tasks) == 1
    assert dlq_tasks[0].task_id == "t-flaky"
