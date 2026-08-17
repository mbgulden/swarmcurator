"""swarmcurator.adapters — Ingestion adapters with sanitization and HMAC webhook verification."""

from __future__ import annotations

import hashlib
import hmac
import re
from typing import Any, Mapping, Sequence
from .models import CuratorTask, TaskInputSource, sanitize_token


def _sanitize_label(label: str) -> str:
    # Allow alphanumeric, colon, dash, underscore, dot
    clean = re.sub(r"[^a-zA-Z0-9_\-\.:]", "_", label.strip()).strip("._")
    return clean[:64] if clean else "label"


def _normalize_labels(raw_labels: Any) -> list[str]:
    if isinstance(raw_labels, list):
        out = []
        for l in raw_labels:
            if isinstance(l, dict):
                name = l.get("name", "")
                if name:
                    out.append(_sanitize_label(str(name)))
            elif isinstance(l, str) and l.strip():
                out.append(_sanitize_label(l.strip()))
        return out
    elif isinstance(raw_labels, dict) and "nodes" in raw_labels:
        return [_sanitize_label(n.get("name", "")) for n in raw_labels.get("nodes", []) if n.get("name")]
    return []


def _extract_lane_id(labels: list[str], fallback: str = "default") -> str:
    for label in labels:
        lbl_lower = label.lower()
        if lbl_lower.startswith("lane:") or lbl_lower.startswith("lane_"):
            delim = ":" if ":" in lbl_lower else "_"
            return sanitize_token(lbl_lower.split(delim, 1)[1].strip())
        if lbl_lower.startswith("repo:") or lbl_lower.startswith("repo_"):
            delim = ":" if ":" in lbl_lower else "_"
            return sanitize_token(lbl_lower.split(delim, 1)[1].strip())
    return sanitize_token(fallback)


def verify_github_signature(payload_bytes: bytes, signature_header: str, secret: str) -> bool:
    """Verify GitHub webhook payload against X-Hub-Signature-256 header."""
    if not signature_header or not secret:
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header.strip())


def verify_linear_signature(payload_bytes: bytes, signature_header: str, secret: str) -> bool:
    """Verify Linear webhook payload against Linear-Signature header."""
    if not signature_header or not secret:
        return False
    expected = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header.strip())


class LinearAdapter:
    """Normalizes Linear GraphQL or webhook payloads into a CuratorTask."""

    @staticmethod
    def from_dict(issue: Mapping[str, Any]) -> CuratorTask:
        ident = sanitize_token(str(issue.get("identifier") or issue.get("id") or "LINEAR-000"))
        title = str(issue.get("title") or "")
        desc = str(issue.get("description") or "")
        labels = _normalize_labels(issue.get("labels", []))

        # Linear priority mapping: 0=No priority, 1=Urgent, 2=High, 3=Medium, 4=Low
        raw_pri = issue.get("priority", 3)
        if raw_pri == 1:
            base_pri = 0  # Urgent
        elif raw_pri == 2:
            base_pri = 1  # High
        elif raw_pri == 3:
            base_pri = 2  # Medium
        elif raw_pri == 4:
            base_pri = 3  # Low
        else:
            base_pri = 4  # Backlog / No priority

        proj = issue.get("project", {})
        proj_name = proj.get("name") if isinstance(proj, dict) else str(proj or "")
        team = issue.get("team", {})
        team_key = team.get("key") if isinstance(team, dict) else str(team or "")
        fallback_lane = proj_name or team_key or "linear"
        lane_id = _extract_lane_id(labels, fallback=fallback_lane)

        task = CuratorTask(
            task_id=f"linear-{ident.lower()}",
            provider="linear",
            external_id=ident,
            title=title,
            description=desc,
            base_priority=base_pri,
            lane_id=lane_id,
            labels=labels,
            metadata={"project": proj_name, "team": team_key},
        )
        task.add_input_source("linear", ident, desc, {"project": proj_name})
        return task


class GitHubAdapter:
    """Normalizes GitHub Issue REST/webhook payloads into a CuratorTask."""

    @staticmethod
    def from_dict(issue: Mapping[str, Any], repo_name: str = "github") -> CuratorTask:
        number = issue.get("number") or issue.get("id") or 0
        ident = f"GH-{number}"
        title = str(issue.get("title") or "")
        desc = str(issue.get("body") or "")
        labels = _normalize_labels(issue.get("labels", []))

        # Infer priority from labels
        base_pri = 2  # default Medium
        for lbl in labels:
            lbl_lower = lbl.lower()
            if "p0" in lbl_lower or "urgent" in lbl_lower or "critical" in lbl_lower:
                base_pri = 0
                break
            elif "p1" in lbl_lower or "high" in lbl_lower:
                base_pri = 1
                break
            elif "p3" in lbl_lower or "low" in lbl_lower:
                base_pri = 3
                break

        clean_repo = sanitize_token(repo_name, fallback="github")
        lane_id = _extract_lane_id(labels, fallback=clean_repo)

        task = CuratorTask(
            task_id=f"gh-{number}",
            provider="github",
            external_id=ident,
            title=title,
            description=desc,
            base_priority=base_pri,
            lane_id=lane_id,
            labels=labels,
            metadata={"repo": clean_repo, "url": issue.get("html_url", "")},
        )
        task.add_input_source("github", ident, desc, {"repo": clean_repo, "url": issue.get("html_url", "")})
        return task


