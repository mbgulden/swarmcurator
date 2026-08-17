"""tests/test_priority_override.py — Tests for set_priority() dynamic task escalation."""

from pathlib import Path
from swarmcurator.models import CuratorTask
from swarmcurator.queue import SwarmCuratorQueue
from swarmcurator.aging import sort_tasks_by_effective_priority


def _make_task(task_id: str, priority: int, lane: str | None = None) -> CuratorTask:
    return CuratorTask(
        task_id=task_id,
        provider="generic",
        external_id=task_id,
        title=f"Task {task_id}",
        base_priority=priority,
        lane_id=lane or f"lane-{task_id}",
    )


def test_set_priority_escalates_task(tmp_path: Path) -> None:
    """A P3 task promoted to P0 should become first in dispatch order."""
    queue = SwarmCuratorQueue(path=tmp_path / "q.json")

    # P1 task (High)
    queue.admit(_make_task("high-task", priority=1, lane="lane-a"))
    # P3 task (Low) — normally would dispatch second
    queue.admit(_make_task("low-task", priority=3, lane="lane-b"))

    pending = queue.list_tasks(status="pending")
    ordered_before = sort_tasks_by_effective_priority(pending)
    assert ordered_before[0].task_id == "high-task"  # High first initially

    # ESCALATE low-task to P0 (Urgent)
    updated = queue.set_priority("low-task", new_priority=0)
    assert updated is True

    pending = queue.list_tasks(status="pending")
    updated_task = next(t for t in pending if t.task_id == "low-task")
    assert updated_task.base_priority == 0

    # After escalation, low-task should be dispatched first
    first_dispatch = queue.pop_next(agent_id="agent-ops")
    assert first_dispatch is not None
    assert first_dispatch.task_id == "low-task"
    assert first_dispatch.base_priority == 0


def test_set_priority_deescalates_task(tmp_path: Path) -> None:
    """A P0 task de-escalated to P4 should drop to last position."""
    queue = SwarmCuratorQueue(path=tmp_path / "q.json")

    queue.admit(_make_task("urgent-task", priority=0, lane="lane-a"))
    queue.admit(_make_task("medium-task", priority=2, lane="lane-b"))

    # De-escalate urgent to backlog
    updated = queue.set_priority("urgent-task", new_priority=4)
    assert updated is True

    # medium-task should now dispatch first
    first = queue.pop_next(agent_id="agent-x")
    assert first is not None
    assert first.task_id == "medium-task"


def test_set_priority_on_leased_task_returns_false(tmp_path: Path) -> None:
    """set_priority() should not affect tasks that are already leased."""
    queue = SwarmCuratorQueue(path=tmp_path / "q.json")
    queue.admit(_make_task("t1", priority=2))
    queue.pop_next(agent_id="agent-x")

    result = queue.set_priority("t1", new_priority=0)
    assert result is False


def test_set_priority_on_nonexistent_returns_false(tmp_path: Path) -> None:
    queue = SwarmCuratorQueue(path=tmp_path / "q.json")
    result = queue.set_priority("does-not-exist", new_priority=0)
    assert result is False


def test_set_priority_clamps_values(tmp_path: Path) -> None:
    """set_priority() should clamp out-of-range values to [0, 4]."""
    queue = SwarmCuratorQueue(path=tmp_path / "q.json")
    queue.admit(_make_task("t1", priority=2))

    # Setting priority to -5 should clamp to 0
    queue.set_priority("t1", new_priority=-5)
    tasks = queue.list_tasks(status="pending")
    assert tasks[0].base_priority == 0

    # Setting priority to 99 should clamp to 4
    queue.set_priority("t1", new_priority=99)
    tasks = queue.list_tasks(status="pending")
    assert tasks[0].base_priority == 4
