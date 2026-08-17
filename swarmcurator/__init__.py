"""SwarmCurator — Universal task admission, priority aging, and lane-locking queue primitive."""

from .models import (
    CuratorTask,
    LaneState,
    TaskStatus,
    compute_fingerprint,
)
from .adapters import (
    LinearAdapter,
    GitHubAdapter,
    KanbanAdapter,
    GenericAdapter,
)
from .aging import (
    compute_effective_priority,
    sort_tasks_by_effective_priority,
)
from .queue import SwarmCuratorQueue

__version__ = "0.1.0"

__all__ = [
    "CuratorTask",
    "LaneState",
    "TaskStatus",
    "compute_fingerprint",
    "LinearAdapter",
    "GitHubAdapter",
    "KanbanAdapter",
    "GenericAdapter",
    "compute_effective_priority",
    "sort_tasks_by_effective_priority",
    "SwarmCuratorQueue",
]
