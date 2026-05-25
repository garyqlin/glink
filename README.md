# Glink — The Bus That Makes Your Agents Work Together

> *I built three things:*
> 1. ***GBase** — an AI agent framework with a soul, that self-evolves and gets real work done.*
> 2. ***Glink** — the technology that lets GBase, OpenClaw, Hermes, Claude Code, and any AI agent truly collaborate on projects.*
> 3. ***Opprime World** — a metaverse built for AI, where agents work, live, meet, and communicate.*
> &mdash; Gary Lin, 2026. Founder of the three.

---

**Zero-dependency workflow orchestration. Define a pipeline in YAML. Glink routes every step to the right agent, logs every heartbeat onto a shared bus, and recovers when things go wrong.**

<p align="center">
<a href="#quick-start"><img src="https://img.shields.io/badge/🚀-Quick_Start-8A2BE2" alt="Quick Start"></a>
<a href="#features"><img src="https://img.shields.io/badge/✨-Features-blue" alt="Features"></a>
<a href="#architecture"><img src="https://img.shields.io/badge/🏗-Architecture-green" alt="Architecture"></a>
<a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License: MIT"></a>
</p>

---

Most workflow engines force you to choose: lightweight but dumb, or powerful but a database, a queue, and a team to maintain it.

**Glink chose neither.**

One Python process. One JSONL file. One YAML pipeline definition. That's all it takes to coordinate multiple AI agents across a complex, multi-step workflow — with automatic recovery, real-time dashboards, and per-step failure handling.

This is not an orchestrator you configure. This is the bus your agents ride on.

---

## ✨ What Makes Glink Different

| | |
|---|---|
| 🚌 **Main Bus** | Append-only JSONL timeline. Every step, every agent output, every failure — logged, timestamped, replayable. No database, no message queue |
| 🔄 **Automatic Recovery** | PID-based watchdog + cron healthcheck. If the daemon stops, it restarts. If a step fails, it retries. You don't watch it — it watches itself |
| 🧩 **YAML Workflows** | Define your pipeline in a single YAML file. Each step specifies an agent, a task prompt, input/output files, and retry policy |
| 🧠 **Smart Routing** | Route each step to a specific agent by name or capability. Supports fallback agents if the primary is unavailable |
| 📊 **Commander Dashboard** | Real-time web dashboard — see agent status, step progress, event timeline. SSE pushes live updates. No refresh required |
| 🛡 **Self-Recovery** | `self_restart()` resumes from the last completed checkpoint step. Even crash recovery is intentional |
| 🎯 **Task Chaining** | Each step receives the output of the previous step as context. Build on what came before — don't start from scratch |
| 📬 **Rich Status API** | 17 REST endpoints: `/health`, `/status`, `/status/agents`, `/status/events`, `/intel/step`, `/intel/agents`, `/intel/timeline`, `/events/stream` (SSE), and more |
| 🧪 **Zero Dependencies** | Pure Python standard library. Nothing to install beyond Python 3.11+ |

---

## 🚀 Quick Start

```bash
# 1. Clone
git clone https://github.com/garyqlin/glink.git
cd glink

# 2. Run
python3 glink-daemon.py --serve

# 3. Submit a workflow
curl -X POST http://127.0.0.1:8426/run \
  -H "Content-Type: application/json" \
  -d '{"project": "hello-world"}'

# 4. Watch it live
curl http://127.0.0.1:8426/status
```

### Commander Dashboard

Open `http://127.0.0.1:8426/dashboard` in your browser — see all agents, all steps, all events in real time.

### One-Step Example

```yaml
# workflows/hello-world.yaml
steps:
  - title: "Say Hello"
    agent: standard
    task: "Respond with 'Hello, World!' and count to 3."
```

Then run:
```bash
python3 glink-daemon.py --serve --project hello-world
```

---

## 🏗 Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    Glink Daemon                           │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐  │
│  │                   Main Bus                           │  │
│  │             Append-only JSONL Timeline               │  │
│  └──────┬──────────┬──────────┬──────────┬─────────────┘  │
│         │          │          │          │                │
│         ▼          ▼          ▼          ▼                │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐        │
│  │Agent A  │ │Agent B  │ │Agent C  │ │ Forge   │        │
│  │(port N) │ │(port M) │ │(port P) │ │(port Q) │        │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘        │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐  │
│  │            Commander Dashboard (Web UI)              │  │
│  │     Real-time SSE push + per-agent status cards      │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐  │
│  │          Auto-Recovery (PID + watchdog cron)         │  │
│  └─────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

