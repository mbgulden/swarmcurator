"""tests/test_queue_full.py — Tests for QueueFullError and rejected_full tracking in batch admission."""

import pytest
from pathlib import Path
from swarmcurator.models import CuratorTask, QueueFullError
from swarmcurator.queue import SwarmCuratorQueue


def _make_task(n: int) -> CuratorTask:
    return CuratorTask(
        task_id=f"task-{n}",
        provider="generic",
        external_id=str(n),
        title=f"Task {n}",
        base_priority=2,
        lane_id=f"lane-{n}",
    )


def test_admit_returns_false_when_full(tmp_path: Path) -> None:
    """admit() should return False (not raise) by default when queue is at capacity."""
    queue = SwarmCuratorQueue(path=tmp_path / "q.json", max_queue_size=3)

    assert queue.admit(_make_task(1)) is True
    assert queue.admit(_make_task(2)) is True
    assert queue.admit(_make_task(3)) is True

    # 4th task should return False (queue full, default behavior)
    result = queue.admit(_make_task(4))
    assert result is False


def test_admit_raises_when_full_with_raise_if_full(tmp_path: Path) -> None:
    """admit(raise_if_full=True) should raise QueueFullError when queue is at capacity."""
    queue = SwarmCuratorQueue(path=tmp_path / "q.json", max_queue_size=2)
    queue.admit(_make_task(1))
    queue.admit(_make_task(2))

    with pytest.raises(QueueFullError) as exc_info:
        queue.admit(_make_task(3), raise_if_full=True)

    assert "capacity" in str(exc_info.value).lower()


def test_batch_admission_tracks_rejected_full(tmp_path: Path) -> None:
    """admit_batch() should track tasks rejected due to queue capacity separately from duplicates."""
    queue = SwarmCuratorQueue(path=tmp_path / "q.json", max_queue_size=3)

    items = [_make_task(i) for i in range(1, 7)]  # 6 tasks, capacity 3
    result = queue.admit_batch(items)

    assert result.total_admitted == 3
    assert result.total_rejected_full == 3
    assert result.total_duplicates == 0
    assert len(result.rejected_full) == 3

    # Queue should still have exactly 3 tasks
    assert len(queue.list_tasks()) == 3


def test_queue_full_error_has_useful_message(tmp_path: Path) -> None:
    queue = SwarmCuratorQueue(path=tmp_path / "q.json", max_queue_size=1)
    queue.admit(_make_task(1))

    with pytest.raises(QueueFullError) as exc_info:
        queue.admit(_make_task(2), raise_if_full=True)

    msg = str(exc_info.value)
    assert "1" in msg  # max_size referenced
    assert exc_info.value.max_size == 1
