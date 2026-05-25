# SPDX-License-Identifier: MIT
"""
Main Bus — Shared project timeline

All agents read/write project-level shared memory through this module.

Storage: JSONL (one event per line)
Event types:
  - task.created:    Task created
  - task.assigned:   Task assigned to an agent
  - task.started:    Task execution started
  - task.completed:  Task completed
  - task.failed:     Task failed
  - task.log:        Execution log
  - project.update:  Project status update
"""

import fcntl
import json
import os
import sys

BUS_ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECTS_DIR = os.path.join(BUS_ROOT, "projects")

# Project name whitelist: only alphanumeric, underscore, hyphen (prevents path traversal)
_PROJECT_RE = __import__("re").compile(r"^[\w\-]+$")


def _sanitize(project_name: str) -> str:
    """Filter project name, prevent path traversal (only [\\w\\-] allowed)."""
    if not _PROJECT_RE.match(project_name):
        import re as _re

        return _re.sub(r"[^\w\-]", "", project_name).strip().lower() or "unnamed"
    return project_name.strip().lower()


def _bus_path(project_name: str) -> str:
    """Get bus file path for project."""
    safe = _sanitize(project_name)
    os.makedirs(PROJECTS_DIR, exist_ok=True)
    return os.path.join(PROJECTS_DIR, f"{safe}.jsonl")


def write(
    project_name: str, event_type: str, agent: str, data: dict, stage: str = ""
) -> bool:
    """Write an event to Main Bus (file-locked, concurrent-safe)."""
    import time as _time

    path = _bus_path(project_name)
    ev = {
        "type": event_type,
        "agent": agent,
        "data": data,
        "stage": stage,
        "ts": _time.time(),
        "iso": __import__("datetime").datetime.now().isoformat(),
    }
    try:
        with open(path, "a") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return True
    except Exception:
        # Write failure does not propagate — logged to stderr, won't crash the caller
        import traceback

        print(f"[MainBus] Write failed: {traceback.format_exc()}", file=sys.stderr)
        return False


def read(project_name: str, limit: int = 100) -> list[dict]:
    """Read recent events from Main Bus."""
    # BUG-02: Negative or zero n parameter validation (Forge 2026-05-25)
    if limit <= 0:
        return []
    path = _bus_path(project_name)
    if not os.path.exists(path):
        return []
    events = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return events[-limit:]


def latest(project_name: str, event_type: str | None = None) -> dict | None:
    """Get the latest event, optionally filtered by type."""
    events = read(project_name)
    if event_type:
        for ev in reversed(events):
            if ev["type"] == event_type:
                return ev
        return None
    return events[-1] if events else None


def status(project_name: str) -> dict:
    """Get current project status summary."""
    events = read(project_name, limit=500)
    total = len(events)
    stats = {"completed": 0, "failed": 0, "started": 0, "others": 0}
    agents = set()
    stages = set()
    for ev in events:
        et = ev.get("type", "")
        if et == "task.completed":
            stats["completed"] += 1
        elif et == "task.failed":
            stats["failed"] += 1
        elif et == "task.started":
            stats["started"] += 1
        else:
            stats["others"] += 1
        agents.add(ev.get("agent", ""))
        if ev.get("stage"):
            stages.add(ev.get("stage", ""))
    return {
        "project": project_name,
        "total_events": total,
        "tasks_completed": stats["completed"],
        "tasks_failed": stats["failed"],
        "tasks_started": stats["started"],
        "agents_involved": sorted(a for a in agents if a),
        "stages": sorted(s for s in stages if s),
    }


if __name__ == "__main__":
    # CLI entry
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if not cmd:
        print(f"Usage: python3 {sys.argv[0]} <command> [args...]")
        print("Commands: write, read, status, latest")
        sys.exit(0)

    proj = sys.argv[2] if len(sys.argv) > 2 else "hello-world"

    if cmd == "write":
        etype = sys.argv[3] if len(sys.argv) > 3 else "task.log"
        agent = sys.argv[4] if len(sys.argv) > 4 else "cli"
        data_str = sys.argv[5] if len(sys.argv) > 5 else '{"msg":"test"}'
        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            data = {"msg": data_str}
        write(proj, etype, agent, data)
        print(f"Written: {etype}/{agent} to {proj}")

    elif cmd == "read":
        limit = int(sys.argv[3]) if len(sys.argv) > 3 else 20
        evs = read(proj, limit)
        for ev in evs:
            print(json.dumps(ev, ensure_ascii=False)[:200])

    elif cmd == "status":
        s = status(proj)
        print(f"Project: {s['project']}")
        print(f"Total events: {s['total_events']}")
        print("Tasks: created/started/completed/failed")
        print(f"Agents: {', '.join(s['agents_involved'])}")
        print(f"Stages: {', '.join(s['stages'])}")

    elif cmd == "latest":
        ev = latest(proj)
        if ev:
            print(json.dumps(ev, ensure_ascii=False)[:300])
        else:
            print("No events")
