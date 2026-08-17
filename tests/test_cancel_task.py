"""tests/test_cancel_task.py — Tests for cancel_task() on pending and leased tasks."""

from pathlib import Path
from swarmcurator.models import CuratorTask
from swarmcurator.queue import SwarmCuratorQueue


def _make_task(task_id: str, lane: str = "lane-a") -> CuratorTask:
    return CuratorTask(
        task_id=task_id,
        provider="generic",
        external_id=task_id,
        title=f"Task {task_id}",
        base_priority=2,
        lane_id=lane,
    )


def test_cancel_pending_task(tmp_path: Path) -> None:
    """cancel_task() on a pending task marks it canceled and removes from dispatchable pool."""
    queue = SwarmCuratorQueue(path=tmp_path / "q.json")
    queue.admit(_make_task("t-pending"))

    result = queue.cancel_task("t-pending")
    assert result is True

    tasks = queue.list_tasks()
    assert tasks[0].status == "canceled"

    # Should not be dispatchable
    popped = queue.pop_next(agent_id="agent-x")
    assert popped is None


def test_cancel_leased_task_releases_lane(tmp_path: Path) -> None:
    """cancel_task() on a leased task also releases the locked lane."""
    queue = SwarmCuratorQueue(path=tmp_path / "q.json")
    queue.admit(_make_task("t-leased", lane="lane-x"))
    queue.admit(_make_task("t-next", lane="lane-x"))  # waits behind lane-x

    # Pop t-leased
    popped = queue.pop_next(agent_id="agent-ned")
    assert popped is not None
    assert popped.task_id == "t-leased"

    # Lane is locked
    assert "lane-x" in queue.active_lanes()

    # Cancel the leased task
    result = queue.cancel_task("t-leased")
    assert result is True

    # Lane should now be freed
    assert "lane-x" not in queue.active_lanes()

    # t-next should now be dispatchable
    next_task = queue.pop_next(agent_id="agent-agy")
    assert next_task is not None
    assert next_task.task_id == "t-next"


def test_cancel_nonexistent_task_returns_false(tmp_path: Path) -> None:
    queue = SwarmCuratorQueue(path=tmp_path / "q.json")
    result = queue.cancel_task("does-not-exist")
    assert result is False


def test_cancel_already_completed_task_returns_false(tmp_path: Path) -> None:
    queue = SwarmCuratorQueue(path=tmp_path / "q.json")
    queue.admit(_make_task("t-done"))
    queue.pop_next(agent_id="agent-a")
    queue.release_lane("lane-a", task_id="t-done", final_status="completed")

    result = queue.cancel_task("t-done")
    assert result is False


def test_cancel_task_shows_in_stats(tmp_path: Path) -> None:
    """Canceled tasks should appear in stats.canceled_count."""
    queue = SwarmCuratorQueue(path=tmp_path / "q.json")
    queue.admit(_make_task("t-cancel-1"))
    queue.admit(_make_task("t-cancel-2", lane="lane-b"))

    queue.cancel_task("t-cancel-1")
    queue.cancel_task("t-cancel-2")

    stats = queue.get_stats()
    assert stats.canceled_count == 2
    assert stats.pending_count == 0
