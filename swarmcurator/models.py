"""swarmcurator.models — Standardized task, queue, and lane models."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Literal

TaskStatus = Literal["pending", "leased", "completed", "failed", "canceled"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_fingerprint(provider: str, external_id: str, title: str) -> str:
    """Generate deterministic SHA256 fingerprint for deduplication."""
    raw = f"{provider.lower()}:{external_id.strip()}:{title.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class CuratorTask:
    """Universal normalized task representation across issue providers."""
    task_id: str
    provider: str  # "linear", "github", "kanban", "custom"
    external_id: str
    title: str
    description: str = ""
    base_priority: int = 2  # 0=Urgent, 1=High, 2=Medium, 3=Low, 4=Backlog
    lane_id: str = "default"  # Exclusive lane / workspace collision domain
    labels: list[str] = field(default_factory=list)
    status: TaskStatus = "pending"
    assigned_agent: str | None = None
    enqueued_at: str = field(default_factory=_now_iso)
    leased_at: str | None = None
    completed_at: str | None = None
    fingerprint: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.fingerprint:
            self.fingerprint = compute_fingerprint(self.provider, self.external_id, self.title)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CuratorTask:
        valid = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid)


@dataclass
class LaneState:
    """State tracking an actively locked workspace/repo lane."""
    lane_id: str
    active_task_id: str
    holder_agent: str
    locked_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LaneState:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
