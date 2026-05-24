# Glink — 多 Agent 协作编排引擎

> 让 AI 战甲一起干活。

**Glink** 是一个轻量级多 Agent 工作流编排引擎。它通过 **Main Bus**（共享黑板模式）协调多个 AI Agent 协同完成复杂任务，支持断点续跑、智能路由、实时看板监控。

## 架构

```
┌─────────────────────────────────────────────┐
│                Glink Daemon                  │
│  (HTTP 8426 · 工作流调度 · 状态监听)          │
│                                              │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐ │
│  │   重锤    │   │   绘墨    │   │   大黄蜂  │ │
│  │  (8431)  │   │  (8432)  │   │  (8434)  │ │
│  │  工程臂   │   │  设计臂   │   │  搜索臂   │ │
│  └────┬─────┘   └────┬─────┘   └────┬─────┘ │
│       │              │              │        │
│       └──────────────┼──────────────┘        │
│                      ▼                       │
│              ┌──────────────┐                │
│              │   Laser      │                │
│              │  (8435)     │                │
│              │  测试臂      │                │
│              └──────────────┘                │
└─────────────────────────────────────────────┘
         │
         ▼
   ┌─────────────┐
   │  Main Bus   │
   │ (JSONL 日志) │
   └─────────────┘
```

## 核心特性

- **工作流编排** — YAML 定义多步流水线，每步指定 agent + 任务描述
- **Main Bus 黑板** — 所有步骤输出持久化到 JSONL，断点续跑随时接入
- **智能路由** — 自动 fallback：主 agent 离线自动切换备选
- **断点续跑** — 从任意步骤恢复（`start_step=N`），不重跑已完成步骤
- **指挥官看板** — 实时 SSE 推送 + REST API，全流程可视化
- **自动恢复** — Daemon PID 守护 + cron 自检，崩溃后自动拉起
- **飞书告警** — 步骤失败自动推送飞书卡片（配置 `GLINK_ALERT_WEBHOOK`）

## 快速开始

```bash
# 1. 克隆仓库
git clone https://github.com/garyqlin/glink.git
cd glink

# 2. 启动 Daemon
python3 glink-daemon.py

# 3. 运行示例工作流
curl -X POST http://127.0.0.1:8426/run \
  -H "Content-Type: application/json" \
  -d '{"name": "sandbox-builder"}'

# 4. 查看状态
curl http://127.0.0.1:8426/status

# 5. 打开看板
open dashboard/commander.html
```

## 工作流定义 (YAML)

```yaml
name: sandbox-builder
steps:
  - title: 场景初始化
    agent: 重锤
    task: 用 Three.js 创建 3D 沙盒场景
    input_file: null

  - title: UI 系统
    agent: 绘墨
    task: 添加玻璃态 UI 界面
    input_file: step1.html

  - title: 代码审查
    agent: forge
    task: 审查代码质量
    input_file: step2.html
```

## 技术栈

- Python 3.11+ (标准库，零外部依赖)
- JSONL 作为事件总线
- SSE 实时推送
- YAML 工作流定义

## 配置文件

`glink-config.yaml`:

```yaml
server:
  port: 8426
  retries: 2
  sse:
    heartbeat_seconds: 60
    poll_interval_seconds: 2

project:
  default: sandbox-builder

reporting:
  channels:
    feishu:
      webhook: ${GLINK_ALERT_WEBHOOK}
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /health | 健康检查 |
| GET | /status | 工作流状态（含步骤详情） |
| POST | /run | 启动工作流 |
| POST | /step | 单步骤执行 |
| GET | /intel/step | 步骤情报详情 |
| GET | /intel/agents | 各 agent 状态 |
| GET | /intel/timeline | 时间线 |
| GET | /events/stream | SSE 实时推送 |

## 相关项目

- **Gbase** — 底层多 Agent 框架（[github.com/garyqlin/opprime](https://github.com/garyqlin/opprime)）

## License

MIT © 2026 Gary Lin