### Project Structure

```
glink/
├── glink-daemon.py        # Entry point
├── glink.py               # CLI runner
├── glink-config.yaml      # Server & agent configuration
├── daemon/
│   ├── __init__.py        # Public API
│   ├── core.py            # Workflow engine
│   ├── api.py             # REST API (17 endpoints + SSE)
│   ├── checks.py          # Healthcheck & self-recovery
│   ├── config.py          # Config loader
│   └── log.py             # Reporter integration
├── bus/
│   ├── main_bus.py        # Event bus (append-only JSONL)
│   └── agent_client.py    # Agent HTTP client
├── reporter/
│   └── reporter.py        # Multi-channel reporting (webhook/console)
├── dashboard/
│   ├── commander.html     # Real-time commander interface
│   └── index.html         # Step-by-step workflow viewer
├── workflows/             # YAML pipeline definitions
├── bin/                   # Launch & healthcheck scripts
└── docs/
    └── GLINK_WHITEPAPER.md
```

---

## 🛠 Configuration

### `glink-config.yaml`

```yaml
server:
  port: 8426
  retries: 2
  sse:
    heartbeat_interval: 60
    poll_interval: 2

project:
  default: hello-world

reporting:
  channels: []
```

### Agent Ports

| Agent | Default Port | Purpose |
|-------|-------------|---------|
| `standard` | 8420 | General-purpose agent |
| `hammer` | 8431 | Heavy engineering |
| `ink` | 8432 | Frontend & design |
| `bumblebee` | 8434 | Research & analysis |
| `laser` | 8435 | QA & documentation |
| `forge` | 8436 | Code art & review |

Add your own agents by extending `AGENT_PORTS` in `bus/agent_client.py` — no limit.

---

## 📡 API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/status` | GET | Full workflow & agent status |
| `/status/agents` | GET | Per-agent online/offline |
| `/status/events` | GET | Recent event timeline |
| `/intel/step` | GET | Step-level intelligence (duration, agent, status) |
| `/intel/agents` | GET | Per-agent intelligence |
| `/intel/timeline` | GET | Timeline with timestamps |
| `/events/stream` | GET | SSE real-time push |
| `/run` | POST | Start/restart a workflow |
| `/restart` | POST | Restart daemon self |
| `/reset` | POST | Clear project bus events |

---

## ❌ What Glink Is Not

- ❌ **Not a task queue.** Glink doesn't store pending tasks. It runs a pipeline and exits — every step is a live agent call.
- ❌ **Not a database.** The Main Bus is a log, not a query store. Use it for audit and recovery, not for ad-hoc analysis.
- ❌ **Not a replacement for Airflow/Kubeflow.** Glink is for agent orchestration, not data pipeline orchestration. If you're moving terabytes, look elsewhere.
- ❌ **Not tied to any framework.** Your agents can be anything — OpenClaw, Hermes, GBase, Claude Code, a shell script. If it speaks HTTP, Glink drives it.

## ✅ What Glink Is

**The simplest way to make multiple AI agents collaborate on a complex task.**

One daemon. One bus. One YAML file. Your agents talk to each other through the bus, and you watch it all happen on a real-time dashboard.

---

## 🔗 Related Projects

<table>
<tr>
<td><strong>GBase</strong></td>
<td>Recursive self-improvement agent framework. Give GBase agents a Glink pipeline and they orchestrate themselves.</td>
</tr>
<tr>
<td><strong>Opprime World</strong></td>
<td>The first metaverse where AI agents are natives. Glink workflows run across agents in Opprime World.</td>
</tr>
</table>

---

## 📄 License

MIT — free to use, modify, and distribute. No strings attached.

---

<p align="center">
<a href="https://github.com/garyqlin">@garyqlin</a> · <a href="https://github.com/garyqlin/glink">📦 Glink</a> · <a href="https://github.com/garyqlin/gbase">🧠 GBase</a>
</p>
