"""examples/01_multi_provider_ingestion.py

Demonstrates how SwarmCurator normalizes tasks across Linear, GitHub, and Kanban into a unified queue with deduplication and priority aging.
"""

import tempfile
from pathlib import Path
from swarmcurator import (
    SwarmCuratorQueue,
    LinearAdapter,
    GitHubAdapter,
    KanbanAdapter,
    GenericAdapter,
)


def main() -> None:
    print("=" * 70)
    print("📥 SwarmCurator Example: Multi-Provider Ingestion & Normalization")
    print("=" * 70)

    with tempfile.TemporaryDirectory() as tmpdir:
        queue_path = Path(tmpdir) / "curator_queue.json"
        queue = SwarmCuratorQueue(path=queue_path)

        # 1. Ingest Linear Issue
        linear_issue = {
            "identifier": "GRO-3320",
            "title": "Prismatic Hub Phase 5 Control Plane",
            "description": "Implement mobile approval portal and curator lane",
            "priority": 1,  # Urgent
            "project": {"name": "Prismatic-Hub"},
            "labels": [{"name": "lane:hub-core"}, {"name": "agent:agy"}],
        }
        task_linear = LinearAdapter.from_dict(linear_issue)
        queue.admit(task_linear)
        print(f"✅ Ingested Linear: [{task_linear.external_id}] '{task_linear.title}' (Priority P{task_linear.base_priority}, Lane '{task_linear.lane_id}')")

        # 2. Ingest GitHub Issue
        github_issue = {
            "number": 104,
            "title": "Fix memory leak in WebSocket connection pool",
            "body": "Profile memory growth during reconnect loops",
            "labels": ["bug", "priority:critical", "lane:gateway"],
        }
        task_github = GitHubAdapter.from_dict(github_issue, repo_name="gateway-service")
        queue.admit(task_github)
        print(f"✅ Ingested GitHub: [{task_github.external_id}] '{task_github.title}' (Priority P{task_github.base_priority}, Lane '{task_github.lane_id}')")

        # 3. Ingest Kanban Card
        kanban_card = {
            "id": "KB-202",
            "title": "Update SSL Certificate and Cloudflare DNS",
            "priority": 2,
            "lane_id": "infra-ops",
        }
        task_kanban = KanbanAdapter.from_dict(kanban_card)
        queue.admit(task_kanban)
        print(f"✅ Ingested Kanban: [{task_kanban.external_id}] '{task_kanban.title}' (Priority P{task_kanban.base_priority}, Lane '{task_kanban.lane_id}')")

        # 4. Demonstrate Deduplication
        duplicate_ok = queue.admit(task_linear)
        print(f"🔒 Deduplication Check: Re-admitting same Linear task -> Admitted: {duplicate_ok} (Expected False)")

        # 5. List Queue Tasks
        print(f"\n📋 Unified Queue Contains {len(queue.list_tasks())} Normalized Tasks:")
        for t in queue.list_tasks():
            print(f"   • [{t.provider.upper()}] {t.external_id}: {t.title} (Status: {t.status})")

    print("\n" + "=" * 70)
    print("🎉 All heterogeneous issue sources normalized and deduplicated!")
    print("=" * 70)


if __name__ == "__main__":
    main()
