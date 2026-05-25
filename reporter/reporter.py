#!/usr/bin/env python3
"""
Glink Reporter — Channel-agnostic notification session layer

Core interface: ReportSession
  - push(message)   → Push an informational message
  - alert(title)    → Push an alert / notification
  - summary(data)   → Push a step progress summary

Built-in implementations:
  - WebhookReporter  → Generic HTTP webhook (Slack, Discord, custom)
  - ConsoleReporter  → stdout (default fallback)
  - SilentReporter   → Silent mode (log only, no push)
  - MultiReporter    → Fan-out to multiple channels simultaneously

Planned:
  - Custom channels via plugin mechanism

Configuration (in order of priority):
  1. reporting.channels in glink-config.yaml
  2. GLINK_REPORTER env var (webhook|console|silent)
  3. Default: ConsoleReporter
"""

import json
import logging
import os
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from datetime import datetime

log = logging.getLogger("glink.reporter")

# ── Severity colors ─────────────────────────────────────
C_OK = "green"
C_WARN = "yellow"
C_ERR = "red"
C_INFO = "blue"


# ══════════════════════════════════════════════════════════
# Abstract interface
# ══════════════════════════════════════════════════════════


class ReportSession(ABC):
    """Channel-agnostic notification session."""

    @abstractmethod
    def push(self, message: str) -> bool:
        """Push an informational message."""
        ...

    @abstractmethod
    def alert(self, title: str, detail: str = "", severity: str = C_ERR) -> bool:
        """Push an alert notification."""
        ...

    def summary(
        self,
        project: str,
        step_index: int,
        total: int,
        status: str,
        agent: str,
        duration: str,
        detail: str = "",
    ) -> bool:
        """Push a step progress summary."""
        bar = "█" * step_index + "░" * (total - step_index)
        msg = (
            f"📋 {project} · Step {step_index}/{total}\n"
            f"   {bar}\n"
            f"   Agent: {agent}  |  Status: {status}  |  Duration: {duration}"
        )
        if detail:
            msg += f"\n   📝 {detail}"
        return self.push(msg)


# ══════════════════════════════════════════════════════════
# Webhook implementation
# ══════════════════════════════════════════════════════════

SEVERITY_COLORS = {
    C_OK: "green",
    C_WARN: "yellow",
    C_ERR: "red",
    C_INFO: "blue",
}


class WebhookReporter(ReportSession):
    """Generic webhook reporter (Slack, Discord, custom endpoints)."""

    def __init__(self, webhook_url: str, session_label: str = ""):
        self.url = webhook_url
        self.label = session_label or "Glink"

    def push(self, message: str) -> bool:
        payload = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": f"📡 {self.label}"},
                    "template": "blue",
                },
                "elements": [
                    {"tag": "markdown", "content": message},
                    {"tag": "hr"},
                    {
                        "tag": "note",
                        "elements": [
                            {
                                "tag": "plain_text",
                                "content": f"Glink Reporter | {datetime.now().strftime('%H:%M:%S')}",
                            }
                        ],
                    },
                ],
            },
        }
        return self._send(payload)

    def alert(self, title: str, detail: str = "", severity: str = C_ERR) -> bool:
        color = SEVERITY_COLORS.get(severity, "red")
        payload = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": f"⚠️ {self.label}: {title}",
                    },
                    "template": color,
                },
                "elements": [
                    {"tag": "markdown", "content": detail or "No details"},
                    {"tag": "hr"},
                    {
                        "tag": "note",
                        "elements": [
                            {
                                "tag": "plain_text",
                                "content": f"Glink Reporter | {datetime.now().strftime('%H:%M:%S')}",
                            }
                        ],
                    },
                ],
            },
        }
        return self._send(payload)

    def _send(self, payload: dict) -> bool:
        try:
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                self.url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = resp.read().decode()
                ok = json.loads(body).get("StatusCode", 1) == 0
                return ok
        except Exception as e:
            log.warning(f"Webhook send failed: {e}")
            return False


# ══════════════════════════════════════════════════════════
# Console implementation
# ══════════════════════════════════════════════════════════


class ConsoleReporter(ReportSession):
    """stdout reporter (default fallback)."""

    def __init__(self, label: str = "Glink"):
        self.label = label

    def push(self, message: str) -> bool:
        ts = datetime.now().strftime("%H:%M:%S")
        banner = f"\n{'─' * 50}\n📡 [{ts}] {self.label}\n{'─' * 50}"
        print(f"{banner}\n{message}\n")
        return True

    def alert(self, title: str, detail: str = "", severity: str = C_ERR) -> bool:
        tag = {"green": "✅", "yellow": "⚠️", "red": "❌", "blue": "ℹ️"}.get(
            severity, "❌"
        )
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"\n{tag} [{ts}] {self.label}: {title}")
        if detail:
            print(f"   {detail}")
        print()
        return True


