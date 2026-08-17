"""swarmcurator.queue — Hardened, concurrent priority aging and lane-locking queue."""

from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

from .models import (
    CuratorTask,
    LaneState,
    TaskStatus,
    BatchAdmissionResult,
    QueueStats,
    _now_iso,
    _now_utc,
    _parse_iso,
)
from .adapters import AutoAdapter
from .aging import sort_tasks_by_effective_priority, compute_effective_priority

DEFAULT_MAX_QUEUE_SIZE = 10_000


def _default_queue_path() -> Path:
    base = Path(os.environ.get("SWARMCURATOR_HOME", Path.home() / ".swarmcurator"))
    base.mkdir(parents=True, exist_ok=True)
    return base / "queue.json"


@contextmanager
def _file_lock(lock_path: Path, timeout_seconds: float = 10.0) -> Iterator[None]:
    """Cross-platform advisory file lock ensuring atomic multi-process operations."""
    lock_file = lock_path.with_suffix(".lock")
    start = time.time()
    has_fcntl = False
    f_desc = None

    try:
        import fcntl
        has_fcntl = True
    except ImportError:
        has_fcntl = False

    while True:
        try:
            if has_fcntl:
                f_desc = open(lock_file, "w")
                fcntl.flock(f_desc, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            else:
                # Windows / Fallback atomic O_CREAT | O_EXCL lock
                fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_RDWR)
                os.close(fd)
                break
        except (BlockingIOError, OSError):
            if time.time() - start > timeout_seconds:
                # Break stale lock if expired > timeout
                try:
                    if not has_fcntl and lock_file.exists():
                        lock_file.unlink(missing_ok=True)
                except Exception:
                    pass
            time.sleep(0.02)

    try:
        yield
    finally:
        if has_fcntl and f_desc is not None:
            try:
                fcntl.flock(f_desc, fcntl.LOCK_UN)
                f_desc.close()
            except Exception:
                pass
        if not has_fcntl:
            try:
                lock_file.unlink(missing_ok=True)
            except Exception:
                pass


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    dir_name = path.parent
    with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, encoding="utf-8") as tmp:
        json.dump(payload, tmp, indent=2, sort_keys=True)
        tmp_name = tmp.name
    os.replace(tmp_name, path)


