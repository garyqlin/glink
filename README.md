# Glink

> **Multi-Agent Workflow Orchestration. One Bus. Zero Friction.**

Glink is a lightweight orchestration engine that turns your AI agents into a **collaborative assembly line**. Define a workflow in YAML, and Glink routes each step to the right agent — passing context, handling failures, and logging every heartbeat onto a shared event bus.

No database. No message queue. No external dependencies.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                     Glink Daemon                          │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐  │
│  │                    Main Bus                          │  │
│  │              Append-only JSONL Timeline              │  │
│  └──────┬──────────┬──────────┬──────────┬─────────────┘  │
│         │          │          │          │                │
│    ┌────▼───┐ ┌───▼────┐ ┌───▼────┐ ┌──▼──────┐         │
│    │Agent-1 │ │Agent-2 │ │Agent-3 │ │...      │         │
│    │:8420   │ │:8431   │ │:8432   │ │         │         │
│    └────────┘ └────────┘ └────────┘ └─────────┘         │
│         │          │          │          │                │
│         └──────────┴──────────┴──────────┘                │
│                    Your AI Fleet                          │
└──────────────────────────────────────────────────────────┘
```

---

## Quick Start

```bash
# Define your agents in main.py or daemon/core.py
# Default port mapping (customize freely):
#   agent-1 :8420 (generalist)
#   agent-2 :8431 (backend)
#   agent-3 :8432 (frontend/UI)
#   agent-4 :8434 (data)
#   agent-5 :8435 (testing)

# Run a workflow (auto-resumes from last checkpoint)
python3 glink-daemon.py my-workflow

# Force restart from step 1
python3 glink-daemon.py my-workflow --force

# Jump to a specific step
python3 glink-daemon.py my-workflow --step 4

# Serve-only mode (API daemon without running workflow)
python3 glink-daemon.py --serve

# Open dashboard
open http://127.0.0.1:8426/commander.html
```

---

## Features

| Feature | Description |
|:--------|:------------|
| **YAML Workflows** | Define steps, agents, dependencies, and fallbacks in one file |
| **Main Bus** | JSONL blackboard — append-only, agent-agnostic, replayable |
| **Smart Routing** | Primary agent down? Auto-fallback to the next in line |
| **Checkpoint Resume** | Crash mid-workflow? Restart picks up where it left off |
| **Dependency Graph** | Steps can `depends_on` each other; Glink handles ordering |
| **Retry Loop** | Auto-retry failed steps (configurable, default 2×) |
| **HTTP API + SSE** | Live status, agent health, and event stream on `:8426` |
| **Self-Healing** | Daemon auto-restarts on crash, PID-based watchdog |
| **Webhook Alerts** | Push notifications to any HTTP endpoint |
| **Zero External Deps** | Pure Python 3.10+, standard library. No pip install. |

---

## Define a Workflow

```yaml
name: my-pipeline
version: 1.0.0
description: "A simple 3-step demo"

global_context: |
  You are part of a multi-agent orchestration pipeline.
  Build upon the output of previous steps.

steps:
  - id: step-1
    executor: agent-1
    title: "Generate content"
    output_file: projects/demo/step1.txt
    task: |
      Create a summary of what makes a good multi-agent workflow.

  - id: step-2
    executor: agent-2
    title: "Enhance"
    input_file: projects/demo/step1.txt
    output_file: projects/demo/step2.md
    task: |
      Read and enhance the step-1 output. Add code examples.

  - id: step-3
    executor: agent-3
    title: "Verify"
    input_file: projects/demo/step2.md
    output_file: projects/demo/VERIFIED.md
    task: |
      Verify the enhanced document is complete.
      Append a verification seal if all checks pass.
```

---

## API Reference

All endpoints served on the configured port (`:8426` by default).

| Method | Endpoint | Description |
|:-------|:---------|:------------|
| `GET` | `/health` | Liveness check |
| `GET` | `/status` | Full project status + step-by-step progress |
| `GET` | `/status/agents` | Which agents are online |
| `GET` | `/status/events?n=20` | Last N bus events |
| `GET` | `/intel/step` | Detailed intelligence per step stage |
| `GET` | `/intel/agents` | Agent-specific metrics |
| `GET` | `/intel/timeline` | Step timeline visualization data |
| `GET` | `/events/stream` | SSE real-time event stream |
| `POST` | `/restart` | Resume from last checkpoint |
| `POST` | `/restart?force` | Force restart from step 1 |
| `POST` | `/restart?step=N` | Jump to specific step |

---

## Configuration

See `glink-config.yaml`:

```yaml
project:
  default: hello-world

scheduling:
  max_retries: 2
  poll_interval: 3
  poll_max_wait: 180
  max_concurrent_steps: 1

reporting:
  channels:
    - type: console
      label: "Glink"
    # - type: webhook
    #   url: "https://hooks.example.com/..."
    #   label: "Slack"

server:
  host: "127.0.0.1"
  port: 8426

security:
  startup_timeout: 10
```

Environment variables:
- `GLINK_DEFAULT_PROJECT` — override default project name
- `GLINK_PORT` — override API server port
- `GLINK_REPORTER` — set to `webhook`, `console`, or `silent`
- `GLINK_ALERT_WEBHOOK` — webhook URL for alerts

---

## Real-World Usage

Glink was used to orchestrate a **10-step game development pipeline** across 5 agents:

- Step 1-4: 3D scene, physics, textures, UI
- Step 5-6: Game systems (save/load, scoring)
- Step 7-8: Quality verification
- Result: Single playable HTML file, 97 KB / 2,751 lines

All built by agent collaboration — zero lines of human-written code.

---

## Project Structure

```
glink/
├── glink-daemon.py         # CLI entry point
├── glink-config.yaml        # Configuration
├── daemon/
│   ├── core.py              # Workflow orchestration engine
│   ├── api.py               # HTTP API server (17 endpoints)
│   ├── checks.py            # PID management & auto-recovery
│   ├── config.py            # Config loader
│   └── log.py               # Reporter initialization
├── bus/
│   ├── main_bus.py          # JSONL event bus
│   └── agent_client.py      # Agent HTTP client
├── reporter/
│   └── reporter.py          # Notification session (webhook/console)
├── dashboard/
│   ├── commander.html       # C2 dashboard (realtime)
│   └── index.html           # Legacy dashboard
├── workflows/               # Your YAML workflow definitions
└── projects/                # Step outputs by project
```

---

## License

MIT — free for any use, open or commercial.