# ══════════════════════════════════════════════════════════
# Silent implementation
# ══════════════════════════════════════════════════════════


class SilentReporter(ReportSession):
    """Silent mode — log only at DEBUG level, no push."""

    def push(self, message: str) -> bool:
        log.debug(f"[Silent] push: {message[:80]}...")
        return True

    def alert(self, title: str, detail: str = "", severity: str = C_ERR) -> bool:
        log.debug(f"[Silent] alert: {title}")
        return True


# ══════════════════════════════════════════════════════════
# MultiReporter — fan-out to multiple reporters
# ══════════════════════════════════════════════════════════


class MultiReporter(ReportSession):
    """Push to multiple channels simultaneously."""

    def __init__(self, reporters: list[ReportSession]):
        self.reporters = reporters

    def push(self, message: str) -> bool:
        results = [r.push(message) for r in self.reporters]
        return all(results)

    def alert(self, title: str, detail: str = "", severity: str = C_ERR) -> bool:
        results = [r.alert(title, detail, severity) for r in self.reporters]
        return all(results)

    def summary(
        self,
        project: str,
        step_index: int,
        total: int,
        status: str,
        agent: str,
        duration: str,
        detail: str = "",
    ) -> bool:
        results = [
            r.summary(project, step_index, total, status, agent, duration, detail)
            for r in self.reporters
        ]
        return all(results)


# ══════════════════════════════════════════════════════════
# Factory
# ══════════════════════════════════════════════════════════

DEFAULT_WEBHOOK = os.environ.get("GLINK_ALERT_WEBHOOK", "")


def create_reporter(config: dict | None = None) -> ReportSession:
    """
    Create a reporter by priority:
    1. reporting.channels in config
    2. GLINK_REPORTER env var
    3. Default ConsoleReporter
    """
    reporters: list[ReportSession] = []

    # 1. From config channels
    if config:
        channels = config.get("reporting", {}).get("channels", [])
        for ch in channels:
            t = ch.get("type", "")
            label = ch.get("session", ch.get("label", "Glink"))
            if t == "webhook":
                url = ch.get("url", "") or DEFAULT_WEBHOOK
                if url:
                    reporters.append(WebhookReporter(url, label))
                else:
                    log.warning("webhook channel missing 'url' in config")
            elif t == "feishu":
                # Backward compatibility — maps to WebhookReporter with same endpoint format
                url = ch.get("webhook", "") or DEFAULT_WEBHOOK
                if url:
                    reporters.append(WebhookReporter(url, label))
                else:
                    log.warning("webhook channel (feishu compat) missing url")
            elif t == "console":
                reporters.append(ConsoleReporter(label))
            elif t == "silent":
                reporters.append(SilentReporter())
            else:
                log.warning(f"Unknown channel type: {t}")

    # 2. From env var
    env_reporter = os.environ.get("GLINK_REPORTER", "").lower()
    if not reporters and env_reporter:
        if env_reporter in ("webhook", "feishu"):
            if DEFAULT_WEBHOOK:
                reporters.append(WebhookReporter(DEFAULT_WEBHOOK))
            else:
                log.warning("GLINK_REPORTER=webhook but GLINK_ALERT_WEBHOOK is not set")
        elif env_reporter == "silent":
            reporters.append(SilentReporter())
        else:
            reporters.append(ConsoleReporter())

    # 3. Default
    if not reporters:
        reporters.append(ConsoleReporter())

    if len(reporters) == 1:
        return reporters[0]
    return MultiReporter(reporters)


# ══════════════════════════════════════════════════════════
# CLI test
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    if "--test-webhook" in sys.argv:
        idx = sys.argv.index("--test-webhook")
        url = sys.argv[idx + 1]
        r = WebhookReporter(url, "Glink Test")
        r.push(
            "This is a test message from Glink Reporter ✅\nChannel-agnostic session design ready."
        )
        r.alert("API Test", "Alert test from Glink Reporter", "red")
        r.summary(
            "demo-workflow", 5, 10, "✅ Complete", "agent-1", "1m23s", "Step completed"
        )
        print("✅ Webhook test sent")

    elif "--list" in sys.argv:
        r = ConsoleReporter("Glink Test")
        r.push(
            "Available Reporter implementations:\n"
            "- ConsoleReporter (default)\n"
            "- WebhookReporter (Slack, Discord, custom)\n"
            "- SilentReporter\n"
            "- MultiReporter (fan-out)"
        )
    else:
        r = ConsoleReporter()
        r.push(
            "Glink Reporter v1.0\n\n"
            "Usage:\n"
            "  python3 reporter.py --test-webhook <webhook_url>\n"
            "  python3 reporter.py --list"
        )
