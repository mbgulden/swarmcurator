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
    CURRENT_SCHEMA_VERSION,
    CuratorTask,
    LaneState,
    QueueFullError,
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

import threading

_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCKS_META = threading.Lock()


def _get_thread_lock(path: Path) -> threading.Lock:
    """Return a per-queue-path threading.Lock for intra-process serialization."""
    key = str(path.resolve())
    with _THREAD_LOCKS_META:
        if key not in _THREAD_LOCKS:
            _THREAD_LOCKS[key] = threading.Lock()
        return _THREAD_LOCKS[key]

def _default_queue_path() -> Path:
    base = Path(os.environ.get("SWARMCURATOR_HOME", Path.home() / ".swarmcurator"))
    base.mkdir(parents=True, exist_ok=True)
    return base / "queue.json"


@contextmanager
def _file_lock(lock_path: Path, timeout_seconds: float = 10.0) -> Iterator[None]:
    """Two-level lock ensuring atomic operations both across threads and across processes.

    Level 1: threading.Lock — serializes concurrent threads within the same process.
             This prevents the flock re-entrancy issue on Linux where two threads in
             the same process can each acquire flock on different open fds of the same file.
    Level 2: fcntl.flock(LOCK_EX, blocking) — serializes across separate OS processes.

    Raises TimeoutError if the file lock cannot be acquired within timeout_seconds.
    """
    thread_lock = _get_thread_lock(lock_path)
    lock_file = lock_path.with_suffix(".lock")
    has_fcntl = False
    f_desc = None

    try:
        import fcntl
        has_fcntl = True
    except ImportError:
        has_fcntl = False

    # Level 1: acquire thread lock first (blocks until this thread has sole access)
    thread_lock.acquire()
    try:
        # Level 2: acquire cross-process file lock
        if has_fcntl:
            import fcntl as _fcntl
            f_desc = open(lock_file, "w")
            # Blocking lock — waits until the process-level lock is available
            # One fd opened once per context, so flock upgrade works correctly
            _fcntl.flock(f_desc, _fcntl.LOCK_EX)
        else:
            # Windows O_EXCL spin-acquire with timeout
            start = time.monotonic()
            while True:
                elapsed = time.monotonic() - start
                if elapsed >= timeout_seconds:
                    try:
                        lock_file.unlink(missing_ok=True)
                    except Exception:
                        pass
                    try:
                        fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_RDWR)
                        os.close(fd)
                        break
                    except OSError:
                        raise TimeoutError(
                            f"SwarmCurator: could not acquire file lock for {lock_path} "
                            f"after {timeout_seconds:.1f}s. Check for stuck processes or stale lock at {lock_file}."
                        )
                try:
                    fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_RDWR)
                    os.close(fd)
                    break
                except OSError:
                    time.sleep(0.02)

        try:
            yield
        finally:
            if has_fcntl and f_desc is not None:
                try:
                    import fcntl as _fcntl
                    _fcntl.flock(f_desc, _fcntl.LOCK_UN)
                    f_desc.close()
                except Exception:
                    pass
            if not has_fcntl:
                try:
                    lock_file.unlink(missing_ok=True)
                except Exception:
                    pass
            elif f_desc is not None:
                try:
                    lock_file.unlink(missing_ok=True)
                except Exception:
                    pass
    finally:
        # Always release the thread lock
        thread_lock.release()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    dir_name = path.parent
    with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, encoding="utf-8") as tmp:
        json.dump(payload, tmp, indent=2, sort_keys=True)
        tmp_name = tmp.name
    os.replace(tmp_name, path)


def _migrate_data(data: dict[str, Any]) -> dict[str, Any]:
    """Upgrade queue JSON from older schema versions to CURRENT_SCHEMA_VERSION."""
    version = data.get("schema_version", 0)

    if version == CURRENT_SCHEMA_VERSION:
        return data

    # Version 0 → 1: ensure tasks have retry/lease/max_retries fields
    if version == 0:
        for task in data.get("tasks", []):
            task.setdefault("retry_count", 0)
            task.setdefault("max_retries", 3)
            task.setdefault("lease_ttl_seconds", 600)
            task.setdefault("error_message", None)
            task.setdefault("inputs", [])
            task.setdefault("metadata", {})
        data["schema_version"] = 1

    return data


