"""Loopback bridge for the local browser extension. Tokens are hashed at rest."""

from __future__ import annotations

import asyncio
import hashlib
import json
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
    "wenxin": {"origins": ["https://chat.baidu.com", "https://wenxin.baidu.com", "https://yiyan.baidu.com"], "label": "文心网页"},
    "zai": {"origins": ["https://chat.z.ai"], "label": "Z.ai 网页"},
}

# The extension reads a Yuanbao reply for 90s after send. This wait is longer so that report wins.
WEB_JOB_WAIT_S = 120
SITE_STATUS = {
    "fixture": {"state": "verified_local", "detail": "2026-11-14 扩展经本机桥完成：发送一次、读完新回复、再转发另一成员公开答复、停止后没有第三次提交。"},
    "gemini": {
        "state": "guest_extension_passed",
        "detail": "2026-11-15 01:30 CST（2026-11-14T17:30:36Z）https://gemini.google.com/app 游客，页面显示 Flash-Lite。扩展写回两条回复。另一成员是演示模型，不是第二个网页模型。",
    },
    "qwen": {
        "state": "guest_verified_live",
        "detail": "2026-11-15 扩展 0.4.2 实页端到端已通过（发送、读回、转发）。若服务端提示没有权限，回报「千问游客发送被拒绝，可能需要登录」，清空输入框，不重发。年龄确认弹窗只回报，不点。",
    },
    "chatgpt": {
        "state": "guest_gated",
        "detail": "2026-11-15 实页：游客额度用完后页面出现「Sign in to continue」，扩展 0.4.3 在写入前识别并回报「ChatGPT 需要登录后才能继续（游客额度可能用完）」，不写入、不重试。ChatGPT 游客模式不可靠。",
    },
    "claude": {"state": "BLOCKED", "detail": "本环境早前打开 https://claude.ai/ 得到 403。没有重试，没有绕过。"},
    "deepseek": {
        "state": "login_verified_live",
        "detail": "2026-11-15 扩展 0.4.2 在已登录、单独可见窗口的标签页里实页端到端已通过。标签页在后台时虚拟消息列表可能不渲染。停在 /sign_in 或出现登录输入框时不发送。",
    },
    "grok": {"state": "login_wall", "detail": "本环境早前打开 https://grok.com/ 先是登录与 Cookie 说明，没有当成游客聊天。"},
    "doubao": {
        "state": "login_verified_live",
        "detail": "2026-11-15 已登录实页发送和读回已通过（较早版本核对）。出现登录框时不发送。地区不可用页只回报「豆包当前网络地区不可用」，不绕过。",
    },
    "yuanbao": {
        "state": "guest_login_required",
        "detail": "2026-11-15 登录后的自动发送，以及一轮 A/B 取答案 1，已核对。0.2.9 把转发压成一段再比较，待实页再核对。同一轮失败后不再转发。游客输入仍要先登录一次。",
    },
    "zhipu": {
        "state": "guest_adapter",
        "detail": "2026-11-15 0.4.2 实页报「已填入，未发送」（站点没认到写入，发送键一直带 .empty）。扩展 0.4.3 改用 execCommand('insertText') 写入、等发送键可点、点按钮中心元素；实页待再核对。只读最终回答，不读思考过程。",
    },
    "wenxin": {
        "state": "guest_adapter",
        "detail": "2026-11-15 0.4.2 实页报「已填入，未发送」。扩展 0.4.3 改用 execCommand('insertText') 写入、点发送图标 img#ci-submit-button-ai；若页面发出的不是待发文本（例如示例提示）就停下报错。实页待再核对。wenxin.baidu.com / chat.baidu.com / yiyan.baidu.com 算同一个绑定。",
    },
    "zai": {
        "state": "guest_verified_live",
        "detail": "2026-11-15 扩展 0.4.2 游客实页端到端已通过，地址到 /c/<id>，只读回答不读 Thought Process。",
    },
}


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def origin_of(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def same_site_origin(a: str, b: str) -> bool:
    """Two origins count as the same tab binding when they are equal or belong to the same site
    (wenxin.baidu.com / chat.baidu.com / yiyan.baidu.com redirect into each other; chatgpt.com / chat.openai.com)."""
    if not a or not b:
        return False
    if a == b:
        return True
    site = site_for_origin(a)
    return site is not None and site == site_for_origin(b)


def site_for_origin(origin: str) -> str | None:
    for site, spec in SITES.items():
        if origin in spec["origins"]:
            return site
    return None


HEALTH_ROLES = {"composer", "send", "users", "assistants", "messages", "body", "user_text"}


def clean_health(raw) -> dict | None:
    """Keep only the dry-run page check fields (no page text). The extension sends this with the heartbeat."""
    if not isinstance(raw, dict):
        return None

    def text(value, limit=200):
        return str(value)[:limit] if isinstance(value, (str, int, float)) else ""

    roles = {}
    for name, item in (raw.get("roles") or {}).items():
        if name in HEALTH_ROLES and isinstance(item, dict):
            roles[name] = {
                "found": int(item.get("found") or 0) if str(item.get("found") or 0).isdigit() else 0,
                "index": int(item.get("index")) if isinstance(item.get("index"), int) else -1,
            }
    registry = raw.get("registry") if isinstance(raw.get("registry"), dict) else {}
    return {
        "site": text(raw.get("site"), 24),
        "ok": bool(raw.get("ok")),
        "missing": [text(x, 24) for x in (raw.get("missing") or []) if isinstance(x, str)][:8],
        "empty": [text(x, 24) for x in (raw.get("empty") or []) if isinstance(x, str)][:8],
        "deferred": [text(x, 24) for x in (raw.get("deferred") or []) if isinstance(x, str) and x in HEALTH_ROLES][:8],
        "gate": text(raw.get("gate")) or None,
        "detail": text(raw.get("detail"), 300),
        "roles": roles,
        "registry_version": text(registry.get("version"), 24),
        "registry_source": text(registry.get("source"), 160),
        "checked_at": text(raw.get("checked_at"), 40),
    }


class WebBridge:
    def __init__(self, db):
        self.db = db
        self.waiters: dict[str, asyncio.Event] = {}
        self.locks: dict[str, asyncio.Lock] = {}
        self.loop: asyncio.AbstractEventLoop | None = None
        self.on_progress = None

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

    def note_progress(self, request_id: str, phase: str, note: str = "") -> dict:
        job = self.get_job(request_id)
        if not job or job["status"] not in {"queued", "sending"}:
            return {"ok": False}
        if self.on_progress:
            self.on_progress(job, phase, note or "")
        return {"ok": True}

    def note_tabs(self, tabs: list[dict]) -> dict:
        updated = 0
        sessions: set[str] = set()
        with self.db._lock:
            rows = self.db.conn.execute(
                "SELECT id, session_id, web_tab_key, web_origin FROM members WHERE provider='web'"
            ).fetchall()
            now = now_iso()
            for beat in tabs:
                key = (beat.get("tab_key") or "").strip()
                origin = origin_of(beat.get("origin") or "")
                if not key or not origin:
                    continue
                alive = bool(beat.get("alive"))
                health = clean_health(beat.get("health")) if alive else None
                for row in rows:
                    if (row["web_tab_key"] or "") != key or not same_site_origin(row["web_origin"] or "", origin):
                        continue
                    if alive:
                        self.db.conn.execute(
                            "UPDATE members SET web_conversation='tab', web_seen_at=? WHERE id=?",
                            (now, row["id"]),
                        )
                        if health is not None:
                            self.db.conn.execute(
                                "UPDATE members SET web_health=? WHERE id=?",
                                (json.dumps(health, ensure_ascii=False), row["id"]),
                            )
                    else:
                        self.db.conn.execute(
                            "UPDATE members SET web_conversation='down' WHERE id=?",
                            (row["id"],),
                        )
                    updated += 1
                    if row["session_id"]:
                        sessions.add(row["session_id"])
            self.db.conn.commit()
        return {"ok": True, "updated": updated, "session_ids": sorted(sessions)}

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

    def tab_busy(self, tab_key: str) -> bool:
        with self.db._lock:
            row = self.db.conn.execute(
                "SELECT request_id FROM ext_jobs WHERE tab_key=? AND status IN ('queued', 'sending') LIMIT 1",
                (tab_key,),
            ).fetchone()
        return row is not None

    def create_job(self, fields: dict) -> dict | None:
        request_id = fields["request_id"]
        session = self.db.get_session(fields["session_id"])
        if session and session["status"] in {"stopped", "finished", "failed"}:
            return None
        if self.tab_busy(fields["tab_key"]):
            return None
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
        if not same_site_origin(origin, job["origin"]):
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
        deadline = asyncio.get_running_loop().time() + WEB_JOB_WAIT_S
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
