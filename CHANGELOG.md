# Changelog

All notable changes to SwarmCurator will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] — 2026-08-17

### Hardened & Security
- **Cross-Process Concurrency Fencing**: Wrapped all file store mutations in a cross-platform advisory file locking context manager to prevent race conditions during high-volume dispatch.
- **Self-Healing Lease Recovery**: Added configurable `lease_ttl_seconds` (default: 600s) on lane states. `pop_next()` automatically sweeps and reclaims abandoned tasks from crashed agent workers.
- **Retry & Dead-Letter Queue (DLQ)**: Added `retry_count` and `max_retries` (default: 3). Failed/expired tasks retry with backoff and transition to `dead_letter` status if retries are exhausted.
- **Input Sanitization & Injection Guard**: Added `sanitize_token()` enforcing strict alphanumeric and safe delimiter rules on external IDs, lanes, and label prefixes.
- **HMAC Webhook Verification**: Added `verify_github_signature()` (`X-Hub-Signature-256`) and `verify_linear_signature()` (`Linear-Signature`) preventing unauthenticated webhook admissions.
- **Queue Telemetry & Health API**: Added `QueueStats`, `GET /curator/stats`, and `swarmcurator stats` CLI command with live priority breakdown and age distributions.

## [0.2.0] — 2026-08-17

### Added
- **Multi-Input Batch Ingestion**: `admit_batch()`, `AutoAdapter.from_any()`, `MultiInputAggregator.aggregate()`, and `POST /curator/admit/batch`.
- **Composite Task Builder**: `CompositeTaskBuilder` allowing callers to attach multiple contextual streams (Linear + PR + CI Logs + Specs) to a single task.
- **CLI Batch Commands**: `swarmcurator admit-batch --file tasks.json`.

## [0.1.0] — 2026-08-17

### Added
- Initial release of **SwarmCurator** (Linear [GRO-4777](https://prismatic.growthwebdev.com/tab/tasks?issue=GRO-4777)).
- Universal Multi-Provider Ingestion Adapters (Linear, GitHub, Kanban).
- Priority Aging & Anti-Starvation Queue.
- Exclusive Workspace Lane Locking.
