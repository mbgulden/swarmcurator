"""tests/test_lane_locking.py — Unit tests for workspace/lane mutual exclusion."""

from pathlib import Path
from swarmcurator.models import CuratorTask
from swarmcurator.queue import SwarmCuratorQueue


def test_lane_locking_prevents_concurrent_dispatch(tmp_path: Path) -> None:
    queue_file = tmp_path / "queue.json"
    queue = SwarmCuratorQueue(path=queue_file)

    # Task 1 and Task 2 both target lane "repo-engine"
    t1 = CuratorTask(task_id="t1", provider="linear", external_id="1", title="Task 1", base_priority=0, lane_id="repo-engine")
    t2 = CuratorTask(task_id="t2", provider="linear", external_id="2", title="Task 2", base_priority=1, lane_id="repo-engine")

    # Task 3 targets lane "repo-docs"
    t3 = CuratorTask(task_id="t3", provider="linear", external_id="3", title="Task 3", base_priority=2, lane_id="repo-docs")

    assert queue.admit(t1) is True
    assert queue.admit(t2) is True
    assert queue.admit(t3) is True

    # 1. Agent 1 pops -> should get Task 1 (lane "repo-engine" becomes LOCKED)
    popped_1 = queue.pop_next(agent_id="agent-agy")
    assert popped_1 is not None
    assert popped_1.task_id == "t1"
    assert "repo-engine" in queue.active_lanes()

    # 2. Agent 2 pops -> Task 2 is blocked because "repo-engine" is locked.
    #    Agent 2 should receive Task 3 (lane "repo-docs") instead!
    popped_2 = queue.pop_next(agent_id="agent-ned")
    assert popped_2 is not None
    assert popped_2.task_id == "t3"
    assert "repo-docs" in queue.active_lanes()

    # 3. Agent 3 pops -> Both lanes are locked, no task available
    popped_3 = queue.pop_next(agent_id="agent-jules")
    assert popped_3 is None

    # 4. Agent 1 releases "repo-engine"
    released = queue.release_lane(lane_id="repo-engine", task_id="t1", final_status="completed")
    assert released is True
    assert "repo-engine" not in queue.active_lanes()

    # 5. Agent 3 pops again -> now receives Task 2!
    popped_4 = queue.pop_next(agent_id="agent-jules")
    assert popped_4 is not None
    assert popped_4.task_id == "t2"
