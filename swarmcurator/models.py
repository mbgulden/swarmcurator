"""swarmcurator.models — Standardized task, queue, lane, batch, and telemetry models."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Any, Literal, Sequence

TaskStatus = Literal["pending", "leased", "completed", "failed", "dead_letter", "canceled"]

CURRENT_SCHEMA_VERSION = 1

_SAFE_IDENT_RE = re.compile(r"^[a-zA-Z0-9_\-\.]{1,128}$")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_utc().isoformat()


def _parse_iso(iso_str: str) -> datetime:
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except Exception:
        return _now_utc()


def sanitize_token(value: str, fallback: str = "default", max_len: int = 128) -> str:
    """Sanitize identifier or lane name against control/path-traversal characters."""
    if not value or not isinstance(value, str):
        return fallback
    clean = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", value.strip())
    clean = clean.strip("._")
    if not clean:
        return fallback
    return clean[:max_len]


def compute_fingerprint(provider: str, external_id: str, title: str) -> str:
    """Generate deterministic SHA256 fingerprint for deduplication."""
    raw = f"{provider.lower()}:{external_id.strip()}:{title.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class QueueFullError(Exception):
    """Raised when the queue has reached its maximum capacity."""

    def __init__(self, max_size: int) -> None:
        super().__init__(f"SwarmCurator queue is at capacity ({max_size} tasks). Purge completed tasks or increase max_queue_size.")
        self.max_size = max_size


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
    """Universal normalized task representation with retry and dead-letter governance."""
    task_id: str
    provider: str  # "linear", "github", "kanban", "composite", "generic", "custom"
    external_id: str
    title: str
    description: str = ""
    base_priority: int = 2  # 0=Urgent, 1=High, 2=Medium, 3=Low, 4=Backlog
    lane_id: str = "default"  # Exclusive lane / workspace collision domain
    labels: list[str] = field(default_factory=list)
    status: TaskStatus = "pending"
    assigned_agent: str | None = None
    retry_count: int = 0
    max_retries: int = 3
    lease_ttl_seconds: int = 600  # 10 minutes lease TTL
    error_message: str | None = None
    enqueued_at: str = field(default_factory=_now_iso)
    leased_at: str | None = None
    completed_at: str | None = None
    fingerprint: str = ""
    inputs: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.lane_id = sanitize_token(self.lane_id, fallback="default")
        self.provider = sanitize_token(self.provider, fallback="generic")
        if not self.fingerprint:
            self.fingerprint = compute_fingerprint(self.provider, self.external_id, self.title)
        # Clamp priority to valid range
        self.base_priority = max(0, min(4, int(self.base_priority)))

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
        known_fields = set(cls.__dataclass_fields__.keys())
        unknown = set(data.keys()) - known_fields
        if unknown:
            import warnings
            warnings.warn(
                f"CuratorTask.from_dict: ignoring unknown fields: {sorted(unknown)}. "
                "This may indicate a schema version mismatch. Check CURRENT_SCHEMA_VERSION.",
                stacklevel=2,
            )
        valid = {k: v for k, v in data.items() if k in known_fields}
        return cls(**valid)


@dataclass
class LaneState:
    """State tracking an actively locked workspace/repo lane with automatic lease TTL."""
    lane_id: str
    active_task_id: str
    holder_agent: str
    locked_at: str = field(default_factory=_now_iso)
    lease_ttl_seconds: int = 600
    expires_at: str = ""

    def __post_init__(self) -> None:
        if not self.expires_at:
            locked_dt = _parse_iso(self.locked_at)
            exp_dt = locked_dt + timedelta(seconds=max(1, self.lease_ttl_seconds))
            self.expires_at = exp_dt.isoformat()

    def is_expired(self, now: datetime | None = None) -> bool:
        current_time = now or _now_utc()
        exp_dt = _parse_iso(self.expires_at)
        return current_time >= exp_dt

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LaneState:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class BatchAdmissionResult:
    """Result of admitting multiple tasks/inputs simultaneously."""
    admitted: list[CuratorTask] = field(default_factory=list)
    duplicates: list[CuratorTask] = field(default_factory=list)
    rejected_full: list[CuratorTask] = field(default_factory=list)
    total_admitted: int = 0
    total_duplicates: int = 0
    total_rejected_full: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "total_admitted": self.total_admitted,
            "total_duplicates": self.total_duplicates,
            "total_rejected_full": self.total_rejected_full,
            "admitted_ids": [t.task_id for t in self.admitted],
            "duplicate_ids": [t.task_id for t in self.duplicates],
            "rejected_full_ids": [t.task_id for t in self.rejected_full],
            "admitted": [t.to_dict() for t in self.admitted],
            "duplicates": [t.to_dict() for t in self.duplicates],
        }


@dataclass
class QueueStats:
    """Comprehensive queue health and telemetry statistics."""
    total_tasks: int
    pending_count: int
    leased_count: int
    completed_count: int
    failed_count: int
    dead_letter_count: int
    canceled_count: int
    active_lanes_count: int
    priority_distribution: dict[str, int]
    oldest_pending_age_seconds: float
    schema_version: int = CURRENT_SCHEMA_VERSION
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
