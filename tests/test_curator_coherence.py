"""
Tests for SwarmCurator Cache Coherence and Semantic Attention Distillation.
"""

import tempfile
from pathlib import Path
import pytest

from swarmcurator.coherence import CacheCoherenceManager
from swarmcurator.distiller import SemanticAttentionDistiller
from swarmledger.core.node import EventType
from swarmledger.storage.engine import StorageEngine


def test_cache_invalidation_on_transaction_abort():
    coherence = CacheCoherenceManager()

    # Store cache items for transaction A
    e1 = coherence.put("search_auth", "def login(): pass", tx_id="tx_A", embedding=[0.1, 0.2])
    e2 = coherence.put("search_jwt", "import jwt", tx_id="tx_A", embedding=[0.3, 0.4])

    # Store cache items for transaction B
    e3 = coherence.put("search_db", "import sqlite3", tx_id="tx_B", embedding=[0.5, 0.6])

    assert coherence.total_entries == 3

    # Invalidate transaction A
    evicted = coherence.invalidate_transaction("tx_A")
    assert evicted == 2
    assert coherence.total_entries == 1

    # Assert tx_A entries are gone
    assert coherence.get(e1) is None
    assert coherence.get(e2) is None

    # Assert tx_B entry remains intact
    assert coherence.get(e3) is not None
    assert coherence.get(e3).content == "import sqlite3"


def test_semantic_attention_distiller_on_merkle_dag():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "ledger.db"
        engine = StorageEngine(db_path=db_path)
        span_id = "span_curator_audit_1"

        # Build 5-node trace in Merkle DAG
        n1 = engine.append_node(span_id, EventType.PROMPT, "user_1", {"prompt": "Refactor token auth"})
        n2 = engine.append_node(span_id, EventType.MUTATE, "agent_x", {"tx_id": "tx_refactor_99", "lines_changed": 25}, [n1.node_id])
        n3 = engine.append_node(span_id, EventType.PROOF, "proof_bot", {"proof_id": "prf_ast_cert_42"}, [n2.node_id])
        n4 = engine.append_node(span_id, EventType.GATE, "gate_bot", {"escalation_score": 0.35}, [n3.node_id])
        n5 = engine.append_node(span_id, EventType.COMMIT, "hypervisor", {"status": "COMMITTED"}, [n4.node_id])

        distiller = SemanticAttentionDistiller(engine)
        brief = distiller.distill_span(span_id)

        assert brief.span_id == span_id
        assert brief.tx_id == "tx_refactor_99"
        assert brief.agent_id == "user_1"
        assert brief.total_nodes == 5
        assert brief.mutations_count == 1
        assert brief.proof_certificates == ["prf_ast_cert_42"]
        assert brief.escalation_scores == [0.35]
        assert brief.final_state == "COMMITTED"

        md = brief.to_markdown()
        assert "🟢 COMMITTED" in md
        assert "prf_ast_cert_42" in md
        assert "tx_refactor_99" in md