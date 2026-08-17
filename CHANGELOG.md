# Changelog

All notable changes to SwarmCurator will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-08-17

### Added
- Initial release of **SwarmCurator** (Linear [GRO-4777](https://prismatic.growthwebdev.com/tab/tasks?issue=GRO-4777)).
- **Universal Multi-Provider Ingestion Adapters** ([GRO-4778](https://prismatic.growthwebdev.com/tab/tasks?issue=GRO-4778)):
  - `LinearAdapter`: Parses Linear GraphQL and webhook issue payloads into normalized `CuratorTask` descriptors.
  - `GitHubAdapter`: Normalizes GitHub Issues REST/Webhook payloads.
  - `KanbanAdapter`: Normalizes Hermes Markdown/JSON Kanban cards.
  - `GenericAdapter`: Fallback dictionary normalizer.
  - Idempotent fingerprint deduplication preventing duplicate task admissions.
- **Priority Aging & Lane-Locking Admission Engine** ([GRO-4779](https://prismatic.growthwebdev.com/tab/tasks?issue=GRO-4779)):
  - Anti-starvation aging formula promoting starved low-priority tickets dynamically over time.
  - Exclusive `lane_id` locking preventing multi-agent collisions and merge conflicts on shared workspaces.
  - Atomic JSON persistence protected by cross-process file locks.
- **Multi-Modal Interfaces & Prismatic Integration** ([GRO-4780](https://prismatic.growthwebdev.com/tab/tasks?issue=GRO-4780)):
  - Interactive CLI tool (`swarmcurator admit`, `pop`, `lanes`, `list`, `release`).
  - Drop-in FastAPI router (`/curator/queue`, `/curator/pop`, `/curator/admit`, `/curator/release`).
  - Prismatic Engine ops deployment scripts (`scripts/ops/update-swarmcurator.sh`).
- **Standardized Type Annotations & Packaging**:
  - PEP 561 `py.typed` marker for `mypy` and `pyright`.
  - Comprehensive unit test suite with 100% pass rate.
