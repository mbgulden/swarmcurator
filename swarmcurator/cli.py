"""swarmcurator.cli — Command-line interface for SwarmCurator with stats & telemetry."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .models import CuratorTask
from .queue import SwarmCuratorQueue


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="swarmcurator",
        description="SwarmCurator — Hardened Task Admission, Priority Aging & Lane-Locking Queue",
    )
    parser.add_argument(
        "--store",
        type=str,
        default=None,
        help="Path to queue.json file (default: ~/.swarmcurator/queue.json)",
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    # admit
    admit_cmd = sub.add_parser("admit", help="Admit a single task into the queue")
    admit_cmd.add_argument("--id", required=True, dest="external_id", help="External issue ID (e.g. GRO-123, GH-45)")
    admit_cmd.add_argument("--title", required=True, help="Task title")
    admit_cmd.add_argument("--provider", default="generic", choices=["linear", "github", "kanban", "generic"], help="Source issue provider")
    admit_cmd.add_argument("--desc", default="", help="Task description")
    admit_cmd.add_argument("--priority", type=int, default=2, choices=[0, 1, 2, 3, 4], help="Priority (0=Urgent to 4=Backlog)")
    admit_cmd.add_argument("--lane", default="default", help="Lane / workspace collision domain ID")
    admit_cmd.add_argument("--labels", default="", help="Comma-separated labels")
    admit_cmd.add_argument("--ttl", type=int, default=600, help="Lease TTL seconds (default: 600s)")
    admit_cmd.add_argument("--max-retries", type=int, default=3, help="Max failure retries before DLQ (default: 3)")

    # admit-batch
    batch_cmd = sub.add_parser("admit-batch", help="Admit multiple tasks from a JSON file or stdin")
    batch_cmd.add_argument("--file", default=None, help="Path to JSON file containing array of tasks (reads stdin if omitted)")

    # pop
    pop_cmd = sub.add_parser("pop", help="Pop the next available task for an agent")
    pop_cmd.add_argument("--agent", required=True, help="Agent identifier popping the task (e.g. agy, ned-code)")
    pop_cmd.add_argument("--lanes", default="", help="Comma-separated available lane IDs")

    # release
    rel_cmd = sub.add_parser("release", help="Release a lane lock and complete/fail task")
    rel_cmd.add_argument("--lane", required=True, help="Lane ID to release")
    rel_cmd.add_argument("--task", default=None, help="Optional task ID")
    rel_cmd.add_argument("--status", default="completed", choices=["completed", "failed", "canceled"], help="Final task status")
    rel_cmd.add_argument("--error", default=None, help="Optional failure error message")

    # list
    list_cmd = sub.add_parser("list", help="List tasks in the queue")
    list_cmd.add_argument("--status", default=None, choices=["pending", "leased", "completed", "failed", "dead_letter", "canceled"])

    # lanes
    sub.add_parser("lanes", help="List all currently locked lanes")

    # stats
    sub.add_parser("stats", help="Show live queue health, priority distribution, and telemetry stats")

    # purge
    sub.add_parser("purge", help="Purge completed/failed tasks from queue")

    args = parser.parse_args(argv)
    queue_path = Path(args.store) if args.store else None
    queue = SwarmCuratorQueue(path=queue_path)

    if args.cmd == "admit":
        labels = [l.strip() for l in args.labels.split(",") if l.strip()]
        task = CuratorTask(
            task_id=f"{args.provider}-{args.external_id.lower()}",
            provider=args.provider,
            external_id=args.external_id,
            title=args.title,
            description=args.desc,
            base_priority=args.priority,
            lane_id=args.lane,
            labels=labels,
            lease_ttl_seconds=args.ttl,
            max_retries=args.max_retries,
        )
        ok = queue.admit(task)
        res = {"ok": ok, "task": task.to_dict(), "admitted": ok}
        print(json.dumps(res, indent=2, sort_keys=True))
        return 0 if ok else 1

    if args.cmd == "admit-batch":
        if args.file:
            raw_content = Path(args.file).read_text(encoding="utf-8")
        else:
            raw_content = sys.stdin.read()
        items = json.loads(raw_content)
        if isinstance(items, dict) and ("items" in items or "tasks" in items):
            items = items.get("items") or items.get("tasks")
        if not isinstance(items, list):
            print(json.dumps({"ok": False, "detail": "Input JSON must be an array of tasks"}, indent=2))
            return 1
        res = queue.admit_batch(items)
        print(json.dumps(res.to_dict(), indent=2, sort_keys=True))
        return 0

    if args.cmd == "pop":
        available_lanes = [l.strip() for l in args.lanes.split(",") if l.strip()] or None
        task = queue.pop_next(agent_id=args.agent, available_lanes=available_lanes)
        if task:
            print(json.dumps({"ok": True, "task": task.to_dict()}, indent=2, sort_keys=True))
            return 0
        else:
            print(json.dumps({"ok": False, "task": None, "detail": "No dispatchable task available"}, indent=2, sort_keys=True))
            return 1

    if args.cmd == "release":
        ok = queue.release_lane(
            lane_id=args.lane,
            task_id=args.task,
            final_status=args.status,
            error_message=args.error,
        )
        print(json.dumps({"ok": ok, "lane_id": args.lane, "released": ok}, indent=2, sort_keys=True))
        return 0 if ok else 1

    if args.cmd == "list":
        tasks = [t.to_dict() for t in queue.list_tasks(status=args.status)]
        print(json.dumps(tasks, indent=2, sort_keys=True))
        return 0

    if args.cmd == "lanes":
        lanes = {k: v.to_dict() for k, v in queue.active_lanes().items()}
        print(json.dumps(lanes, indent=2, sort_keys=True))
        return 0

    if args.cmd == "stats":
        stats = queue.get_stats()
        print(json.dumps(stats.to_dict(), indent=2, sort_keys=True))
        return 0

    if args.cmd == "purge":
        purged = queue.purge()
        print(json.dumps({"ok": True, "purged_count": purged}, indent=2, sort_keys=True))
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
