"""
Transaction Cache Coherence Engine for SwarmCurator.
Provides deterministic eviction of cached tool responses, vector embeddings,
and context memory items when a SwarmSaga transaction aborts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("swarmcurator.coherence")


@dataclass
class CachedMemoryEntry:
    entry_id: str
    tx_id: str
    key: str
    content: Any
    embedding: list[float] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class CacheCoherenceManager:
    """
    Manages in-memory cache and vector index coherence aligned with transactional lifecycles.
    """

    def __init__(self):
        self._entries: dict[str, CachedMemoryEntry] = {}
        self._tx_index: dict[str, set[str]] = {}  # tx_id -> Set of entry_ids

    def put(
        self,
        key: str,
        content: Any,
        tx_id: str,
        embedding: list[float] | None = None,
        metadata: dict[str, Any] | None = None
    ) -> str:
        """Stores a cached item associated with a transaction ID."""
        import uuid
        entry_id = f"mem_{uuid.uuid4().hex[:12]}"
        entry = CachedMemoryEntry(
            entry_id=entry_id,
            tx_id=tx_id,
            key=key,
            content=content,
            embedding=embedding,
            metadata=metadata or {}
        )
        self._entries[entry_id] = entry
        self._tx_index.setdefault(tx_id, set()).add(entry_id)
        return entry_id

    def get(self, entry_id: str) -> CachedMemoryEntry | None:
        return self._entries.get(entry_id)

    def get_by_key(self, key: str) -> list[CachedMemoryEntry]:
        return [e for e in self._entries.values() if e.key == key]

    def invalidate_transaction(self, tx_id: str) -> int:
        """
        Purges all cached tool outputs, embeddings, and context items tied to an aborted transaction.
        Returns the number of entries evicted.
        """
        entry_ids = self._tx_index.pop(tx_id, set())
        evicted_count = len(entry_ids)
        for eid in entry_ids:
            self._entries.pop(eid, None)
        logger.info("Evicted %d stale cache entries for aborted transaction %s", evicted_count, tx_id)
        return evicted_count

    @property
    def total_entries(self) -> int:
        return len(self._entries)
