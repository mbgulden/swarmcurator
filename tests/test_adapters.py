"""tests/test_adapters.py — Unit tests for multi-provider issue adapters."""

from swarmcurator.adapters import (
    LinearAdapter,
    GitHubAdapter,
    KanbanAdapter,
    GenericAdapter,
)


def test_linear_adapter_parsing() -> None:
    raw_linear = {
        "id": "lin-issue-123",
        "identifier": "GRO-4778",
        "title": "Standardize Task Ingestion Schema",
        "description": "Create universal task descriptor",
        "priority": 1,  # Urgent
        "project": {"name": "SwarmCurator"},
        "team": {"key": "GRO"},
        "labels": [{"name": "agent:agy"}, {"name": "lane:prismatic-core"}],
    }

    task = LinearAdapter.from_dict(raw_linear)
    assert task.provider == "linear"
    assert task.external_id == "GRO-4778"
    assert task.title == "Standardize Task Ingestion Schema"
    assert task.base_priority == 0  # Urgent mapped to 0
    assert task.lane_id == "prismatic-core"
    assert "agent:agy" in task.labels
    assert task.metadata["project"] == "SwarmCurator"


def test_github_adapter_parsing() -> None:
    raw_github = {
        "id": 98765,
        "number": 42,
        "title": "Fix memory leak in websocket stream",
        "body": "Detailed reproduction steps...",
        "html_url": "https://github.com/org/repo/issues/42",
        "labels": ["bug", "priority:critical"],
    }

    task = GitHubAdapter.from_dict(raw_github, repo_name="my-repo")
    assert task.provider == "github"
    assert task.external_id == "GH-42"
    assert task.base_priority == 0  # Critical
    assert task.lane_id == "my-repo"


def test_kanban_adapter_parsing() -> None:
    raw_kanban = {
        "id": "CARD-99",
        "title": "Deploy staging cluster update",
        "description": "Apply terraform changes",
        "priority": 1,
        "column": "In Progress",
        "lane_id": "infra-staging",
        "labels": ["infra"],
    }

    task = KanbanAdapter.from_dict(raw_kanban)
    assert task.provider == "kanban"
    assert task.external_id == "CARD-99"
    assert task.base_priority == 1
    assert task.lane_id == "infra-staging"


def test_generic_adapter_parsing() -> None:
    raw_generic = {
        "task_id": "custom-1",
        "provider": "custom",
        "external_id": "C-1",
        "title": "Custom worker payload",
        "base_priority": 3,
    }

    task = GenericAdapter.from_dict(raw_generic)
    assert task.provider == "custom"
    assert task.title == "Custom worker payload"
    assert task.base_priority == 3
