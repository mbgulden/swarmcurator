# 📥 SwarmCurator

**Universal multi-provider task admission, priority aging, and lane-locking queue primitive for AI agent swarms.**

[![PyPI](https://img.shields.io/pypi/v/swarmcurator.svg)](https://pypi.org/project/swarmcurator/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Typing: Typed](https://img.shields.io/badge/Typing-Typed-blue.svg)](https://peps.python.org/pep-0561/)

---

## 🌟 What Sets SwarmCurator Apart

In modern AI agent swarms, tasks arrive from diverse issue trackers (Linear, GitHub, Kanban). Without a unified admission queue, two agents will simultaneously attempt to edit the same repository or workspace, creating merge conflicts, race conditions, and worktree collisions. Furthermore, low-priority maintenance tickets starve forever behind urgent feature requests.

**SwarmCurator** solves this with a **zero-dependency task admission engine** featuring dynamic anti-starvation priority aging and exclusive workspace lane locking.

```
       ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
       │ Linear Issue │     │ GitHub Issue │     │ Kanban Card  │
       └──────┬───────┘     └──────┬───────┘     └──────┬───────┘
              │                    │                    │
              ▼                    ▼                    ▼
       ┌────────────────────────────────────────────────────────┐
       │             SwarmCurator Ingestion Adapters            │
       │       `LinearAdapter`, `GitHubAdapter`, `KanbanAdapter`│
       └───────────────────────────┬────────────────────────────┘
                                   │
                                   ▼
       ┌────────────────────────────────────────────────────────┐
       │           Unified Schema (`CuratorTask`)               │
       │  • task_id, external_id, title, priority (0-4)         │
       │  • lane_id (workspace/repo collision domain)           │
       │  • deduplication_hash, labels, metadata                │
       └───────────────────────────┬────────────────────────────┘
                                   │
                                   ▼
       ┌────────────────────────────────────────────────────────┐
       │       Priority Aging & Lane Locking Queue Engine       │
       │  • Anti-Starvation Formula: EffectivePriority(t)       │
       │  • Lane Locks: Active agents acquire exclusive lane_id │
       │  • Atomic JSON persistence & FileLock protection       │
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
- 🔒 **Exclusive Lane Locking**: Prevents multiple agents from working on the same repository, branch, or workspace domain concurrently.
- ⏳ **Anti-Starvation Priority Aging**: Dynamically calculates effective priority so aging low-priority tickets bubble up fairly.
- 🛡️ **Idempotent Deduplication**: Fingerprint hashing drops duplicate issue admissions automatically.
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
from swarmcurator import SwarmCuratorQueue, LinearAdapter, GitHubAdapter

# 1. Initialize queue (defaults to ~/.swarmcurator/queue.json)
queue = SwarmCuratorQueue()

# 2. Ingest tasks from Linear and GitHub
task_1 = LinearAdapter.from_dict({
    "identifier": "GRO-101",
    "title": "Refactor auth middleware",
    "priority": 1,  # High
    "labels": [{"name": "lane:auth-service"}],
})
queue.admit(task_1)

task_2 = GitHubAdapter.from_dict({
    "number": 52,
    "title": "Fix database connection leak",
    "labels": ["bug", "priority:critical", "lane:auth-service"],
}, repo_name="auth-service")
queue.admit(task_2)

# 3. Pop next available task for Worker 1
worker1_task = queue.pop_next(agent_id="agent-ned")
print(f"Worker 1 leased: [{worker1_task.external_id}] (Lane '{worker1_task.lane_id}' is now LOCKED)")

# 4. Worker 2 requests work -> Bypasses task_2 because lane 'auth-service' is locked!
worker2_task = queue.pop_next(agent_id="agent-agy")
print(f"Worker 2 received: {worker2_task} (Collision prevented!)")

# 5. Worker 1 finishes work and releases lane
queue.release_lane(lane_id="auth-service", task_id=worker1_task.task_id, final_status="completed")
print("Lane released for next worker.")
```

---

## 🛠️ CLI Reference

SwarmCurator includes a terminal CLI:

```bash
# Admit a task into the queue
swarmcurator admit \
  --id "GRO-4780" \
  --title "Wire SwarmCurator to Prismatic Ingestion" \
  --provider "linear" \
  --priority 1 \
  --lane "prismatic-core"

# Pop next available task for an agent
swarmcurator pop --agent "agent-agy"

# List active lane locks
swarmcurator lanes

# Release a lane lock upon task completion
swarmcurator release --lane "prismatic-core" --status "completed"

# List tasks in queue
swarmcurator list --status "pending"

# Purge completed tasks
swarmcurator purge
```

---

## 🌐 FastAPI Integration

Mount the admission router directly to your FastAPI gateway:

```python
from fastapi import FastAPI, Header, HTTPException
from swarmcurator.fastapi_router import create_router

app = FastAPI(title="Swarm Admission Hub")

def verify_token(x_token: str = Header(...)):
    if x_token != "secret-key":
        raise HTTPException(status_code=401, detail="Unauthorized")

app.include_router(
    create_router(auth_dependency=verify_token),
    prefix="/api",
)
```

Exposes:
- `GET /api/curator/queue` — List queue tasks.
- `POST /api/curator/admit` — Ingest task payload.
- `POST /api/curator/pop` — Pop next dispatchable task for an agent.
- `POST /api/curator/release` — Release locked lane.
- `GET /api/curator/lanes` — Inspect active lane locks.

---

## 📁 Repository Examples

Explore runnable examples in the [`examples/`](file:///c:/Users/Michael%20Gulden/Github/swarmcurator/examples) directory:

- [`01_multi_provider_ingestion.py`](file:///c:/Users/Michael%20Gulden/Github/swarmcurator/examples/01_multi_provider_ingestion.py) — Ingestion across Linear, GitHub, and Kanban.
- [`02_lane_locked_dispatch.py`](file:///c:/Users/Michael%20Gulden/Github/swarmcurator/examples/02_lane_locked_dispatch.py) — Lane locking mutual exclusion.

---

## 📄 License

MIT License © 2026 Michael Gulden
