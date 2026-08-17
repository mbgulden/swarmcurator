"""tests/test_stats.py — Unit tests for QueueStats and telemetry computation."""

from pathlib import Path
from swarmcurator.models import CuratorTask
from swarmcurator.queue import SwarmCuratorQueue


def test_queue_stats_computation(tmp_path: Path) -> None:
    queue_file = tmp_path / "queue_stats.json"
    queue = SwarmCuratorQueue(path=queue_file)

    # 1. Initially empty
    stats0 = queue.get_stats()
    assert stats0.total_tasks == 0
    assert stats0.pending_count == 0
    assert stats0.active_lanes_count == 0

    # 2. Add tasks with various priorities
    queue.admit(CuratorTask(task_id="t1", provider="linear", external_id="1", title="P0 Task", base_priority=0, lane_id="lane-a"))
    queue.admit(CuratorTask(task_id="t2", provider="linear", external_id="2", title="P1 Task", base_priority=1, lane_id="lane-b"))
    queue.admit(CuratorTask(task_id="t3", provider="linear", external_id="3", title="P2 Task", base_priority=2, lane_id="lane-c"))

    # 3. Pop one task
    queue.pop_next(agent_id="agent-agy")

    stats1 = queue.get_stats()
    assert stats1.total_tasks == 3
    assert stats1.pending_count == 2
    assert stats1.leased_count == 1
    assert stats1.active_lanes_count == 1
    assert stats1.priority_distribution["P1"] == 1
    assert stats1.priority_distribution["P2"] == 1
    assert stats1.oldest_pending_age_seconds >= 0.0
