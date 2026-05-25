# SPDX-License-Identifier: MIT
"""
agent_client — Glink shared Agent communication & workflow loading module

Shared by: glink.py (one-shot) and glink-daemon.py (checkpoint-resume daemon).

Exports:
  - AGENT_PORTS:  Agent name → HTTP port mapping
  - call_agent(): HTTP call to agent's /ask endpoint
  - load_workflow(): Load YAML workflow from workflows/ or bus/projects/
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
import time

# ── Agent port mapping (single source of truth) ────────────
# One port can have multiple aliases
AGENT_PORTS = {
    "agent-1": 8420,
    "agent-2": 8431,
    "agent-3": 8432,
    "agent-4": 8434,
    "agent-5": 8435,
    "agent-6": 8436,
}

# ── Project name sanitizer (prevents path traversal) ────
_PROJECT_RE = re.compile(r"^[\w\-]+$")


def _sanitize_project_name(name: str) -> str:
    """Filter project name — only alphanumeric, underscore, hyphen allowed."""
    safe = _PROJECT_RE.sub("", name)
    if safe != name:
        safe = re.sub(r"[^\w\-]", "", name)
    return safe.strip().lower() or "unnamed"


# ── HTTP call to agent ─────────────────────────────────────


def call_agent(
    agent: str,
    task: str,
    port: int | None = None,
    timeout: int = 600,
    parse_reply: bool = True,
) -> dict:
    """Call an agent's /ask endpoint via HTTP.

    Args:
        agent:        Agent name (e.g. "agent-1", "Forge")
        task:         Task description for the agent
        port:         Explicit port; falls back to AGENT_PORTS lookup
        timeout:      Request timeout in seconds
        parse_reply:  If True, try to parse JSON and extract 'reply' field.
                      If False, return raw response text.

    Returns:
        {"status": "ok",     "output": "<reply or first 500 chars>"}
        {"status": "failed", "error":  "<description>"}
    """
    p = port or AGENT_PORTS.get(agent, 8420)
    url = f"http://127.0.0.1:{p}/ask"
    payload = json.dumps({"message": task}).encode()
    start = time.time()
    try:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode()
            dur = round(time.time() - start, 1)
            if parse_reply:
                try:
                    data = json.loads(body)
                    reply = data.get(
                        "reply", data.get("response", data.get("output", body[:500]))
                    )
                    return {"status": "ok", "output": reply[:2000], "duration": dur}
                except json.JSONDecodeError:
                    return {"status": "ok", "output": body[:2000], "duration": dur}
            return {"status": "ok", "output": body[:2000], "duration": dur}
    except urllib.error.HTTPError as e:
        dur = round(time.time() - start, 1)
        return {
            "status": "failed",
            "error": f"HTTP {e.code}: {e.reason}",
            "duration": dur,
        }
    except urllib.error.URLError as e:
        dur = round(time.time() - start, 1)
        return {
            "status": "failed",
            "error": f"Connection refused: {agent}(:{p})",
            "duration": dur,
        }
    except Exception as e:
        dur = round(time.time() - start, 1)
        return {"status": "failed", "error": str(e), "duration": dur}


# ── Workflow loading ───────────────────────────────────────


def load_workflow(project_name: str, base_dir: str | None = None) -> dict:
    """Load a workflow YAML. Searches workflows/ first, then bus/projects/.

    Args:
        project_name: Project name (sanitized by _sanitize_project_name)
        base_dir:     Glink root directory; defaults to parent of this file

    Returns:
        Parsed workflow dict

    Raises:
        SystemExit(1): Workflow file not found
    """
    if base_dir is None:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    safe_name = _sanitize_project_name(project_name)

    # Search: workflows/<name>.yaml, workflows/<name>.yml, bus/projects/<name>.yaml
    search_paths = []
    base_wf = os.path.join(base_dir, "workflows")
    for ext in (".yaml", ".yml"):
        search_paths.append(os.path.join(base_wf, f"{safe_name}{ext}"))
        search_paths.append(os.path.join(base_wf, f"{project_name}{ext}"))
    bus_dir = os.path.join(base_dir, "bus", "projects")
    search_paths.append(os.path.join(bus_dir, f"{safe_name}.yaml"))

    for p in search_paths:
        if os.path.exists(p):
            try:
                import yaml
            except ImportError:
                import subprocess

                subprocess.check_call(
                    [
                        sys.executable,
                        "-m",
                        "pip",
                        "install",
                        "pyyaml",
                        "-q",
                        "--quiet",
                        "--quiet",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                import yaml  # noqa: F811
            with open(p) as f:
                return yaml.safe_load(f)

    print(f"❌ Workflow not found: {safe_name}", file=sys.stderr)
    sys.exit(1)
