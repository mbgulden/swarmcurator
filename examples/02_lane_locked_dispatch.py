"""examples/02_lane_locked_dispatch.py

Demonstrates SwarmCurator's lane locking mutual exclusion and priority aging dispatch.
"""

import tempfile
from pathlib import Path
from swarmcurator import SwarmCuratorQueue, CuratorTask


def main() -> None:
    print("=" * 70)
    print("🔒 SwarmCurator Example: Exclusive Lane Locking & Conflict-Free Dispatch")
    print("=" * 70)

    with tempfile.TemporaryDirectory() as tmpdir:
        queue_path = Path(tmpdir) / "lane_queue.json"
        queue = SwarmCuratorQueue(path=queue_path)

        # Enqueue 3 tasks: Two in 'repo-backend' lane, one in 'repo-frontend' lane
        t1 = CuratorTask(
            task_id="t1",
            provider="linear",
            external_id="GRO-101",
            title="Update User Authentication Schema",
            base_priority=0,  # Urgent
            lane_id="repo-backend",
        )
        t2 = CuratorTask(
            task_id="t2",
            provider="linear",
            external_id="GRO-102",
            title="Refactor Database Connection Pool",
            base_priority=1,  # High
            lane_id="repo-backend",  # Same collision lane!
        )
        t3 = CuratorTask(
            task_id="t3",
            provider="linear",
            external_id="GRO-103",
            title="Redesign Mobile Navigation Drawer",
            base_priority=2,  # Medium
            lane_id="repo-frontend",  # Independent lane
        )

        queue.admit(t1)
        queue.admit(t2)
        queue.admit(t3)

        print("\n📝 1. Enqueued 3 tasks (2 in 'repo-backend', 1 in 'repo-frontend')")

        # Worker 1 (Ned) requests work
        w1_task = queue.pop_next(agent_id="agent-ned")
        print(f"\n🚀 2. Agent 'Ned' popped task: [{w1_task.external_id}] '{w1_task.title}'")
        print(f"   • Locked Lane: '{w1_task.lane_id}' is now HELD by agent-ned")

        # Worker 2 (AGY) requests work
        # Even though GRO-102 (P1) has higher priority than GRO-103 (P2),
        # GRO-102 is blocked because 'repo-backend' is currently locked!
        w2_task = queue.pop_next(agent_id="agent-agy")
        print(f"\n🚀 3. Agent 'AGY' popped task: [{w2_task.external_id}] '{w2_task.title}'")
        print(f"   • Note: GRO-102 was bypassed to prevent multi-agent collision on 'repo-backend'!")
        print(f"   • Locked Lane: '{w2_task.lane_id}' is now HELD by agent-agy")

        # Worker 3 requests work while both lanes are locked
        w3_task = queue.pop_next(agent_id="agent-jules")
        print(f"\n⏸️ 4. Agent 'Jules' popped task: {w3_task} (Correctly None — all active lanes occupied)")

        # Worker 1 completes task and releases lane
        queue.release_lane(lane_id="repo-backend", task_id="t1", final_status="completed")
        print(f"\n🔓 5. Agent 'Ned' completed task and RELEASED lane 'repo-backend'")

        # Now Worker 3 can safely pop GRO-102!
        w3_task_retry = queue.pop_next(agent_id="agent-jules")
        print(f"🚀 6. Agent 'Jules' retries and pops: [{w3_task_retry.external_id}] '{w3_task_retry.title}'")

    print("\n" + "=" * 70)
    print("🎉 Zero worktree collisions and zero merge conflicts!")
    print("=" * 70)


if __name__ == "__main__":
    main()
