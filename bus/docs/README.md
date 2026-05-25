# Main Bus — Shared Project Timeline

> All agents read/write project-level shared memory through this module.

## Overview

Main Bus is the core communication layer for **Glink** multi-agent orchestration.
It's a **JSONL file system** — one `.jsonl` file per project, recording all events.
Append-only, never overwritten.

## Event Types

| Type | Meaning | Triggered By |
|------|---------|-------------|
| `task.created` | Task created | Glink orchestrator |
| `task.assigned` | Task assigned | Glink orchestrator |
| `task.started` | Task execution started | Execution agent |
| `task.completed` | Task completed successfully | Execution agent |
| `task.failed` | Task failed | Execution agent |
| `task.log` | Execution log entry | Execution agent |
| `project.update` | Project status changed | Glink orchestrator |

## API Reference

### Python API

```python
import main_bus

# Write an event
main_bus.write("myproject", "task.started", "agent-5", {"title": "Testing"})

# Read recent 20 events
events = main_bus.read("myproject", limit=20)

# Get latest event
ev = main_bus.latest("myproject", "task.completed")

# Get project status
s = main_bus.status("myproject")
print(s["tasks_completed"], "/", s["total_events"])
```

### CLI

```bash
# Write
GLINK_PROJECT=hello-world python3 main_bus.py write task.started agent-5 '{"title":"Testing"}'

# Read (last 20)
GLINK_PROJECT=hello-world python3 main_bus.py read 20

# Status
GLINK_PROJECT=hello-world python3 main_bus.py status
```

## Data Storage

- Project files: `projects/{project_name}.jsonl`
- Format: One JSON object per line
- Event structure: `{ts, type, agent, data, stage}`

## Concurrency Safety

- File-locked writes via `fcntl.flock` (exclusive lock)
- `n` parameter validated (positive integer, max 1000)
- Empty project event lists return `[]` gracefully
