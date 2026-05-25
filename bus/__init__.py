# SPDX-License-Identifier: MIT
"""Glink Bus 包 — 共享工具与总线模块"""

import re

# ── 项目名白名单：仅允许字母、数字、下划线、连字符（防 path traversal）──
_PROJECT_NAME_RE = re.compile(r"[^\w\-]")


def sanitize_project_name(project_name: str) -> str:
    """过滤项目名，防止 path traversal（仅保留 [\\w\\-]）"""
    return _PROJECT_NAME_RE.sub("", project_name or "")
