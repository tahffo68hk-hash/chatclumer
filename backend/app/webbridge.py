"""Loopback bridge for the local browser extension. Tokens are hashed at rest."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from .util import new_id, now_iso

SITES = {
    "fixture": {"origins": ["http://127.0.0.1:43124"], "label": "本地夹具"},
    "gemini": {"origins": ["https://gemini.google.com"], "label": "Gemini 网页"},
    "qwen": {"origins": ["https://chat.qwen.ai"], "label": "Qwen 网页"},
    "chatgpt": {"origins": ["https://chatgpt.com", "https://chat.openai.com"], "label": "ChatGPT 网页"},
    "claude": {"origins": ["https://claude.ai"], "label": "Claude 网页"},
    "grok": {"origins": ["https://grok.com"], "label": "Grok 网页"},
    "deepseek": {"origins": ["https://chat.deepseek.com"], "label": "DeepSeek 网页"},
    "doubao": {"origins": ["https://www.doubao.com"], "label": "豆包网页"},
    "yuanbao": {"origins": ["https://yuanbao.tencent.com"], "label": "腾讯元宝网页"},
    "zhipu": {"origins": ["https://chatglm.cn"], "label": "智谱清言网页"},
}

# Observed on 2026-11-15 from this environment. Not a claim that the block is permanent.
SITE_STATUS = {
    "fixture": {"state": "verified_local", "detail": "2026-11-14 扩展经本机桥完成：发送一次、读完新回复、再转发另一成员公开答复、停止后没有第三次提交。"},
    "gemini": {
        "state": "guest_extension_passed",
        "detail": "2026-11-15 01:30 CST（2026-11-14T17:30:36Z）https://gemini.google.com/app 游客，页面显示 Flash-Lite。扩展写回两条回复。另一成员是演示模型，不是第二个网页模型。",
    },
    "qwen": {
        "state": "age_gate_stopped",
        "detail": "2026-11-14 https://chat.qwen.ai/ 手动可见操作，不是扩展回路。输入框可见，页面有 Qwen3.7-Plus。点了一次 Send 后出现确认年龄，没有填写出生年，也没有点 Continue。没有读到回复。",
    },
    "chatgpt": {"state": "BLOCKED", "detail": "本环境早前打开 https://chatgpt.com/ 停在挑战页。没有重试，没有绕过。"},
    "claude": {"state": "BLOCKED", "detail": "本环境早前打开 https://claude.ai/ 得到 403。没有重试，没有绕过。"},
    "deepseek": {"state": "BLOCKED", "detail": "本环境早前打开 https://chat.deepseek.com/ 得到 CloudFront 403。没有重试，没有绕过。"},
    "grok": {"state": "login_wall", "detail": "本环境早前打开 https://grok.com/ 先是登录与 Cookie 说明，没有当成游客聊天。"},
    "doubao": {
        "state": "UNVERIFIED",
        "detail": "允许逐站授权 https://www.doubao.com/chat/ 。协调方看到登录后才有回复。本机还没有核验输入框，不会发送，也不写成永远没有游客。",
    },
    "yuanbao": {
        "state": "coordinator_dom_not_e2e",
        "detail": "结构取自协调方实页 2026-11-15。只读发送后新增的 .agent-chat__list__item--ai 里的 .hyc-common-markdown，排除参考资料、过程列表和全屏图片。本机没有完成游客发送，自动发送还没有经过协调方验收，不是扩展端到端。",
    },
    "zhipu": {
        "state": "login_wall",
        "detail": "2026-11-15 01:40 CST 本机打开 https://chatglm.cn/ 停在手机号登录。公开回复正文位置未验证，扩展不会发送，也不用整页文字代替。页面标签 GLM-5.3-Flash极致 不是精确底层 ID。",
    },
}


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def origin_of(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def site_for_origin(origin: str) -> str | None:
    for site, spec in SITES.items():
        if origin in spec["origins"]:
            return site
    return None


class WebBridge:
    def __init__(self, db):
        self.db = db
        self.waiters: dict[str, asyncio.Event] = {}
        self.locks: dict[str, asyncio.Lock] = {}
        self.loop: asyncio.AbstractEventLoop | None = None

    def tab_lock(self, key: str) -> asyncio.Lock:
        lock = self.locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self.locks[key] = lock
        return lock

    def issue_code(self) -> dict:
        raw = secrets.token_hex(4)
        expires = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        with self.db._lock:
            self.db.conn.execute(
                "INSERT INTO ext_codes (code_hash, expires_at, used) VALUES (?, ?, 0)",
                (_hash(raw), expires),
            )
            self.db.conn.commit()
        return {"code": raw, "expires_at": expires}

    def pair(self, code: str) -> str | None:
        digest = _hash((code or "").strip())
        now = datetime.now(timezone.utc).isoformat()
        with self.db._lock:
            row = self.db.conn.execute("SELECT * FROM ext_codes WHERE code_hash=?", (digest,)).fetchone()
            if not row or row["used"] or row["expires_at"] < now:
                return None
            self.db.conn.execute("UPDATE ext_codes SET used=1 WHERE code_hash=?", (digest,))
            token = secrets.token_hex(24)
            self.db.conn.execute(
                "INSERT INTO ext_tokens (token_hash, created_at) VALUES (?, ?)",
                (_hash(token), now_iso()),
            )
            self.db.conn.commit()
        return token

    def authorized(self, header: str | None) -> bool:
        if not header or not header.lower().startswith("bearer "):
            return False
        token = header.split(" ", 1)[1].strip()
        if not token:
            return False
        with self.db._lock:
            row = self.db.conn.execute(
                "SELECT token_hash FROM ext_tokens WHERE token_hash=?",
                (_hash(token),),
            ).fetchone()
        return row is not None

    def note_tabs(self, tabs: list[dict]) -> dict:
        updated = 0
        with self.db._lock:
            rows = self.db.conn.execute(
                "SELECT id, web_tab_key, web_origin FROM members WHERE provider='web'"
            ).fetchall()
            now = now_iso()
            for beat in tabs:
                key = (beat.get("tab_key") or "").strip()
                origin = origin_of(beat.get("origin") or "")
                if not key or not origin:
                    continue
                alive = bool(beat.get("alive"))
                for row in rows:
                    if (row["web_tab_key"] or "") != key or (row["web_origin"] or "") != origin:
                        continue
                    if alive:
                        self.db.conn.execute(
                            "UPDATE members SET web_conversation='tab', web_seen_at=? WHERE id=?",
                            (now, row["id"]),
                        )
                    else:
                        self.db.conn.execute(
                            "UPDATE members SET web_conversation='down' WHERE id=?",
                            (row["id"],),
                        )
                    updated += 1
            self.db.conn.commit()
        return {"ok": True, "updated": updated}

    def site_blocked(self, site: str) -> str | None:
        with self.db._lock:
            row = self.db.conn.execute("SELECT reason FROM site_blocks WHERE site=?", (site,)).fetchone()
        if row:
            return row["reason"]
        status = SITE_STATUS.get(site) or {}
        if status.get("state") in {"BLOCKED", "UNVERIFIED", "login_wall", "vm_login_on_send"}:
            return status["detail"]
        return None

    def block_site(self, site: str, reason: str) -> None:
        with self.db._lock:
            self.db.conn.execute(
                """
                INSERT INTO site_blocks (site, reason, created_at) VALUES (?, ?, ?)
                ON CONFLICT(site) DO UPDATE SET reason=excluded.reason
                """,
                (site, reason[:300], now_iso()),
            )
            self.db.conn.commit()

    def create_job(self, fields: dict) -> dict:
        request_id = fields["request_id"]
        with self.db._lock:
            self.db.conn.execute(
                """
                INSERT INTO ext_jobs (
                  id, request_id, session_id, run_token, group_id, member_id, context_version,
                  group_generation, origin, site, tab_key, prompt, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?)
                """,
                (
                    new_id(),
                    request_id,
                    fields["session_id"],
                    fields.get("run_token"),
                    fields.get("group_id"),
                    fields["member_id"],
                    int(fields["context_version"]),
                    int(fields.get("group_generation") or 0),
                    fields["origin"],
                    fields["site"],
                    fields["tab_key"],
                    fields["prompt"],
                    now_iso(),
                ),
            )
            self.db.conn.commit()
        self.waiters[request_id] = asyncio.Event()
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            self.loop = None
        return self.get_job(request_id)

    def get_job(self, request_id: str) -> dict | None:
        with self.db._lock:
            row = self.db.conn.execute("SELECT * FROM ext_jobs WHERE request_id=?", (request_id,)).fetchone()
        return dict(row) if row else None

    def claim_jobs(self) -> list[dict]:
        """One queued job per tab. A second job for the same tab stays queued."""
        with self.db._lock:
            rows = [
                dict(row)
                for row in self.db.conn.execute(
                    "SELECT * FROM ext_jobs WHERE status IN ('queued', 'sending', 'cancel') ORDER BY created_at"
                )
            ]
            claimed = []
            busy: set[str] = set()
            for row in rows:
                if row["status"] == "cancel":
                    claimed.append(self._public_job(row))
                    continue
                if row["status"] == "sending":
                    claimed.append(self._public_job(row))
                    busy.add(row["tab_key"])
                    continue
                if row["tab_key"] in busy:
                    continue
                self.db.conn.execute(
                    "UPDATE ext_jobs SET status='sending' WHERE request_id=? AND status='queued'",
                    (row["request_id"],),
                )
                row["status"] = "sending"
                busy.add(row["tab_key"])
                claimed.append(self._public_job(row))
            self.db.conn.commit()
        return claimed

    def _public_job(self, row: dict) -> dict:
        return {
            "request_id": row["request_id"],
            "run_id": row.get("run_token"),
            "group_id": row.get("group_id"),
            "member_id": row["member_id"],
            "context_version": row["context_version"],
            "group_generation": row["group_generation"],
            "origin": row["origin"],
            "site": row["site"],
            "tab_key": row["tab_key"],
            "prompt": row["prompt"],
            "action": "cancel" if row["status"] == "cancel" else "send",
            "open_new": self._needs_new(row["member_id"]),
        }

    def _needs_new(self, member_id: str) -> bool:
        row = self.db.conn.execute("SELECT web_conversation FROM members WHERE id=?", (member_id,)).fetchone()
        return bool(row and row["web_conversation"] == "needs_new")

    def cancel_request(self, request_id: str, reason: str) -> None:
        with self.db._lock:
            self.db.conn.execute(
                """
                UPDATE ext_jobs SET status='cancel', error=?, finished_at=?
                WHERE request_id=? AND status IN ('queued', 'sending')
                """,
                (reason, now_iso(), request_id),
            )
            self.db.conn.commit()
        self._wake(request_id)

    def cancel_members(self, member_ids: list[str], reason: str) -> None:
        if not member_ids:
            return
        marks = ",".join("?" for _ in member_ids)
        with self.db._lock:
            rows = self.db.conn.execute(
                f"SELECT request_id FROM ext_jobs WHERE member_id IN ({marks}) AND status IN ('queued', 'sending')",
                tuple(member_ids),
            ).fetchall()
            self.db.conn.execute(
                f"""
                UPDATE ext_jobs SET status='cancel', error=?, finished_at=?
                WHERE member_id IN ({marks}) AND status IN ('queued', 'sending')
                """,
                (reason, now_iso(), *member_ids),
            )
            self.db.conn.commit()
        for row in rows:
            self._wake(row["request_id"])

    def cancel_session(self, session_id: str, reason: str) -> None:
        with self.db._lock:
            rows = self.db.conn.execute(
                "SELECT request_id FROM ext_jobs WHERE session_id=? AND status IN ('queued', 'sending', 'cancel')",
                (session_id,),
            ).fetchall()
            self.db.conn.execute(
                """
                UPDATE ext_jobs SET status='cancel', error=?, finished_at=?
                WHERE session_id=? AND status IN ('queued', 'sending')
                """,
                (reason, now_iso(), session_id),
            )
            self.db.conn.commit()
        for row in rows:
            self._wake(row["request_id"])

    def finish_job(self, body: dict) -> dict:
        request_id = (body.get("request_id") or "").strip()
        job = self.get_job(request_id)
        if not job:
            return {"ok": False, "error": "unknown_request"}
        if job["run_token"] != body.get("run_id") or job["member_id"] != body.get("member_id"):
            return {"ok": False, "error": "mismatch"}
        if (job.get("group_id") or "") != (body.get("group_id") or ""):
            return {"ok": False, "error": "mismatch"}
        if int(job["context_version"]) != int(body.get("context_version") or -1):
            self._store(request_id, "discarded", "", body.get("model_label"), "stale_context")
            self._wake(request_id)
            return {"ok": True, "duplicate": False, "accepted": False, "reason": "stale_context"}
        origin = origin_of(body.get("page_url") or "")
        if origin != job["origin"]:
            return {"ok": False, "error": "origin"}
        if job["status"] in {"complete", "discarded", "error"}:
            return {"ok": True, "duplicate": True, "accepted": False}
        status = body.get("status") or "error"
        if status not in {"complete", "login", "rate_limit", "blocked", "error", "cancelled"}:
            status = "error"
        text = (body.get("text") or "")[:8000]
        if status in {"rate_limit", "blocked"}:
            self.block_site(job["site"], body.get("detail") or status)
        stored = "complete" if status == "complete" else "error"
        if job["status"] == "cancel" or status == "cancelled":
            stored = "discarded"
        detail = body.get("detail") or status
        self._store(request_id, stored, text if stored == "complete" else "", body.get("model_label"), detail)
        if any(phrase in detail for phrase in ("没有响应", "绑定不匹配", "内容脚本没有")):
            self.db.update_member(job["member_id"], {"web_conversation": "down"})
        self._wake(request_id)
        return {"ok": True, "duplicate": False, "accepted": stored == "complete"}

    def _store(self, request_id: str, status: str, text: str, model_label: str | None, error: str | None) -> None:
        with self.db._lock:
            self.db.conn.execute(
                """
                UPDATE ext_jobs
                SET status=?, result_text=?, model_label=?, error=?, finished_at=?
                WHERE request_id=? AND status NOT IN ('complete', 'discarded')
                """,
                (status, text, (model_label or "")[:120], (error or "")[:300], now_iso(), request_id),
            )
            self.db.conn.commit()

    def _wake(self, request_id: str) -> None:
        event = self.waiters.get(request_id)
        loop = self.loop
        if event and loop and loop.is_running():
            loop.call_soon_threadsafe(event.set)
        elif event:
            event.set()

    async def wait_job(self, request_id: str, cancel: asyncio.Event, stale: asyncio.Event):
        event = self.waiters.get(request_id)
        if event is None:
            event = asyncio.Event()
            self.waiters[request_id] = event
        self.loop = asyncio.get_running_loop()
        deadline = asyncio.get_running_loop().time() + 75
        while True:
            if cancel.is_set() or stale.is_set():
                self.cancel_request(request_id, "stopped" if cancel.is_set() else "stale_context")
                return None
            if asyncio.get_running_loop().time() > deadline:
                self.cancel_request(request_id, "extension_timeout")
                return self.get_job(request_id)
            job = self.get_job(request_id)
            if job and job["status"] in {"complete", "error", "discarded"}:
                return job
            if job and job["status"] == "cancel":
                return job
            waiter = asyncio.create_task(event.wait())
            stopper = asyncio.create_task(asyncio.sleep(0.05))
            done, _pending = await asyncio.wait({waiter, stopper}, return_when=asyncio.FIRST_COMPLETED)
            for task in (waiter, stopper):
                if task not in done:
                    task.cancel()
            event.clear()
