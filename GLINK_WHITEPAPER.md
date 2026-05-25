# 🚀 Glink — Multi-Agent Workflow Orchestration Engine

> **Whitepaper v1.0 | 2026-05-25**
> Making agents genuinely work together, not fight in silos.

## 1. Overview

**Glink** is a **lightweight multi-agent orchestration engine** for AI agent workflows.

Traditionally, AI agents run in isolation — no shared information, no result handover.
Glink breaks this isolation through **Main Bus shared blackboard architecture**:

```
                        ┌─────────────────────────────────┐
                        │         Glink Engine              │
                        ├─────────────────────────────────┤
                        │  Agent-1  │  Agent-2  │ Agent-3  │
                        │  (Hammer) │  (Ink)    │ (Forge)  │
                        └─────┬─────────┬──────────┬──────┘
                              │         │          │
                        ┌─────▼─────────▼──────────▼──────┐
                        │      Main Bus (JSONL blackboard) │
                        │    One timeline per project      │
                        └─────────────────────────────────┘
```

**Core philosophy:**

- **Lightweight** — One Python file + one JSONL file. Zero external dependencies.
- **Incremental** — From simple sequential orchestration to smart routing + auto-recovery.
- **Agent-agnostic** — Agents don't need to know Glink exists. Communication via standard HTTP `/ask` interface.
- **Observable** — Every step writes to the Bus, Dashboard shows real-time status.

## 2. Core Concepts

### 2.1 Workflow

A YAML file defines a set of steps — "who does what and passes to whom."

```yaml
# Example: Sandbox Builder Pipeline
project:
  title: Sandbox Builder
  goal: Build a 3D sandbox game (single HTML)
steps:
  - executor: agent-2
    title: Scene Initialization
    description: Three.js scene + camera + lighting + render loop
    input_file: ""
    output_file: "step1-scene.html"
  - executor: agent-2
    title: Block Placement System
    description: Raycasting + grid snapping + 6 textures
    input_file: "step1-scene.html"
    output_file: "step2-blocks.html"
```

### 2.2 Main Bus (Shared Blackboard)

One `.jsonl` file per project, recording all events (`task.started` / `task.completed` / `task.failed` etc.).

```json
{
  "type": "task.completed",
  "agent": "agent-3",
  "stage": "step-6",
  "data": { "title": "Menu + End Screen", "output_preview": "..." },
  "ts": 1748187652
}
```

Features:
- **Append-only**, never overwrites
- **Smart routing**: auto-fallback on agent failure
- **Checkpoint**: resume after crash
- **Dependency wait**: step A automatically waits for step B

### 2.3 Agent Armors

Built-in agent port mapping (single source of truth):

| Agent | Port | Role |
|-------|------|------|
| agent-1 | 8420 | General purpose, default fallback |
| agent-2 | 8431 | Backend, database, engineering code |
| agent-3 | 8432 | Frontend UI, visual design, UX |
| agent-4 | 8434 | Data population, search, execution |
| agent-5 | 8435 | Testing, verification, documentation |
| agent-6 | 8436 | Code review, quality gate, code craft |

## 3. Architecture

### 3.1 Layered Architecture

```
┌───────────────────────────────────────────────┐
│              Caller / API Layer                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐     │
│  │ :8426    │  │  CLI     │  │  Web UI  │     │
│  └──────────┘  └──────────┘  └──────────┘     │
├───────────────────────────────────────────────┤
│              Glink Engine Layer                │
│  ┌─────────────────────────────────────────┐   │
│  │  Workflow Orchestrator                  │   │
│  │  - Step parsing + dependency management │   │
│  │  - Smart routing (planned → fallback)   │   │
│  │  - Retry loop (default 2x)             │   │
│  │  - Checkpoint resume                   │   │
│  └─────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────┐   │
│  │  Agent Communication (agent_client)     │   │
│  │  - AGENT_PORTS unified mapping          │   │
│  │  - HTTP POST /ask standard interface    │   │
│  │  - input_file injection + output dir.   │   │
│  └─────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────┐   │
│  │  Main Bus (Shared Timeline / Blackboard) │   │
│  │  - 8 event types                        │   │
│  │  - stage domain isolation               │   │
│  └─────────────────────────────────────────┘   │
├───────────────────────────────────────────────┤
│              Infrastructure Layer              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐     │
│  │ PIDGuard │  │ AutoRecov│  │ HTTP Srv │     │
│  │ pidfile  │  │ cron     │  │ :8426    │     │
│  └──────────┘  └──────────┘  └──────────┘     │
└───────────────────────────────────────────────┘
```

