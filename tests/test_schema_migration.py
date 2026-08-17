"""tests/test_schema_migration.py — Tests for queue JSON schema versioning and migration."""

import json
from pathlib import Path
from swarmcurator.models import CURRENT_SCHEMA_VERSION, CuratorTask
from swarmcurator.queue import SwarmCuratorQueue, _migrate_data


def test_migrate_version_0_to_1_adds_missing_fields() -> None:
    """Version 0 queue JSON (pre-v0.3.0) missing retry/lease fields should be migrated cleanly."""
    old_v0_data = {
        # No schema_version key at all
        "tasks": [
            {
                "task_id": "t-old-1",
                "provider": "linear",
                "external_id": "GRO-100",
                "title": "Old task from v0.2.0",
                "base_priority": 1,
                "lane_id": "legacy-lane",
                "status": "pending",
                "labels": [],
                "fingerprint": "abc123",
                "enqueued_at": "2026-08-01T00:00:00+00:00",
                # Missing: retry_count, max_retries, lease_ttl_seconds, error_message, inputs, metadata
            }
        ],
        "lanes": {},
        "updated_at": "2026-08-01T00:00:00+00:00",
    }

    migrated = _migrate_data(old_v0_data)

    assert migrated["schema_version"] == CURRENT_SCHEMA_VERSION
    task_dict = migrated["tasks"][0]
    assert task_dict["retry_count"] == 0
    assert task_dict["max_retries"] == 3
    assert task_dict["lease_ttl_seconds"] == 600
    assert task_dict["error_message"] is None
    assert task_dict["inputs"] == []
    assert task_dict["metadata"] == {}


def test_load_old_queue_file_migrates_on_read(tmp_path: Path) -> None:
    """Loading an old-version queue.json from disk should transparently migrate it."""
    queue_file = tmp_path / "old_queue.json"

    # Write a v0 format queue file (no schema_version)
    old_data = {
        "tasks": [
            {
                "task_id": "t-old",
                "provider": "kanban",
                "external_id": "KB-50",
                "title": "Legacy kanban task",
                "base_priority": 2,
                "lane_id": "kanban-default",
                "status": "pending",
                "labels": [],
                "fingerprint": "xyz789",
                "enqueued_at": "2026-08-01T00:00:00+00:00",
            }
        ],
        "lanes": {},
    }
    queue_file.write_text(json.dumps(old_data), encoding="utf-8")

    # Load via SwarmCuratorQueue — should migrate transparently
    queue = SwarmCuratorQueue(path=queue_file)
    tasks = queue.list_tasks()

    assert len(tasks) == 1
    task = tasks[0]
    assert task.task_id == "t-old"
    assert task.retry_count == 0
    assert task.max_retries == 3

    # File on disk should now have schema_version = 1
    saved = json.loads(queue_file.read_text())
    assert saved["schema_version"] == CURRENT_SCHEMA_VERSION


def test_current_version_data_not_re_migrated() -> None:
    """Data already at CURRENT_SCHEMA_VERSION should pass through unchanged."""
    current_data = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "tasks": [{"task_id": "t1"}],
        "lanes": {},
    }
    migrated = _migrate_data(current_data)
    assert migrated == current_data


def test_unknown_fields_in_task_emit_warning() -> None:
    """CuratorTask.from_dict() with unknown keys should warn, not crash."""
    import warnings
    data = {
        "task_id": "t-future",
        "provider": "linear",
        "external_id": "GRO-999",
        "title": "Task from future schema",
        "unknown_future_field": "some_value",
        "another_new_field": 42,
    }
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        task = CuratorTask.from_dict(data)
        # Should have emitted a warning about unknown fields
        assert len(w) == 1
        assert "unknown fields" in str(w[0].message).lower()
        assert "unknown_future_field" in str(w[0].message)

    # Task should still be created with known fields
    assert task.task_id == "t-future"
    assert task.external_id == "GRO-999"
