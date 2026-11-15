"""SQLite persistence. One process, one file, lock around statements."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .util import new_id, now_iso

MEMBER_COLORS = ["#9a3412", "#0f766e", "#1d4ed8", "#7c2d12", "#6d28d9", "#3f6212"]
TAB_HEARTBEAT_SECONDS = 20


def _web_link(row: dict) -> str:
    if row.get("provider") != "web":
        return ""
    conversation = row.get("web_conversation") or ""
    seen = row.get("web_seen_at") or ""
    fresh = False
    if seen:
        try:
            moment = datetime.fromisoformat(seen)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            fresh = (datetime.now(timezone.utc) - moment).total_seconds() <= TAB_HEARTBEAT_SECONDS
        except ValueError:
            fresh = False
    if conversation in {"down", "needs_rebind"} or (conversation == "tab" and not fresh):
        return "掉线"
    if conversation == "tab" and fresh and row.get("web_origin") and row.get("web_tab_key"):
        return "已绑定标签页"
    if row.get("web_origin") and row.get("web_tab_key"):
        return "已配置，等待扩展绑定"
    return "未绑定"


def _bool_message(row: dict) -> dict:
    for key in ("has_new_point", "is_demo", "is_summary"):
        row[key] = bool(row.get(key))
    return row


class Database:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=4000")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init()

    def _init(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
              id TEXT PRIMARY KEY,
              title TEXT NOT NULL,
              status TEXT NOT NULL,
              mode TEXT NOT NULL,
              max_rounds INTEGER NOT NULL,
              max_ai_messages INTEGER NOT NULL,
              max_seconds REAL NOT NULL,
              max_tokens INTEGER,
              max_cost_usd REAL,
              summary_mode TEXT NOT NULL,
              summary_member_id TEXT,
              summary_provider TEXT,
              summary_model_id TEXT,
              cross_delay_ms INTEGER NOT NULL,
              room_rule TEXT NOT NULL,
              stop_on_no_new_point INTEGER NOT NULL,
              current_round INTEGER NOT NULL DEFAULT 0,
              ai_message_count INTEGER NOT NULL DEFAULT 0,
              run_tokens INTEGER NOT NULL DEFAULT 0,
              run_cost_usd REAL NOT NULL DEFAULT 0,
              run_cost_known INTEGER NOT NULL DEFAULT 1,
              total_tokens INTEGER NOT NULL DEFAULT 0,
              total_cost_usd REAL NOT NULL DEFAULT 0,
              context_version INTEGER NOT NULL DEFAULT 0,
              run_token TEXT,
              end_reason TEXT,
              speaking_json TEXT NOT NULL DEFAULT '[]',
              started_at TEXT,
              deadline_at TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS members (
              id TEXT PRIMARY KEY,
              session_id TEXT NOT NULL,
              nickname TEXT NOT NULL,
              role_name TEXT NOT NULL,
              persona TEXT NOT NULL,
              provider TEXT NOT NULL,
              model_id TEXT NOT NULL,
              api_base TEXT,
              api_key_env TEXT,
              enabled INTEGER NOT NULL,
              avatar_color TEXT NOT NULL,
              sort_order INTEGER NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_member_nick ON members(session_id, nickname);
            CREATE TABLE IF NOT EXISTS messages (
              id TEXT PRIMARY KEY,
              session_id TEXT NOT NULL,
              author_type TEXT NOT NULL,
              member_id TEXT,
              nickname TEXT,
              role_name TEXT,
              provider TEXT,
              model_id TEXT,
              avatar_color TEXT,
              content TEXT NOT NULL,
              status TEXT NOT NULL,
              reply_to_id TEXT,
              round_number INTEGER,
              phase TEXT,
              context_version INTEGER NOT NULL,
              run_token TEXT,
              step_key TEXT,
              suggest_next_id TEXT,
              suggest_next_nickname TEXT,
              prompt_tokens INTEGER NOT NULL DEFAULT 0,
              completion_tokens INTEGER NOT NULL DEFAULT 0,
              cost_usd REAL NOT NULL DEFAULT 0,
              has_new_point INTEGER NOT NULL DEFAULT 0,
              is_demo INTEGER NOT NULL DEFAULT 0,
              is_summary INTEGER NOT NULL DEFAULT 0,
              discarded_reason TEXT,
              created_at TEXT NOT NULL,
              finished_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_msg_session ON messages(session_id, created_at);
            CREATE TABLE IF NOT EXISTS steps (
              step_key TEXT PRIMARY KEY,
              session_id TEXT NOT NULL,
              run_token TEXT NOT NULL,
              status TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runs (
              id TEXT PRIMARY KEY,
              session_id TEXT NOT NULL,
              run_token TEXT NOT NULL UNIQUE,
              mode TEXT NOT NULL,
              status TEXT NOT NULL,
              trigger_message_id TEXT,
              end_reason TEXT,
              created_at TEXT NOT NULL,
              finished_at TEXT
            );
            """
        )
        cols = {row[1] for row in self.conn.execute("PRAGMA table_info(sessions)")}
        if "summary_provider" not in cols:
            self.conn.execute("ALTER TABLE sessions ADD COLUMN summary_provider TEXT")
        if "summary_model_id" not in cols:
            self.conn.execute("ALTER TABLE sessions ADD COLUMN summary_model_id TEXT")
        if "layout" not in cols:
            self.conn.execute("ALTER TABLE sessions ADD COLUMN layout TEXT NOT NULL DEFAULT 'shared'")
        self._ensure_column("members", "web_site", "TEXT")
        self._ensure_column("members", "web_origin", "TEXT")
        self._ensure_column("members", "web_tab_key", "TEXT")
        self._ensure_column("members", "web_model_label", "TEXT")
        self._ensure_column("members", "web_conversation", "TEXT")
        self._ensure_column("members", "web_auto", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("members", "web_seen_at", "TEXT")
        self._ensure_column("members", "web_health", "TEXT")
        self._ensure_column("sessions", "parent_started_at", "TEXT")
        self._ensure_column("sessions", "parent_deadline_at", "TEXT")
        self._ensure_column("sessions", "run_tokens_known", "INTEGER NOT NULL DEFAULT 1")
        self._ensure_column("messages", "group_id", "TEXT")
        self._ensure_column("messages", "audience", "TEXT")
        self._ensure_column("messages", "target_member_id", "TEXT")
        self._ensure_column("messages", "event_kind", "TEXT")
        self._ensure_column("messages", "source_message_id", "TEXT")
        self._ensure_column("messages", "source_group_id", "TEXT")
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS highlights (
              id TEXT PRIMARY KEY,
              session_id TEXT NOT NULL,
              message_id TEXT NOT NULL,
              title TEXT NOT NULL,
              note TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              UNIQUE(session_id, message_id)
            )
            """
        )
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS groups (
              id TEXT PRIMARY KEY,
              session_id TEXT NOT NULL,
              name TEXT NOT NULL,
              kind TEXT NOT NULL,
              status TEXT NOT NULL,
              generation INTEGER NOT NULL DEFAULT 0,
              settled INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS group_members (
              id TEXT PRIMARY KEY,
              group_id TEXT NOT NULL,
              session_id TEXT NOT NULL,
              member_id TEXT NOT NULL,
              active INTEGER NOT NULL,
              joined_at TEXT NOT NULL,
              left_at TEXT
            );
            CREATE TABLE IF NOT EXISTS ext_codes (
              code_hash TEXT PRIMARY KEY,
              expires_at TEXT NOT NULL,
              used INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS ext_tokens (
              token_hash TEXT PRIMARY KEY,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ext_jobs (
              id TEXT PRIMARY KEY,
              request_id TEXT NOT NULL UNIQUE,
              session_id TEXT NOT NULL,
              run_token TEXT,
              group_id TEXT,
              member_id TEXT NOT NULL,
              context_version INTEGER NOT NULL,
              group_generation INTEGER NOT NULL,
              origin TEXT NOT NULL,
              site TEXT NOT NULL,
              tab_key TEXT NOT NULL,
              prompt TEXT NOT NULL,
              status TEXT NOT NULL,
              result_text TEXT,
              model_label TEXT,
              error TEXT,
              created_at TEXT NOT NULL,
              finished_at TEXT
            );
            CREATE TABLE IF NOT EXISTS site_blocks (
              site TEXT PRIMARY KEY,
              reason TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            """
        )
        self.conn.commit()

    def _ensure_column(self, table: str, column: str, decl: str) -> None:
        cols = {row[1] for row in self.conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    def _one(self, sql: str, params: tuple = ()) -> dict | None:
        row = self.conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def _all(self, sql: str, params: tuple = ()) -> list[dict]:
        return [dict(row) for row in self.conn.execute(sql, params).fetchall()]

    def _hydrate_session(self, row: dict | None) -> dict | None:
        if not row:
            return None
        row["speaking_member_ids"] = json.loads(row.pop("speaking_json") or "[]")
        row["stop_on_no_new_point"] = bool(row["stop_on_no_new_point"])
        row["run_cost_known"] = bool(row["run_cost_known"])
        row["run_tokens_known"] = bool(row.get("run_tokens_known", 1))
        row["layout"] = row.get("layout") or "shared"
        return row

    def _hydrate_member(self, row: dict | None) -> dict | None:
        if not row:
            return None
        row["enabled"] = bool(row["enabled"])
        row["web_auto"] = bool(row.get("web_auto"))
        row["web_link"] = _web_link(row)
        raw = row.pop("web_health", None)
        try:
            row["web_health"] = json.loads(raw) if raw else None
        except (TypeError, ValueError):
            row["web_health"] = None
        return row

    def create_session(self, **fields: Any) -> dict:
        with self._lock:
            sid = new_id()
            ts = now_iso()
            self.conn.execute(
                """
                INSERT INTO sessions (
                  id, title, status, mode, max_rounds, max_ai_messages, max_seconds,
                  max_tokens, max_cost_usd, summary_mode, summary_member_id, summary_provider, summary_model_id,
                  cross_delay_ms, room_rule, stop_on_no_new_point, created_at, updated_at
                ) VALUES (?, ?, 'idle', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sid,
                    fields.get("title") or "未命名群聊",
                    fields.get("mode") or "free_chat",
                    int(fields.get("max_rounds", 3)),
                    int(fields.get("max_ai_messages", 10)),
                    float(fields.get("max_seconds", 120)),
                    fields.get("max_tokens"),
                    fields.get("max_cost_usd"),
                    fields.get("summary_mode") or "local",
                    fields.get("summary_member_id"),
                    fields.get("summary_provider"),
                    fields.get("summary_model_id"),
                    int(fields.get("cross_delay_ms", 120)),
                    fields.get("room_rule") or "",
                    1 if fields.get("stop_on_no_new_point", True) else 0,
                    ts,
                    ts,
                ),
            )
            layout = fields.get("layout") or "shared"
            if layout not in {"shared", "branches"}:
                layout = "shared"
            self.conn.execute("UPDATE sessions SET layout=? WHERE id=?", (layout, sid))
            self.conn.commit()
            return self.get_session(sid)

    def list_sessions(self) -> list[dict]:
        with self._lock:
            rows = self._all(
                """
                SELECT s.*,
                  (SELECT COUNT(*) FROM messages m WHERE m.session_id=s.id) AS message_count,
                  (SELECT COUNT(*) FROM members mb WHERE mb.session_id=s.id) AS member_count
                FROM sessions s
                ORDER BY s.updated_at DESC
                """
            )
            return [self._hydrate_session(row) for row in rows]

    def get_session(self, sid: str) -> dict | None:
        with self._lock:
            return self._hydrate_session(self._one("SELECT * FROM sessions WHERE id=?", (sid,)))

    def update_settings(self, sid: str, fields: dict) -> dict | None:
        allowed = {
            "title",
            "mode",
            "max_rounds",
            "max_ai_messages",
            "max_seconds",
            "max_tokens",
            "max_cost_usd",
            "summary_mode",
            "summary_member_id",
            "summary_provider",
            "summary_model_id",
            "cross_delay_ms",
            "room_rule",
            "stop_on_no_new_point",
        }
        with self._lock:
            current = self._one("SELECT * FROM sessions WHERE id=?", (sid,))
            if not current:
                return None
            sets = []
            params: list[Any] = []
            for key, value in fields.items():
                if key not in allowed:
                    continue
                if key == "stop_on_no_new_point":
                    value = 1 if value else 0
                sets.append(f"{key}=?")
                params.append(value)
            if sets:
                sets.append("updated_at=?")
                params.append(now_iso())
                params.append(sid)
                self.conn.execute(f"UPDATE sessions SET {', '.join(sets)} WHERE id=?", params)
                self.conn.commit()
            return self.get_session(sid)

    def delete_session(self, sid: str) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM messages WHERE session_id=?", (sid,))
            self.conn.execute("DELETE FROM group_members WHERE session_id=?", (sid,))
            self.conn.execute("DELETE FROM groups WHERE session_id=?", (sid,))
            self.conn.execute("DELETE FROM members WHERE session_id=?", (sid,))
            self.conn.execute("DELETE FROM steps WHERE session_id=?", (sid,))
            self.conn.execute("DELETE FROM runs WHERE session_id=?", (sid,))
            self.conn.execute("DELETE FROM highlights WHERE session_id=?", (sid,))
            self.conn.execute("DELETE FROM sessions WHERE id=?", (sid,))
            self.conn.commit()

    def insert_run(self, sid: str, run_token: str, mode: str, trigger_message_id: str | None) -> None:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO runs (id, session_id, run_token, mode, status, trigger_message_id, created_at)
                VALUES (?, ?, ?, ?, 'running', ?, ?)
                """,
                (new_id(), sid, run_token, mode, trigger_message_id, now_iso()),
            )
            self.conn.commit()

    def finish_run_row(self, run_token: str, status: str, end_reason: str | None) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE runs SET status=?, end_reason=?, finished_at=? WHERE run_token=?",
                (status, end_reason, now_iso(), run_token),
            )
            self.conn.commit()

    def count_runs(self, sid: str) -> int:
        with self._lock:
            row = self._one("SELECT COUNT(*) AS n FROM runs WHERE session_id=?", (sid,))
            return int(row["n"] if row else 0)

    def begin_run(
        self,
        sid: str,
        run_token: str,
        mode: str,
        started_at: str,
        deadline_at: str,
        *,
        reset_budget: bool = True,
    ) -> bool:
        with self._lock:
            if reset_budget:
                cur = self.conn.execute(
                    """
                    UPDATE sessions SET
                      status='running', mode=?, run_token=?, current_round=0, ai_message_count=0,
                      run_tokens=0, run_cost_usd=0, run_cost_known=1, run_tokens_known=1, end_reason=NULL,
                      speaking_json='[]', started_at=?, deadline_at=?, updated_at=?
                    WHERE id=? AND status NOT IN ('running', 'paused')
                    """,
                    (mode, run_token, started_at, deadline_at, now_iso(), sid),
                )
            else:
                cur = self.conn.execute(
                    """
                    UPDATE sessions SET
                      status='running', mode=?, run_token=?, current_round=0, end_reason=NULL,
                      speaking_json='[]', updated_at=?
                    WHERE id=? AND status NOT IN ('running', 'paused')
                    """,
                    (mode, run_token, now_iso(), sid),
                )
            self.conn.commit()
            return cur.rowcount == 1

    def remember_parent_budget(self, sid: str, started_at: str, deadline_at: str) -> None:
        with self._lock:
            self.conn.execute(
                """
                UPDATE sessions SET parent_started_at=?, parent_deadline_at=?, updated_at=?
                WHERE id=? AND (parent_started_at IS NULL OR parent_started_at='')
                """,
                (started_at, deadline_at, now_iso(), sid),
            )
            self.conn.commit()

    def mark_tokens_unknown(self, sid: str) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE sessions SET run_tokens_known=0, updated_at=? WHERE id=?",
                (now_iso(), sid),
            )
            self.conn.commit()

    def stop_session(self, sid: str, run_token: str | None, reason: str) -> bool:
        with self._lock:
            cur = self.conn.execute(
                """
                UPDATE sessions SET status='stopped', end_reason=?, speaking_json='[]', updated_at=?
                WHERE id=? AND (? IS NULL OR run_token=?) AND status IN ('running', 'paused')
                  AND (end_reason IS NULL OR end_reason='')
                """,
                (reason, now_iso(), sid, run_token, run_token),
            )
            self.conn.commit()
            return cur.rowcount == 1

    def finish_session(self, sid: str, run_token: str, status: str, reason: str) -> bool:
        with self._lock:
            cur = self.conn.execute(
                """
                UPDATE sessions SET status=?, end_reason=?, speaking_json='[]', updated_at=?
                WHERE id=? AND run_token=? AND status IN ('running', 'paused')
                """,
                (status, reason, now_iso(), sid, run_token),
            )
            self.conn.commit()
            return cur.rowcount == 1

    def set_paused(self, sid: str, paused: bool) -> bool:
        with self._lock:
            if paused:
                cur = self.conn.execute(
                    "UPDATE sessions SET status='paused', updated_at=? WHERE id=? AND status='running'",
                    (now_iso(), sid),
                )
            else:
                cur = self.conn.execute(
                    "UPDATE sessions SET status='running', updated_at=? WHERE id=? AND status='paused'",
                    (now_iso(), sid),
                )
            self.conn.commit()
            return cur.rowcount == 1

    def bump_context(self, sid: str) -> int:
        with self._lock:
            self.conn.execute(
                "UPDATE sessions SET context_version=context_version+1, updated_at=? WHERE id=?",
                (now_iso(), sid),
            )
            self.conn.commit()
            row = self._one("SELECT context_version FROM sessions WHERE id=?", (sid,))
            return int(row["context_version"]) if row else 0

    def inc_round(self, sid: str) -> int:
        with self._lock:
            self.conn.execute(
                "UPDATE sessions SET current_round=current_round+1, updated_at=? WHERE id=?",
                (now_iso(), sid),
            )
            self.conn.commit()
            row = self._one("SELECT current_round FROM sessions WHERE id=?", (sid,))
            return int(row["current_round"]) if row else 0

    def reserve_slot(
        self,
        sid: str,
        cap: int,
        prompt_tokens: int = 0,
        cost_known: bool = True,
    ) -> tuple[bool, str | None]:
        with self._lock:
            session = self._one("SELECT * FROM sessions WHERE id=?", (sid,))
            if not session or session["status"] != "running":
                return False, "not_running"
            if session["ai_message_count"] >= session["max_ai_messages"] or session["ai_message_count"] >= cap:
                return False, "limit_messages"
            incoming = max(0, int(prompt_tokens))
            if session["max_tokens"] is not None and int(session["run_tokens"]) + incoming > int(session["max_tokens"]):
                return False, "limit_tokens"
            if session["max_cost_usd"] is not None:
                if not cost_known or not int(session.get("run_cost_known") or 0):
                    return False, "limit_cost"
                if float(session["run_cost_usd"]) >= float(session["max_cost_usd"]) - 1e-9:
                    return False, "limit_cost"
            self.conn.execute(
                """
                UPDATE sessions SET
                  ai_message_count=ai_message_count+1,
                  run_tokens=run_tokens+?,
                  total_tokens=total_tokens+?,
                  updated_at=?
                WHERE id=?
                """,
                (incoming, incoming, now_iso(), sid),
            )
            self.conn.commit()
            return True, None

    def add_usage(
        self,
        sid: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost: float,
        cost_known: bool,
        reserved_prompt: int = 0,
    ) -> None:
        with self._lock:
            tokens = max(0, int(prompt_tokens) - int(reserved_prompt)) + int(completion_tokens)
            known_sql = "" if cost_known else ", run_cost_known=0"
            self.conn.execute(
                f"""
                UPDATE sessions SET
                  run_tokens=run_tokens+?,
                  total_tokens=total_tokens+?,
                  run_cost_usd=run_cost_usd+?,
                  total_cost_usd=total_cost_usd+?,
                  updated_at=?
                  {known_sql}
                WHERE id=?
                """,
                (tokens, tokens, cost, cost, now_iso(), sid),
            )
            self.conn.commit()

    def set_speaking(self, sid: str, member_id: str, on: bool) -> None:
        with self._lock:
            row = self._one("SELECT speaking_json FROM sessions WHERE id=?", (sid,))
            if not row:
                return
            current = json.loads(row["speaking_json"] or "[]")
            if on and member_id not in current:
                current.append(member_id)
            if not on:
                current = [item for item in current if item != member_id]
            self.conn.execute(
                "UPDATE sessions SET speaking_json=?, updated_at=? WHERE id=?",
                (json.dumps(current), now_iso(), sid),
            )
            self.conn.commit()

    def list_unfinished(self) -> list[dict]:
        with self._lock:
            rows = self._all("SELECT * FROM sessions WHERE status IN ('running', 'paused')")
            return [self._hydrate_session(row) for row in rows]

    def create_member(self, **fields: Any) -> dict:
        with self._lock:
            mid = new_id()
            count = self._one("SELECT COUNT(*) AS n FROM members WHERE session_id=?", (fields["session_id"],))
            color = fields.get("avatar_color") or MEMBER_COLORS[int(count["n"]) % len(MEMBER_COLORS)]
            self.conn.execute(
                """
                INSERT INTO members (
                  id, session_id, nickname, role_name, persona, provider, model_id,
                  api_base, api_key_env, enabled, avatar_color, sort_order, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mid,
                    fields["session_id"],
                    fields["nickname"],
                    fields["role_name"],
                    fields.get("persona") or "",
                    fields["provider"],
                    fields["model_id"],
                    fields.get("api_base"),
                    fields.get("api_key_env"),
                    1 if fields.get("enabled", True) else 0,
                    color,
                    int(count["n"]),
                    now_iso(),
                ),
            )
            self.conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now_iso(), fields["session_id"]))
            session = self._one("SELECT layout FROM sessions WHERE id=?", (fields["session_id"],))
            if session and (session.get("layout") or "shared") == "branches":
                self._ensure_branch(fields["session_id"], mid, fields["nickname"])
            self.conn.commit()
            return self.get_member(mid)

    def get_member(self, mid: str) -> dict | None:
        with self._lock:
            return self._hydrate_member(self._one("SELECT * FROM members WHERE id=?", (mid,)))

    def list_members(self, sid: str) -> list[dict]:
        with self._lock:
            rows = self._all("SELECT * FROM members WHERE session_id=? ORDER BY sort_order, created_at", (sid,))
            return [self._hydrate_member(row) for row in rows]

    def nickname_taken(self, sid: str, nickname: str, exclude: str | None = None) -> bool:
        with self._lock:
            if exclude:
                row = self._one(
                    "SELECT id FROM members WHERE session_id=? AND nickname=? AND id!=?",
                    (sid, nickname, exclude),
                )
            else:
                row = self._one("SELECT id FROM members WHERE session_id=? AND nickname=?", (sid, nickname))
            return row is not None

    def update_member(self, mid: str, fields: dict) -> dict | None:
        allowed = {
            "nickname",
            "role_name",
            "persona",
            "provider",
            "model_id",
            "api_base",
            "api_key_env",
            "enabled",
            "avatar_color",
            "web_site",
            "web_origin",
            "web_tab_key",
            "web_model_label",
            "web_conversation",
            "web_auto",
            "web_seen_at",
        }
        with self._lock:
            sets = []
            params: list[Any] = []
            for key, value in fields.items():
                if key not in allowed:
                    continue
                if key in {"enabled", "web_auto"}:
                    value = 1 if value else 0
                sets.append(f"{key}=?")
                params.append(value)
            if not sets:
                return self.get_member(mid)
            params.append(mid)
            self.conn.execute(f"UPDATE members SET {', '.join(sets)} WHERE id=?", params)
            self.conn.commit()
            member = self.get_member(mid)
            if member:
                self.conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now_iso(), member["session_id"]))
                self.conn.commit()
            return member

    def delete_member(self, mid: str) -> None:
        with self._lock:
            member = self._one("SELECT session_id FROM members WHERE id=?", (mid,))
            self.conn.execute("DELETE FROM members WHERE id=?", (mid,))
            if member:
                self.conn.execute(
                    "UPDATE sessions SET summary_member_id=NULL WHERE summary_member_id=?",
                    (mid,),
                )
                self.conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now_iso(), member["session_id"]))
            self.conn.commit()

    def add_message(self, fields: dict) -> dict:
        with self._lock:
            mid = fields.get("id") or new_id()
            ts = fields.get("created_at") or now_iso()
            self.conn.execute(
                """
                INSERT INTO messages (
                  id, session_id, author_type, member_id, nickname, role_name, provider, model_id,
                  avatar_color, content, status, reply_to_id, round_number, phase, context_version,
                  run_token, step_key, suggest_next_id, suggest_next_nickname, prompt_tokens,
                  completion_tokens, cost_usd, has_new_point, is_demo, is_summary, discarded_reason,
                  group_id, audience, target_member_id, event_kind, source_message_id, source_group_id,
                  created_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mid,
                    fields["session_id"],
                    fields["author_type"],
                    fields.get("member_id"),
                    fields.get("nickname"),
                    fields.get("role_name"),
                    fields.get("provider"),
                    fields.get("model_id"),
                    fields.get("avatar_color"),
                    fields.get("content") or "",
                    fields.get("status") or "complete",
                    fields.get("reply_to_id"),
                    fields.get("round_number"),
                    fields.get("phase"),
                    int(fields.get("context_version") or 0),
                    fields.get("run_token"),
                    fields.get("step_key"),
                    fields.get("suggest_next_id"),
                    fields.get("suggest_next_nickname"),
                    int(fields.get("prompt_tokens") or 0),
                    int(fields.get("completion_tokens") or 0),
                    float(fields.get("cost_usd") or 0),
                    1 if fields.get("has_new_point") else 0,
                    1 if fields.get("is_demo") else 0,
                    1 if fields.get("is_summary") else 0,
                    fields.get("discarded_reason"),
                    fields.get("group_id"),
                    fields.get("audience"),
                    fields.get("target_member_id"),
                    fields.get("event_kind"),
                    fields.get("source_message_id"),
                    fields.get("source_group_id"),
                    ts,
                    fields.get("finished_at"),
                ),
            )
            self.conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now_iso(), fields["session_id"]))
            self.conn.commit()
            return self.get_message(mid)

    def get_message(self, mid: str) -> dict | None:
        with self._lock:
            row = self._one("SELECT * FROM messages WHERE id=?", (mid,))
            return _bool_message(row) if row else None

    def update_message(self, mid: str, **fields: Any) -> dict | None:
        allowed = {
            "content",
            "status",
            "finished_at",
            "discarded_reason",
            "has_new_point",
            "is_demo",
            "is_summary",
            "prompt_tokens",
            "completion_tokens",
            "cost_usd",
            "provider",
            "model_id",
            "nickname",
            "role_name",
        }
        with self._lock:
            sets = []
            params: list[Any] = []
            for key, value in fields.items():
                if key not in allowed:
                    continue
                if key in {"has_new_point", "is_demo", "is_summary"}:
                    value = 1 if value else 0
                sets.append(f"{key}=?")
                params.append(value)
            if sets:
                params.append(mid)
                self.conn.execute(f"UPDATE messages SET {', '.join(sets)} WHERE id=?", params)
                self.conn.commit()
            return self.get_message(mid)

    def append_message(self, mid: str, chunk: str) -> dict | None:
        with self._lock:
            self.conn.execute("UPDATE messages SET content=content || ? WHERE id=?", (chunk, mid))
            self.conn.commit()
            return self.get_message(mid)

    def list_highlights(self, sid: str) -> list[dict]:
        with self._lock:
            rows = self._all(
                "SELECT * FROM highlights WHERE session_id=? ORDER BY created_at, rowid",
                (sid,),
            )
            return [dict(row) for row in rows]

    def save_highlight(self, sid: str, message_id: str, title: str, note: str) -> dict:
        with self._lock:
            existing = self._one(
                "SELECT id FROM highlights WHERE session_id=? AND message_id=?",
                (sid, message_id),
            )
            if existing:
                self.conn.execute(
                    "UPDATE highlights SET title=?, note=? WHERE id=?",
                    (title, note, existing["id"]),
                )
                hid = existing["id"]
            else:
                hid = new_id()
                self.conn.execute(
                    """
                    INSERT INTO highlights (id, session_id, message_id, title, note, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (hid, sid, message_id, title, note, now_iso()),
                )
            self.conn.commit()
            row = self._one("SELECT * FROM highlights WHERE id=?", (hid,))
            return dict(row)

    def delete_highlight(self, sid: str, hid: str) -> bool:
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM highlights WHERE session_id=? AND id=?",
                (sid, hid),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def list_messages(self, sid: str) -> list[dict]:
        with self._lock:
            rows = self._all(
                "SELECT * FROM messages WHERE session_id=? ORDER BY created_at, rowid",
                (sid,),
            )
            return [_bool_message(row) for row in rows]

    def model_transcript(self, sid: str) -> list[dict]:
        return [
            m
            for m in self.list_messages(sid)
            if m["status"] == "complete" and m["author_type"] in {"user", "ai"} and not m["is_summary"]
        ]

    def has_summary(self, run_token: str | None) -> bool:
        if not run_token:
            return False
        with self._lock:
            row = self._one(
                "SELECT id FROM messages WHERE run_token=? AND is_summary=1 AND status='complete' LIMIT 1",
                (run_token,),
            )
            return row is not None

    def complete_ai_in_run(self, sid: str, run_token: str) -> list[dict]:
        with self._lock:
            rows = self._all(
                """
                SELECT * FROM messages
                WHERE session_id=? AND run_token=? AND author_type='ai' AND status='complete' AND is_summary=0
                ORDER BY created_at, rowid
                """,
                (sid, run_token),
            )
            return [_bool_message(row) for row in rows]

    def messages_for_round(self, sid: str, run_token: str, round_number: int, phase: str) -> list[dict]:
        with self._lock:
            rows = self._all(
                """
                SELECT * FROM messages
                WHERE session_id=? AND run_token=? AND round_number=? AND phase=?
                  AND author_type='ai' AND status='complete' AND is_summary=0
                """,
                (sid, run_token, round_number, phase),
            )
            return [_bool_message(row) for row in rows]

    def cancel_streaming(self, sid: str, reason: str) -> None:
        with self._lock:
            self.conn.execute(
                """
                UPDATE messages SET status='cancelled', discarded_reason=?, finished_at=?
                WHERE session_id=? AND status='streaming'
                """,
                (reason, now_iso(), sid),
            )
            self.conn.commit()

    def has_preflight_block(self, sid: str, run_token: str, member_id: str) -> bool:
        with self._lock:
            row = self._one(
                "SELECT step_key FROM steps WHERE step_key=? AND status='preflight'",
                (f"{run_token}:preflight:{member_id}",),
            )
            return row is not None

    def insert_step(self, step_key: str, sid: str, run_token: str, status: str) -> bool:
        with self._lock:
            try:
                self.conn.execute(
                    "INSERT INTO steps (step_key, session_id, run_token, status, created_at) VALUES (?, ?, ?, ?, ?)",
                    (step_key, sid, run_token, status, now_iso()),
                )
                self.conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def step_exists(self, step_key: str) -> bool:
        with self._lock:
            return self._one("SELECT step_key FROM steps WHERE step_key=?", (step_key,)) is not None

    def finish_step(self, step_key: str, status: str) -> None:
        with self._lock:
            self.conn.execute("UPDATE steps SET status=? WHERE step_key=?", (status, step_key))
            self.conn.commit()

    def _ensure_branch(self, session_id: str, member_id: str, nickname: str) -> str:
        row = self._one(
            """
            SELECT g.id FROM groups g
            JOIN group_members gm ON gm.group_id=g.id
            WHERE gm.member_id=? AND gm.active=1 AND g.status='active'
            """,
            (member_id,),
        )
        if row:
            return row["id"]
        gid = new_id()
        now = now_iso()
        self.conn.execute(
            """
            INSERT INTO groups (id, session_id, name, kind, status, generation, settled, created_at)
            VALUES (?, ?, ?, 'branch', 'active', 0, 0, ?)
            """,
            (gid, session_id, f"{nickname} 的独立分支", now),
        )
        self.conn.execute(
            """
            INSERT INTO group_members (id, group_id, session_id, member_id, active, joined_at)
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (new_id(), gid, session_id, member_id, now),
        )
        return gid

    def list_groups(self, sid: str) -> list[dict]:
        with self._lock:
            groups = self._all(
                "SELECT * FROM groups WHERE session_id=? ORDER BY created_at, rowid",
                (sid,),
            )
            for group in groups:
                members = self._all(
                    """
                    SELECT member_id FROM group_members
                    WHERE group_id=? AND active=1 ORDER BY joined_at, rowid
                    """,
                    (group["id"],),
                )
                group["member_ids"] = [item["member_id"] for item in members]
                group["settled"] = bool(group.get("settled"))
            return groups

    def get_group(self, gid: str) -> dict | None:
        with self._lock:
            group = self._one("SELECT * FROM groups WHERE id=?", (gid,))
            if not group:
                return None
            members = self._all(
                "SELECT member_id FROM group_members WHERE group_id=? AND active=1 ORDER BY joined_at",
                (gid,),
            )
            group["member_ids"] = [item["member_id"] for item in members]
            group["settled"] = bool(group.get("settled"))
            return group

    def active_group_id(self, member_id: str) -> str | None:
        with self._lock:
            row = self._one(
                """
                SELECT g.id FROM groups g
                JOIN group_members gm ON gm.group_id=g.id
                WHERE gm.member_id=? AND gm.active=1 AND g.status='active'
                """,
                (member_id,),
            )
            return row["id"] if row else None

    def set_groups_settled(self, group_ids: list[str], settled: bool) -> None:
        with self._lock:
            for gid in group_ids:
                self.conn.execute("UPDATE groups SET settled=? WHERE id=?", (1 if settled else 0, gid))
            self.conn.commit()

    def bump_groups(self, group_ids: list[str]) -> None:
        with self._lock:
            for gid in group_ids:
                self.conn.execute(
                    "UPDATE groups SET generation=generation+1, settled=0 WHERE id=?",
                    (gid,),
                )
            self.conn.commit()

    def set_group_status(self, gid: str, status: str) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE groups SET status=?, generation=generation+1, settled=0 WHERE id=?",
                (status, gid),
            )
            self.conn.commit()

    def move_members(
        self,
        session_id: str,
        member_ids: list[str],
        *,
        kind: str,
        name: str,
        event_kind: str,
        event_text: str,
        context_version: int,
        run_token: str | None,
    ) -> dict:
        with self._lock:
            now = now_iso()
            touched: list[str] = []
            for member_id in member_ids:
                rows = self._all(
                    """
                    SELECT group_id FROM group_members
                    WHERE member_id=? AND active=1
                    """,
                    (member_id,),
                )
                for row in rows:
                    touched.append(row["group_id"])
                    self.conn.execute(
                        "UPDATE group_members SET active=0, left_at=? WHERE group_id=? AND member_id=? AND active=1",
                        (now, row["group_id"], member_id),
                    )
            for gid in set(touched):
                left = self._one(
                    "SELECT COUNT(*) AS n FROM group_members WHERE group_id=? AND active=1",
                    (gid,),
                )
                if int(left["n"]) == 0:
                    self.conn.execute(
                        "UPDATE groups SET status='closed', generation=generation+1, settled=0 WHERE id=? AND status='active'",
                        (gid,),
                    )
                else:
                    self.conn.execute(
                        "UPDATE groups SET generation=generation+1, settled=0 WHERE id=?",
                        (gid,),
                    )
            gid = new_id()
            self.conn.execute(
                """
                INSERT INTO groups (id, session_id, name, kind, status, generation, settled, created_at)
                VALUES (?, ?, ?, ?, 'active', 1, 0, ?)
                """,
                (gid, session_id, name, kind, now),
            )
            for member_id in member_ids:
                self.conn.execute(
                    """
                    INSERT INTO group_members (id, group_id, session_id, member_id, active, joined_at)
                    VALUES (?, ?, ?, ?, 1, ?)
                    """,
                    (new_id(), gid, session_id, member_id, now),
                )
            self.conn.commit()
        self.add_message(
            {
                "session_id": session_id,
                "author_type": "system",
                "nickname": "房间",
                "content": event_text,
                "status": "complete",
                "phase": "meta",
                "context_version": context_version,
                "run_token": run_token,
                "group_id": gid,
                "event_kind": event_kind,
                "finished_at": now_iso(),
            }
        )
        return self.get_group(gid)
