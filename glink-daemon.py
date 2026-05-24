#!/usr/bin/env python3
"""
Glink Daemon v0.5 — 监控 Dashboard + 智能路由 + 自动恢复

相比 v0.4 的改进：
1. 自动恢复：Daemon 意外停止后 30 秒内自动重启（pidfile + cron 自检）
2. 绝对路径：所有路径使用 BASE_DIR 推导，不依赖 cwd
3. HTTP server 独立进程：主进程退出后 API 仍存活
4. 新增 /restart 端点：通过 API 一键重启工作流

使用:
  python3 glink-daemon.py <项目名>          # 自动断点续跑
  python3 glink-daemon.py <项目名> --force  # 强制从 step-1 重新开始
  python3 glink-daemon.py <项目名> --step N # 从第 N 步开始
  python3 glink-daemon.py <项目名> --serve  # 只启动 API server，不跑工作流
  # REST API（端口 8426）
  GET  /status             # 项目概览 + Step 状态
  GET  /status/agents      # Agent 在线状态
  GET  /status/events?n=20 # 最新 n 条 Bus 事件
  POST /restart            # 重启当前项目工作流
  POST /restart?force=true # 强制重跑
"""

import json
import os
import socketserver
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import yaml

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BUS_DIR = os.path.join(BASE_DIR, "bus")
WORKFLOWS_DIR = os.path.join(BASE_DIR, "workflows")
PIDFILE = os.path.join(BASE_DIR, ".glink-daemon.pid")
BOOT_TIMESTAMP = os.path.join(BASE_DIR, ".glink-boot.ts")
DAEMON_SCRIPT = os.path.abspath(__file__)

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

# ── 自动恢复 ──────────────────────────────────────


def write_pidfile():
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))
    with open(BOOT_TIMESTAMP, "w") as f:
        f.write(datetime.now().isoformat())


def is_alive():
    """检查守护进程是否存活（通过 pidfile）"""
    if not os.path.exists(PIDFILE):
        return False
    with open(PIDFILE) as f:
        pid = f.read().strip()
    if not pid.isdigit():
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def ensure_pid():
    """启动时确保唯一实例；若旧进程已死则接管"""
    if os.path.exists(PIDFILE):
        if is_alive():
            log_warn(f"已有实例运行 (pid={open(PIDFILE).read().strip()})，退出")
            sys.exit(0)
        else:
            log("pidfile 存留但进程已死，接管")
    write_pidfile()


def cleanup_pidfile():
    if os.path.exists(PIDFILE):
        os.remove(PIDFILE)
    if os.path.exists(BOOT_TIMESTAMP):
        os.remove(BOOT_TIMESTAMP)


def self_restart(project, force=False):
    """启动自身的新进程，取代当前进程"""
    log_warn("⚠ 自动恢复：准备重启自身...")
    send_alert(
        "Daemon 自动恢复",
        f"**项目**: {project}\n**force**: {force}\n**pid**: {os.getpid()}\n**脚本**: {DAEMON_SCRIPT}",
    )
    cmd = [sys.executable, DAEMON_SCRIPT]
    if force:
        cmd.append("--force")
    if project:
        cmd.append(project)
    log(f"   重启命令: {' '.join(cmd)}")
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    log_ok("已启动新进程，当前进程即将退出")
    cleanup_pidfile()
    sys.exit(0)


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


# ── Agent 探测（智能路由用）────────────────────────────
def probe_agent(agent):
    """探测 agent 是否在线，返回 (bool, port)"""
    port = AGENT_PORTS.get(agent, 8420)
    url = f"http://127.0.0.1:{port}/health"
    try:
        req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as _:
            return True, port
    except Exception:
        return False, port


