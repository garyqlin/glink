#!/usr/bin/env python3
"""
Main Bus — 共享项目时间线
所有 agent 通过此文件读写项目级共享记忆

存储格式：JSONL（每行一个事件）
事件类型：
  - task.created: 任务创建
  - task.assigned: 任务分派
  - task.started: 任务开始执行
  - task.completed: 任务完成
  - task.failed: 任务失败
  - task.log: 执行过程中的日志
  - project.update: 项目状态更新
"""

import json
import os
import sys
from datetime import datetime

BUS_DIR = os.path.dirname(os.path.abspath(__file__))


def bus_path(project_name):
    """获取项目总线文件路径"""
    projects_dir = os.path.join(BUS_DIR, "projects")
    os.makedirs(projects_dir, exist_ok=True)
    return os.path.join(projects_dir, f"{project_name}.jsonl")


def write(project_name, event_type, agent, data, stage=""):
    """写入一条事件到 Main Bus"""
    path = bus_path(project_name)
    entry = {
        "ts": datetime.now().isoformat(),
        "type": event_type,
        "agent": agent,
        "data": data,
        "stage": stage,
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def read(project_name, limit=20, since_type=None):
    """读取 Main Bus 最近的事件"""
    path = bus_path(project_name)
    if not os.path.exists(path):
        return []

    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if since_type is None or entry["type"] == since_type:
                    entries.append(entry)
            except json.JSONDecodeError:
                continue

    return entries[-limit:]


def latest(project_name, event_type=None, agent=None):
    """获取最新的一条事件"""
    entries = read(project_name, limit=100)
    for e in reversed(entries):
        if event_type and e["type"] != event_type:
            continue
        if agent and e["agent"] != agent:
            continue
        return e
    return None


def status(project_name):
    """获取项目当前状态总结"""
    entries = read(project_name, limit=1000)

    tasks = [e for e in entries if e["type"].startswith("task.")]
    completed = [t for t in tasks if t["type"] == "task.completed"]
    failed = [t for t in tasks if t["type"] == "task.failed"]
    started = [t for t in tasks if t["type"] == "task.started"]

    return {
        "project": project_name,
        "total_events": len(entries),
        "tasks_created": len([t for t in tasks if t["type"] == "task.created"]),
        "tasks_started": len(started),
        "tasks_completed": len(completed),
        "tasks_failed": len(failed),
        "agents_involved": list(set(e["agent"] for e in entries)),
        "stages": list(set(e.get("stage", "") for e in entries if e.get("stage"))),
    }


def cli():
    """命令行入口"""
    if len(sys.argv) < 2:
        print("用法: python3 main-bus.py <命令> [参数...]")
        print("命令: write, read, status, latest")
        sys.exit(1)

    cmd = sys.argv[1]
    project = os.environ.get("GLINK_PROJECT", "testglink")

    if cmd == "write":
        if len(sys.argv) < 5:
            print("用法: write <event_type> <agent> <data_json>")
            sys.exit(1)
        entry = write(project, sys.argv[2], sys.argv[3], json.loads(sys.argv[4]))
        print(json.dumps(entry, ensure_ascii=False))

    elif cmd == "read":
        entries = read(project, limit=int(sys.argv[2]) if len(sys.argv) > 2 else 20)
        for e in entries:
            print(
                f"[{e['ts'][:19]}] {e['type']:20s} | {e['agent']:10s} | {json.dumps(e['data'], ensure_ascii=False)[:80]}"
            )

    elif cmd == "status":
        s = status(project)
        print(f"项目: {s['project']}")
        print(f"总事件: {s['total_events']}")
        print(
            f"任务: 创建{s['tasks_created']} / 开始{s['tasks_started']} / 完成{s['tasks_completed']} / 失败{s['tasks_failed']}"
        )
        print(f"参与Agent: {', '.join(s['agents_involved'])}")
        print(f"阶段: {', '.join(s['stages'])}")

    elif cmd == "latest":
        entry = latest(
            project,
            event_type=sys.argv[2] if len(sys.argv) > 2 else None,
            agent=sys.argv[3] if len(sys.argv) > 3 else None,
        )
        if entry:
            print(json.dumps(entry, ensure_ascii=False))
        else:
            print("null")


if __name__ == "__main__":
    cli()
