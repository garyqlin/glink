#!/usr/bin/env python3
"""
Glink Daemon v0.3 — 断点续跑 + 失败重试

相比 v0.2 的改进：
1. 断点续跑：读取 Bus 事件，自动找到第一个未完成的 step，从断点继续
2. 失败重试：可选步骤失败不中断；必选步骤失败最多重试 2 次
3. 完成检测：通过 Bus 事件（task.completed / task.failed）确认步骤状态，不依赖单次 HTTP 调用结果
4. Checkpoint 持久化：当前执行位置写入 .checkpoint.json，重启后自动续跑

使用:
  python3 glink-daemon.py <项目名>          # 自动断点续跑
  python3 glink-daemon.py <项目名> --force  # 强制从 step-1 重新开始
  python3 glink-daemon.py <项目名> --step N # 从第 N 步开始
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

import yaml

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BUS_DIR = os.path.join(BASE_DIR, "bus")
WORKFLOWS_DIR = os.path.join(BASE_DIR, "workflows")

sys.path.insert(0, BUS_DIR)
import main_bus

# ── Agent 端口映射 ──────────────────────────────────────
AGENT_PORTS = {
    "标准版": 8420,
    "扎古": 8420,
    "重锤": 8431,
    "绘墨": 8432,
    "大黄蜂": 8434,
    "Laser": 8435,
}

MAX_RETRIES = 2  # 失败重试次数
POLL_INTERVAL = 3  # Bus 完成检测轮询间隔（秒）
POLL_MAX_WAIT = 180  # 单步最大等待时间（秒）
CHECKPOINT_FILE = ".checkpoint.json"


# ── 日志 ─────────────────────────────────────────────────
def log(msg, tag="  "):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}]{tag} {msg}")


def log_step(msg):
    log(msg, "━━ ")


def log_ok(msg):
    log(msg, " ✅")


def log_err(msg):
    log(msg, " ❌")


def log_warn(msg):
    log(msg, " ⚠️ ")


def log_retry(msg):
    log(msg, " ↻ ")


# ── 工作流加载 ───────────────────────────────────────────
def load_workflow(project_name):
    for path in [
        os.path.join(WORKFLOWS_DIR, f"{project_name}.yaml"),
        os.path.join(BUS_DIR, "projects", f"{project_name}.yaml"),
    ]:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                wf = yaml.safe_load(f)
            log(f"加载工作流: {path}")
            return wf
    log_err(f"找不到工作流: {project_name}")
    sys.exit(1)


# ── Checkpoint 持久化 ────────────────────────────────────
def load_checkpoint(project_name):
    """读取 checkpoint，返回 last_completed_step_index（0-based），-1 表示无记录"""
    path = os.path.join(BUS_DIR, "projects", f"{project_name}_{CHECKPOINT_FILE}")
    if os.path.exists(path):
        with open(path) as f:
            ck = json.load(f)
        return ck.get("last_completed_step_index", -1), ck
    return -1, None


def save_checkpoint(project_name, step_index, step_title, status="running"):
    path = os.path.join(BUS_DIR, "projects", f"{project_name}_{CHECKPOINT_FILE}")
    ck = {
        "project": project_name,
        "step_index": step_index,
        "title": step_title,
        "status": status,
        "ts": datetime.now().isoformat(),
    }
    with open(path, "w") as f:
        json.dump(ck, f, ensure_ascii=False, indent=2)
    return ck


def clear_checkpoint(project_name):
    path = os.path.join(BUS_DIR, "projects", f"{project_name}_{CHECKPOINT_FILE}")
    if os.path.exists(path):
        os.remove(path)


# ── 断点分析 ──────────────────────────────────────────────
def find_resume_point(project_name, steps, _force_start=False):
    """
    分析 Bus 事件，找到第一个需要执行的 step index。
    - force_start=True: 从 step-0 开始
    - 否则：扫描 Bus，标记 completed / failed 的 step，下一个未完成的即为断点
    返回: (start_index, skipped_reasons)
    """
    events = main_bus.read(project_name, limit=500)

    # 建立 stage → 状态 映射
    step_status = {}  # stage -> "completed" | "failed" | "started"
    for e in events:
        etype = e.get("type", "")
        stage = e.get("stage", "")
        if not stage:
            continue
        if etype == "task.completed":
            step_status[stage] = "completed"
        elif etype == "task.failed":
            # 不覆盖 completed
            step_status[stage] = "failed"
        elif etype == "task.started" and stage not in step_status:
            step_status[stage] = "started"

    # 按顺序找第一个未完成
    skipped = []
    for i, step in enumerate(steps):
        stage = step.get("stage", f"step-{i + 1}")
        status = step_status.get(stage, "pending")
        if status == "pending":
            if i == 0:
                return 0, []
            return i, skipped
        elif status in ("completed",):
            skipped.append((i + 1, step.get("title", stage), status))
        elif status == "failed":
            skipped.append((i + 1, step.get("title", stage), "failed-previous"))
            return i, skipped  # 从失败的 step 续跑

    # 所有 step 都完成了
    return len(steps), skipped


# ── Agent HTTP 调用 ─────────────────────────────────────
def call_agent(agent, task_desc, timeout=600):
    """HTTP 调用 agent，返回回复文本"""
    port = AGENT_PORTS.get(agent, 8420)
    url = f"http://127.0.0.1:{port}/ask"
    payload = json.dumps({"message": task_desc, "session": True}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode()
            try:
                return {"status": "ok", "output": json.loads(body).get("reply", body[:500])}
            except json.JSONDecodeError:
                return {"status": "ok", "output": body[:500]}
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200]
        return {"status": "failed", "error": f"HTTP {e.code}: {body}"}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


# ── 依赖等待 ─────────────────────────────────────────────
def wait_for_deps(project_name, depends_on, _stage, poll_interval=POLL_INTERVAL, max_wait=POLL_MAX_WAIT):
    """等待前置依赖的 task.completed 事件"""
    if not depends_on:
        return True

    start = time.time()
    dep_stages = [d if d.startswith("step-") else d for d in depends_on]

    while time.time() - start < max_wait:
        events = main_bus.read(project_name, limit=200)
        completed_stages = {e.get("stage") for e in events if e["type"] == "task.completed"}
        if all(ds in completed_stages for ds in dep_stages):
            log(f"  依赖满足: {dep_stages}")
            return True
        time.sleep(poll_interval)

    log_warn(f"依赖超时: {dep_stages}")
    return False


# ── 单步执行 ─────────────────────────────────────────────
def execute_step(project_name, step, step_index, total_steps, retries=MAX_RETRIES):
    """执行单个 step，含重试逻辑"""
    agent = step.get("executor", "标准版")
    title = step.get("title", f"Step {step_index + 1}")
    task = step.get("description") or step.get("task", "")
    stage = step.get("stage", f"step-{step_index + 1}")
    depends_on = step.get("depends_on", [])
    optional = step.get("optional", False)

    port = AGENT_PORTS.get(agent, 8420)

    log_step(f"╔══ [{step_index + 1}/{total_steps}] {title} → {agent}")

    # 更新 checkpoint（运行中）
    save_checkpoint(project_name, step_index, title, "running")

    # 写 Bus: 任务开始
    main_bus.write(
        project_name,
        "task.started",
        agent,
        {
            "title": title,
            "stage": stage,
            "step_index": step_index,
        },
        stage=stage,
    )

    # 等待依赖
    if depends_on:
        log(f"  ⏳ 等待依赖: {depends_on}")
        if not wait_for_deps(project_name, depends_on, stage):
            main_bus.write(
                project_name,
                "task.failed",
                "glink",
                {
                    "title": title,
                    "error": f"依赖超时: {depends_on}",
                    "stage": stage,
                },
                stage=stage,
            )
            return False

    # 重试循环
    last_error = None
    for attempt in range(retries + 1):
        if attempt > 0:
            log_retry(f"重试 {attempt}/{retries} → {title}")
            time.sleep(3)

        log(f"  📤 调用 {agent}(:{port}) [attempt-{attempt + 1}]")
        result = call_agent(agent, task)

        if result["status"] == "ok":
            # 写 Bus: 完成
            main_bus.write(
                project_name,
                "task.completed",
                agent,
                {
                    "title": title,
                    "output_preview": result["output"][:200],
                    "stage": stage,
                    "step_index": step_index,
                },
                stage=stage,
            )
            log_ok(f"完成 | {result['output'][:60]}…")
            return True
        else:
            last_error = result.get("error", "unknown")
            log_warn(f"  attempt-{attempt + 1} 失败: {last_error}")

    # 所有重试都失败
    if optional:
        main_bus.write(
            project_name,
            "task.completed",
            agent,
            {
                "title": title,
                "status": "skipped_optional",
                "error": last_error,
                "stage": stage,
            },
            stage=stage,
        )
        log_warn(f"可选步骤，最终失败（跳过）: {last_error}")
        return True  # 可选失败不中断

    # 必选步骤失败
    main_bus.write(
        project_name,
        "task.failed",
        agent,
        {
            "title": title,
            "error": last_error,
            "stage": stage,
            "step_index": step_index,
        },
        stage=stage,
    )
    log_err(f"必选步骤失败，流程中断: {last_error}")
    return False


# ── 主流程 ────────────────────────────────────────────────
def run_workflow(project_name, workflow, force_start=False, start_step=None):
    steps = workflow.get("steps", [])
    total_steps = len(steps)

    if total_steps == 0:
        log_err("工作流没有步骤")
        return

    # Bus: 项目启动事件（幂等）
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
                "total_steps": total_steps,
            },
        )

    # ── 断点分析 ──────────────────────────────────────────
    if start_step is not None:
        start_index = max(0, int(start_step) - 1)
        skipped = []
        log(f"强制从 step-{start_index + 1} 开始")
    elif force_start:
        start_index, skipped = 0, []
        clear_checkpoint(project_name)
        log("强制重跑，清除 checkpoint")
    else:
        start_index, skipped = find_resume_point(project_name, steps)
        if skipped:
            for num, t, s in skipped:
                tag = "✅" if s == "completed" else "⚠️"
                log(f"  {tag} Step-{num} 已完成/失败: {t[:50]}")

    if start_index >= total_steps:
        s = main_bus.status(project_name)
        log_ok(f"工作流已完成！Bus 统计: {s['tasks_completed']}/{total_steps} 步")
        clear_checkpoint(project_name)
        return

    log(f"断点续跑 → 从 Step-{start_index + 1} 开始（共 {total_steps} 步）")

    # ── 执行循环 ──────────────────────────────────────────
    success = True
    for i in range(start_index, total_steps):
        step = steps[i]
        ok = execute_step(project_name, step, i, total_steps)
        if not ok:
            save_checkpoint(project_name, i, step.get("title", f"step-{i + 1}"), "failed")
            success = False
            break
        time.sleep(1)

    # ── 完成 ──────────────────────────────────────────────
    if success:
        clear_checkpoint(project_name)
        main_bus.write(
            project_name,
            "project.update",
            "glink",
            {
                "action": "completed",
                "total_steps": total_steps,
            },
        )
        s = main_bus.status(project_name)
        log("")
        log("=" * 50)
        log_ok(f"[{project_name}] ✅ 全流程完成！{total_steps}/{total_steps} 步")
        log(f"  Bus: {s['total_events']} 事件 | Agent: {', '.join(s['agents_involved'])}")
        log("=" * 50)
    else:
        save_checkpoint(project_name, start_index, steps[start_index].get("title", ""), "interrupted")
        s = main_bus.status(project_name)
        log_err(f"流程中断于 Step-{start_index + 1}，checkpoint 已保存")

    return success


# ── CLI ─────────────────────────────────────────────────
def main():
    project = "testglink"
    force = False
    start_step = None

    for arg in sys.argv[1:]:
        if arg == "--force":
            force = True
        elif arg.startswith("--step="):
            start_step = arg.split("=", 1)[1]
        elif not arg.startswith("-"):
            project = arg

    log(f"🚀 Glink Daemon v0.3 | 项目: {project}")
    log(f"   工作流: {WORKFLOWS_DIR}/{project}.yaml")
    log(f"   Bus:    {BUS_DIR}/projects/{project}.jsonl")
    log(f"   重试:   {MAX_RETRIES}x | 轮询间隔: {POLL_INTERVAL}s")

    workflow = load_workflow(project)
    log(f"   加载: {workflow.get('project', {}).get('title', project)}")
    log(f"   步骤: {len(workflow.get('steps', []))} 步")

    run_workflow(project, workflow, force_start=force, start_step=start_step)


if __name__ == "__main__":
    main()
