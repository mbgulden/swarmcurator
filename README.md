# 📥 SwarmCurator

**Hardened multi-provider task admission, priority aging, and lane-locking queue primitive for AI agent swarms.**

[![PyPI](https://img.shields.io/pypi/v/swarmcurator.svg)](https://pypi.org/project/swarmcurator/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Typing: Typed](https://img.shields.io/badge/Typing-Typed-blue.svg)](https://peps.python.org/pep-0561/)

---

## 🌟 What Sets SwarmCurator Apart

In modern AI agent swarms, tasks arrive from diverse issue trackers (Linear, GitHub, Kanban). Without a unified admission queue, two agents will simultaneously attempt to edit the same repository or workspace, creating merge conflicts, race conditions, and worktree collisions. Furthermore, low-priority maintenance tickets starve forever behind urgent feature requests, and crashed workers leave locks orphaned indefinitely.

**SwarmCurator** solves this with an **enterprise-hardened, zero-dependency task admission engine** featuring dynamic anti-starvation priority aging, exclusive workspace lane locking, self-healing lease recovery, and dead-letter queue governance.

```
       ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
       │ Linear Issue │     │ GitHub Issue │     │ Kanban Card  │
       └──────┬───────┘     └──────┬───────┘     └──────┬───────┘
              │                    │                    │
              ▼                    ▼                    ▼
       ┌────────────────────────────────────────────────────────┐
       │             SwarmCurator Ingestion Adapters            │
       │  `AutoAdapter`, `LinearAdapter`, `CompositeTaskBuilder`│
       └───────────────────────────┬────────────────────────────┘
                                   │
                                   ▼
       ┌────────────────────────────────────────────────────────┐
       │           Unified Schema (`CuratorTask`)               │
       │  • task_id, external_id, title, priority (0-4)         │
       │  • lane_id (workspace/repo collision domain)           │
       │  • deduplication_hash, multi-input streams, metadata   │
       └───────────────────────────┬────────────────────────────┘
                                   │
                                   ▼
       ┌────────────────────────────────────────────────────────┐
       │   Hardened Priority Aging & Lane Locking Queue Engine  │
       │  • Anti-Starvation Formula: EffectivePriority(t)       │
       │  • Lane Locks: Active agents acquire exclusive lane_id │
       │  • Self-Healing: Lease TTL auto-reclaims crashed tasks │
       │  • Retry & DLQ: Automatic exponential backoff & DLQ    │
       │  • Atomic FileLock: Multi-process race protection      │
       └───────────────────────────┬────────────────────────────┘
                                   │
                                   ▼
       ┌────────────────────────────────────────────────────────┐
       │          Popped Task for Dispatch (`pop_next()`)       │
       │  Dispatched to optimal agent without collision risk    │
       └────────────────────────────────────────────────────────┘
```

### Core Capabilities:
- 🚀 **Zero External Dependencies**: Pure Python 3.10+ standard library.
- 🔌 **Universal Multi-Provider Adapters**: Ingest Linear GraphQL, GitHub REST/Webhook, or Hermes Kanban cards into normalized `CuratorTask` records.
- 🌊 **Simultaneous Multi-Input Batching**: Admit batches of mixed issues at once with `admit_batch()`.
- 🧩 **Composite Multi-Stream Context**: Attach issues, PR diffs, CI logs, and specs to a single task using `CompositeTaskBuilder`.
- 🔒 **Exclusive Lane Locking**: Prevents multiple agents from working on the same repository, branch, or workspace domain concurrently.
- ⏳ **Anti-Starvation Priority Aging**: Dynamically calculates effective priority so aging low-priority tickets bubble up fairly.
- 🛡️ **Self-Healing Crash Recovery**: Configurable `lease_ttl_seconds` automatically reclaims tasks from dead/crashed worker processes.
- 📬 **Dead-Letter Queue (DLQ)**: Configurable `max_retries` routes repeatedly failing tasks to dead-letter storage.
- 🔐 **HMAC Webhook Security**: Built-in HMAC SHA256 signature verification for Linear and GitHub webhooks.
- 🌐 **Unified Interfaces**: Python API, command-line tool (`swarmcurator`), and drop-in FastAPI router.

---

## 💻 Installation

```bash
# Core package (zero dependencies)
pip install swarmcurator

# With optional FastAPI support
pip install swarmcurator[fastapi]
```

---

## ⚡ Quickstart

```python
from swarmcurator import SwarmCuratorQueue, AutoAdapter, CompositeTaskBuilder

# 1. Initialize queue (defaults to ~/.swarmcurator/queue.json)
queue = SwarmCuratorQueue()

# 2. Ingest batch of mixed tasks simultaneously
queue.admit_batch([
    {"identifier": "GRO-101", "title": "Refactor auth middleware", "priority": 1, "labels": ["lane:auth-service"]},
    {"number": 52, "title": "Fix DB leak", "repo": "auth-service", "labels": ["priority:critical"]},
])

# 3. Pop next available task for Worker 1
worker1_task = queue.pop_next(agent_id="agent-ned")
print(f"Worker 1 leased: [{worker1_task.external_id}] (Lane '{worker1_task.lane_id}' is now LOCKED)")

# 4. Worker 2 requests work -> Bypasses second task because lane 'auth-service' is locked!
worker2_task = queue.pop_next(agent_id="agent-agy")
print(f"Worker 2 received: {worker2_task} (Collision prevented!)")

# 5. Worker 1 finishes work and releases lane
queue.release_lane(lane_id="auth-service", task_id=worker1_task.task_id, final_status="completed")
print("Lane released for next worker.")
```

---

## 🛠️ CLI Reference

SwarmCurator includes a full-featured terminal CLI:

```bash
# Admit a task into the queue with custom TTL and retries
swarmcurator admit \
  --id "GRO-4780" \
  --title "Wire SwarmCurator to Prismatic Ingestion" \
  --provider "linear" \
  --priority 1 \
  --lane "prismatic-core" \
  --ttl 900 \
  --max-retries 3

# Admit a batch from file or stdin
swarmcurator admit-batch --file incoming_tasks.json

# Pop next available task for an agent
swarmcurator pop --agent "agent-agy"

# Inspect queue health and telemetry stats
swarmcurator stats

# Release a lane lock upon task completion
swarmcurator release --lane "prismatic-core" --status "completed"

# List tasks in queue (including dead-letter)
swarmcurator list --status "dead_letter"

# Purge completed/failed tasks
swarmcurator purge
```

---

## 🌐 FastAPI Integration

Mount the hardened admission router directly to your FastAPI gateway:

```python
from fastapi import FastAPI
from swarmcurator.fastapi_router import create_router

app = FastAPI(title="Swarm Admission Hub")

app.include_router(
    create_router(
        github_webhook_secret="my-gh-secret",
        linear_webhook_secret="my-linear-secret",
    ),
    prefix="/api",
)
```

Exposes:
- `GET /api/curator/queue` — List queue tasks.
- `GET /api/curator/stats` — Live queue health & priority distribution telemetry.
- `POST /api/curator/admit` — Ingest single task payload.
- `POST /api/curator/admit/batch` — Ingest multiple tasks simultaneously.
- `POST /api/curator/pop` — Pop next dispatchable task for an agent.
- `POST /api/curator/release` — Release locked lane with retry support.
- `POST /api/curator/webhook/github` — Secure GitHub webhook receiver with HMAC check.
- `POST /api/curator/webhook/linear` — Secure Linear webhook receiver with HMAC check.

---

## 📄 License

MIT License © 2026 Michael Gulden
