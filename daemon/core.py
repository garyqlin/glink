# SPDX-License-Identifier: MIT
"""Glink Daemon — Workflow orchestration core: run, checkpoint, step execution"""

import fcntl
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

from .checks import BUS_DIR, CHECKPOINT_FILE
from .log import (
    get_reporter,
    log,
    log_err,
    log_ok,
    log_retry,
    log_step,
    log_warn,
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, "bus"))

import main_bus
from agent_client import AGENT_PORTS
from agent_client import _sanitize_project_name as _sanitize
from agent_client import call_agent as _call_agent
from agent_client import load_workflow as _load_workflow

from .config import get_max_retries, get_poll_interval, get_poll_max_wait

MAX_RETRIES = get_max_retries()
POLL_INTERVAL = get_poll_interval()
POLL_MAX_WAIT = get_poll_max_wait()


def load_workflow(project_name: str):
    safe = _sanitize(project_name)
    wf = _load_workflow(project_name, base_dir=BASE_DIR)
    log(f"Loading workflow: {safe}")
    return wf


def load_checkpoint(project_name: str):
    safe = _sanitize(project_name)
    path = os.path.join(BUS_DIR, "projects", f"{safe}_{CHECKPOINT_FILE}")
    if os.path.exists(path):
        with open(path) as f:
            ck = json.load(f)
        return ck.get("step_index", -1), ck
    return -1, None


