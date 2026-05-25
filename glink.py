#!/usr/bin/env python3
"""
Glink v0.1 — Workflow orchestration engine (one-shot)

Reads workflow.yaml → calls agents in sequence → writes results to Main Bus.

For checkpoint-resume capability, use glink-daemon.py instead.
"""

import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, "bus"))  # noqa: E402

import main_bus
from agent_client import call_agent as _call_agent, load_workflow as _load_workflow


def execute_step(project_name, step, total_steps, step_index=0):
    """Execute one workflow step."""
    title = step.get("title", "Untitled")
    agent = step.get("executor", "agent-1")
    task = step.get("description", step.get("task", ""))
    stage = step.get("stage", f"step-{step_index + 1}")
    optional = step.get("optional", False)

    print(f"▶ Step: {title}")
    print(f"   Agent: {agent}")
    print(f"   Task: {task[:80]}...")

    # Write bus: started
    main_bus.write(
        project_name,
        "task.started",
        agent,
        {"title": title, "stage": stage},
        stage=stage,
    )

    # Call agent
    result = _call_agent(agent, task)
    if result["status"] == "ok":
        output = result["output"][:200]
        main_bus.write(
            project_name,
            "task.completed",
            agent,
            {"title": title, "output_preview": output, "stage": stage},
            stage=stage,
        )
        print(f"✅ {agent} done: {output[:100]}...")
        return True
    else:
        error = result.get("error", "unknown")
        if optional:
            main_bus.write(
                project_name,
                "task.completed",
                agent,
                {
                    "title": title,
                    "status": "skipped_optional",
                    "error": error,
                    "stage": stage,
                },
                stage=stage,
            )
            print(f"⚠ Optional step skipped: {error[:80]}")
            return True
        main_bus.write(
            project_name,
            "task.failed",
            agent,
            {"title": title, "error": error, "stage": stage},
            stage=stage,
        )
        print(f"❌ {agent} failed: {error[:80]}")
        return False


def run_workflow(project_name, workflow):
    """Run full workflow."""
    steps = workflow.get("steps", [])
    total = len(steps)
    print(f"# Glink started: {project_name}")

    # Write bus: project start
    main_bus.write(
        project_name,
        "project.update",
        "glink",
        {
            "action": "started",
            "title": workflow.get("project", {}).get("title", project_name),
            "total_steps": total,
        },
    )

    overall_ok = True
    for i, step in enumerate(steps):
        print(f"\n  [{i + 1}/{total}] {step.get('title', 'Untitled')}")
        ok = execute_step(project_name, step, total, step_index=i)
        time.sleep(1)
        if not ok:
            if step.get("optional", False):
                print("  ⚠ Optional step failed, continuing")
            else:
                print(f"\n❌ Pipeline interrupted at step {i + 1}")
                overall_ok = False
                break

    # Write bus: project complete
    main_bus.write(
        project_name,
        "project.update",
        "glink",
        {"action": "completed" if overall_ok else "interrupted", "total_steps": total},
    )

    print(f"\n# ✅ Project complete: {project_name}")

    s = main_bus.status(project_name)
    print("\n📊 Bus stats:")
    print(f"   Total events: {s['total_events']}")
    print(f"   Agents: {', '.join(s['agents_involved'])}")
    print(f"   Stages: {', '.join(s['stages'])}")

    return overall_ok


if __name__ == "__main__":
    project = sys.argv[1] if len(sys.argv) > 1 else "hello-world"
    wf = _load_workflow(project, base_dir=BASE_DIR)
    run_workflow(project, wf)
