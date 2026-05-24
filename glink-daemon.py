#!/usr/bin/env python3
"""
Glink Daemon v0.5 — 监控 Dashboard + 智能路由 + 自动恢复
兼容入口，实现在 daemon/ 模块中。
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

WORKFLOWS_DIR = os.path.join(BASE_DIR, "workflows")
_BOOT_TIMESTAMP = os.path.join(BASE_DIR, ".glink-boot.ts")

_REST_PROJECT = {"name": "testglink"}


def run_daemon(project, force=False, start_step=None):
    from daemon import C_OK, C_WARN

    ensure_pid()
    log(f"🚀 Glink Daemon v0.5 | 项目: {project}")
    start_api_server()
    log(f"   工作流: {WORKFLOWS_DIR}/{project}.yaml")
    log(f"   Bus:    {BASE_DIR}/bus/projects/{project}.jsonl")
    log("   重试:   2x | 轮询间隔: 3s")

    workflow = load_workflow(project)
    wf_title = workflow.get("project", {}).get("title", project)
    step_count = len(workflow.get("steps", []))
    log(f"   加载: {wf_title}")
    log(f"   步骤: {step_count} 步")

    get_reporter().push(
        f"🚀 **Glink 工作流启动**\n   项目：{project}\n   步骤：{step_count} 步\n   模式：{'重跑' if force else '断点续跑'}"
    )

    success = run_workflow(project, workflow, force_start=force, start_step=start_step)

    if success:
        get_reporter().alert("✅ Glink 工作流完成", f"项目 **{project}** 的全部 {step_count} 步已完成。", severity=C_OK)
    else:
        get_reporter().alert(
            "⚠️ Glink 工作流中断", f"项目 **{project}** 未完成，可通过 /restart 重启。", severity=C_WARN
        )

    log("")
    if success:
        log_ok("工作流完成，API 持续运行中...")
    else:
        log_warn("工作流中断，API 持续运行中（可通过 /restart 重启）...")
    log("  📡 Dashboard: http://127.0.0.1:8426")
    log("  停止: kill $(lsof -ti :8426)")

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        cleanup_pidfile()
        log("Glink Daemon 已停止")
        sys.exit(0)


def main():
    project = "testglink"
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
                log_err(f"--step 参数必须是整数，收到: {raw!r}")
                sys.exit(2)
        elif not arg.startswith("-"):
            project = arg

    _REST_PROJECT["name"] = project

    if serve_only:
        log("🔄 Glink Daemon v0.5 (serve-only) | API 端口 8426")
        ensure_pid()
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