def save_checkpoint(
    project_name: str,
    step_index: int,
    title: str,
    status: str = "running",
):
    safe = _sanitize(project_name)
    path = os.path.join(BUS_DIR, "projects", f"{safe}_{CHECKPOINT_FILE}")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    ck = {
        "project": project_name,
        "step_index": step_index,
        "title": title,
        "status": status,
        "ts": datetime.now().isoformat(),
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        json.dump(ck, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    return ck


def clear_checkpoint(project_name: str) -> None:
    safe = _sanitize(project_name)
    path = os.path.join(BUS_DIR, "projects", f"{safe}_{CHECKPOINT_FILE}")
    if os.path.exists(path):
        os.remove(path)


def find_resume_point(project_name, steps, force_start=False):
    if force_start:
        clear_checkpoint(project_name)
        return 0, []

    events = main_bus.read(project_name, limit=500)
    step_status = {}
    for e in events:
        etype = e.get("type", "")
        stage = e.get("stage", "")
        if not stage:
            continue
        if etype == "task.completed":
            step_status[stage] = "completed"
        elif etype == "task.failed" and step_status.get(stage) != "completed":
            step_status[stage] = "failed"
        elif etype == "task.started" and stage not in step_status:
            step_status[stage] = "started"

    skipped = []
    for i, step in enumerate(steps):
        stage = step.get("stage", f"step-{i + 1}")
        s = step_status.get(stage, "pending")
        if s == "pending":
            return i, skipped
        elif s in ("completed",):
            skipped.append((i + 1, step.get("title", stage), s))
        elif s == "failed":
            skipped.append((i + 1, step.get("title", stage), "failed-previous"))
            return i, skipped

    return len(steps), skipped


def probe_agent(agent):
    port = AGENT_PORTS.get(agent, 8420)
    url = f"http://127.0.0.1:{port}/health"
    try:
        req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3):
            return True, port
    except Exception:
        return False, port


def resolve_agent(agent, fallback_agents=None):
    online, port = probe_agent(agent)
    if online:
        return agent, port, None
    fallbacks = fallback_agents or []
    for fb in fallbacks:
        fb_online, fb_port = probe_agent(fb)
        if fb_online:
            log_warn(f"Primary agent [{agent}] offline, switching to fallback [{fb}]")
            return fb, fb_port, agent
    return agent, port, None


def call_agent(agent, task_desc, timeout=600):
    return _call_agent(agent, task_desc, timeout=timeout)


def wait_for_deps(
    project_name,
    depends_on,
    poll_interval=POLL_INTERVAL,
    max_wait=POLL_MAX_WAIT,
):
    if not depends_on:
        return True
    start = time.time()
    dep_stages = [d if d.startswith("step-") else d for d in depends_on]
    while time.time() - start < max_wait:
        events = main_bus.read(project_name, limit=200)
        completed = {e.get("stage") for e in events if e["type"] == "task.completed"}
        if all(ds in completed for ds in dep_stages):
            log(f"  Dependencies satisfied: {dep_stages}")
            return True
        time.sleep(poll_interval)
    log_warn(f"Dependency timeout: {dep_stages}")
    return False


def execute_step(
    project_name,
    step,
    step_index,
    total_steps,
    retries=MAX_RETRIES,
):
    planned_agent = step.get("executor", "agent-1")
    fallback_agents = step.get("fallback_agents", [])
    title = step.get("title", f"Step {step_index + 1}")
    task = step.get("description") or step.get("task", "")
    stage = step.get("stage", f"step-{step_index + 1}")
    depends_on = step.get("depends_on", [])
    optional = step.get("optional", False)

    actual_agent, port, fallback_from = resolve_agent(planned_agent, fallback_agents)
    log_step(
        f"╔══ [{step_index + 1}/{total_steps}] {title} → {actual_agent}"
        + (f" (fallback from {fallback_from})" if fallback_from else "")
    )

    save_checkpoint(project_name, step_index, title, "running")
    main_bus.write(
        project_name,
        "task.started",
        actual_agent,
        {
            "title": title,
            "stage": stage,
            "step_index": step_index,
            "planned_agent": planned_agent,
            "fallback_from": fallback_from,
        },
        stage=stage,
    )

    if depends_on:
        log(f"  ⏳ Waiting for dependencies: {depends_on}")
        if not wait_for_deps(project_name, depends_on):
            main_bus.write(
                project_name,
                "task.failed",
                "glink",
                {"title": title, "error": f"Dependency timeout: {depends_on}", "stage": stage},
                stage=stage,
            )
            return False

    enriched_task = task
    input_file_path = step.get("input_file", "")
    output_file_path = step.get("output_file", "")
    if input_file_path:
        resolved_input = os.path.join(BASE_DIR, "projects", input_file_path)
        if os.path.isfile(resolved_input):
            try:
                with open(resolved_input) as f:
                    prev_content = f.read()
                input_summary = (
                    f"[Input file] {resolved_input}\n"
                    f"Size: {len(prev_content)} chars\n"
                    f"Content:\n```html\n{prev_content}\n```\n"
                )
                resolved_output = os.path.join(BASE_DIR, "projects", output_file_path) if output_file_path else ""
                output_hint = (
                    (
                        "\n🔴🔴🔴 MANDATORY INSTRUCTIONS 🔴🔴🔴\n"
                        "1. The task below describes the INCREMENTAL change for THIS step.\n"
                        "2. **Must** fully read the input_file content below.\n"
                        "3. Build UPON the input_file — add/modify code sections within it.\n"
                        "4. **Output the COMPLETE file** (not just new code snippets).\n"
                        "5. Write the complete file to the specified output path:\n"
                        f"   {resolved_output}\n"
                        "6. **Do NOT create standalone demo/test files** — merge all code into one file.\n"
                    )
                    if output_file_path
                    else ""
                )
                enriched_task = (
                    f"## {title}\n\n### Incremental change for this step\n{task}\n\n{output_hint}"
                    "### Input file (must read in full before modifying)\n"
                    "This is the current complete source. Add your changes on top of it.\n"
                    "Keep all existing functionality. Output the complete file with all code.\n\n"
                    f"{input_summary}"
                )
                log(f"  Read input_file: {resolved_input} ({len(prev_content)} chars)")
            except Exception as exc:
                log_warn(f"  Could not read input_file {resolved_input}: {exc}")
        else:
            log_warn(f"  input_file not found: {resolved_input}")

    ctx_events = main_bus.read(project_name, limit=30)
    prev_completed = [ev for ev in ctx_events if ev["type"] == "task.completed" and ev.get("stage", "") != stage]
    if prev_completed:
        ctx_lines = ["\n### Previously completed steps"]
        for ev in prev_completed[-5:]:
            s = ev.get("stage", "?")
            t = ev.get("data", {}).get("title", "?")
            o = ev.get("data", {}).get("output_preview", "")[:150]
            ctx_lines.append(f"- **{t}** ({s}): {o}")
        enriched_task += "\n" + "\n".join(ctx_lines)

    last_error = None
    for attempt in range(retries + 1):
        if attempt > 0:
            log_retry(f"Retry {attempt}/{retries} → {title}")
            time.sleep(3)
        log(f"  📤 Calling {actual_agent}(:{port}) [attempt-{attempt + 1}]")
        log(f"  Task length: {len(enriched_task)} chars")
        result = call_agent(actual_agent, enriched_task)

        if result["status"] == "ok":
            main_bus.write(
                project_name,
                "task.completed",
                actual_agent,
                {
                    "title": title,
                    "output_preview": result["output"][:200],
                    "stage": stage,
                    "step_index": step_index,
                    "planned_agent": planned_agent,
                    "fallback_from": fallback_from,
                },
                stage=stage,
            )
            output_preview = result["output"][:200]
            log_ok(f"Done | {output_preview}…")
            dur_sec = result.get("duration", 0)
            dur_str = (
                f"{int(dur_sec // 60)}m{int(dur_sec % 60)}s" if isinstance(dur_sec, (int, float)) else str(dur_sec)
            )
            get_reporter().summary(
                project=project_name,
                step_index=step_index + 1,
                total=total_steps,
                status=actual_agent,
                agent=actual_agent,
                duration=dur_str,
                detail=output_preview[:100],
            )
            return True
        else:
            last_error = result.get("error", "unknown")
            log_warn(f"  attempt-{attempt + 1} failed: {last_error}")

    if optional:
        main_bus.write(
            project_name,
            "task.completed",
            actual_agent,
            {
                "title": title,
                "status": "skipped_optional",
                "error": last_error,
                "stage": stage,
            },
            stage=stage,
        )
        msg = f"Optional step {title} failed (skipping): {last_error[:80]}"
        log_warn(msg)
        get_reporter().alert(f"⏭ Skipped optional step: {title}", msg, severity="yellow")
        return True

    main_bus.write(
        project_name,
        "task.failed",
        actual_agent,
        {
            "title": title,
            "error": last_error,
            "stage": stage,
            "step_index": step_index,
            "planned_agent": planned_agent,
            "fallback_from": fallback_from,
        },
        stage=stage,
    )
    msg = f"Required step {title} failed, pipeline interrupted: {last_error[:120]}"
    log_err(msg)
    get_reporter().alert(f"❌ Step failed: {title}", msg, severity="red")
    return False


def run_workflow(project_name, workflow, force_start=False, start_step=None):
    steps = workflow.get("steps", [])
    total = len(steps)
    if total == 0:
        log_err("Workflow has no steps")
        return

    events = main_bus.read(project_name, limit=5)
    if not any(e["type"] == "project.update" for e in events):
        main_bus.write(
            project_name,
            "project.update",
            "glink",
            {
                "action": "started",
                "title": workflow.get("project", {}).get("title", project_name),
                "goal": workflow.get("project", {}).get("goal", ""),
                "total_steps": total,
            },
        )

    if start_step is not None:
        start_index = max(0, int(start_step) - 1)
        skipped = []
        log(f"Forcing from step-{start_index + 1}")
    elif force_start:
        start_index, skipped = 0, []
        clear_checkpoint(project_name)
        log("Force restart, clearing checkpoint")
    else:
        start_index, skipped = find_resume_point(project_name, steps)
        for num, t, s in skipped:
            tag = "✅" if s == "completed" else "⚠️"
            log(f"  {tag} Step-{num} {s}: {t[:50]}")

    if start_index >= total:
        s = main_bus.status(project_name)
        log_ok(f"Workflow complete! Bus: {s['tasks_completed']}/{total} steps")
        clear_checkpoint(project_name)
        return True

    log(f"Resume → Step-{start_index + 1} of {total}")

    success = True
    for i in range(start_index, total):
        step = steps[i]
        ok = execute_step(project_name, step, i, total)
        if not ok:
            save_checkpoint(project_name, i, step.get("title", f"step-{i + 1}"), "failed")
            success = False
            break
        time.sleep(1)

    if success:
        clear_checkpoint(project_name)
        main_bus.write(
            project_name,
            "project.update",
            "glink",
            {"action": "completed", "total_steps": total},
        )
        s = main_bus.status(project_name)
        log("")
        log("=" * 50)
        log_ok(f"[{project_name}] ✅ Pipeline complete! {total}/{total} steps")
        log(f"  Bus: {s['total_events']} events | Agents: {', '.join(s['agents_involved'])}")
        log("=" * 50)
    else:
        save_checkpoint(
            project_name,
            start_index,
            steps[start_index].get("title", ""),
            "interrupted",
        )
        s = main_bus.status(project_name)
        log_err(f"Pipeline interrupted at Step-{start_index + 1}, checkpoint saved")

    return success
