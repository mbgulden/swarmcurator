"""swarmcurator.models — Standardized task, queue, lane, and batch models."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Literal, Sequence

TaskStatus = Literal["pending", "leased", "completed", "failed", "canceled"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_fingerprint(provider: str, external_id: str, title: str) -> str:
    """Generate deterministic SHA256 fingerprint for deduplication."""
    raw = f"{provider.lower()}:{external_id.strip()}:{title.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class TaskInputSource:
    """Represents an auxiliary input stream or context attached to a task."""
    source_type: str  # e.g., "linear", "github_pr", "ci_log", "figma", "slack", "spec_file"
    reference: str    # e.g., URL, file path, commit SHA, or external ID
    content: str = "" # Optional raw payload / body snippet
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskInputSource:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class CuratorTask:
    """Universal normalized task representation supporting multi-provider & multi-input contexts."""
    task_id: str
    provider: str  # "linear", "github", "kanban", "composite", "custom"
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
    inputs: list[dict[str, Any]] = field(default_factory=list)  # Multi-input sources / attachments
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.fingerprint:
            self.fingerprint = compute_fingerprint(self.provider, self.external_id, self.title)

    def add_input_source(self, source_type: str, reference: str, content: str = "", metadata: dict[str, Any] | None = None) -> None:
        """Attach an auxiliary context or input stream to this task."""
        src = TaskInputSource(
            source_type=source_type,
            reference=reference,
            content=content,
            metadata=metadata or {},
        )
        self.inputs.append(src.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CuratorTask:
        valid = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid)


@dataclass
class BatchAdmissionResult:
    """Result of admitting multiple tasks/inputs simultaneously."""
    admitted: list[CuratorTask] = field(default_factory=list)
    duplicates: list[CuratorTask] = field(default_factory=list)
    total_admitted: int = 0
    total_duplicates: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "total_admitted": self.total_admitted,
            "total_duplicates": self.total_duplicates,
            "admitted_ids": [t.task_id for t in self.admitted],
            "duplicate_ids": [t.task_id for t in self.duplicates],
            "admitted": [t.to_dict() for t in self.admitted],
            "duplicates": [t.to_dict() for t in self.duplicates],
        }


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
