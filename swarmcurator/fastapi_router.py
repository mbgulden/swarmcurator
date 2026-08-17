"""swarmcurator.fastapi_router — Hardened drop-in FastAPI router for SwarmCurator with webhooks and telemetry stats."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from .models import CuratorTask, TaskStatus, QueueFullError
from .queue import SwarmCuratorQueue
from .adapters import (
    GitHubAdapter,
    LinearAdapter,
    verify_github_signature,
    verify_linear_signature,
)

try:
    from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request
except ImportError:
    raise ImportError(
        "FastAPI is required for swarmcurator.fastapi_router. "
        "Install it with: pip install swarmcurator[fastapi]"
    )


def create_router(
    queue_instance: SwarmCuratorQueue | None = None,
    auth_dependency: Any = None,
    github_webhook_secret: str | None = None,
    linear_webhook_secret: str | None = None,
) -> APIRouter:
    """Create a FastAPI APIRouter exposing SwarmCurator queue, webhook, and telemetry endpoints."""
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

    @router.get("/stats")
    def get_stats() -> Dict[str, Any]:
        """Get live queue health and telemetry statistics."""
        stats = q.get_stats()
        return {"ok": True, "stats": stats.to_dict()}

    @router.post("/admit")
    def admit_task(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        """Admit a single task into the admission queue."""
        try:
            task = CuratorTask.from_dict(payload) if "task_id" in payload else payload
            admitted = q.admit(task)
            if not admitted:
                return {"ok": False, "detail": "Duplicate active task or queue full", "admitted": False}
            return {"ok": True, "admitted": True}
        except QueueFullError as exc:
            raise HTTPException(status_code=507, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @router.post("/admit/batch")
    def admit_batch_tasks(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        """Admit multiple heterogeneous tasks/inputs simultaneously."""
        items = payload.get("items") or payload.get("tasks") or []
        if not isinstance(items, list):
            raise HTTPException(status_code=400, detail="Expected 'items' or 'tasks' list")
        res = q.admit_batch(items)
        return res.to_dict()

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
        """Release a lane lock upon task completion or failure with retry support."""
        lane_id = payload.get("lane_id") or payload.get("lane")
        if not lane_id:
            raise HTTPException(status_code=400, detail="lane_id is required")
        task_id = payload.get("task_id") or payload.get("task")
        final_status: TaskStatus = payload.get("status", "completed")
        error_msg = payload.get("error_message") or payload.get("error")
        released = q.release_lane(
            lane_id=lane_id,
            task_id=task_id,
            final_status=final_status,
            error_message=error_msg,
        )
        return {"ok": released, "lane_id": lane_id, "released": released}

    @router.post("/cancel")
    def cancel_task(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        """Cancel a pending or leased task by ID, releasing any associated lane lock."""
        task_id = payload.get("task_id") or payload.get("id")
        if not task_id:
            raise HTTPException(status_code=400, detail="task_id is required")
        canceled = q.cancel_task(task_id=task_id)
        if not canceled:
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found or already terminal")
        return {"ok": True, "task_id": task_id, "canceled": True}

    @router.post("/set-priority")
    def set_task_priority(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        """Override the base priority of a pending task (operator escalation endpoint).

        Use this to promote a low-priority bug to urgent (P0) after discovering
        it is impacting production. Has no effect on already-dispatched tasks.
        """
        task_id = payload.get("task_id") or payload.get("id")
        if not task_id:
            raise HTTPException(status_code=400, detail="task_id is required")
        new_priority = payload.get("priority")
        if new_priority is None:
            raise HTTPException(status_code=400, detail="priority (0-4) is required")
        updated = q.set_priority(task_id=task_id, new_priority=int(new_priority))
        if not updated:
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found or not in pending state")
        return {"ok": True, "task_id": task_id, "new_priority": int(new_priority)}

    @router.get("/lanes")
    def get_lanes() -> Dict[str, Any]:
        """List all currently active lane locks."""
        lanes = {k: v.to_dict() for k, v in q.active_lanes().items()}
        return {"ok": True, "lanes": lanes}

    @router.post("/webhook/github")
    async def github_webhook(
        request: Request,
        x_hub_signature_256: str | None = Header(None),
    ) -> Dict[str, Any]:
        """Secure webhook endpoint ingesting GitHub Issues with HMAC validation."""
        body = await request.body()
        if github_webhook_secret:
            if not x_hub_signature_256 or not verify_github_signature(body, x_hub_signature_256, github_webhook_secret):
                raise HTTPException(status_code=401, detail="Invalid GitHub webhook signature")

        try:
            payload = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {exc}")

        issue_data = payload.get("issue")
        if not issue_data or payload.get("action") not in ["opened", "reopened", "labeled", None]:
            return {"ok": True, "detail": "Ignored action or non-issue event"}

        repo_name = payload.get("repository", {}).get("name", "github")
        task = GitHubAdapter.from_dict(issue_data, repo_name=repo_name)
        try:
            admitted = q.admit(task)
        except QueueFullError:
            raise HTTPException(status_code=507, detail="Queue is at capacity")
        return {"ok": admitted, "task_id": task.task_id, "admitted": admitted}

    @router.post("/webhook/linear")
    async def linear_webhook(
        request: Request,
        linear_signature: str | None = Header(None, alias="Linear-Signature"),
    ) -> Dict[str, Any]:
        """Secure webhook endpoint ingesting Linear Issues with HMAC validation."""
        body = await request.body()
        if linear_webhook_secret:
            if not linear_signature or not verify_linear_signature(body, linear_signature, linear_webhook_secret):
                raise HTTPException(status_code=401, detail="Invalid Linear webhook signature")

        try:
            payload = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {exc}")

        data = payload.get("data")
        if not data or payload.get("type") != "Issue":
            return {"ok": True, "detail": "Ignored event"}

        task = LinearAdapter.from_dict(data)
        try:
            admitted = q.admit(task)
        except QueueFullError:
            raise HTTPException(status_code=507, detail="Queue is at capacity")
        return {"ok": admitted, "task_id": task.task_id, "admitted": admitted}

    return router


# Default router instance
router = create_router()