class KanbanAdapter:
    """Normalizes Hermes Kanban cards into a CuratorTask."""

    @staticmethod
    def from_dict(card: Mapping[str, Any]) -> CuratorTask:
        card_id = sanitize_token(str(card.get("id") or "KANBAN-000"))
        title = str(card.get("title") or "")
        desc = str(card.get("description") or card.get("content") or "")
        labels = _normalize_labels(card.get("labels", []))
        base_pri = int(card.get("priority", 2))
        raw_lane = str(card.get("lane_id") or card.get("column") or "kanban")
        lane_id = sanitize_token(raw_lane, fallback="kanban")

        task = CuratorTask(
            task_id=f"kanban-{card_id.lower()}",
            provider="kanban",
            external_id=card_id,
            title=title,
            description=desc,
            base_priority=base_pri,
            lane_id=lane_id,
            labels=labels,
            metadata={"column": card.get("column", "")},
        )
        task.add_input_source("kanban", card_id, desc, {"column": card.get("column", "")})
        return task


class GenericAdapter:
    """Generic fallback dictionary converter."""

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> CuratorTask:
        return CuratorTask.from_dict(dict(data))


class AutoAdapter:
    """Automatically detects provider schema and converts any input dictionary into a CuratorTask."""

    @classmethod
    def from_any(cls, item: Any) -> CuratorTask:
        if isinstance(item, CuratorTask):
            return item

        if not isinstance(item, (dict, Mapping)):
            raise TypeError(f"Expected dict or CuratorTask, got {type(item).__name__}")

        provider = str(item.get("provider", "")).lower()
        if provider == "linear":
            return LinearAdapter.from_dict(item)
        if provider == "github":
            repo = str(item.get("repo") or item.get("metadata", {}).get("repo") or "github")
            return GitHubAdapter.from_dict(item, repo_name=repo)
        if provider == "kanban":
            return KanbanAdapter.from_dict(item)

        if "identifier" in item or "team" in item:
            return LinearAdapter.from_dict(item)
        if "number" in item or "html_url" in item or "body" in item:
            repo = str(item.get("repo") or item.get("metadata", {}).get("repo") or "github")
            return GitHubAdapter.from_dict(item, repo_name=repo)
        if "column" in item:
            return KanbanAdapter.from_dict(item)

        if "title" in item and ("task_id" in item or "id" in item or "external_id" in item):
            task_id = sanitize_token(str(item.get("task_id") or item.get("id") or item.get("external_id")))
            return CuratorTask(
                task_id=task_id,
                provider=sanitize_token(str(item.get("provider") or "generic")),
                external_id=sanitize_token(str(item.get("external_id") or task_id)),
                title=str(item.get("title")),
                description=str(item.get("description") or item.get("desc") or ""),
                base_priority=int(item.get("priority") or item.get("base_priority") or 2),
                lane_id=sanitize_token(str(item.get("lane_id") or item.get("lane") or "default")),
                labels=_normalize_labels(item.get("labels", [])),
                inputs=item.get("inputs", []),
                metadata=item.get("metadata", {}),
            )

        return GenericAdapter.from_dict(item)


class CompositeTaskBuilder:
    """Fluent builder for composing a single unified task out of multiple heterogeneous input streams."""

    def __init__(self, task_id: str, title: str, lane_id: str = "default", base_priority: int = 2) -> None:
        self.task_id = sanitize_token(task_id)
        self.title = title
        self.lane_id = sanitize_token(lane_id)
        self.base_priority = base_priority
        self.description_parts: list[str] = []
        self.labels: list[str] = []
        self.inputs: list[dict[str, Any]] = []
        self.metadata: dict[str, Any] = {}

    def add_linear_issue(self, issue: Mapping[str, Any]) -> CompositeTaskBuilder:
        ident = sanitize_token(str(issue.get("identifier") or issue.get("id") or "LINEAR"))
        desc = str(issue.get("description") or "")
        self.inputs.append(TaskInputSource("linear", ident, desc, {"project": issue.get("project")}).to_dict())
        if desc:
            self.description_parts.append(f"### Linear Context ({ident}):\n{desc}")
        self.labels.extend(_normalize_labels(issue.get("labels", [])))
        return self

    def add_github_pr_or_issue(self, issue: Mapping[str, Any], repo: str = "") -> CompositeTaskBuilder:
        ident = f"GH-{issue.get('number', issue.get('id', 'PR'))}"
        body = str(issue.get("body") or "")
        url = str(issue.get("html_url") or "")
        clean_repo = sanitize_token(repo, fallback="github")
        self.inputs.append(TaskInputSource("github", ident, body, {"repo": clean_repo, "url": url}).to_dict())
        if body:
            self.description_parts.append(f"### GitHub Context ({ident}):\n{body}")
        return self

    def add_context(self, source_type: str, reference: str, content: str = "", metadata: dict[str, Any] | None = None) -> CompositeTaskBuilder:
        clean_src = sanitize_token(source_type, fallback="context")
        clean_ref = sanitize_token(reference, fallback="ref")
        self.inputs.append(TaskInputSource(clean_src, clean_ref, content, metadata or {}).to_dict())
        if content:
            self.description_parts.append(f"### {clean_src.upper()} Context ({clean_ref}):\n{content}")
        return self

    def build(self) -> CuratorTask:
        full_desc = "\n\n".join(self.description_parts)
        return CuratorTask(
            task_id=self.task_id,
            provider="composite",
            external_id=self.task_id,
            title=self.title,
            description=full_desc,
            base_priority=self.base_priority,
            lane_id=self.lane_id,
            labels=list(set(self.labels)),
            inputs=self.inputs,
            metadata=self.metadata,
        )


class MultiInputAggregator:
    """Normalizes a collection of mixed raw input objects simultaneously."""

    @staticmethod
    def aggregate(items: Sequence[Any]) -> list[CuratorTask]:
        tasks: list[CuratorTask] = []
        for it in items:
            try:
                tasks.append(AutoAdapter.from_any(it))
            except Exception:
                continue
        return tasks