def resolve_agent(agent, fallback_agents=None):
    """
    智能路由：返回 (实际使用的agent名, port, fallback_from/None)
    1. 探测主 agent
    2. 不在线则遍历 fallback_agents
    3. 都找不到返回 (agent, port, None) 由调用方决定等待
    """
    online, port = probe_agent(agent)
    if online:
        return agent, port, None

    fallbacks = fallback_agents or []
    for fb in fallbacks:
        fb_online, fb_port = probe_agent(fb)
        if fb_online:
            log_warn(f"主 agent [{agent}] 不在线，切换至 fallback [{fb}]")
            return fb, fb_port, agent

    return agent, port, None  # 主 agent 不在线，但没找到 fallback


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
    planned_agent = step.get("executor", "标准版")
    fallback_agents = step.get("fallback_agents", [])
    title = step.get("title", f"Step {step_index + 1}")
    task = step.get("description") or step.get("task", "")
    stage = step.get("stage", f"step-{step_index + 1}")
    depends_on = step.get("depends_on", [])
    optional = step.get("optional", False)

    # ── 智能路由 ───────────────────────────────────────
    actual_agent, port, fallback_from = resolve_agent(planned_agent, fallback_agents)

    log_step(
        f"╔══ [{step_index + 1}/{total_steps}] {title} → {actual_agent}"
        + (f" (fallback from {fallback_from})" if fallback_from else "")
    )

    # 更新 checkpoint（运行中）
    save_checkpoint(project_name, step_index, title, "running")

    # 写 Bus: 任务开始
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

        log(f"  📤 调用 {actual_agent}(:{port}) [attempt-{attempt + 1}]")
        result = call_agent(actual_agent, task)

        if result["status"] == "ok":
            # 写 Bus: 完成
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
            actual_agent,
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


# ══════════════════════════════════════════════════════
# REST API Server（Dashboard 用）
# ══════════════════════════════════════════════════════
_REST_PROJECT = {"name": "testglink"}  # 全局：当前项目名

# ── 飞书告警 ────────────────────────────────────────────
FEISHU_ALERT_WEBHOOK = os.environ.get(
    "GLINK_ALERT_WEBHOOK",
    "",
)