class SwarmCuratorQueue:
    """Hardened persistent task admission queue with dynamic priority aging,
    exclusive lane locking, self-healing lease recovery, and schema migration.

    Features:
    - Zero external dependencies (pure Python stdlib)
    - Cross-process atomic file locking with stale-lock recovery
    - Anti-starvation priority aging: low-priority tasks bubble up over time
    - Exclusive workspace lane locking prevents multi-agent collisions
    - Self-healing lease TTL: crashed agent tasks are automatically reclaimed
    - Dead-letter queue with configurable retry limits
    - Schema versioning for safe upgrades across deployments
    """

    def __init__(
        self,
        path: Path | None = None,
        aging_half_life_seconds: float = 3600,
        max_queue_size: int = DEFAULT_MAX_QUEUE_SIZE,
    ) -> None:
        self.path = path or _default_queue_path()
        self.aging_half_life = aging_half_life_seconds
        self.max_queue_size = max_queue_size

    def _load_data_unlocked(self) -> tuple[dict[str, Any], bool]:
        """Load and migrate queue data. Returns (data, was_migrated)."""
        if not self.path.exists():
            return {"schema_version": CURRENT_SCHEMA_VERSION, "tasks": [], "lanes": {}, "updated_at": _now_iso()}, False
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            old_version = raw.get("schema_version", 0)
            migrated = _migrate_data(raw)
            was_migrated = old_version != CURRENT_SCHEMA_VERSION
            return migrated, was_migrated
        except Exception:
            return {"schema_version": CURRENT_SCHEMA_VERSION, "tasks": [], "lanes": {}, "updated_at": _now_iso()}, False

    def _save_data_unlocked(self, data: dict[str, Any]) -> None:
        data["updated_at"] = _now_iso()
        data["schema_version"] = CURRENT_SCHEMA_VERSION
        _atomic_write_json(self.path, data)

    def _reclaim_expired_leases(self, data: dict[str, Any], now: datetime | None = None) -> int:
        """Sweep and auto-recover tasks whose lease TTL has expired (crash recovery).

        IMPORTANT: Call _save_data_unlocked(data) if the return value > 0 to persist
        the recovery. Callers inside the file lock are responsible for saving.
        """
        current_time = now or _now_utc()
        raw_lanes = data.get("lanes", {})
        tasks = [CuratorTask.from_dict(t) for t in data.get("tasks", [])]

        reclaimed_count = 0
        lanes_to_delete: list[str] = []

        for lane_id, ldict in raw_lanes.items():
            lane = LaneState.from_dict(ldict)
            if lane.is_expired(current_time):
                lanes_to_delete.append(lane_id)
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

    def admit(self, task: CuratorTask | dict[str, Any], raise_if_full: bool = False) -> bool:
        """Admit a single task into the queue.

        Returns:
            True  — task was admitted successfully
            False — task is a duplicate of an active/pending task

        Raises:
            QueueFullError — if raise_if_full=True and queue is at max capacity
        """
        if not isinstance(task, CuratorTask):
            task = AutoAdapter.from_any(task)

        with _file_lock(self.path):
            data, was_migrated = self._load_data_unlocked()
            reclaimed = self._reclaim_expired_leases(data)
            existing_tasks = [CuratorTask.from_dict(t) for t in data.get("tasks", [])]

            if len(existing_tasks) >= self.max_queue_size:
                if raise_if_full:
                    raise QueueFullError(self.max_queue_size)
                return False

            active_fingerprints = {
                t.fingerprint for t in existing_tasks if t.status in ["pending", "leased"]
            }
            if task.fingerprint in active_fingerprints:
                return False

            existing_tasks.append(task)
            data["tasks"] = [t.to_dict() for t in existing_tasks]
            if reclaimed > 0:
                # Ensure reclaim mutations are also persisted
                pass  # already written to data["tasks"] above
            self._save_data_unlocked(data)
            return True

    def admit_batch(self, items: Sequence[CuratorTask | dict[str, Any]]) -> BatchAdmissionResult:
        """Admit multiple tasks/inputs simultaneously in a single atomic operation."""
        result = BatchAdmissionResult()

        with _file_lock(self.path):
            data, was_migrated = self._load_data_unlocked()
            reclaimed = self._reclaim_expired_leases(data)
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
                    result.rejected_full.append(task)
                    result.total_rejected_full += 1
                elif task.fingerprint in active_fingerprints:
                    result.duplicates.append(task)
                    result.total_duplicates += 1
                else:
                    existing_tasks.append(task)
                    active_fingerprints.add(task.fingerprint)
                    result.admitted.append(task)
                    result.total_admitted += 1

            if result.total_admitted > 0 or reclaimed > 0 or was_migrated:
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
            data, was_migrated = self._load_data_unlocked()
            reclaimed = self._reclaim_expired_leases(data)

            tasks = [CuratorTask.from_dict(t) for t in data.get("tasks", [])]
            active_lanes = data.get("lanes", {})

            pending = [t for t in tasks if t.status == "pending"]
            if not pending:
                if reclaimed > 0 or was_migrated:
                    self._save_data_unlocked(data)
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
                if reclaimed > 0 or was_migrated:
                    self._save_data_unlocked(data)
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
            data, was_migrated = self._load_data_unlocked()
            reclaimed = self._reclaim_expired_leases(data)

            tasks = [CuratorTask.from_dict(t) for t in data.get("tasks", [])]
            active_lanes = data.get("lanes", {})

            target_task_id = task_id
            if not target_task_id and lane_id in active_lanes:
                target_task_id = active_lanes[lane_id].get("active_task_id")

            if not target_task_id and lane_id not in active_lanes:
                if reclaimed > 0 or was_migrated:
                    self._save_data_unlocked(data)
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

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a task by ID regardless of its current state (pending or leased).

        Releases any held lane lock for the task and marks it canceled.

        Returns:
            True  — task was found and canceled
            False — task not found or already completed/dead_letter
        """
        with _file_lock(self.path):
            data, _migrated = self._load_data_unlocked()
            self._reclaim_expired_leases(data)

            tasks = [CuratorTask.from_dict(t) for t in data.get("tasks", [])]
            active_lanes = data.get("lanes", {})

            found = False
            now = _now_iso()
            for idx, t in enumerate(tasks):
                if t.task_id == task_id:
                    if t.status in ("completed", "canceled", "dead_letter"):
                        return False
                    t.status = "canceled"
                    t.completed_at = now
                    tasks[idx] = t
                    found = True
                    # Release any associated lane lock
                    if t.lane_id in active_lanes:
                        held = active_lanes[t.lane_id]
                        if held.get("active_task_id") == task_id:
                            del active_lanes[t.lane_id]
                    break

            if found:
                data["tasks"] = [t.to_dict() for t in tasks]
                data["lanes"] = active_lanes
                self._save_data_unlocked(data)

            return found

    def set_priority(self, task_id: str, new_priority: int) -> bool:
        """Override the base priority of any pending task.

        Useful for operator escalation (e.g., promoting a P3 bug to P0 urgent after
        discovering it is production-impacting). Has no effect on leased/completed tasks.

        Args:
            task_id: The task to escalate or de-escalate.
            new_priority: 0=Urgent, 1=High, 2=Medium, 3=Low, 4=Backlog

        Returns:
            True if the priority was updated, False if not found or not pending.
        """
        new_priority = max(0, min(4, int(new_priority)))

        with _file_lock(self.path):
            data, _migrated = self._load_data_unlocked()
            self._reclaim_expired_leases(data)

            tasks = [CuratorTask.from_dict(t) for t in data.get("tasks", [])]
            found = False

            for idx, t in enumerate(tasks):
                if t.task_id == task_id:
                    if t.status != "pending":
                        return False
                    t.base_priority = new_priority
                    # Refresh fingerprint NOT needed — priority is not part of dedup key
                    tasks[idx] = t
                    found = True
                    break

            if found:
                data["tasks"] = [t.to_dict() for t in tasks]
                self._save_data_unlocked(data)

            return found

    def list_tasks(self, status: TaskStatus | None = None) -> list[CuratorTask]:
        """Return all tasks matching status filter. Auto-saves any reclaimed leases or migrations."""
        with _file_lock(self.path):
            data, was_migrated = self._load_data_unlocked()
            reclaimed = self._reclaim_expired_leases(data)
            if reclaimed > 0 or was_migrated:
                self._save_data_unlocked(data)
            tasks = [CuratorTask.from_dict(t) for t in data.get("tasks", [])]
            if status:
                return [t for t in tasks if t.status == status]
            return tasks

    def active_lanes(self) -> dict[str, LaneState]:
        """Return all currently locked lanes. Auto-saves any reclaimed leases or migrations."""
        with _file_lock(self.path):
            data, was_migrated = self._load_data_unlocked()
            reclaimed = self._reclaim_expired_leases(data)
            if reclaimed > 0 or was_migrated:
                self._save_data_unlocked(data)
            raw_lanes = data.get("lanes", {})
            return {k: LaneState.from_dict(v) for k, v in raw_lanes.items()}

    def get_stats(self) -> QueueStats:
        """Compute live queue health and telemetry statistics. Auto-saves reclaimed leases or migrations."""
        with _file_lock(self.path):
            data, was_migrated = self._load_data_unlocked()
            reclaimed = self._reclaim_expired_leases(data)
            if reclaimed > 0 or was_migrated:
                self._save_data_unlocked(data)

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
            canceled = [t for t in tasks if t.status == "canceled"]

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
                canceled_count=len(canceled),
                active_lanes_count=len(raw_lanes),
                priority_distribution=p_counts,
                oldest_pending_age_seconds=round(oldest_age, 2),
            )

    def purge(self) -> int:
        """Purge completed, failed, dead_letter, and canceled tasks. Returns count purged."""
        with _file_lock(self.path):
            data, _migrated = self._load_data_unlocked()
            tasks = [CuratorTask.from_dict(t) for t in data.get("tasks", [])]
            initial_len = len(tasks)
            retained = [t for t in tasks if t.status in ["pending", "leased"]]
            data["tasks"] = [t.to_dict() for t in retained]
            self._save_data_unlocked(data)
            return initial_len - len(retained)