### 3.2 Execution Flow

When a workflow is triggered:

1. Glink reads `workflows/<project>.yaml`
2. Checks checkpoint for resume point
3. For each step:
   - Resolve dependencies (`depends_on`)
   - Read `input_file` content, inject into task context
   - Smart routing (planned → fallback agents)
   - Write `task.started` to Bus
   - HTTP call agent: `POST /ask {message, session}`
   - Wait for completion (long-poll, max 180s)
   - Write `task.completed` or `task.failed` to Bus
   - Save checkpoint.json
4. All steps done → write `project.update (completed)`

### 3.3 Smart Routing

When the primary agent is unavailable, Glink auto-falls back:

```yaml
steps:
  - executor: agent-3
    fallback_agents: ["agent-2", "agent-1"]
```

Routing process:
1. Check agent-3 port (8432) → down → try agent-2 (8431)
2. Down → try agent-1 (8420)
3. All fallbacks down → step fails

## 4. State Model

Each step at runtime:

| State | Meaning | Icon |
|-------|---------|------|
| `ok` | Completed | 🟢 |
| `running` | Executing | 🟡 |
| `wait` | Waiting for dependencies | ⚪ |
| `failed` | Failed | 🔴 |

Project states: `started` → `running` → `completed` / `failed`

## 5. API Reference

### HTTP API (port 8426)

#### Project Status
```
GET /status → { project, steps[], status }
```
Each step: `{ index, title, status, agent, stage }`.

#### Agent Online Status
```
GET /intel/agents → { agents: [{name, port, online}] }
```

#### Bus Events
```
GET /status/events?n=20 → [{type, agent, data, ts}]
```

#### Restart Workflow
```
POST /restart          # Resume from checkpoint
POST /restart?force    # Force restart from step 1
POST /restart?step=6   # Start from step 6
```

#### Health Check
```
GET /health → { status: "ok" }
```

### CLI

```bash
python3 glink-daemon.py <project>           # Auto-resume
python3 glink-daemon.py <project> --force   # Force restart
python3 glink-daemon.py <project> --step N  # Start from step N
python3 glink-daemon.py <project> --serve   # API server only
```

## 6. Main Bus

Main Bus is Glink's heartbeat — all agents share state through it. Not a database, not a message queue. Just an **append-only JSONL file**.

### Event Types

| Event | Meaning | Trigger |
|-------|---------|---------|
| `task.created` | Task created | Glink orchestrator |
| `task.assigned` | Assigned to an agent | Glink orchestrator |
| `task.started` | Agent started | Execution agent |
| `task.completed` | Done (with output preview) | Execution agent |
| `task.failed` | Failed | Execution agent |
| `task.log` | Log during execution | Execution agent |
| `project.update` | Project status change | Glink orchestrator |

### Quick Example

```python
# Write an event
write("myproject", "task.started", "agent-5", {"title": "Testing"})

# Read recent 20
events = read("myproject", limit=20)

# Get latest completed
ev = latest("myproject", "task.completed")

# Get project status
s = status("myproject")
```

## 7. Case Study: Sandbox Builder (v1.0 Completed)

**Project**: `sandbox-builder`
**Steps**: 10 steps × 5 agent types
**Output**: 97KB / 2751 lines HTML (double-click to run)

| Step | Agent | Feature | Duration |
|------|-------|---------|----------|
| 1 | agent-2 | Three.js scene + camera + lighting | ~5min |
| 2 | agent-2 | Raycasting block placement/deletion | ~5min |
| 3 | agent-2 | Canvas procedural texture generation | ~5min |
| 4 | agent-2 | Cannon-es physics sync | ~5min |
| 5 | agent-3 | Glassmorphism UI toolbar | ~8min |
| 6 | agent-3 | Start menu + end screen + ESC | ~12min |
| 7 | agent-4 | localStorage 3-slot save/load | ~6min |
| 8 | agent-4 | Scoring + 6 achievements | ~6min |
| 9 | agent-5 | Full black-box test | ~5min |
| 10 | agent-6 | Complete code review + quality report | ~6min |

**Result**: Three.js r160 + Cannon-es full-featured 3D sandbox with start menu, save/load, scoring, glassmorphism UI.

