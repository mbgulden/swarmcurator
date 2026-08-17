"""tests/test_security_sanitization.py — Unit tests for token sanitization and injection guard."""

from swarmcurator.models import sanitize_token, CuratorTask
from swarmcurator.adapters import AutoAdapter


def test_sanitize_token_edge_cases() -> None:
    # Path traversal attack
    assert sanitize_token("../../../etc/passwd") == "etc_passwd"
    # Null byte & control characters
    assert sanitize_token("my_lane\x00\r\n\t") == "my_lane"
    # Shell injection characters
    assert sanitize_token("lane; rm -rf /; echo") == "lane__rm_-rf____echo"
    # Empty / whitespace
    assert sanitize_token("   ", fallback="safe_lane") == "safe_lane"
    # Length truncate
    assert len(sanitize_token("a" * 300, max_len=64)) == 64


def test_curator_task_auto_sanitization() -> None:
    task = AutoAdapter.from_any({
        "identifier": "GRO/../3300",
        "title": "Path Traversal Test",
        "lane": "../secret-lane/",
        "labels": ["lane:../../core", "dangerous\nlabel"],
    })

    assert "/" not in task.lane_id
    assert ".." not in task.lane_id
    assert "/" not in task.external_id
    assert "\n" not in task.labels[0]
