"""Small shared helpers. No provider SDKs."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

REASON_LABELS = {
    "limit_rounds": "达到轮数上限",
    "limit_messages": "达到 AI 消息上限",
    "limit_time": "达到时间上限",
    "limit_tokens": "达到 token 上限",
    "limit_cost": "达到费用上限",
    "user_stop": "用户停止",
    "no_new_viewpoints": "无新观点早停",
    "independent_complete": "独立回答完成",
    "summary_only": "仅生成总结",
    "all_passed": "成员选择不再发言",
    "provider_failed": "提供方失败",
    "engine_error": "调度失败",
    "server_restart": "服务重启，讨论已停止且未自动重开",
    "no_members": "没有可发言的成员",
    "no_user_message": "没有用户问题",
}

STATUS_LABELS = {
    "idle": "空闲",
    "running": "运行中",
    "paused": "已暂停",
    "finished": "已完成",
    "stopped": "已停止",
    "failed": "失败",
}

STOPPED_REASONS = {"user_stop", "limit_time", "server_restart"}
FAILED_REASONS = {"provider_failed", "engine_error", "no_members", "no_user_message"}

_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{6,}|Bearer\s+[A-Za-z0-9._\-]{6,}|(api[_-]?key|token|secret)(['\"]?\s*[:=]\s*['\"]?)[^'\"\s,]{4,})",
    re.IGNORECASE,
)


def new_id() -> str:
    return uuid.uuid4().hex[:16]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def reason_label(reason: str | None) -> str:
    if not reason:
        return ""
    return REASON_LABELS.get(reason, reason)


def status_for(reason: str) -> str:
    if reason in STOPPED_REASONS:
        return "stopped"
    if reason in FAILED_REASONS:
        return "failed"
    return "finished"


def redact(text: str) -> str:
    if not text:
        return ""

    def repl(match: re.Match[str]) -> str:
        chunk = match.group(0)
        if chunk.lower().startswith("bearer "):
            return "Bearer ***"
        if chunk.lower().startswith(("api", "token", "secret")):
            return re.sub(r"[^:=\s'\"]+$", "***", chunk)
        return "sk-***"

    return _SECRET_RE.sub(repl, text)


def excerpt(text: str, limit: int = 36) -> str:
    clean = " ".join((text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[:limit] + "…"


def infer_new_point(text: str) -> bool:
    markers = ("没有新的观点", "无新观点", "没有补充")
    return not any(item in (text or "") for item in markers)


def mention_ids(text: str, members: list[dict]) -> list[str]:
    if not text:
        return []
    if "@所有人" in text or "@all" in text or "@All" in text:
        return [m["id"] for m in members if m.get("enabled", True)]
    found: list[str] = []
    ordered = sorted(members, key=lambda m: len(m.get("nickname") or ""), reverse=True)
    for member in ordered:
        nick = member.get("nickname") or ""
        if nick and f"@{nick}" in text and member["id"] not in found:
            found.append(member["id"])
    return found


def status_label(status: str | None) -> str:
    return STATUS_LABELS.get(status or "", status or "")
