"""examples/04_crash_recovery_demo.py

The #1 differentiating feature of SwarmCurator vs. any other task queue:
SELF-HEALING CRASH RECOVERY via configurable lease TTL expiry.

Every other task queue (Redis, Celery, RQ, SQLite-backed) requires human
intervention or a supervisor process to unstick a crashed worker's task.
SwarmCurator does it automatically, at the next poll, by any surviving agent.

This demo simulates:
    1. Agent "agent-ned" pops a task and begins work
    2. agent-ned CRASHES (process death simulation)
    3. The task's lane remains locked — all other agents are blocked from that workspace
    4. The lease TTL expires (we simulate time advancing)
    5. agent-agy polls for work → SwarmCurator AUTOMATICALLY reclaims the abandoned task
    6. agent-agy picks up seamlessly from where agent-ned left off
    7. The lane is eventually released cleanly

No human intervention. No supervisor daemon. No Redis BLPOP workaround.
Just the queue healing itself.
"""

import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from swarmcurator import SwarmCuratorQueue, CuratorTask
from swarmcurator.queue import _file_lock
from swarmcurator.models import _parse_iso, LaneState


def _simulate_ttl_expiry(queue: SwarmCuratorQueue, lane_id: str) -> None:
    """Reach into the queue file and backdate the lease expires_at to simulate TTL expiry.

    In production you'd simply wait for the real TTL to elapse. This helper
    lets us demonstrate the behavior without sleeping for 10 minutes.
    """
    with _file_lock(queue.path):
        data, _migrated = queue._load_data_unlocked()
        lanes = data.get("lanes", {})
        if lane_id in lanes:
            # Backdate expiry to 5 seconds ago
            expired_time = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
            lanes[lane_id]["expires_at"] = expired_time
            data["lanes"] = lanes
            queue._save_data_unlocked(data)


