"""tests/test_aging.py — Unit tests for priority aging and anti-starvation calculations."""

from datetime import datetime, timezone, timedelta
from swarmcurator.models import CuratorTask
from swarmcurator.aging import (
    compute_effective_priority,
    sort_tasks_by_effective_priority,
)


def test_priority_fresh_order() -> None:
    now = datetime.now(timezone.utc)
    t_urgent = CuratorTask(task_id="t1", provider="linear", external_id="1", title="P0", base_priority=0, enqueued_at=now.isoformat())
    t_medium = CuratorTask(task_id="t2", provider="linear", external_id="2", title="P2", base_priority=2, enqueued_at=now.isoformat())
    t_low = CuratorTask(task_id="t3", provider="linear", external_id="3", title="P3", base_priority=3, enqueued_at=now.isoformat())

    sorted_tasks = sort_tasks_by_effective_priority([t_medium, t_low, t_urgent], now=now)
    assert [t.task_id for t in sorted_tasks] == ["t1", "t2", "t3"]


def test_priority_aging_anti_starvation() -> None:
    now = datetime.now(timezone.utc)
    # A fresh P1 task enqueued right now (Base score = 3000)
    t_fresh_p1 = CuratorTask(task_id="t-p1", provider="linear", external_id="1", title="Fresh P1", base_priority=1, enqueued_at=now.isoformat())

    # An old P3 task enqueued 100 hours ago (Base score 1000 + (100 * 3600 / 3600) * 100 = 1000 + 10000 = 11000)
    old_time = (now - timedelta(hours=100)).isoformat()
    t_old_p3 = CuratorTask(task_id="t-p3", provider="linear", external_id="2", title="Starved P3", base_priority=3, enqueued_at=old_time)

    # The starved P3 task should bubble up above the fresh P1 task!
    score_p1 = compute_effective_priority(t_fresh_p1, now=now, aging_half_life_seconds=3600)
    score_p3 = compute_effective_priority(t_old_p3, now=now, aging_half_life_seconds=3600)

    assert score_p3 > score_p1
    sorted_tasks = sort_tasks_by_effective_priority([t_fresh_p1, t_old_p3], now=now)
    assert sorted_tasks[0].task_id == "t-p3"
