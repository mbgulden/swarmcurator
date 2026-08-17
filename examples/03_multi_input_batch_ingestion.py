"""examples/03_multi_input_batch_ingestion.py

Demonstrates:
1. Multi-input simultaneous batch admission into SwarmCurator.
2. Composite multi-stream task construction (Linear + PR + CI Logs + Design Specs).
"""

import tempfile
from pathlib import Path
from swarmcurator import (
    SwarmCuratorQueue,
    CompositeTaskBuilder,
    AutoAdapter,
)


def main() -> None:
    print("=" * 75)
    print("🌊 SwarmCurator Example: Simultaneous Multi-Input Ingestion & Composition")
    print("=" * 75)

    with tempfile.TemporaryDirectory() as tmpdir:
        queue_path = Path(tmpdir) / "multi_input_queue.json"
        queue = SwarmCuratorQueue(path=queue_path)

        # -------------------------------------------------------------
        # Part 1: Simultaneous Batch Admission of Mixed Issue Sources
        # -------------------------------------------------------------
        print("\n📦 1. Admitting a batch of heterogeneous items simultaneously...")

        incoming_batch = [
            # Linear Issue
            {
                "identifier": "GRO-4770",
                "title": "Build SwarmProof CLI Tooling",
                "priority": 1,
                "project": {"name": "SwarmProof"},
                "labels": [{"name": "lane:swarmproof-core"}],
            },
            # GitHub Issue
            {
                "number": 512,
                "title": "Fix memory leak in websocket reconnection loop",
                "body": "Profile memory growth during rapid reconnect cycles",
                "repo": "gateway-service",
                "labels": ["priority:critical", "lane:gateway-service"],
            },
            # Kanban Card
            {
                "id": "CARD-77",
                "title": "Update Proxmox VM template images",
                "priority": 2,
                "lane_id": "infra-ops",
                "column": "Backlog",
            },
            # Generic Task
            {
                "task_id": "cron-heal-1",
                "title": "Re-run silent failed journal snapshot cron",
                "priority": 0,
                "lane_id": "cron-jobs",
            },
            # Duplicate item in same batch
            {
                "identifier": "GRO-4770",
                "title": "Build SwarmProof CLI Tooling",
                "priority": 1,
            },
        ]

        batch_result = queue.admit_batch(incoming_batch)
        print(f"   • Total Processed: {len(incoming_batch)}")
        print(f"   • Total Admitted:  {batch_result.total_admitted}")
        print(f"   • Duplicates:      {batch_result.total_duplicates}")
        for t in batch_result.admitted:
            print(f"     ✅ [{t.provider.upper()}] {t.external_id}: '{t.title}' (Lane: {t.lane_id}, Base P{t.base_priority})")

        # -------------------------------------------------------------
        # Part 2: Composing a Rich Multi-Stream Composite Task
        # -------------------------------------------------------------
        print("\n🧩 2. Composing a multi-stream task (Linear + PR + CI Logs + Specs)...")

        builder = CompositeTaskBuilder(
            task_id="composite-gro-4767",
            title="Investigate & Repair Flaky Gateway Telemetry Sync",
            lane_id="gateway-service",
            base_priority=0,  # Urgent
        )

        # Stream 1: Linear Issue
        builder.add_linear_issue({
            "identifier": "GRO-4767",
            "description": "Telemetry packets dropped during agent handoff under high load.",
            "labels": [{"name": "agent:agy"}, {"name": "type:bug"}],
        })

        # Stream 2: GitHub PR
        builder.add_github_pr_or_issue({
            "number": 314,
            "body": "PR attempting non-blocking buffer flush (failing CI).",
            "html_url": "https://github.com/org/gateway/pull/314",
        }, repo="gateway-service")

        # Stream 3: CI Failure Log
        builder.add_context(
            source_type="ci_log",
            reference="github-actions://run/987654321",
            content="AssertionError: Expected 100 packets delivered, received 94.\nTest timeout after 30s.",
        )

        # Stream 4: Architectural Spec Document
        builder.add_context(
            source_type="spec_file",
            reference="specs/gateway-telemetry-protocol.md",
            content="Section 4.2: Buffer flush must be atomic and acknowledge backpressure.",
        )

        composite_task = builder.build()
        queue.admit(composite_task)

        print(f"   ✅ Created Composite Task: [{composite_task.task_id}] '{composite_task.title}'")
        print(f"   • Attached Input Streams: {len(composite_task.inputs)}")
        for inp in composite_task.inputs:
            print(f"     - Source: {inp['source_type'].upper():<10} Reference: {inp['reference']}")

        # -------------------------------------------------------------
        # Part 3: Dispatching from Unified Multi-Input Queue
        # -------------------------------------------------------------
        print("\n🚀 3. Popping dispatchable task for Agent AGY...")
        dispatched = queue.pop_next(agent_id="agent-agy")
        print(f"   • Dispatched Task: [{dispatched.task_id}] '{dispatched.title}' (Lane: '{dispatched.lane_id}')")
        print(f"   • Full Consolidated Context Length: {len(dispatched.description)} characters")

    print("\n" + "=" * 75)
    print("🎉 Multi-input batching and composite context assembly complete!")
    print("=" * 75)


if __name__ == "__main__":
    main()
