"""swarmcurator.adapters — Ingestion adapters for Linear, GitHub, and Kanban issues."""

from __future__ import annotations

from typing import Any, Mapping
from .models import CuratorTask


def _normalize_labels(raw_labels: Any) -> list[str]:
    if isinstance(raw_labels, list):
        out = []
        for l in raw_labels:
            if isinstance(l, dict):
                name = l.get("name", "")
                if name:
                    out.append(name)
            elif isinstance(l, str) and l.strip():
                out.append(l.strip())
        return out
    elif isinstance(raw_labels, dict) and "nodes" in raw_labels:
        return [n.get("name", "") for n in raw_labels.get("nodes", []) if n.get("name")]
    return []


def _extract_lane_id(labels: list[str], fallback: str = "default") -> str:
    for label in labels:
        lbl_lower = label.lower()
        if lbl_lower.startswith("lane:"):
            return lbl_lower.split(":", 1)[1].strip()
        if lbl_lower.startswith("repo:"):
            return lbl_lower.split(":", 1)[1].strip()
    return fallback


class LinearAdapter:
    """Normalizes Linear GraphQL or webhook payloads into a CuratorTask."""

    @staticmethod
    def from_dict(issue: Mapping[str, Any]) -> CuratorTask:
        ident = str(issue.get("identifier") or issue.get("id") or "LINEAR-000")
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

        # Extract lane from project name, team key, or label
        proj = issue.get("project", {})
        proj_name = proj.get("name") if isinstance(proj, dict) else str(proj or "")
        team = issue.get("team", {})
        team_key = team.get("key") if isinstance(team, dict) else str(team or "")
        fallback_lane = proj_name or team_key or "linear"
        lane_id = _extract_lane_id(labels, fallback=fallback_lane)

        return CuratorTask(
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

        lane_id = _extract_lane_id(labels, fallback=repo_name)

        return CuratorTask(
            task_id=f"gh-{number}",
            provider="github",
            external_id=ident,
            title=title,
            description=desc,
            base_priority=base_pri,
            lane_id=lane_id,
            labels=labels,
            metadata={"repo": repo_name, "url": issue.get("html_url", "")},
        )


class KanbanAdapter:
    """Normalizes Hermes Kanban cards into a CuratorTask."""

    @staticmethod
    def from_dict(card: Mapping[str, Any]) -> CuratorTask:
        card_id = str(card.get("id") or "KANBAN-000")
        title = str(card.get("title") or "")
        desc = str(card.get("description") or card.get("content") or "")
        labels = _normalize_labels(card.get("labels", []))
        base_pri = int(card.get("priority", 2))
        lane_id = str(card.get("lane_id") or card.get("column") or "kanban")

        return CuratorTask(
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


class GenericAdapter:
    """Generic fallback dictionary converter."""

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> CuratorTask:
        return CuratorTask.from_dict(dict(data))