class SwarmCuratorQueue:
    """Hardened persistent task admission queue with dynamic priority aging, exclusive lane locking, and self-healing lease recovery."""

    def __init__(
        self,
        path: Path | None = None,
        aging_half_life_seconds: float = 3600,
        max_queue_size: int = DEFAULT_MAX_QUEUE_SIZE,
    ) -> None:
        self.path = path or _default_queue_path()
        self.aging_half_life = aging_half_life_seconds
        self.max_queue_size = max_queue_size

    def _load_data_unlocked(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"tasks": [], "lanes": {}, "updated_at": _now_iso()}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"tasks": [], "lanes": {}, "updated_at": _now_iso()}

    def _save_data_unlocked(self, data: dict[str, Any]) -> None:
        data["updated_at"] = _now_iso()
        _atomic_write_json(self.path, data)

    def _reclaim_expired_leases(self, data: dict[str, Any], now: datetime | None = None) -> int:
        """Sweep and auto-recover tasks whose lease TTL has expired (crash recovery)."""
        current_time = now or _now_utc()
        raw_lanes = data.get("lanes", {})
        tasks = [CuratorTask.from_dict(t) for t in data.get("tasks", [])]

        reclaimed_count = 0
        lanes_to_delete: list[str] = []

        for lane_id, ldict in raw_lanes.items():
            lane = LaneState.from_dict(ldict)
            if lane.is_expired(current_time):
                lanes_to_delete.append(lane_id)
                # Find task and increment retry or transition to dead letter
                for idx, t in enumerate(tasks):
                    if t.task_id == lane.active_task_id:
                        t.retry_count += 1
                        if t.retry_count <= t.max_retries:
                            t.status = "pending"
                            t.assigned_agent = None
                            t.leased_at = None
                            t.error_message = f"Lease TTL expired (retry {t.retry_count}/{t.max_retries})"
                        else:
                            t.status = "dead_letter"
                            t.error_message = f"Lease TTL expired repeatedly: exceeded max retries ({t.max_retries})"
                        tasks[idx] = t
                        reclaimed_count += 1
                        break

        for lid in lanes_to_delete:
            del raw_lanes[lid]

        if reclaimed_count > 0:
            data["tasks"] = [t.to_dict() for t in tasks]
            data["lanes"] = raw_lanes

        return reclaimed_count

    def admit(self, task: CuratorTask | dict[str, Any]) -> bool:
        """Admit a single task into the queue. Returns False if duplicate or queue is full."""
        if not isinstance(task, CuratorTask):
            task = AutoAdapter.from_any(task)

        with _file_lock(self.path):
            data = self._load_data_unlocked()
            self._reclaim_expired_leases(data)
            existing_tasks = [CuratorTask.from_dict(t) for t in data.get("tasks", [])]

            if len(existing_tasks) >= self.max_queue_size:
                return False

            active_fingerprints = {
                t.fingerprint for t in existing_tasks if t.status in ["pending", "leased"]
            }
            if task.fingerprint in active_fingerprints:
                return False

            existing_tasks.append(task)
            data["tasks"] = [t.to_dict() for t in existing_tasks]
            self._save_data_unlocked(data)
            return True

    def admit_batch(self, items: Sequence[CuratorTask | dict[str, Any]]) -> BatchAdmissionResult:
        """Admit multiple tasks/inputs simultaneously in a single atomic operation."""
        result = BatchAdmissionResult()

        with _file_lock(self.path):
            data = self._load_data_unlocked()
            self._reclaim_expired_leases(data)
            existing_tasks = [CuratorTask.from_dict(t) for t in data.get("tasks", [])]

            active_fingerprints = {
                t.fingerprint for t in existing_tasks if t.status in ["pending", "leased"]
            }

            for raw_item in items:
                try:
                    task = AutoAdapter.from_any(raw_item)
                except Exception:
                    continue

                if len(existing_tasks) >= self.max_queue_size:
                    result.duplicates.append(task)
                    continue

                if task.fingerprint in active_fingerprints:
                    result.duplicates.append(task)
                    result.total_duplicates += 1
                else:
                    existing_tasks.append(task)
                    active_fingerprints.add(task.fingerprint)
                    result.admitted.append(task)
                    result.total_admitted += 1

            if result.total_admitted > 0:
                data["tasks"] = [t.to_dict() for t in existing_tasks]
                self._save_data_unlocked(data)

        return result

    def pop_next(
        self,
        agent_id: str,
        available_lanes: Sequence[str] | None = None,
    ) -> CuratorTask | None:
        """Pop highest effective priority task whose lane is free, with automatic lease recovery."""
        with _file_lock(self.path):
            data = self._load_data_unlocked()
            self._reclaim_expired_leases(data)

            tasks = [CuratorTask.from_dict(t) for t in data.get("tasks", [])]
            active_lanes = data.get("lanes", {})

            pending = [t for t in tasks if t.status == "pending"]
            if not pending:
                return None

            sorted_pending = sort_tasks_by_effective_priority(
                pending,
                aging_half_life_seconds=self.aging_half_life,
            )

            selected_task: CuratorTask | None = None
            for candidate in sorted_pending:
                if available_lanes is not None and candidate.lane_id not in available_lanes:
                    continue
                if candidate.lane_id in active_lanes:
                    continue
                selected_task = candidate
                break

            if not selected_task:
                return None

            now = _now_iso()
            for idx, t in enumerate(tasks):
                if t.task_id == selected_task.task_id:
                    t.status = "leased"
                    t.assigned_agent = agent_id
                    t.leased_at = now
                    tasks[idx] = t
                    selected_task = t
                    break

            lane_state = LaneState(
                lane_id=selected_task.lane_id,
                active_task_id=selected_task.task_id,
                holder_agent=agent_id,
                locked_at=now,
                lease_ttl_seconds=selected_task.lease_ttl_seconds,
            )
            active_lanes[selected_task.lane_id] = lane_state.to_dict()

            data["tasks"] = [t.to_dict() for t in tasks]
            data["lanes"] = active_lanes
            self._save_data_unlocked(data)

            return selected_task

    def release_lane(
        self,
        lane_id: str,
        task_id: str | None = None,
        final_status: TaskStatus = "completed",
        error_message: str | None = None,
    ) -> bool:
        """Release a locked lane and transition the task with optional retry on failure."""
        with _file_lock(self.path):
            data = self._load_data_unlocked()
            self._reclaim_expired_leases(data)

            tasks = [CuratorTask.from_dict(t) for t in data.get("tasks", [])]
            active_lanes = data.get("lanes", {})

            target_task_id = task_id
            if not target_task_id and lane_id in active_lanes:
                target_task_id = active_lanes[lane_id].get("active_task_id")

            if not target_task_id and lane_id not in active_lanes:
                return False

            now = _now_iso()
            found = False
            for idx, t in enumerate(tasks):
                if t.task_id == target_task_id or (t.lane_id == lane_id and t.status == "leased"):
                    if final_status == "failed":
                        t.retry_count += 1
                        t.error_message = error_message
                        if t.retry_count <= t.max_retries:
                            t.status = "pending"
                            t.assigned_agent = None
                            t.leased_at = None
                        else:
                            t.status = "dead_letter"
                    else:
                        t.status = final_status
                        t.completed_at = now
                    tasks[idx] = t
                    found = True

            if lane_id in active_lanes:
                del active_lanes[lane_id]

            data["tasks"] = [t.to_dict() for t in tasks]
            data["lanes"] = active_lanes
            self._save_data_unlocked(data)
            return found

    def list_tasks(self, status: TaskStatus | None = None) -> list[CuratorTask]:
        """Return all tasks matching status filter."""
        with _file_lock(self.path):
            data = self._load_data_unlocked()
            self._reclaim_expired_leases(data)
            tasks = [CuratorTask.from_dict(t) for t in data.get("tasks", [])]
            if status:
                return [t for t in tasks if t.status == status]
            return tasks

    def active_lanes(self) -> dict[str, LaneState]:
        """Return all currently locked lanes."""
        with _file_lock(self.path):
            data = self._load_data_unlocked()
            self._reclaim_expired_leases(data)
            raw_lanes = data.get("lanes", {})
            return {k: LaneState.from_dict(v) for k, v in raw_lanes.items()}

    def get_stats(self) -> QueueStats:
        """Compute live queue health and telemetry statistics."""
        with _file_lock(self.path):
            data = self._load_data_unlocked()
            self._reclaim_expired_leases(data)
            tasks = [CuratorTask.from_dict(t) for t in data.get("tasks", [])]
            raw_lanes = data.get("lanes", {})

            now = _now_utc()
            p_counts = {"P0": 0, "P1": 0, "P2": 0, "P3": 0, "P4": 0}
            oldest_age = 0.0

            pending = [t for t in tasks if t.status == "pending"]
            leased = [t for t in tasks if t.status == "leased"]
            completed = [t for t in tasks if t.status == "completed"]
            failed = [t for t in tasks if t.status == "failed"]
            dead_letter = [t for t in tasks if t.status == "dead_letter"]

            for t in pending:
                p_key = f"P{t.base_priority}"
                p_counts[p_key] = p_counts.get(p_key, 0) + 1
                age = (now - _parse_iso(t.enqueued_at)).total_seconds()
                if age > oldest_age:
                    oldest_age = age

            return QueueStats(
                total_tasks=len(tasks),
                pending_count=len(pending),
                leased_count=len(leased),
                completed_count=len(completed),
                failed_count=len(failed),
                dead_letter_count=len(dead_letter),
                active_lanes_count=len(raw_lanes),
                priority_distribution=p_counts,
                oldest_pending_age_seconds=round(oldest_age, 2),
            )

    def purge(self) -> int:
        """Purge completed, failed, dead_letter, or canceled tasks."""
        with _file_lock(self.path):
            data = self._load_data_unlocked()
            tasks = [CuratorTask.from_dict(t) for t in data.get("tasks", [])]
            initial_len = len(tasks)
            retained = [t for t in tasks if t.status in ["pending", "leased"]]
            data["tasks"] = [t.to_dict() for t in retained]
            self._save_data_unlocked(data)
            return initial_len - len(retained)
