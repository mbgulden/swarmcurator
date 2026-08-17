"""swarmcurator.aging — Anti-starvation priority aging engine."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence
from .models import CuratorTask, _parse_iso

DEFAULT_AGING_HALF_LIFE_SECONDS = 3600  # 1 hour


def compute_effective_priority(
    task: CuratorTask,
    now: datetime | None = None,
    aging_half_life_seconds: float = DEFAULT_AGING_HALF_LIFE_SECONDS,
) -> float:
    """Calculate dynamic priority score where higher number indicates higher dispatch urgency.

    Formula:
      Base Score = (4 - base_priority) * 1000
      Aging Boost = (elapsed_seconds / half_life) * 100
      Effective Score = Base Score + Aging Boost

    Examples:
      - A P0 (Urgent) task enqueued now scores 4000.0
      - A P4 (Backlog) task enqueued 3 hours ago with half_life=1h scores (0) + (10800/3600)*100 = 300.0
      - A P3 (Low) task sitting for 4 hours beats a freshly queued P2 (Medium) task after ~36 hours.
        This ensures low-priority work is never permanently starved.
    """
    current_time = now or datetime.now(timezone.utc)
    enqueued_dt = _parse_iso(task.enqueued_at)

    elapsed_seconds = max(0.0, (current_time - enqueued_dt).total_seconds())

    # Base score: P0=4000, P1=3000, P2=2000, P3=1000, P4=0
    base_score = max(0, 4 - task.base_priority) * 1000.0

    # Aging boost
    aging_boost = (elapsed_seconds / max(1.0, aging_half_life_seconds)) * 100.0

    return round(base_score + aging_boost, 4)


def sort_tasks_by_effective_priority(
    tasks: Sequence[CuratorTask],
    now: datetime | None = None,
    aging_half_life_seconds: float = DEFAULT_AGING_HALF_LIFE_SECONDS,
) -> list[CuratorTask]:
    """Sort tasks by dynamic effective priority in descending order (highest score first)."""
    current_time = now or datetime.now(timezone.utc)
    return sorted(
        tasks,
        key=lambda t: compute_effective_priority(t, current_time, aging_half_life_seconds),
        reverse=True,
    )
