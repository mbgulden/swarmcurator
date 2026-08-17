"""SwarmCurator — Universal task admission, priority aging, and lane-locking queue primitive."""

from .models import (
    CuratorTask,
    LaneState,
    TaskStatus,
    TaskInputSource,
    BatchAdmissionResult,
    QueueStats,
    compute_fingerprint,
    sanitize_token,
)
from .adapters import (
    LinearAdapter,
    GitHubAdapter,
    KanbanAdapter,
    GenericAdapter,
    AutoAdapter,
    CompositeTaskBuilder,
    MultiInputAggregator,
    verify_github_signature,
    verify_linear_signature,
)
from .aging import (
    compute_effective_priority,
    sort_tasks_by_effective_priority,
)
from .queue import SwarmCuratorQueue

__version__ = "0.3.0"

__all__ = [
    "CuratorTask",
    "LaneState",
    "TaskStatus",
    "TaskInputSource",
    "BatchAdmissionResult",
    "QueueStats",
    "compute_fingerprint",
    "sanitize_token",
    "LinearAdapter",
    "GitHubAdapter",
    "KanbanAdapter",
    "GenericAdapter",
    "AutoAdapter",
    "CompositeTaskBuilder",
    "MultiInputAggregator",
    "verify_github_signature",
    "verify_linear_signature",
    "compute_effective_priority",
    "sort_tasks_by_effective_priority",
    "SwarmCuratorQueue",
]
