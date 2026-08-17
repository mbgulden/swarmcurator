"""examples/05_priority_override_demo.py

Demonstrates SwarmCurator's operator priority escalation via set_priority().

Real scenario: A low-priority task ("Investigate occasional 500s") was filed
at P3 (Low). Later, the ops team discovers this is causing a production outage.
They need to immediately promote it above all current work — without canceling
and re-filing, and without restarting the queue.

set_priority() lets any operator (human or agent) dynamically escalate or
de-escalate any pending task, and the next pop_next() call will respect the
updated priority ordering without any restart or rebuild.
"""

import tempfile
from pathlib import Path
from swarmcurator import SwarmCuratorQueue, CuratorTask
from swarmcurator.aging import compute_effective_priority


def main() -> None:
    print("=" * 72)
    print("🎯 SwarmCurator Example: Operator Priority Override & Escalation")
    print("=" * 72)

    with tempfile.TemporaryDirectory() as tmpdir:
        queue_path = Path(tmpdir) / "priority_queue.json"
        queue = SwarmCuratorQueue(path=queue_path)

        # Enqueue a backlog of tasks at different priorities
        tasks = [
            CuratorTask(
                task_id="task-a",
                provider="linear",
                external_id="GRO-200",
                title="Implement new dashboard export feature",
                base_priority=1,   # High
                lane_id="prismatic-hub",
            ),
            CuratorTask(
                task_id="task-b",
                provider="linear",
                external_id="GRO-201",
                title="Investigate occasional 500s on /api/auth/refresh",
                base_priority=3,   # Low — originally filed as non-urgent
                lane_id="gateway-service",
            ),
            CuratorTask(
                task_id="task-c",
                provider="linear",
                external_id="GRO-202",
                title="Update Node.js dependencies to patch CVE",
                base_priority=2,   # Medium
                lane_id="infra-ops",
            ),
            CuratorTask(
                task_id="task-d",
                provider="github",
                external_id="GH-88",
                title="Refactor legacy session cookie handling",
                base_priority=4,   # Backlog
                lane_id="auth-service",
            ),
        ]

        for t in tasks:
            queue.admit(t)

        print("\n📋 Initial Queue Order (by effective priority):")
        pending = queue.list_tasks(status="pending")
        from swarmcurator.aging import sort_tasks_by_effective_priority
        ordered = sort_tasks_by_effective_priority(pending)
        for i, t in enumerate(ordered, 1):
            score = compute_effective_priority(t)
            print(f"   {i}. [{t.external_id}] P{t.base_priority} — '{t.title}' (score: {score:.1f})")

        # ----------------------------------------------------------------
        # Incident detected: GRO-201 is causing 30% auth failure rate!
        # ----------------------------------------------------------------
        print()
        print("🚨 PRODUCTION INCIDENT: /api/auth/refresh returning 500 for 30% of users!")
        print("   GRO-201 ('Investigate occasional 500s') must be escalated to P0 immediately.")
        print()

        escalated = queue.set_priority(task_id="task-b", new_priority=0)
        print(f"   ⬆️  queue.set_priority('task-b', new_priority=0) → Updated: {escalated}")

        print()
        print("📋 Updated Queue Order (GRO-201 now leads):")
        pending = queue.list_tasks(status="pending")
        ordered = sort_tasks_by_effective_priority(pending)
        for i, t in enumerate(ordered, 1):
            score = compute_effective_priority(t)
            marker = " ← 🔥 ESCALATED" if t.task_id == "task-b" else ""
            print(f"   {i}. [{t.external_id}] P{t.base_priority} — '{t.title}' (score: {score:.1f}){marker}")

        # ----------------------------------------------------------------
        # Now dispatch — GRO-201 must be first out of the queue
        # ----------------------------------------------------------------
        print()
        print("🚀 Dispatching first available task for agent-agy (on-call responder)...")
        dispatched = queue.pop_next(agent_id="agent-agy-oncall")
        assert dispatched is not None
        assert dispatched.task_id == "task-b", f"Expected task-b (escalated), got {dispatched.task_id}"

        print(f"   ✅ agent-agy-oncall received: [{dispatched.external_id}] '{dispatched.title}'")
        print(f"   ✅ Priority: P{dispatched.base_priority} (was P3, now P0 — Urgent)")
        print(f"   ✅ Incident response started. Zero re-queue needed.")

        # ----------------------------------------------------------------
        # De-escalation after incident resolved
        # ----------------------------------------------------------------
        print()
        print("✅ Incident resolved — releasing lane and marking complete...")
        queue.release_lane(
            lane_id="gateway-service",
            task_id="task-b",
            final_status="completed",
        )
        print("   ✅ GRO-201 completed. Queue continues normal priority ordering.")

        print()
        print("📋 Remaining Queue:")
        pending = queue.list_tasks(status="pending")
        ordered = sort_tasks_by_effective_priority(pending)
        for i, t in enumerate(ordered, 1):
            print(f"   {i}. [{t.external_id}] P{t.base_priority} — '{t.title}'")

    print()
    print("=" * 72)
    print("🎉 Priority override complete — incident response in 1 API call!")
    print()
    print("   set_priority() enables operators to respond dynamically to:")
    print("   • Production incidents requiring immediate escalation")
    print("   • Business-critical deadline changes")
    print("   • Backlog grooming without queue rebuild")
    print("=" * 72)


if __name__ == "__main__":
    main()