## 8. Infrastructure

### Auto-Recovery

```
     cron every 3 min healthcheck
              │
     ┌────────▼────────┐
     │ pidfile alive?   │
     └────────┬────────┘
          alive? ──► OK
          dead?  ──► read checkpoint
                     └── within 30s → restart from checkpoint
                     └── >30s → alert (configure GLINK_ALERT_WEBHOOK)
```

### Deep Error Recovery (P2)

**Detection:**
- Each step writes `checkpoint.json` (tmp + atomic rename, file lock)
- `find_resume_point()` reconstructs from Bus events
- Pure event-driven, no LLM state dependency

**Recovery chain:**
1. pidfile fast check (sub-second) → detect crash
2. healthcheck script every 3min → >30s downtime → alert
3. checkpoint resume (step-level)
4. Alert if `GLINK_ALERT_WEBHOOK` is configured

### Parallelism (Planned)

Current: strict sequential. Planned:

**Phase 1** — Independent step parallelism (v1.x):
```yaml
steps:
  - executor: agent-2
    title: Backend
    depends_on: []
    parallel_group: 1
  - executor: agent-3
    title: Frontend
    depends_on: []
    parallel_group: 1
```

**Phase 2** — Sub-workflow nesting (v1.3):
```yaml
steps:
  - executor: glink  # Special executor
    title: Sub-pipeline
    sub_workflow: backend-pipeline
```

## 9. Comparison

| Feature | Glink | Airflow | Temporal | n8n | LangGraph |
|---------|-------|---------|----------|-----|-----------|
| Deploy | Single file Python | DB + Web Server | gRPC Server | Node.js + Docker | Python |
| Agent Comms | HTTP /ask | Python callable | SDK | HTTP Node | Python callable |
| State | JSONL file | Database | Database | SQLite | Memory |
| Smart Routing | ✅ Built-in | ❌ | ❌ | ✅ | ❌ |
| Checkpoint | ✅ Built-in | ✅ | ✅ | ✅ | ❌ |
| Auto-Recovery | ✅ pidfile+cron | ✅ | ✅ | ❌ | ❌ |
| Input File Inject | ✅ Auto | ❌ | ❌ | ❌ | ❌ |
| Learning Curve | 5 minutes | 2 hours | 4 hours | 1 hour | 1 hour |
| Dependencies | None (stdlib only) | Postgres+Redis | gRPC+etcd | Node.js+Docker | Python |

Glink's unique value: **Minimal + AI agent native**. It's not a general orchestrator — it's built *for* AI agents.

## 10. Getting Started

### Setup

```bash
# Python 3.9+ required
# No pip install needed (stdlib only)
```

### Define a Workflow

```yaml
# workflows/hello-world.yaml
project:
  title: Hello World
  goal: First pipeline
steps:
  - executor: agent-1
    title: Step 1
    description: Write "Hello from Glink" to a file
  - executor: agent-1
    title: Step 2
    description: Read and print the file
    input_file: "step1-output.html"
```

### Run

```bash
python3 glink-daemon.py hello-world
```

## 11. Roadmap

| Version | Feature | Status |
|---------|---------|--------|
| v0.3 | Basic sequential orchestration + HTTP agent call | ✅ |
| v0.4 | Dashboard UI + smart routing + fallback_agents | ✅ |
| v0.5 | Auto-recovery (pidfile/cron) + absolute paths + independent HTTP | ✅ |
| v0.6 | Bug fixes (field mismatch, state semantics, concurrency lock) | ✅ |
| v0.7 | Extract shared code to agent_client | ✅ |
| v1.0 | Input_file injection + output path control (this whitepaper) | ✅ |
| v1.1 | Dashboard UI enhanced (real-time progress + commander view) | ✅ |
| v1.2 | Workflow queue (queue.json + sequential scheduling) | 🔜 |
| v1.3 | Conditional branching | 🔜 |
| v1.4 | Sub-workflow nesting | 🔜 |
| v1.5 | Parallel step execution | 🔜 |
| v1.6 | YAML config-driven + daemon/config.py | ✅ |
| v1.7 | Deep error recovery (atomic checkpoint + multi-level chain) | ✅ |
| v1.8 | Historical project replay | 🔜 |

---

> **Glink** — Making agents work together.

> Repository: `https://github.com/garyqlin/glink`
> Daemon port: 8426
