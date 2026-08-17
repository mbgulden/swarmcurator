# SwarmCurator — Live Demo Guide

> **What makes it indispensable**: SwarmCurator is the only zero-dependency Python task queue that combines semantic workspace lane locking, self-healing crash recovery, and heterogeneous multi-provider ingestion in a single file-backed primitive. No Redis. No Celery. No Postgres. Just Python.

---

## Quick Start (30 seconds)

```bash
pip install git+https://github.com/mbgulden/swarmcurator.git@main
```

Then run any demo:

```bash
python examples/04_crash_recovery_demo.py  # The killer demo — self-healing agent crash
python examples/02_lane_locked_dispatch.py # Collision-free multi-agent dispatch
python examples/05_priority_override_demo.py # Operator incident escalation
```

---

## Demo 1 — Multi-Provider Ingestion & Normalization

**Run**: `python examples/01_multi_provider_ingestion.py`

**What it proves**: SwarmCurator ingests a Linear issue, GitHub issue, and Kanban card in 3 lines of code each — then normalizes them into a unified priority-sorted queue with automatic deduplication.

```
📥 SwarmCurator Example: Multi-Provider Ingestion & Normalization
✅ Ingested Linear: [GRO-3320] 'Prismatic Hub Phase 5 Control Plane' (Priority P0, Lane 'hub-core')
✅ Ingested GitHub: [GH-104] 'Fix memory leak in WebSocket connection pool' (Priority P0, Lane 'gateway')
✅ Ingested Kanban: [KB-202] 'Update SSL Certificate and Cloudflare DNS' (Priority P2, Lane 'infra-ops')
🔒 Deduplication Check: Re-admitting same Linear task -> Admitted: False (Expected False)
```

**The advantage**: Every other approach requires you to write a custom normalization layer per provider. SwarmCurator's `AutoAdapter.from_any()` detects provider schema automatically. Pass it a Linear dict, a GitHub dict, or a Kanban card — it produces a canonical `CuratorTask` every time.

---

## Demo 2 — Exclusive Lane Locking & Conflict-Free Dispatch

**Run**: `python examples/02_lane_locked_dispatch.py`

**The problem it solves**: Without lane locking, if 3 agents all work the same git repository simultaneously, you get merge conflicts, CI failures, and broken builds.

**What it proves**: Two tasks both target `repo-backend`. When Agent Ned pops the first one, the entire `repo-backend` lane is atomically locked. Agent AGY gets redirected to `repo-frontend` (different lane, no conflict). Agent Jules gets `None` — correctly blocked — until Ned releases.

```
🔒 Lane 'repo-backend' is now HELD by agent-ned
🚀 Agent 'AGY' popped task: [GRO-103] 'Redesign Mobile Navigation Drawer'
   • Note: GRO-102 was bypassed to prevent multi-agent collision on 'repo-backend'!
⏸️  Agent 'Jules' popped task: None (Correctly None — all active lanes occupied)
🔓 Agent 'Ned' completed task and RELEASED lane 'repo-backend'
🚀 Agent 'Jules' retries and pops: [GRO-102] 'Refactor Database Connection Pool'
🎉 Zero worktree collisions and zero merge conflicts!
```

**Key insight**: The lane is a *semantic domain*, not a task identifier. This means the lock prevents *classes* of collisions — any task that touches `repo-backend` must wait, regardless of how many such tasks exist.

---

## Demo 3 — Simultaneous Multi-Input Batch Ingestion

**Run**: `python examples/03_multi_input_batch_ingestion.py`

**What it proves**: `admit_batch()` processes a mixed list (Linear + GitHub + Kanban + Generic + duplicate) in a single atomic operation, with one entry correctly rejected as a duplicate.

```
📦 Admitting a batch of heterogeneous items simultaneously...
   • Total Processed: 5
   • Total Admitted:  4
   • Duplicates:      1
```

**Composite tasks**: The second part shows `CompositeTaskBuilder` assembling a single agent task from 4 separate input streams — a Linear issue, a GitHub PR, a CI log, and a design spec. The resulting `CuratorTask.inputs[]` contains all 4 source references with full content for the agent to consume.

---

## Demo 4 — Self-Healing Crash Recovery ⭐ (The Killer Feature)

**Run**: `python examples/04_crash_recovery_demo.py`

**This is the one feature no other task queue offers without a supervisor daemon.**

Every Redis/Celery/RQ/SQLite queue requires either:
- A separate visibility timeout daemon (Celery: `celery beat`)
- Manual human intervention to `DELETE` stuck jobs
- A Redis BRPOPLPUSH visibility timeout that only works if you remember to set it

SwarmCurator's lease TTL is **built into every `pop_next()` call**. No daemon needed.

**Full output**:
```
📝 Step 1: Enqueue 2 tasks in 'prismatic-core' lane
   ✅ Admitted: [GRO-5001] P0 Urgent — 'Apply database migration for auth schema v3'
   ✅ Admitted: [GRO-5002] P1 High   — 'Refactor gateway authentication middleware'

🚀 Step 2: agent-ned pops next available task...
   ✅ agent-ned leased: [GRO-5001]
   🔒 Lane 'prismatic-core' is now LOCKED by agent-ned
   ⏱  Lease expires in: 30s

⏸  Step 3: agent-agy tries to pop...
   ❌ agent-agy received: None  (lane blocked — collision prevented!)

💀 Step 4: agent-ned CRASHES — process dies without releasing lane
   🚨 In a naive system: 'prismatic-core' is now PERMANENTLY LOCKED

⏩ Step 5: Simulating lease TTL expiry...

🔄 Step 6: agent-agy polls for work again...
   🎉 AUTO-RECOVERY: agent-agy received: [GRO-5001]
   ✅ Retry count on recovered task: 1/2
   ✅ Now assigned to: agent-agy
   ✅ Lane 'prismatic-core' re-locked under agent-agy — no data lost!

✅ Crash recovery complete — zero human intervention required!
   No Redis. No Celery. No supervisor daemon. No human.
```

