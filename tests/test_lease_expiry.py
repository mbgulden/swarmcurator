"""tests/test_lease_expiry.py — Unit tests for automatic crash recovery via lease TTL expiration."""

from datetime import datetime, timezone, timedelta
from pathlib import Path
from swarmcurator.models import CuratorTask
from swarmcurator.queue import SwarmCuratorQueue


def test_lease_auto_expiry_and_reclamation(tmp_path: Path) -> None:
    queue_file = tmp_path / "queue_expiry.json"
    queue = SwarmCuratorQueue(path=queue_file)

    task = CuratorTask(
        task_id="t-crash",
        provider="linear",
        external_id="GRO-999",
        title="Worker crash test",
        base_priority=1,
        lane_id="lane-crash",
        lease_ttl_seconds=10,  # 10s TTL
        max_retries=2,
    )
    queue.admit(task)

    # 1. Agent 1 pops the task -> lane locked
    popped = queue.pop_next(agent_id="agent-crashed")
    assert popped is not None
    assert "lane-crash" in queue.active_lanes()

    # 2. Simulate time passing beyond 10s (e.g. 15s in the future)
    future_time = datetime.now(timezone.utc) + timedelta(seconds=15)

    # Agent 2 pops with future_time -> queue should sweep expired lease and auto-reclaim task!
    with queue._file_lock(queue.path) if hasattr(queue, "_file_lock") else open(queue_file):
        pass

    # When queue checks leases at future_time, lease should be expired
    lane_state = queue.active_lanes()["lane-crash"]
    assert lane_state.is_expired(future_time) is True

    # When pop_next is called after expiry, it should reclaim and lease to new agent
    # We can test _reclaim_expired_leases directly with future_time:
    data, _migrated = queue._load_data_unlocked()
    reclaimed = queue._reclaim_expired_leases(data, now=future_time)
    assert reclaimed == 1
    queue._save_data_unlocked(data)

    assert "lane-crash" not in queue.active_lanes()
    tasks = queue.list_tasks()
    assert tasks[0].status == "pending"
    assert tasks[0].retry_count == 1

    # Now agent-survivor can pop the reclaimed task!
    popped_retry = queue.pop_next(agent_id="agent-survivor")
    assert popped_retry is not None
    assert popped_retry.task_id == "t-crash"
    assert popped_retry.assigned_agent == "agent-survivor"