def send_alert(title, message):
    """发送飞书告警消息（环境变量 GLINK_ALERT_WEBHOOK）"""
    if not FEISHU_ALERT_WEBHOOK:
        log_warn(f"告警未发送（未配置 GLINK_ALERT_WEBHOOK）: {title}")
        return False
    payload = json.dumps(
        {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": f"⚠️ Glink: {title}"},
                    "template": "red",
                },
                "elements": [
                    {"tag": "markdown", "content": message},
                    {
                        "tag": "hr",
                    },
                    {
                        "tag": "note",
                        "elements": [
                            {
                                "tag": "plain_text",
                                "content": f"Glink Daemon v0.5 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                            }
                        ],
                    },
                ],
            },
        }
    ).encode()
    req = urllib.request.Request(
        FEISHU_ALERT_WEBHOOK,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode()
            ok = json.loads(body).get("StatusCode", 1) == 0
            if ok:
                log("📬 告警已发送")
            else:
                log_warn(f"告警发送失败: {body[:200]}")
            return ok
    except Exception as e:
        log_warn(f"告警发送异常: {e}")
        return False


def _build_status(project_name):
    """构建 /status 响应"""
    events = main_bus.read(project_name, limit=500)
    steps_cfg = []
    try:
        wf = load_workflow(project_name)
        steps_cfg = wf.get("steps", [])
    except Exception:
        pass

    # stage → 最终状态
    stage_status = {}
    stage_agent = {}
    stage_start = {}
    for e in events:
        s = e.get("stage", "")
        if not s:
            continue
        t = e["type"]
        if t == "task.started":
            if s not in stage_status:
                stage_status[s] = "run"
                stage_agent[s] = e.get("agent", "?")
                stage_start[s] = e.get("ts", "")
        elif t == "task.completed":
            stage_status[s] = "ok"
            stage_agent[s] = e.get("agent", stage_agent.get(s, "?"))
        elif t == "task.failed":
            stage_status[s] = "fail"
            stage_agent[s] = e.get("agent", stage_agent.get(s, "?"))
        elif t == "task.skipped":
            stage_status[s] = "skip"

    # 对齐 steps
    steps_out = []
    for i, step in enumerate(steps_cfg):
        stage = step.get("stage", f"step-{i + 1}")
        s_status = stage_status.get(stage, "wait")
        started = stage_start.get(stage, "")
        duration = ""
        if started and s_status == "ok":
            for e in events:
                if e.get("stage") == stage and e["type"] == "task.completed":
                    try:
                        ts = datetime.fromisoformat(e["ts"])
                        ts0 = datetime.fromisoformat(started)
                        secs = (ts - ts0).seconds
                        duration = f"{secs // 60}m{secs % 60}s"
                    except Exception:
                        pass
                    break

        steps_out.append(
            {
                "index": i + 1,
                "title": step.get("title", stage),
                "stage": stage,
                "agent": stage_agent.get(stage, step.get("executor", "—")),
                "status": s_status,
                "status_class": s_status,
                "duration": duration,
            }
        )

    # 找 project.start
    proj_started = ""
    for e in events:
        if e["type"] == "project.update":
            proj_started = e.get("ts", "")

    return {
        "project_name": project_name,
        "total_steps": len(steps_cfg),
        "run_start": proj_started,
        "steps": steps_out,
        "error": None,
    }


class _DashHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def do_POST(self):
        path = self.path.split("?")[0]
        qstr = dict(p.split("=", 1) for p in self.path.split("?")[1].split("&") if "=" in p) if "?" in self.path else {}
        if path == "/restart":
            is_force = qstr.get("force", "").lower() in ("true", "1")
            proj = _REST_PROJECT.get("name", "testglink")
            self.send_json({"status": "ok", "message": f"重启 {proj} {'(force)' if is_force else ''}"})
            Thread(target=lambda: self_restart(proj, force=is_force), daemon=True).start()
        else:
            self.send_json({"error": "not found"}, 404)

    def log_message(self, fmt, *args):
        pass  # 静默

    def send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False)
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body.encode("utf-8"))))
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def do_GET(self):
        path = self.path.split("?")[0]
        qstr = dict(p.split("=", 1) for p in self.path.split("?")[1].split("&") if "=" in p) if "?" in self.path else {}
        proj = _REST_PROJECT.get("name", "testglink")

        if path == "/status":
            self.send_json(_build_status(proj))

        elif path == "/status/agents":
            agents_out = []
            for name, port in AGENT_PORTS.items():
                online, _ = probe_agent(name)
                agents_out.append({"name": name, "port": port, "online": online})
            self.send_json({"agents": agents_out})

        elif path == "/status/events":
            n = int(qstr.get("n", 20))
            events = main_bus.read(proj, limit=n)
            ev_out = []
            for e in events[-n:]:
                t = e["type"]
                s_map = {"task.completed": "ok", "task.failed": "fail", "task.started": "run", "task.skipped": "skip"}
                ev_out.append(
                    {
                        "ts": e.get("ts", ""),
                        "type": t,
                        "agent": e.get("agent", "?"),
                        "status_class": s_map.get(t, "wait"),
                        "stage": e.get("stage", ""),
                    }
                )
            self.send_json({"events": ev_out})

        elif path == "/bus/latest":
            events = main_bus.read(proj, limit=1)
            self.send_json({"event": events[-1] if events else None})

        elif path == "/health":
            self.send_json({"status": "ok", "service": "glink-daemon-v0.5"})

        else:
            self.send_json({"error": "not found"}, 404)


def _run_server():
    socketserver.TCPServer.allow_reuse_address = True
    srv = HTTPServer(("", 8426), _DashHandler)
    print("  📡 Dashboard API: http://127.0.0.1:8426")
    srv.serve_forever()


def start_api_server():
    """启动独立 API server 线程（daemon，随主进程退出）"""
    t = Thread(target=_run_server, daemon=True)
    t.start()


def run_daemon(project, force=False, start_step=None):
    """执行工作流（主线程）"""
    ensure_pid()

    log(f"🚀 Glink Daemon v0.5 | 项目: {project}")
    start_api_server()
    log(f"   工作流: {WORKFLOWS_DIR}/{project}.yaml")
    log(f"   Bus:    {BUS_DIR}/projects/{project}.jsonl")
    log(f"   重试:   {MAX_RETRIES}x | 轮询间隔: {POLL_INTERVAL}s")

    workflow = load_workflow(project)
    log(f"   加载: {workflow.get('project', {}).get('title', project)}")
    log(f"   步骤: {len(workflow.get('steps', []))} 步")

    success = run_workflow(project, workflow, force_start=force, start_step=start_step)

    # ── 保持存活（API server 持续可访问）────────────────
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
            start_step = arg.split("=", 1)[1]
        elif not arg.startswith("-"):
            project = arg

    _REST_PROJECT["name"] = project

    if serve_only:
        log("🔄 Glink Daemon v0.5 (serve-only) | API 端口 8426")
        log(f"   POST /restart → 运行项目 {project}")
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