def main() -> None:
    print("=" * 72)
    print("💥 SwarmCurator Example: Self-Healing Crash Recovery")
    print("=" * 72)
    print()
    print("  THE PROBLEM: In naive agent swarms, if an agent process dies while")
    print("  holding a task, that repository/workspace is PERMANENTLY LOCKED")
    print("  until a human manually intervenes.")
    print()
    print("  THE SOLUTION: SwarmCurator lease TTLs. Every lane lock has a")
    print("  configurable expiry. When an agent crashes, the next poll from")
    print("  ANY surviving agent automatically reclaims the abandoned task.")
    print()

    with tempfile.TemporaryDirectory() as tmpdir:
        queue_path = Path(tmpdir) / "crash_recovery_queue.json"

        # Short 30-second TTL for demonstration (production default is 600s)
        queue = SwarmCuratorQueue(path=queue_path)

        # ----------------------------------------------------------------
        # 1. Enqueue two tasks in the same 'prismatic-core' lane
        # ----------------------------------------------------------------
        print("📝 Step 1: Enqueue 2 tasks in 'prismatic-core' lane")
        t1 = CuratorTask(
            task_id="task-urgent-migration",
            provider="linear",
            external_id="GRO-5001",
            title="Apply database migration for auth schema v3",
            base_priority=0,   # Urgent
            lane_id="prismatic-core",
            lease_ttl_seconds=30,  # 30s TTL for demo
            max_retries=2,
        )
        t2 = CuratorTask(
            task_id="task-api-refactor",
            provider="linear",
            external_id="GRO-5002",
            title="Refactor gateway authentication middleware",
            base_priority=1,   # High
            lane_id="prismatic-core",  # Same lane — will be blocked by t1
            lease_ttl_seconds=30,
            max_retries=2,
        )
        queue.admit(t1)
        queue.admit(t2)
        print(f"   ✅ Admitted: [{t1.external_id}] P0 Urgent — '{t1.title}'")
        print(f"   ✅ Admitted: [{t2.external_id}] P1 High   — '{t2.title}'")

        # ----------------------------------------------------------------
        # 2. agent-ned pops GRO-5001 (highest priority)
        # ----------------------------------------------------------------
        print()
        print("🚀 Step 2: agent-ned pops next available task...")
        ned_task = queue.pop_next(agent_id="agent-ned")
        assert ned_task is not None
        print(f"   ✅ agent-ned leased: [{ned_task.external_id}] '{ned_task.title}'")
        print(f"   🔒 Lane 'prismatic-core' is now LOCKED by agent-ned")
        print(f"   ⏱  Lease expires in: {ned_task.lease_ttl_seconds}s")

        # Verify no other agent can enter the same lane
        agy_task = queue.pop_next(agent_id="agent-agy")
        print()
        print(f"⏸  Step 3: agent-agy tries to pop...")
        print(f"   ❌ agent-agy received: {agy_task}  (lane blocked — collision prevented!)")
        assert agy_task is None, "Expected None — lane should be locked!"

        # ----------------------------------------------------------------
        # 4. agent-ned CRASHES (simulate by not releasing the lane)
        # ----------------------------------------------------------------
        print()
        print("💀 Step 4: agent-ned CRASHES — process dies without releasing lane")
        print("   🚨 In a naive system: 'prismatic-core' is now PERMANENTLY LOCKED")
        print("   🚨 GRO-5002 would be stuck indefinitely until human intervention")
        print()

        # ----------------------------------------------------------------
        # 5. Simulate TTL expiry (instead of waiting 30 real seconds)
        # ----------------------------------------------------------------
        print("⏩ Step 5: Simulating lease TTL expiry (30s → elapsed)...")
        _simulate_ttl_expiry(queue, "prismatic-core")
        print("   ⏰ Lease for 'prismatic-core' has now expired")

        # ----------------------------------------------------------------
        # 6. agent-agy polls again — queue auto-reclaims the abandoned task!
        # ----------------------------------------------------------------
        print()
        print("🔄 Step 6: agent-agy polls for work again...")
        recovered_task = queue.pop_next(agent_id="agent-agy")
        assert recovered_task is not None, "Expected task recovery!"
        print(f"   🎉 AUTO-RECOVERY: agent-agy received: [{recovered_task.external_id}] '{recovered_task.title}'")
        print(f"   ✅ Retry count on recovered task: {recovered_task.retry_count}/2")
        print(f"   ✅ Now assigned to: {recovered_task.assigned_agent}")
        print(f"   ✅ Lane 'prismatic-core' re-locked under agent-agy — no data lost!")

        # ----------------------------------------------------------------
        # 7. agent-agy completes successfully
        # ----------------------------------------------------------------
        print()
        print("🏁 Step 7: agent-agy completes work and releases the lane...")
        queue.release_lane(
            lane_id="prismatic-core",
            task_id=recovered_task.task_id,
            final_status="completed",
        )
        print(f"   ✅ Lane 'prismatic-core' released")

        # Now GRO-5002 becomes available
        print()
        print("🚀 Step 8: agent-jules polls and picks up GRO-5002 (previously blocked)...")
        jules_task = queue.pop_next(agent_id="agent-jules")
        assert jules_task is not None
        print(f"   ✅ agent-jules leased: [{jules_task.external_id}] '{jules_task.title}'")

        stats = queue.get_stats()
        print()
        print("📊 Final Queue Stats:")
        print(f"   • Total Tasks:  {stats.total_tasks}")
        print(f"   • Pending:      {stats.pending_count}")
        print(f"   • Leased:       {stats.leased_count}  (GRO-5002 held by jules)")
        print(f"   • Completed:    {stats.completed_count}  (GRO-5001 recovered + finished)")
        print(f"   • Active Lanes: {stats.active_lanes_count}")

    print()
    print("=" * 72)
    print("✅ Crash recovery complete — zero human intervention required!")
    print()
    print("   SwarmCurator handled the entire recovery cycle:")
    print("   • Detected the expired lease on the next poll")
    print("   • Freed the blocked lane automatically")
    print("   • Re-queued the task for retry (retry 1 of 2)")
    print("   • Dispatched it to the next available agent seamlessly")
    print()
    print("   No Redis. No Celery. No supervisor daemon. No human.")
    print("=" * 72)


if __name__ == "__main__":
    main()
