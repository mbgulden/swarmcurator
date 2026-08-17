"""swarmcurator.fastapi_router — Drop-in FastAPI router for SwarmCurator."""

from __future__ import annotations

from typing import Any, Dict

from .models import CuratorTask, TaskStatus
from .queue import SwarmCuratorQueue

try:
    from fastapi import APIRouter, Body, Depends, HTTPException
except ImportError:
    raise ImportError(
        "FastAPI is required for swarmcurator.fastapi_router. "
        "Install it with: pip install swarmcurator[fastapi]"
    )


def create_router(
    queue_instance: SwarmCuratorQueue | None = None,
    auth_dependency: Any = None,
) -> APIRouter:
    """Create a FastAPI APIRouter exposing SwarmCurator queue endpoints."""
    q = queue_instance or SwarmCuratorQueue()

    dependencies = []
    if auth_dependency is not None:
        dependencies.append(Depends(auth_dependency))

    router = APIRouter(prefix="/curator", tags=["SwarmCurator"], dependencies=dependencies)

    @router.get("/queue")
    def get_queue(status: str | None = None) -> Dict[str, Any]:
        """List tasks in the queue, optionally filtered by status."""
        tasks = q.list_tasks(status=status)
        return {"ok": True, "tasks": [t.to_dict() for t in tasks]}

    @router.post("/admit")
    def admit_task(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        """Admit a new task into the admission queue."""
        try:
            task = CuratorTask.from_dict(payload)
            admitted = q.admit(task)
            if not admitted:
                return {"ok": False, "detail": "Duplicate active task rejected", "admitted": False}
            return {"ok": True, "task": task.to_dict(), "admitted": True}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @router.post("/pop")
    def pop_task(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        """Pop the next highest priority available task for an agent."""
        agent_id = payload.get("agent_id") or payload.get("agent")
        if not agent_id:
            raise HTTPException(status_code=400, detail="agent_id is required")
        available_lanes = payload.get("available_lanes")
        task = q.pop_next(agent_id=agent_id, available_lanes=available_lanes)
        if not task:
            return {"ok": False, "task": None, "detail": "No dispatchable task available"}
        return {"ok": True, "task": task.to_dict()}

    @router.post("/release")
    def release_lane_lock(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        """Release a lane lock upon task completion or failure."""
        lane_id = payload.get("lane_id") or payload.get("lane")
        if not lane_id:
            raise HTTPException(status_code=400, detail="lane_id is required")
        task_id = payload.get("task_id") or payload.get("task")
        final_status: TaskStatus = payload.get("status", "completed")
        released = q.release_lane(lane_id=lane_id, task_id=task_id, final_status=final_status)
        return {"ok": released, "lane_id": lane_id, "released": released}

    @router.get("/lanes")
    def get_lanes() -> Dict[str, Any]:
        """List all currently active lane locks."""
        lanes = {k: v.to_dict() for k, v in q.active_lanes().items()}
        return {"ok": True, "lanes": lanes}

    return router


# Default router instance
router = create_router()
