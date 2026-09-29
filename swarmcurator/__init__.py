"""SwarmCurator — Universal task admission, priority aging, and lane-locking queue primitive."""

from .adapters import (
    AutoAdapter,
    CompositeTaskBuilder,
    GenericAdapter,
    GitHubAdapter,
    KanbanAdapter,
    LinearAdapter,
    MultiInputAggregator,
    verify_github_signature,
    verify_linear_signature,
)
from .aging import (
    compute_effective_priority,
    sort_tasks_by_effective_priority,
)
from .models import (
    BatchAdmissionResult,
    CuratorTask,
    LaneState,
    QueueStats,
    TaskInputSource,
    TaskStatus,
    compute_fingerprint,
    sanitize_token,
)
from .queue import SwarmCuratorQueue

__version__ = "0.4.0"

__all__ = [
    "__version__",
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
