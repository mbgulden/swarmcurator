"""swarmcurator.queue — Priority aging, lane-locking task admission queue with multi-input batch support."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .models import CuratorTask, LaneState, TaskStatus, BatchAdmissionResult, _now_iso
from .adapters import AutoAdapter
from .aging import sort_tasks_by_effective_priority, compute_effective_priority


def _default_queue_path() -> Path:
    base = Path(os.environ.get("SWARMCURATOR_HOME", Path.home() / ".swarmcurator"))
    base.mkdir(parents=True, exist_ok=True)
    return base / "queue.json"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    dir_name = path.parent
    with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, encoding="utf-8") as tmp:
        json.dump(payload, tmp, indent=2, sort_keys=True)
        tmp_name = tmp.name
    os.replace(tmp_name, path)


class SwarmCuratorQueue:
    """Persistent task admission queue with dynamic priority aging, exclusive lane locking, and multi-input batch support."""

    def __init__(
        self,
        path: Path | None = None,
        aging_half_life_seconds: float = 3600,
    ) -> None:
        self.path = path or _default_queue_path()
        self.aging_half_life = aging_half_life_seconds

    def _load_data(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"tasks": [], "lanes": {}, "updated_at": _now_iso()}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"tasks": [], "lanes": {}, "updated_at": _now_iso()}

    def _save_data(self, data: dict[str, Any]) -> None:
        data["updated_at"] = _now_iso()
        _atomic_write_json(self.path, data)

    def admit(self, task: CuratorTask | dict[str, Any]) -> bool:
        """Admit a single task into the queue. Returns False if duplicate fingerprint already exists."""
        if not isinstance(task, CuratorTask):
            task = AutoAdapter.from_any(task)

        data = self._load_data()
        existing_tasks = [CuratorTask.from_dict(t) for t in data.get("tasks", [])]

        active_fingerprints = {
            t.fingerprint for t in existing_tasks if t.status in ["pending", "leased"]
        }
        if task.fingerprint in active_fingerprints:
            return False

        existing_tasks.append(task)
        data["tasks"] = [t.to_dict() for t in existing_tasks]
        self._save_data(data)
        return True

    def admit_batch(self, items: Sequence[CuratorTask | dict[str, Any]]) -> BatchAdmissionResult:
        """Admit multiple tasks/inputs simultaneously in a single atomic operation."""
        data = self._load_data()
        existing_tasks = [CuratorTask.from_dict(t) for t in data.get("tasks", [])]

        active_fingerprints = {
            t.fingerprint for t in existing_tasks if t.status in ["pending", "leased"]
        }

        result = BatchAdmissionResult()

        for raw_item in items:
            try:
                task = AutoAdapter.from_any(raw_item)
            except Exception:
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
            self._save_data(data)

        return result

    def pop_next(
        self,
        agent_id: str,
        available_lanes: Sequence[str] | None = None,
    ) -> CuratorTask | None:
        """Pop the highest effective priority task whose lane is not currently locked."""
        data = self._load_data()
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

        active_lanes[selected_task.lane_id] = {
            "lane_id": selected_task.lane_id,
            "active_task_id": selected_task.task_id,
            "holder_agent": agent_id,
            "locked_at": now,
        }

        data["tasks"] = [t.to_dict() for t in tasks]
        data["lanes"] = active_lanes
        self._save_data(data)

        return selected_task

    def release_lane(
        self,
        lane_id: str,
        task_id: str | None = None,
        final_status: TaskStatus = "completed",
    ) -> bool:
        """Release a locked lane and mark the associated task with final_status."""
        data = self._load_data()
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
                t.status = final_status
                t.completed_at = now
                tasks[idx] = t
                found = True

        if lane_id in active_lanes:
            del active_lanes[lane_id]

        data["tasks"] = [t.to_dict() for t in tasks]
        data["lanes"] = active_lanes
        self._save_data(data)
        return found

    def list_tasks(self, status: TaskStatus | None = None) -> list[CuratorTask]:
        """Return all tasks matching status filter."""
        data = self._load_data()
        tasks = [CuratorTask.from_dict(t) for t in data.get("tasks", [])]
        if status:
            return [t for t in tasks if t.status == status]
        return tasks

    def active_lanes(self) -> dict[str, LaneState]:
        """Return all currently locked lanes."""
        data = self._load_data()
        raw_lanes = data.get("lanes", {})
        return {k: LaneState.from_dict(v) for k, v in raw_lanes.items()}

    def purge(self) -> int:
        """Purge completed, failed, or canceled tasks."""
        data = self._load_data()
        tasks = [CuratorTask.from_dict(t) for t in data.get("tasks", [])]
        initial_len = len(tasks)
        retained = [t for t in tasks if t.status in ["pending", "leased"]]
        data["tasks"] = [t.to_dict() for t in retained]
        self._save_data(data)
        return initial_len - len(retained)
