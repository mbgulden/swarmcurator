"""
Semantic Attention Distiller for SwarmCurator.
Consumes SwarmLedger Merkle DAG traces and projects high-density operator briefings.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from swarmledger.storage.engine import StorageEngine

logger = logging.getLogger("swarmcurator.distiller")


def _require_event_type() -> type:
    """Import SwarmLedger's EventType lazily — swarmledger is an optional integration."""
    try:
        from swarmledger.core.node import EventType
    except ImportError as exc:
        raise ImportError(
            "SemanticAttentionDistiller requires the 'swarmledger' package, "
            "which is not published on PyPI. Install it from GitHub with:\n"
            "    pip install git+https://github.com/mbgulden/swarmledger.git"
        ) from exc
    return EventType


@dataclass
class ExecutiveBriefing:
    span_id: str
    tx_id: str | None
    agent_id: str
    total_nodes: int
    mutations_count: int
    proof_certificates: list[str]
    escalation_scores: list[float]
    final_state: str  # "COMMITTED", "ABORTED", "PENDING"
    summary_bullets: list[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        status_badge = "🟢 COMMITTED" if self.final_state == "COMMITTED" else "🔴 ABORTED"
        lines = [
            f"### 📋 Executive Briefing: `{self.span_id}` ({status_badge})",
            f"- **Agent**: `{self.agent_id}`",
            f"- **Transaction ID**: `{self.tx_id or 'N/A'}`",
            f"- **Total Provenance Nodes**: {self.total_nodes}",
            f"- **Mutations Applied**: {self.mutations_count}",
            f"- **Proof Certificates**: {', '.join(self.proof_certificates) if self.proof_certificates else 'None'}",
            f"- **Max Escalation Score**: {max(self.escalation_scores) if self.escalation_scores else 0.0:.3f}",
            "",
            "**Event Trace Highlights:**"
        ]
        for b in self.summary_bullets:
            lines.append(f"  * {b}")
        return "\n".join(lines)


class SemanticAttentionDistiller:
    """
    Distills raw cryptographic Merkle spans into executive operator summaries.
    """

    def __init__(self, engine: StorageEngine):
        self.engine = engine

    def distill_span(self, span_id: str) -> ExecutiveBriefing:
        EventType = _require_event_type()
        nodes = self.engine.get_span_nodes(span_id)
        if not nodes:
            return ExecutiveBriefing(
                span_id=span_id,
                tx_id=None,
                agent_id="unknown",
                total_nodes=0,
                mutations_count=0,
                proof_certificates=[],
                escalation_scores=[],
                final_state="UNKNOWN"
            )

        agent_id = nodes[0].agent_id
        tx_id = None
        mutations = 0
        proofs = []
        scores = []
        final_state = "PENDING"
        bullets = []

        for n in nodes:
            bullets.append(f"[{n.event_type.value}] Agent `{n.agent_id}` at sequence {n.lamport_seq}")
            if n.event_type == EventType.MUTATE:
                mutations += 1
                if "tx_id" in n.payload:
                    tx_id = n.payload["tx_id"]
            elif n.event_type == EventType.PROOF:
                if "proof_id" in n.payload:
                    proofs.append(n.payload["proof_id"])
            elif n.event_type == EventType.GATE:
                if "escalation_score" in n.payload:
                    scores.append(float(n.payload["escalation_score"]))
            elif n.event_type == EventType.COMMIT:
                final_state = "COMMITTED"
            elif n.event_type == EventType.ABORT:
                final_state = "ABORTED"

        return ExecutiveBriefing(
            span_id=span_id,
            tx_id=tx_id,
            agent_id=agent_id,
            total_nodes=len(nodes),
            mutations_count=mutations,
            proof_certificates=proofs,
            escalation_scores=scores,
            final_state=final_state,
            summary_bullets=bullets
        )