**How it works under the hood**:
1. Every `pop_next()` call begins by calling `_reclaim_expired_leases()`
2. Any lane where `expires_at < now` is freed; its task is re-queued with `retry_count += 1`
3. If `retry_count > max_retries`, the task moves to `dead_letter` (configurable)
4. The recovered task is **persisted back to disk immediately** before yielding to the caller
5. The next `pop_next()` from any agent picks up the recovered task

---

## Demo 5 — Operator Priority Override (Incident Response)

**Run**: `python examples/05_priority_override_demo.py`

**Scenario**: A P3 (Low) bug filed last week is discovered to be causing a 30% auth failure rate in production. You need to put it ahead of all current work — immediately.

```
📋 Initial Queue Order:
   1. [GRO-200] P1 — 'Implement new dashboard export feature' (score: 3000.0)
   2. [GRO-202] P2 — 'Update Node.js dependencies to patch CVE' (score: 2000.0)
   3. [GRO-201] P3 — 'Investigate occasional 500s on /api/auth/refresh' (score: 1000.0)
   4. [GH-88]   P4 — 'Refactor legacy session cookie handling' (score: 0.0)

🚨 INCIDENT: queue.set_priority('task-b', new_priority=0)

📋 Updated Queue Order:
   1. [GRO-201] P0 — 'Investigate occasional 500s...' (score: 4000.0) ← 🔥 ESCALATED
   2. [GRO-200] P1 — 'Implement new dashboard export feature' (score: 3000.0)
```

One API call. No re-queue. No restart. The next `pop_next()` dispatches the escalated task.

---

## What Is Anti-Starvation Priority Aging?

SwarmCurator prevents low-priority tasks from waiting forever via **exponential priority aging**:

```
Effective Score = (4 - base_priority) × 1000 + (elapsed_seconds / half_life) × 100
```

| Priority | Fresh Score | After 1h (half_life=1h) | After 4h |
|----------|-------------|--------------------------|-----------|
| P0 Urgent | 4000 | 4100 | 4400 |
| P2 Medium | 2000 | 2100 | 2400 |
| P4 Backlog | 0 | 100 | 400 |

A P4 task that has been waiting 40 hours will overtake a freshly-filed P2. No task is permanently starved.

---

## CLI Reference

```bash
# Admit a task
swarmcurator admit --id GRO-123 --title "Fix login bug" --priority 0 --lane auth-service

# Pop next task (agent side)
swarmcurator pop --agent agent-agy

# Release lane after completion
swarmcurator release --lane auth-service --status completed

# Cancel a pending or leased task
swarmcurator cancel --id linear-gro-123

# Operator escalation
swarmcurator set-priority --id linear-gro-123 --priority 0

# Inspect queue
swarmcurator list --status pending
swarmcurator lanes
swarmcurator stats

# Purge completed/failed tasks
swarmcurator purge
```

---

## FastAPI Drop-in Router

```python
from fastapi import FastAPI
from swarmcurator import SwarmCuratorQueue
from swarmcurator.fastapi_router import create_router

app = FastAPI()
queue = SwarmCuratorQueue()
app.include_router(
    create_router(
        queue_instance=queue,
        github_webhook_secret="your-github-secret",
        linear_webhook_secret="your-linear-secret",
    )
)
# Instantly exposes:
# POST /curator/admit           — admit a task
# POST /curator/admit/batch     — batch ingestion
# POST /curator/pop             — agent work request
# POST /curator/release         — mark task complete/failed
# POST /curator/cancel          — cancel pending/leased task
# POST /curator/set-priority    — operator escalation
# GET  /curator/queue           — list tasks
# GET  /curator/lanes           — list active locks
# GET  /curator/stats           — telemetry
# POST /curator/webhook/github  — GitHub webhook (HMAC validated)
# POST /curator/webhook/linear  — Linear webhook (HMAC validated)
```

---

## Why Not [Other Queue]?

| Feature | SwarmCurator | Redis/RQ | Celery | SQLite Queue |
|---------|:---:|:---:|:---:|:---:|
| Zero external dependencies | ✅ | ❌ | ❌ | ❌ |
| Self-healing crash recovery | ✅ | ⚠️ visibility timeout | ⚠️ acks needed | ❌ |
| Semantic lane (workspace) locking | ✅ | ❌ | ❌ | ❌ |
| Anti-starvation priority aging | ✅ | ❌ | ❌ | ❌ |
| Multi-provider auto-ingestion | ✅ | ❌ | ❌ | ❌ |
| Schema migration / versioning | ✅ | ❌ | ❌ | ❌ |
| Thread + process safe | ✅ | ✅ | ✅ | ⚠️ |
| Operator priority override | ✅ | ❌ | ❌ | ❌ |
| Works in AI agent subprocess | ✅ | ❌ | ❌ | ⚠️ |

The design goal is **any AI agent, in any subprocess, on any machine**, with no infrastructure requirement — and still get production-grade safety guarantees.
