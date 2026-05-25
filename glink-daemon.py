#!/usr/bin/env python3
"""
Glink Daemon v0.5 — Monitoring Dashboard + Smart Routing + Auto-Recovery
Compatibility entry point — implementation resides in daemon/ module.
"""

import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "bus"))

from daemon import (
    cleanup_pidfile,
    ensure_pid,
    get_reporter,
    load_workflow,
    log,
    log_err,
    log_ok,
    log_warn,
    run_workflow,
    start_api_server,
)
from daemon.config import get_default_project

WORKFLOWS_DIR = os.path.join(BASE_DIR, "workflows")
_BOOT_TIMESTAMP = os.path.join(BASE_DIR, ".glink-boot.ts")

_REST_PROJECT = {"name": get_default_project()}


def run_daemon(project, force=False, start_step=None):
    from daemon import C_OK, C_WARN

    ensure_pid()
    log(f"🚀 Glink Daemon v0.5 | Project: {project}")
    start_api_server()
    log(f"   Workflow: {WORKFLOWS_DIR}/{project}.yaml")
    log(f"   Bus:      {BASE_DIR}/bus/projects/{project}.jsonl")
    log("   Retries:  2x | Poll: 3s")

    workflow = load_workflow(project)
    wf_title = workflow.get("project", {}).get("title", project)
    step_count = len(workflow.get("steps", []))
    log(f"   Loaded: {wf_title}")
    log(f"   Steps:  {step_count}")

    mode = "force" if force else "resume"
    get_reporter().push(
        f"🚀 **Glink Workflow Started**\n   Project: {project}\n   Steps: {step_count}\n   Mode: {mode}"
    )

    success = run_workflow(project, workflow, force_start=force, start_step=start_step)

    if success:
        get_reporter().alert(
            "✅ Glink Workflow Complete",
            f"Project **{project}**: all {step_count} steps done.",
            severity=C_OK,
        )
    else:
        get_reporter().alert(
            "⚠️ Glink Workflow Interrupted",
            f"Project **{project}** incomplete — resume via /restart.",
            severity=C_WARN,
        )

    log("")
    if success:
        log_ok("Workflow complete, API server running...")
    else:
        log_warn("Workflow interrupted, API server running (resume via /restart)...")
    log("  📡 Dashboard: http://127.0.0.1:8426")
    log("  Stop: kill $(lsof -ti :8426)")

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        cleanup_pidfile()
        log("Glink Daemon stopped")
        sys.exit(0)


DEFAULT_PROJECT = get_default_project()


def main():
    project = DEFAULT_PROJECT
    force = False
    start_step = None
    serve_only = False

    for arg in sys.argv[1:]:
        if arg == "--force":
            force = True
        elif arg == "--serve":
            serve_only = True
        elif arg.startswith("--step="):
            raw = arg.split("=", 1)[1]
            try:
                start_step = int(raw)
            except ValueError:
                log_err(f"--step must be an integer, got: {raw!r}")
                sys.exit(2)
        elif not arg.startswith("-"):
            project = arg

    _REST_PROJECT["name"] = project
    try:
        from daemon.api import set_project as _set_api_project

        _set_api_project(project)
    except ImportError:
        pass

    if serve_only:
        ensure_pid()
        log("🔄 Glink Daemon v0.5 (serve-only) | API port 8426")
        start_api_server()
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            cleanup_pidfile()
            sys.exit(0)
    else:
        run_daemon(project, force=force, start_step=start_step)


if __name__ == "__main__":
    main()
