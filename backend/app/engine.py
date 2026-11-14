"""Chat-room scheduler. Model text is never a new user turn."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import time
from datetime import datetime, timedelta, timezone

from .db import Database
from .groups import quote_block, same_active_group, share_plan, visible_messages
from .providers import GenRequest, ProviderError, render_prompt, web_forward_text
from .summary import build_summary
from .util import excerpt, infer_new_point, mention_ids, new_id, now_iso, reason_label, redact, status_for

LIMITS = {"limit_messages", "limit_tokens", "limit_cost", "limit_time", "limit_rounds"}
HARD_STOP_SUMMARY = {"user_stop", "limit_time", "server_restart", "provider_failed", "engine_error"}


def wants_model_summary(session: dict) -> bool:
    if session.get("summary_mode") == "member" and session.get("summary_member_id"):
        return True
    if session.get("summary_mode") == "provider" and session.get("summary_provider") and session.get("summary_model_id"):
        return True
    return False


def discussion_cap(session: dict) -> int:
    cap = int(session["max_ai_messages"])
    if wants_model_summary(session) and cap >= 2:
        return cap - 1
    return cap


def input_token_estimate(request: GenRequest) -> int:
    """Count the prompt we are about to send. This is the input budget, not a price."""
    return max(1, len(request.prompt or ""))


def _jitter(member_id: str, round_no: int, version: int) -> float:
    digest = hashlib.sha256(f"{member_id}:{round_no}:{version}".encode()).hexdigest()
    return int(digest[:4], 16) % 100 / 10


class RoomEngine:
    def __init__(self, db: Database, provider):
        self.db = db
        self.provider = provider
        self.tasks: dict[str, asyncio.Task] = {}
        self.cancels: dict[str, asyncio.Event] = {}
        self.stales: dict[str, set[asyncio.Event]] = {}
        self.locks: dict[str, asyncio.Lock] = {}
        self.deadlines: dict[str, float] = {}
        self.subscribers: dict[str, set[asyncio.Queue]] = {}

    def _lock(self, session_id: str) -> asyncio.Lock:
        if session_id not in self.locks:
            self.locks[session_id] = asyncio.Lock()
        return self.locks[session_id]

    def subscribe(self, session_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=400)
        self.subscribers.setdefault(session_id, set()).add(queue)
        return queue

    def unsubscribe(self, session_id: str, queue: asyncio.Queue) -> None:
        self.subscribers.get(session_id, set()).discard(queue)

    def attach_web_progress(self, bridge) -> None:
        labels = {
            "filled": "已填入，尚未发送",
            "waiting": "等待回复",
            "unsent": "已填入，未发送",
            "timeout": "超时",
        }

        def publish(job: dict, phase: str) -> None:
            text = labels.get(phase)
            if not text:
                return
            for message in reversed(self.db.list_messages(job["session_id"])):
                if message.get("member_id") == job.get("member_id") and message.get("status") == "streaming":
                    updated = self.db.update_message(message["id"], content=text)
                    self.publish(job["session_id"], "message", updated)
                    return

        bridge.on_progress = publish

    def publish(self, session_id: str, event: str, data) -> None:
        payload = {"event": event, "data": data}
        for queue in list(self.subscribers.get(session_id, set())):
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(payload)

    def publish_state(self, session_id: str) -> None:
        session = self.db.get_session(session_id)
        if session:
            self.publish(session_id, "session", session)

    def _pulse_stale(self, session_id: str) -> None:
        for event in list(self.stales.get(session_id, set())):
            event.set()

    async def ingest_message(
        self,
        session_id: str,
        content: str,
        reply_to_id: str | None = None,
        mode: str | None = None,
        author_type: str = "user",
        audience: str | None = None,
        group_id: str | None = None,
        target_member_id: str | None = None,
    ) -> dict:
        if author_type != "user":
            return {"ok": False, "error": "model_output_cannot_trigger"}
        text = (content or "").strip()
        if not text:
            return {"ok": False, "error": "empty"}
        session = self.db.get_session(session_id)
        if not session:
            return {"ok": False, "error": "missing"}
        if reply_to_id:
            target = self.db.get_message(reply_to_id)
            if not target or target["session_id"] != session_id:
                return {"ok": False, "error": "bad_reply"}
        if mode:
            self.db.update_settings(session_id, {"mode": mode})
        layout = session.get("layout") or "shared"
        if layout == "branches":
            audience = audience or "all"
            if audience not in {"all", "group", "member"}:
                return {"ok": False, "error": "bad_audience"}
            if audience == "group" and not group_id:
                return {"ok": False, "error": "bad_audience"}
            if audience == "member" and not target_member_id:
                return {"ok": False, "error": "bad_audience"}
        else:
            audience = None
            group_id = None
            target_member_id = None
        version = self.db.bump_context(session_id)
        session = self.db.get_session(session_id)
        message = self.db.add_message(
            {
                "session_id": session_id,
                "author_type": "user",
                "nickname": "我",
                "content": text,
                "status": "complete",
                "reply_to_id": reply_to_id,
                "context_version": version,
                "run_token": session.get("run_token") if session["status"] in {"running", "paused"} else None,
                "finished_at": now_iso(),
                "audience": audience,
                "group_id": group_id,
                "target_member_id": target_member_id,
            }
        )
        if layout == "branches":
            self._wake_groups(session_id, audience or "all", group_id, target_member_id)
        if session["title"] in {"", "未命名群聊"}:
            self.db.update_settings(session_id, {"title": text[:24]})
        self._pulse_stale(session_id)
        self.publish(session_id, "message", message)
        self.publish_state(session_id)
        session = self.db.get_session(session_id)
        if session["status"] == "running":
            return {"ok": True, "message": message, "interrupted": True}
        if session["status"] == "paused":
            return {"ok": True, "message": message, "queued": True}
        started = await self.start(session_id, mode=mode, trigger_message_id=message["id"])
        return {"ok": True, "message": message, "run": started}

    async def start(self, session_id: str, mode: str | None = None, trigger_message_id: str | None = None) -> dict:
        async with self._lock(session_id):
            session = self.db.get_session(session_id)
            if not session:
                return {"ok": False, "error": "missing"}
            task = self.tasks.get(session_id)
            alive = task is not None and not task.done()
            if session["status"] == "running" and alive:
                return {"ok": True, "already": True, "run_token": session["run_token"]}
            if session["status"] == "paused" and alive:
                return {"ok": False, "error": "paused", "run_token": session["run_token"]}
            if session["status"] in {"running", "paused"} and not alive:
                self.db.stop_session(session_id, session.get("run_token"), "engine_error")
            if mode:
                self.db.update_settings(session_id, {"mode": mode})
            session = self.db.get_session(session_id)
            run_token = new_id()
            started = datetime.now(timezone.utc)
            keep_parent = (session.get("layout") == "branches") and bool(session.get("parent_started_at"))
            if keep_parent:
                deadline_at = session["parent_deadline_at"]
                deadline_dt = datetime.fromisoformat(deadline_at)
                remaining = (deadline_dt - datetime.now(timezone.utc)).total_seconds()
            else:
                deadline_dt = started + timedelta(seconds=float(session["max_seconds"]))
                deadline_at = deadline_dt.isoformat()
                remaining = float(session["max_seconds"])
            self.db.insert_run(session_id, run_token, session["mode"], trigger_message_id)
            if not self.db.begin_run(
                session_id,
                run_token,
                session["mode"],
                started.isoformat(),
                deadline_at,
                reset_budget=not keep_parent,
            ):
                return {"ok": False, "error": "could_not_start"}
            if not keep_parent and session.get("layout") == "branches":
                self.db.remember_parent_budget(session_id, started.isoformat(), deadline_at)
            cancel = asyncio.Event()
            self.cancels[session_id] = cancel
            self.stales[session_id] = set()
            self.deadlines[session_id] = time.monotonic() + max(0.0, remaining)
            self.tasks[session_id] = asyncio.create_task(self._run(session_id, run_token, cancel))
            self.publish_state(session_id)
            return {"ok": True, "already": False, "run_token": run_token}

    async def pause(self, session_id: str) -> dict:
        ok = self.db.set_paused(session_id, True)
        self.publish_state(session_id)
        return {"ok": ok} if ok else {"ok": False, "error": "not_running"}

    async def resume(self, session_id: str) -> dict:
        ok = self.db.set_paused(session_id, False)
        self.publish_state(session_id)
        return {"ok": ok} if ok else {"ok": False, "error": "not_paused"}

    async def stop(self, session_id: str) -> dict:
        session = self.db.get_session(session_id)
        if not session:
            return {"ok": False, "error": "missing"}
        if session["status"] not in {"running", "paused"}:
            return {"ok": True, "already": True}
        self.db.stop_session(session_id, session.get("run_token"), "user_stop")
        web = getattr(self, "web", None)
        if web:
            web.cancel_session(session_id, "user_stop")
        cancel = self.cancels.get(session_id)
        if cancel:
            cancel.set()
        self._pulse_stale(session_id)
        self.publish_state(session_id)
        return {"ok": True}

    async def recover(self) -> None:
        for session in self.db.list_unfinished():
            session_id = session["id"]
            cancel = self.cancels.get(session_id)
            if cancel:
                cancel.set()
            self._pulse_stale(session_id)
            self.db.cancel_streaming(session_id, "server_restart")
            self.db.stop_session(session_id, session.get("run_token"), "server_restart")
            await self._emit_summary(session_id, session.get("run_token"), "server_restart", asyncio.Event())
            task = self.tasks.get(session_id)
            if task and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            if session.get("run_token"):
                self.db.finish_run_row(session["run_token"], "stopped", "server_restart")
            self.publish_state(session_id)

    async def shutdown(self) -> None:
        for cancel in self.cancels.values():
            cancel.set()
        for task in list(self.tasks.values()):
            if not task.done():
                task.cancel()
        for task in list(self.tasks.values()):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    async def _run(self, session_id: str, run_token: str, cancel: asyncio.Event) -> None:
        watchdog = asyncio.create_task(self._watchdog(session_id, run_token, cancel))
        try:
            reason = await self._loop(session_id, run_token, cancel)
            await self._close(session_id, run_token, reason, cancel)
        except asyncio.CancelledError:
            session = self.db.get_session(session_id)
            reason = (session or {}).get("end_reason") or "server_restart"
            await self._close(session_id, run_token, reason, cancel)
            raise
        except Exception as exc:
            self._system(session_id, f"调度出错：{redact(str(exc))}")
            await self._close(session_id, run_token, "engine_error", cancel)
        finally:
            watchdog.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watchdog

    async def _watchdog(self, session_id: str, run_token: str, cancel: asyncio.Event) -> None:
        try:
            while not cancel.is_set():
                deadline = self.deadlines.get(session_id, time.monotonic())
                left = deadline - time.monotonic()
                if left <= 0:
                    self.db.stop_session(session_id, run_token, "limit_time")
                    cancel.set()
                    self._pulse_stale(session_id)
                    self.publish_state(session_id)
                    return
                await asyncio.sleep(min(0.05, left))
        except asyncio.CancelledError:
            return

    async def _loop(self, session_id: str, run_token: str, cancel: asyncio.Event) -> str:
        session = self.db.get_session(session_id)
        if session and session.get("layout") == "branches":
            return await self._branch_loop(session_id, run_token, cancel)
        while not cancel.is_set():
            if not await self._wait_running(session_id, cancel):
                session = self.db.get_session(session_id)
                return (session or {}).get("end_reason") or "user_stop"
            session = self.db.get_session(session_id)
            if session["status"] in {"stopped", "finished", "failed"}:
                return session.get("end_reason") or "user_stop"
            if session.get("run_token") != run_token:
                return "engine_error"
            expired = self._expire_if_needed(session_id, session)
            if expired:
                return expired
            budget = self._over_budget(session)
            if budget:
                return budget
            transcript = self.db.model_transcript(session_id)
            users = [item for item in transcript if item["author_type"] == "user"]
            if session["mode"] == "summary":
                return "summary_only" if transcript else "no_user_message"
            if not users:
                return "no_user_message"
            members = [item for item in self.db.list_members(session_id) if item["enabled"]]
            if not members:
                return "no_members"
            latest_user = users[-1]["content"]
            picked = self._participants(session_id, session, members, latest_user)
            if not picked:
                self._system(session_id, "点名的成员都没有启用。")
                return "no_members"
            established = self.db.complete_ai_in_run(session_id, run_token)
            if session["mode"] == "independent" or not established:
                if session["current_round"] >= session["max_rounds"]:
                    return "limit_rounds"
                code = await self._independent(session_id, run_token, cancel, picked, session["context_version"])
                if code == "version_changed":
                    continue
                if code in LIMITS or code in {"stopped", "provider_failed", "no_members"}:
                    if code == "stopped":
                        return self.db.get_session(session_id).get("end_reason") or "user_stop"
                    return code
                if session["mode"] == "independent":
                    fresh = self.db.get_session(session_id)
                    if fresh["context_version"] != session["context_version"] and fresh["current_round"] < fresh["max_rounds"]:
                        continue
                    return "independent_complete"
                continue
            if session["current_round"] >= session["max_rounds"]:
                return "limit_rounds"
            if session["stop_on_no_new_point"] and session["current_round"] >= 2:
                previous = self.db.messages_for_round(session_id, run_token, session["current_round"], "cross")
                if previous and not any(item["has_new_point"] for item in previous):
                    return "no_new_viewpoints"
            code = await self._cross(session_id, run_token, cancel, picked, session["context_version"])
            if code == "version_changed":
                continue
            if code == "no_new":
                return "no_new_viewpoints"
            if code == "all_passed":
                return "all_passed"
            if code == "stopped":
                return self.db.get_session(session_id).get("end_reason") or "user_stop"
            if code in LIMITS or code == "provider_failed":
                return code
        session = self.db.get_session(session_id)
        return (session or {}).get("end_reason") or "user_stop"

    async def _wait_flags(self, cancel: asyncio.Event, stale: asyncio.Event) -> None:
        while not cancel.is_set() and not stale.is_set():
            await asyncio.sleep(0.05)

    async def _wait_running(self, session_id: str, cancel: asyncio.Event) -> bool:
        while True:
            if cancel.is_set():
                return False
            session = self.db.get_session(session_id)
            if not session:
                return False
            if session["status"] == "paused":
                await asyncio.sleep(0.05)
                continue
            return session["status"] == "running"

    def _expire_if_needed(self, session_id: str, session: dict) -> str | None:
        deadline = self.deadlines.get(session_id)
        if deadline is not None and time.monotonic() >= deadline:
            self.db.stop_session(session_id, session.get("run_token"), "limit_time")
            cancel = self.cancels.get(session_id)
            if cancel:
                cancel.set()
            self._pulse_stale(session_id)
            return "limit_time"
        return None

    def _over_budget(self, session: dict) -> str | None:
        if session["max_tokens"] is not None and session["run_tokens"] >= session["max_tokens"]:
            return "limit_tokens"
        if session["max_cost_usd"] is not None and not int(session.get("run_cost_known") or 0):
            return "limit_cost"
        if session["max_cost_usd"] is not None and float(session["run_cost_usd"]) >= float(session["max_cost_usd"]) - 1e-9:
            return "limit_cost"
        if session["ai_message_count"] >= session["max_ai_messages"]:
            return "limit_messages"
        return None

    def _participants(self, session_id: str, session: dict, members: list[dict], text: str) -> list[dict]:
        ids = mention_ids(text, members)
        if "@" in text and not ids and session["current_round"] == 0:
            self._system(session_id, "没有匹配到 @ 的成员，这一轮仍邀请全部启用成员。")
        if ids:
            return [member for member in members if member["id"] in ids]
        return members

    def _wake_groups(self, session_id: str, audience: str, group_id: str | None, target_member_id: str | None) -> None:
        groups = self.db.list_groups(session_id)
        if audience == "all":
            ids = [item["id"] for item in groups if item["status"] == "active"]
        elif audience == "group" and group_id:
            ids = [group_id]
        elif audience == "member" and target_member_id:
            found = self.db.active_group_id(target_member_id)
            ids = [found] if found else []
        else:
            ids = []
        if ids:
            self.db.set_groups_settled(ids, False)

    def _group_idle(self, group: dict, members: list[dict], messages: list[dict]) -> bool:
        pending_independent = False
        for member in members:
            transcript = visible_messages(messages, group["id"], member["id"])
            markers = [
                item
                for item in transcript
                if item["author_type"] == "user" or item.get("event_kind") in {"merge", "split", "share"}
            ]
            if not markers:
                continue
            mark = markers[-1]["context_version"]
            answered = any(
                item["author_type"] == "ai"
                and item.get("member_id") == member["id"]
                and item.get("group_id") == group["id"]
                and item["context_version"] >= mark
                for item in transcript
            )
            if not answered:
                pending_independent = True
        if pending_independent:
            return False
        if group["kind"] == "branch" or len(members) < 2:
            return True
        transcript = visible_messages(messages, group["id"], members[0]["id"])
        crosses = [item for item in transcript if item.get("phase") == "cross"]
        if not crosses:
            return False
        return not crosses[-1].get("has_new_point")

    def _plan_group(self, group: dict, members: list[dict], messages: list[dict], text: str, everyone: list[dict]) -> list[dict]:
        mentioned = set(mention_ids(text, everyone))
        pool = [member for member in members if not mentioned or member["id"] in mentioned]
        plans = []
        for member in pool:
            transcript = visible_messages(messages, group["id"], member["id"])
            markers = [
                item
                for item in transcript
                if item["author_type"] == "user" or item.get("event_kind") in {"merge", "split", "share"}
            ]
            if not markers:
                continue
            mark = markers[-1]["context_version"]
            answered = any(
                item["author_type"] == "ai"
                and item.get("member_id") == member["id"]
                and item.get("group_id") == group["id"]
                and item["context_version"] >= mark
                for item in transcript
            )
            if not answered:
                plans.append({"phase": "independent", "member": member, "peers": pool, "transcript": transcript, "group": group})
        if plans or group["kind"] == "branch" or len(pool) < 2:
            return plans
        transcript = visible_messages(messages, group["id"], pool[0]["id"])
        last = next((item for item in reversed(transcript) if item["author_type"] == "ai"), None)
        ranked = sorted(
            pool,
            key=lambda member: (
                sum(1 for item in transcript if item.get("member_id") == member["id"] and item.get("phase") == "cross"),
                member["id"] == (last or {}).get("member_id"),
            ),
        )
        speaker = ranked[0]
        speaker_transcript = visible_messages(messages, group["id"], speaker["id"])
        return [{"phase": "cross", "member": speaker, "peers": pool, "transcript": speaker_transcript, "group": group}]

    async def _branch_loop(self, session_id: str, run_token: str, cancel: asyncio.Event) -> str:
        while not cancel.is_set():
            if not await self._wait_running(session_id, cancel):
                session = self.db.get_session(session_id)
                return (session or {}).get("end_reason") or "user_stop"
            session = self.db.get_session(session_id)
            if session["status"] in {"stopped", "finished", "failed"}:
                return session.get("end_reason") or "user_stop"
            if session.get("run_token") != run_token:
                return "engine_error"
            expired = self._expire_if_needed(session_id, session)
            if expired:
                return expired
            budget = self._over_budget(session)
            if budget:
                return budget
            messages = self.db.list_messages(session_id)
            if not any(item["author_type"] == "user" and item["status"] == "complete" for item in messages):
                return "no_user_message"
            active = [item for item in self.db.list_groups(session_id) if item["status"] == "active"]
            everyone = [item for item in self.db.list_members(session_id) if item["enabled"]]
            latest_user = next((item["content"] for item in reversed(messages) if item["author_type"] == "user"), "")
            work = []
            for group in active:
                if group.get("settled"):
                    continue
                members = [self.db.get_member(mid) for mid in group["member_ids"]]
                members = [item for item in members if item and item["enabled"]]
                if not members:
                    continue
                if self._group_idle(group, members, messages):
                    self.db.set_groups_settled([group["id"]], True)
                    continue
                if session["current_round"] >= session["max_rounds"]:
                    continue
                plans = self._plan_group(group, members, messages, latest_user, everyone)
                work.extend(plans)
            active = [item for item in self.db.list_groups(session_id) if item["status"] == "active"]
            if active and all(item.get("settled") for item in active):
                return "branches_settled"
            if not work:
                if session["current_round"] >= session["max_rounds"]:
                    return "limit_rounds"
                continue
            round_no = self.db.inc_round(session_id)
            self._system(session_id, f"第 {round_no} 轮 · 各分支只看见自己的公开上下文", round_no)
            version = self.db.get_session(session_id)["context_version"]
            session = self.db.get_session(session_id)
            serial = session["max_tokens"] is not None or session["max_cost_usd"] is not None

            async def one(plan: dict) -> str:
                if not await self._wait_running(session_id, cancel):
                    return "stopped"
                if self.db.get_session(session_id)["context_version"] != version:
                    return "version_changed"
                fresh = self.db.get_session(session_id)
                return await self._speak(
                    session_id,
                    run_token,
                    cancel,
                    plan["member"],
                    plan["peers"],
                    plan["phase"],
                    round_no,
                    version,
                    discussion_cap(fresh),
                    plan["transcript"],
                    group_id=plan["group"]["id"],
                    group_generation=int(plan["group"]["generation"]),
                )

            results: list[str] = []
            if serial:
                for plan in work:
                    results.append(await one(plan))
                    if results[-1] in LIMITS or results[-1] == "stopped":
                        break
            else:
                results = list(await asyncio.gather(*[one(plan) for plan in work]))
            reduced = self._reduce(results)
            if reduced == "version_changed":
                continue
            if reduced == "stopped":
                return self.db.get_session(session_id).get("end_reason") or "user_stop"
            if reduced in LIMITS or reduced == "provider_failed":
                return reduced
        session = self.db.get_session(session_id)
        return (session or {}).get("end_reason") or "user_stop"

    async def merge_groups(self, session_id: str, member_ids: list[str], message_ids: list[str] | None = None) -> dict:
        if len(set(member_ids)) < 2:
            return {"ok": False, "error": "need_two"}
        existing = same_active_group(self.db, member_ids)
        if existing and not message_ids:
            return {"ok": True, "already": True, "group": existing, "preview": share_plan(self.db, session_id, member_ids, None)}
        try:
            plan = share_plan(self.db, session_id, member_ids, message_ids)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        names = [self.db.get_member(mid)["nickname"] for mid in member_ids]
        version = self.db.bump_context(session_id)
        session = self.db.get_session(session_id)
        if existing and message_ids:
            self.db.bump_groups([existing["id"]])
            self.db.add_message(
                {
                    "session_id": session_id,
                    "author_type": "system",
                    "nickname": "房间",
                    "content": quote_block(plan, f"【再次合并】小组「{existing['name']}」只追加这些公开答复。"),
                    "status": "complete",
                    "phase": "meta",
                    "context_version": version,
                    "run_token": session.get("run_token"),
                    "group_id": existing["id"],
                    "event_kind": "share",
                    "source_message_id": plan["shares"][0]["message_id"] if plan["shares"] else None,
                    "finished_at": now_iso(),
                }
            )
            self._pulse_stale(session_id)
            self._cancel_web_members(member_ids, "group_changed")
            self.publish_state(session_id)
            return {"ok": True, "already": True, "group": self.db.get_group(existing["id"]), "preview": plan}
        group = self.db.move_members(
            session_id,
            member_ids,
            kind="discussion",
            name="讨论 " + "、".join(names),
            event_kind="merge",
            event_text=quote_block(plan, "【分组合并】新建讨论组，只带上选中的公开答复。"),
            context_version=version,
            run_token=session.get("run_token"),
        )
        self._pulse_stale(session_id)
        self._cancel_web_members(member_ids, "group_changed")
        self.publish_state(session_id)
        return {"ok": True, "already": False, "group": group, "preview": plan}

    async def split_group(
        self,
        session_id: str,
        group_id: str,
        member_ids: list[str],
        carry: str,
        message_ids: list[str] | None = None,
        web_memory: str = "rebind",
    ) -> dict:
        group = self.db.get_group(group_id)
        if not group or group["session_id"] != session_id:
            return {"ok": False, "error": "missing_group"}
        if carry not in {"public", "fresh"}:
            return {"ok": False, "error": "bad_carry"}
        if web_memory not in {"rebind", "retain"}:
            return {"ok": False, "error": "bad_web_memory"}
        if not member_ids or any(mid not in group["member_ids"] for mid in member_ids):
            return {"ok": False, "error": "bad_members"}
        if set(member_ids) == set(group["member_ids"]):
            return {"ok": False, "error": "leave_someone"}
        plan = {"shares": [], "note": "新分支不接收原组之后的发言。已经看见的网页内容不会因此被忘掉。"}
        if carry == "public":
            try:
                plan = share_plan(self.db, session_id, member_ids, message_ids)
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
            title = "【拆分】带走下列已公开的答复。拆出后不再接收原组的新发言。模型已经看见的内容不会被宣称忘掉。"
        else:
            title = "【拆分】从新分支开始，不附带原组历史。拆出后不再接收原组的新发言。若网页会话里已经有旧内容，模型仍可能记得；站点若不能新开对话，会标明能力受限。"
        names = [self.db.get_member(mid)["nickname"] for mid in member_ids]
        version = self.db.bump_context(session_id)
        session = self.db.get_session(session_id)
        kind = "branch" if len(member_ids) == 1 else "discussion"
        name = f"{names[0]} 的新分支" if len(member_ids) == 1 else "拆出 " + "、".join(names)
        created = self.db.move_members(
            session_id,
            member_ids,
            kind=kind,
            name=name,
            event_kind="split",
            event_text=quote_block(plan, title),
            context_version=version,
            run_token=session.get("run_token"),
        )
        for mid in member_ids:
            member = self.db.get_member(mid)
            if not member or member.get("provider") != "web":
                continue
            if web_memory == "retain":
                self.db.update_member(mid, {"web_conversation": "retain"})
            else:
                self.db.update_member(
                    mid,
                    {"web_conversation": "needs_rebind", "web_tab_key": "", "web_auto": False},
                )
        self._pulse_stale(session_id)
        self._cancel_web_members(member_ids, "group_changed")
        self.publish_state(session_id)
        return {"ok": True, "group": created, "carry": carry, "preview": plan}

    def _cancel_web_members(self, member_ids: list[str], reason: str) -> None:
        web = getattr(self, "web", None)
        if web:
            web.cancel_members(member_ids, reason)

    async def _independent(self, session_id: str, run_token: str, cancel: asyncio.Event, members: list[dict], version: int) -> str:
        session = self.db.get_session(session_id)
        if session["current_round"] >= session["max_rounds"]:
            return "limit_rounds"
        expired = self._expire_if_needed(session_id, session)
        if expired:
            return expired
        if not await self._wait_running(session_id, cancel):
            return "stopped"
        round_no = self.db.inc_round(session_id)
        self._system(session_id, f"第 {round_no} 轮 · 独立回答，成员之间看不到彼此本轮正在生成的内容", round_no)
        snapshot = self.db.model_transcript(session_id)
        version = self.db.get_session(session_id)["context_version"]
        session = self.db.get_session(session_id)
        serial = session["max_tokens"] is not None or session["max_cost_usd"] is not None
        cap = discussion_cap(session)
        if serial:
            results = []
            for member in members:
                if not await self._wait_running(session_id, cancel):
                    results.append("stopped")
                    break
                results.append(
                    await self._speak(
                        session_id, run_token, cancel, member, members, "independent", round_no, version, cap, snapshot
                    )
                )
                if results[-1] in LIMITS or results[-1] in {"stopped", "version_changed"}:
                    break
        else:
            results = list(
                await asyncio.gather(
                    *[
                        self._speak(
                            session_id, run_token, cancel, member, members, "independent", round_no, version, cap, snapshot
                        )
                        for member in members
                    ]
                )
            )
        return self._reduce(results)

    async def _cross(self, session_id: str, run_token: str, cancel: asyncio.Event, members: list[dict], version: int) -> str:
        session = self.db.get_session(session_id)
        if session["current_round"] >= session["max_rounds"]:
            return "limit_rounds"
        if not await self._wait_running(session_id, cancel):
            return "stopped"
        round_no = self.db.inc_round(session_id)
        label = "交叉辩论" if session["mode"] == "debate" else "自由讨论"
        self._system(session_id, f"第 {round_no} 轮 · {label}，发言者可以看见已经公开的消息", round_no)
        version = self.db.get_session(session_id)["context_version"]
        latest = self._latest_user(session_id)
        current_members = [item for item in self.db.list_members(session_id) if item["enabled"]]
        pool = self._participants(session_id, self.db.get_session(session_id), current_members, latest)
        speakers, passed = self._select(session_id, run_token, pool, round_no, version)
        for member in passed:
            self._system(session_id, f"{member['nickname']} 选择本轮不发言。", round_no)
        if not speakers:
            return "all_passed"
        results = []
        any_new = False
        any_spoke = False
        for member in speakers:
            if self.db.get_session(session_id)["context_version"] != version:
                return "version_changed"
            if not await self._wait_running(session_id, cancel):
                return "stopped"
            transcript = self.db.model_transcript(session_id)
            session = self.db.get_session(session_id)
            code = await self._speak(
                session_id,
                run_token,
                cancel,
                member,
                pool,
                "cross",
                round_no,
                version,
                discussion_cap(session),
                transcript,
            )
            results.append(code)
            if code == "ok":
                any_spoke = True
                any_new = True
            elif code == "ok_repeat":
                any_spoke = True
            if code in LIMITS or code in {"stopped", "version_changed", "provider_failed"}:
                if code == "provider_failed":
                    continue
                return code
            delay = max(0, int(session.get("cross_delay_ms") or 0)) / 1000
            if delay:
                try:
                    await asyncio.wait_for(cancel.wait(), timeout=delay)
                    return "stopped"
                except asyncio.TimeoutError:
                    pass
        if any_spoke and not any_new and self.db.get_session(session_id)["stop_on_no_new_point"]:
            return "no_new"
        if not any_spoke:
            if any(code in LIMITS for code in results):
                return next(code for code in results if code in LIMITS)
            return "all_passed"
        return "ok"

    def _reduce(self, results: list[str]) -> str:
        if any(code == "version_changed" for code in results):
            return "version_changed"
        if any(code == "stopped" for code in results):
            return "stopped"
        for code in results:
            if code in LIMITS:
                return code
        if any(code in {"ok", "ok_repeat"} for code in results):
            return "ok"
        if any(code == "provider_failed" or code == "error" for code in results):
            return "provider_failed"
        if results and all(code == "skip" for code in results):
            return "provider_failed"
        return "ok"

    def _latest_user(self, session_id: str) -> str:
        users = [item for item in self.db.model_transcript(session_id) if item["author_type"] == "user"]
        return users[-1]["content"] if users else ""

    def _select(self, session_id: str, run_token: str, members: list[dict], round_no: int, version: int):
        session = self.db.get_session(session_id)
        transcript = self.db.model_transcript(session_id)
        latest_user = self._latest_user(session_id)
        mentioned = set(mention_ids(latest_user, members))
        last_ai = None
        for message in reversed(transcript):
            if message["author_type"] == "ai" and message.get("run_token") == run_token:
                last_ai = message
                break
        suggested = last_ai.get("suggest_next_id") if last_ai else None
        last_speaker = last_ai.get("member_id") if last_ai else None
        ranked = []
        passed = []
        for index, member in enumerate(members):
            if mentioned and member["id"] not in mentioned:
                continue
            if self._should_pass(session_id, run_token, member, version, round_no):
                passed.append(member)
                continue
            score = _jitter(member["id"], round_no, version)
            if member["id"] in mentioned:
                score += 100
            if suggested and member["id"] == suggested:
                score += 40
            if last_speaker and member["id"] == last_speaker:
                score -= 35
            cross_count = sum(
                1
                for item in transcript
                if item.get("member_id") == member["id"] and item.get("phase") == "cross" and item.get("run_token") == run_token
            )
            score += max(0, 12 - cross_count * 8)
            if session["mode"] == "debate" and any(word in (member["role_name"] or "") for word in ("质疑", "反对", "审")):
                score += 8
            ranked.append((score, index, member))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        fresh = self.db.get_session(session_id)
        remaining = discussion_cap(fresh) - int(fresh["ai_message_count"])
        if remaining <= 0 or not ranked:
            return [], passed
        count = 1
        if fresh["mode"] == "debate" and round_no == 2 and remaining >= 2:
            count = 2
        count = min(count, remaining, len(ranked))
        return [item[2] for item in ranked[:count]], passed

    def _should_pass(self, session_id: str, run_token: str, member: dict, version: int, round_no: int) -> bool:
        if round_no < 3:
            return False
        rows = [
            item
            for item in self.db.complete_ai_in_run(session_id, run_token)
            if item.get("member_id") == member["id"] and item.get("phase") == "cross" and item.get("context_version") == version
        ]
        return bool(rows) and not rows[-1]["has_new_point"]

    async def _speak(
        self,
        session_id: str,
        run_token: str,
        cancel: asyncio.Event,
        member: dict,
        peers: list[dict],
        phase: str,
        round_no: int,
        version: int,
        cap: int,
        transcript: list[dict],
        group_id: str | None = None,
        group_generation: int | None = None,
    ) -> str:
        if cancel.is_set():
            return "stopped"
        session = self.db.get_session(session_id)
        if not session or session["status"] == "stopped":
            return "stopped"
        if session["context_version"] != version:
            return "version_changed"
        if self._expire_if_needed(session_id, session):
            return "limit_time"
        if self.db.has_preflight_block(session_id, run_token, member["id"]):
            return "skip"
        if group_id:
            current_group = self.db.get_group(group_id)
            if not current_group or current_group["status"] != "active" or int(current_group["generation"]) != int(group_generation or 0):
                return "version_changed"
        step_key = f"{run_token}:v{version}:r{round_no}:{phase}:{member['id']}"
        if group_id:
            step_key += f":{group_id}"
        if self.db.step_exists(step_key):
            return "skip"
        reply_to = None if phase in {"independent", "summary"} else self._pick_reply(member, transcript)
        suggest_id, suggest_name = (None, None) if phase != "cross" else self._suggest(member, peers)
        users = [item for item in transcript if item["author_type"] == "user"]
        request = GenRequest(
            member_id=member["id"],
            member_nickname=member["nickname"],
            role_name=member["role_name"],
            persona=member.get("persona") or "",
            provider=member["provider"],
            model_id=member["model_id"],
            api_base=member.get("api_base"),
            api_key_env=member.get("api_key_env"),
            round_number=round_no,
            phase=phase,
            mode=session["mode"],
            transcript=list(transcript),
            user_latest=users[-1]["content"] if users else "",
            reply_to=reply_to,
            suggest_next_nickname=suggest_name,
            room_rule=session.get("room_rule") or "",
            cost_cap_set=session.get("max_cost_usd") is not None,
            end_reason=session.get("end_reason") or "",
            is_demo=member["provider"] == "demo",
        )
        request.session_id = session_id
        request.run_token = run_token
        request.group_id = group_id or ""
        request.context_version = version
        request.group_generation = int(group_generation or 0)
        request.web_site = member.get("web_site") or ""
        request.web_origin = member.get("web_origin") or ""
        request.web_tab_key = member.get("web_tab_key") or ""
        request.web_model_label = member.get("web_model_label") or ""
        request.web_auto = bool(member.get("web_auto"))
        request.web_conversation = member.get("web_conversation") or ""
        request.web_open_new = False
        request.token_cap_set = session.get("max_tokens") is not None
        request.prompt = web_forward_text(request) if member.get("provider") == "web" else render_prompt(request)
        preflight = getattr(self.provider, "preflight", None)
        if preflight:
            error = preflight(request)
            if error:
                self.db.insert_step(f"{run_token}:preflight:{member['id']}", session_id, run_token, "preflight")
                self._error_message(session_id, member, session, run_token, version, round_no, phase, error)
                return "skip"
        estimate = input_token_estimate(request) if session["max_tokens"] is not None else 0
        cost_known = bool(request.usage.cost_known)
        reserved, reason = self.db.reserve_slot(session_id, cap, estimate, cost_known)
        if not reserved:
            return reason or "limit_messages"
        if not self.db.insert_step(step_key, session_id, run_token, "pending"):
            return "skip"
        stale = asyncio.Event()
        self.stales.setdefault(session_id, set()).add(stale)
        message = self.db.add_message(
            {
                "session_id": session_id,
                "author_type": "ai",
                "member_id": member["id"],
                "nickname": member["nickname"],
                "role_name": member["role_name"],
                "provider": member["provider"],
                "model_id": member["model_id"],
                "avatar_color": member.get("avatar_color"),
                "content": "等待回复" if member.get("provider") == "web" else "",
                "status": "streaming",
                "reply_to_id": reply_to["id"] if reply_to else None,
                "round_number": round_no,
                "phase": phase,
                "context_version": version,
                "run_token": run_token,
                "step_key": step_key,
                "suggest_next_id": suggest_id,
                "suggest_next_nickname": suggest_name,
                "is_demo": member["provider"] == "demo",
                "is_summary": phase == "summary",
                "group_id": group_id,
            }
        )
        self.db.set_speaking(session_id, member["id"], True)
        self.publish(session_id, "message", message)
        self.publish_state(session_id)
        parts: list[str] = []
        stream = self.provider.stream(request, cancel, stale).__aiter__()
        try:
            while True:
                if cancel.is_set() or stale.is_set() or self.db.get_session(session_id)["context_version"] != version:
                    break
                nxt = asyncio.create_task(stream.__anext__())
                stopper = asyncio.create_task(self._wait_flags(cancel, stale))
                _done, _pending = await asyncio.wait({nxt, stopper}, return_when=asyncio.FIRST_COMPLETED)
                if nxt not in _done:
                    nxt.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await nxt
                    break
                stopper.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await stopper
                try:
                    chunk = nxt.result()
                except StopAsyncIteration:
                    break
                if request.provider == "web" and not parts:
                    self.db.update_message(message["id"], content="")
                parts.append(chunk)
                updated = self.db.append_message(message["id"], chunk)
                self.publish(session_id, "message", updated)
            text = "".join(parts).strip()
            self._apply_usage(session_id, request, text, estimate)
            if cancel.is_set() or self.db.get_session(session_id)["status"] == "stopped":
                self.db.update_message(
                    message["id"],
                    content=text,
                    status="cancelled",
                    discarded_reason="stopped",
                    finished_at=now_iso(),
                    prompt_tokens=request.usage.prompt_tokens,
                    completion_tokens=request.usage.completion_tokens,
                    cost_usd=request.usage.cost_usd,
                )
                self.db.finish_step(step_key, "cancelled")
                self.publish(session_id, "message", self.db.get_message(message["id"]))
                return "stopped"
            group_moved = False
            if group_id:
                current_group = self.db.get_group(group_id)
                group_moved = not current_group or int(current_group["generation"]) != int(group_generation or 0)
            if stale.is_set() or self.db.get_session(session_id)["context_version"] != version or group_moved:
                self.db.update_message(
                    message["id"],
                    content=text,
                    status="discarded",
                    discarded_reason="stale_context",
                    finished_at=now_iso(),
                )
                self.db.finish_step(step_key, "discarded")
                self.publish(session_id, "message", self.db.get_message(message["id"]))
                return "version_changed"
            if not text:
                self.db.update_message(
                    message["id"],
                    content="模型没有返回公开文本。",
                    status="error",
                    discarded_reason="empty",
                    finished_at=now_iso(),
                )
                self.db.finish_step(step_key, "done")
                self.publish(session_id, "message", self.db.get_message(message["id"]))
                return "error"
            new_point = infer_new_point(text)
            shown_model = member["model_id"]
            if member.get("provider") == "web":
                shown_model = request.web_model_label or "未能核验精确 model ID"
            self.db.update_message(
                message["id"],
                content=text,
                status="complete",
                has_new_point=new_point,
                finished_at=now_iso(),
                prompt_tokens=request.usage.prompt_tokens,
                completion_tokens=request.usage.completion_tokens,
                cost_usd=0 if member.get("provider") == "web" else request.usage.cost_usd,
                model_id=shown_model,
                is_demo=member["provider"] == "demo",
                is_summary=phase == "summary",
            )
            self.db.finish_step(step_key, "done")
            self.publish(session_id, "message", self.db.get_message(message["id"]))
            return "ok" if new_point else "ok_repeat"
        except asyncio.CancelledError:
            self.db.update_message(
                message["id"],
                content="".join(parts),
                status="cancelled",
                discarded_reason="stopped",
                finished_at=now_iso(),
            )
            self.db.finish_step(step_key, "cancelled")
            raise
        except ProviderError as exc:
            self.db.update_message(
                message["id"],
                content=redact(str(exc)),
                status="error",
                discarded_reason="provider",
                finished_at=now_iso(),
            )
            self.db.finish_step(step_key, "done")
            self.publish(session_id, "message", self.db.get_message(message["id"]))
            return "error"
        finally:
            self.stales.get(session_id, set()).discard(stale)
            closer = getattr(stream, "aclose", None)
            if closer:
                with contextlib.suppress(Exception):
                    await closer()
            self.db.set_speaking(session_id, member["id"], False)
            self.publish_state(session_id)

    def _apply_usage(self, session_id: str, request: GenRequest, text: str, reserved_prompt: int = 0) -> None:
        if request.provider == "web":
            self.db.mark_tokens_unknown(session_id)
            request.usage.prompt_tokens = 0
            request.usage.completion_tokens = 0
            request.usage.cost_known = False
            return
        if request.usage.completion_tokens == 0 and text:
            request.usage.completion_tokens = len(text)
        if request.usage.prompt_tokens == 0 and request.prompt:
            request.usage.prompt_tokens = len(request.prompt)
        if request.usage.prompt_tokens or request.usage.completion_tokens or request.usage.cost_usd or reserved_prompt:
            self.db.add_usage(
                session_id,
                request.usage.prompt_tokens,
                request.usage.completion_tokens,
                float(request.usage.cost_usd or 0),
                bool(request.usage.cost_known),
                reserved_prompt=reserved_prompt,
            )

    def _pick_reply(self, member: dict, transcript: list[dict]) -> dict | None:
        for message in reversed(transcript):
            if message["author_type"] == "ai" and message.get("member_id") != member["id"]:
                return message
        for message in reversed(transcript):
            if message["author_type"] == "user":
                return message
        return None

    def _suggest(self, member: dict, peers: list[dict]) -> tuple[str | None, str | None]:
        others = [item for item in peers if item["id"] != member["id"]]
        if not others:
            return None, None
        start = int(hashlib.sha256(member["id"].encode()).hexdigest(), 16) % len(others)
        chosen = others[start]
        return chosen["id"], chosen["nickname"]

    def _error_message(self, session_id, member, session, run_token, version, round_no, phase, error: str) -> None:
        message = self.db.add_message(
            {
                "session_id": session_id,
                "author_type": "ai",
                "member_id": member["id"],
                "nickname": member["nickname"],
                "role_name": member["role_name"],
                "provider": member["provider"],
                "model_id": member["model_id"],
                "avatar_color": member.get("avatar_color"),
                "content": error,
                "status": "error",
                "round_number": round_no,
                "phase": phase,
                "context_version": version,
                "run_token": run_token,
                "is_demo": False,
                "discarded_reason": "preflight",
                "finished_at": now_iso(),
            }
        )
        self.publish(session_id, "message", message)

    def _system(self, session_id: str, content: str, round_number: int | None = None) -> None:
        session = self.db.get_session(session_id)
        if not session:
            return
        message = self.db.add_message(
            {
                "session_id": session_id,
                "author_type": "system",
                "nickname": "房间",
                "content": content,
                "status": "complete",
                "round_number": round_number,
                "phase": "meta",
                "context_version": session["context_version"],
                "run_token": session.get("run_token"),
                "finished_at": now_iso(),
            }
        )
        self.publish(session_id, "message", message)

    async def _close(self, session_id: str, run_token: str, reason: str, cancel: asyncio.Event) -> None:
        session = self.db.get_session(session_id)
        if not session or session.get("run_token") != run_token:
            return
        already_closed = session["status"] in {"finished", "stopped", "failed"} and session.get("end_reason")
        if not already_closed and reason in {"independent_complete", "ok"} and not self.db.complete_ai_in_run(session_id, run_token):
            errors = [
                item
                for item in self.db.list_messages(session_id)
                if item.get("run_token") == run_token and item["status"] == "error"
            ]
            if errors:
                reason = "provider_failed"
        await self._emit_summary(session_id, run_token, session.get("end_reason") or reason, cancel)
        if not already_closed:
            self.db.finish_session(session_id, run_token, status_for(reason), reason)
        final = self.db.get_session(session_id)
        self.db.finish_run_row(run_token, final["status"], final.get("end_reason"))
        self.db.set_speaking(session_id, "", False)
        self.publish_state(session_id)

    async def _emit_summary(self, session_id: str, run_token: str | None, reason: str, cancel: asyncio.Event) -> None:
        if not run_token or self.db.has_summary(run_token):
            return
        session = self.db.get_session(session_id)
        if not session:
            return
        if session.get("layout") == "branches":
            self._system(session_id, "分支房间结束。没有把不同分支的答复合成一份跨组总结。")
            return
        target = self._summary_target(session)
        allowed, why = self._model_summary_allowed(session, reason, cancel, session_id)
        if target and allowed:
            blocked = self._summary_preflight(target, session)
            if blocked:
                self._write_local_summary(session_id, run_token, reason, blocked)
                return
            code = await self._speak(
                session_id,
                run_token,
                cancel,
                target,
                [target],
                "summary",
                int(session["current_round"] or 0),
                int(session["context_version"]),
                int(session["max_ai_messages"]),
                self.db.model_transcript(session_id),
            )
            if code in {"ok", "ok_repeat"} or self.db.has_summary(run_token):
                self._normalize_summary(session_id, run_token, reason)
                self.publish_state(session_id)
                return
            why = why or "总结模型没有返回可用的六段综述，未再请求。"
        self._write_local_summary(session_id, run_token, reason, "" if allowed else why)

    def _summary_target(self, session: dict) -> dict | None:
        if session.get("summary_mode") == "member" and session.get("summary_member_id"):
            member = self.db.get_member(session["summary_member_id"])
            if member and member["enabled"] and member["session_id"] == session["id"]:
                return member
            return None
        if session.get("summary_mode") != "provider":
            return None
        provider = (session.get("summary_provider") or "").strip()
        model_id = (session.get("summary_model_id") or "").strip()
        if not provider or not model_id:
            return None
        return {
            "id": f"summary:{provider}",
            "session_id": session["id"],
            "nickname": "总结模型",
            "role_name": "综合",
            "persona": "只根据已经公开的发言写六段综述。不要编造记录里没有的共识。",
            "provider": provider,
            "model_id": model_id,
            "api_base": None,
            "api_key_env": None,
            "enabled": True,
            "avatar_color": "#44403c",
        }

    def _summary_preflight(self, member: dict, session: dict) -> str | None:
        preflight = getattr(self.provider, "preflight", None)
        if not preflight:
            return None
        request = GenRequest(
            member_id=member["id"],
            member_nickname=member["nickname"],
            role_name=member["role_name"],
            persona=member.get("persona") or "",
            provider=member["provider"],
            model_id=member["model_id"],
            api_base=member.get("api_base"),
            api_key_env=member.get("api_key_env"),
            round_number=int(session.get("current_round") or 0),
            phase="summary",
            mode=session.get("mode") or "free_chat",
            transcript=[],
            user_latest="",
            reply_to=None,
            suggest_next_nickname=None,
            room_rule=session.get("room_rule") or "",
            cost_cap_set=session.get("max_cost_usd") is not None,
            is_demo=member["provider"] == "demo",
        )
        error = preflight(request)
        if not error:
            return None
        return f"总结模型未调用：{error} 下面仍是本地回顾。"

    def _model_summary_allowed(self, session: dict, reason: str, cancel: asyncio.Event, session_id: str) -> tuple[bool, str]:
        if not wants_model_summary(session):
            return False, ""
        if reason in HARD_STOP_SUMMARY or cancel.is_set() or session.get("status") == "stopped":
            return False, "讨论已停止、超时或失败，未再请求总结模型。"
        deadline = self.deadlines.get(session_id)
        if deadline is not None and time.monotonic() >= deadline:
            return False, "时间上限已到，未再请求总结模型。"
        if reason in {"limit_time", "limit_tokens", "limit_cost"}:
            return False, "已经到达硬上限，未再请求总结模型。"
        if session["max_tokens"] is not None and session["run_tokens"] >= session["max_tokens"]:
            return False, "token 上限已到，未再请求总结模型。"
        if session["max_cost_usd"] is not None and not int(session.get("run_cost_known") or 0):
            return False, "费用未知，未再请求总结模型。"
        if session["max_cost_usd"] is not None and float(session["run_cost_usd"]) >= float(session["max_cost_usd"]) - 1e-9:
            return False, "费用上限已到，未再请求总结模型。"
        if session["ai_message_count"] >= session["max_ai_messages"]:
            return False, "消息额度已用完，未再请求总结模型。"
        return True, ""

    def _normalize_summary(self, session_id: str, run_token: str, reason: str) -> None:
        messages = [
            item
            for item in self.db.list_messages(session_id)
            if item.get("run_token") == run_token and item["is_summary"] and item["status"] == "complete"
        ]
        if not messages:
            return
        message = messages[-1]
        text = message["content"]
        headings = ("主要结论", "共识", "分歧", "未验证事实", "最推荐建议", "下一步行动")
        if all(item in text for item in headings):
            return
        replacement = build_summary(
            self.db.model_transcript(session_id),
            reason,
            note="总结模型没有完整六段结构，已改用本地回顾，没有再次请求。",
        )
        self.db.update_message(message["id"], content=replacement, provider="local", model_id="local-retrospective", is_demo=False)
        self.publish(session_id, "message", self.db.get_message(message["id"]))

    def _write_local_summary(self, session_id: str, run_token: str, reason: str, note: str) -> None:
        if self.db.has_summary(run_token):
            return
        session = self.db.get_session(session_id)
        body = build_summary(self.db.model_transcript(session_id), reason, note=note)
        message = self.db.add_message(
            {
                "session_id": session_id,
                "author_type": "system",
                "nickname": "记录",
                "role_name": "本地回顾",
                "provider": "local",
                "model_id": "local-retrospective",
                "content": body,
                "status": "complete",
                "round_number": session["current_round"] if session else None,
                "phase": "summary",
                "context_version": session["context_version"] if session else 0,
                "run_token": run_token,
                "is_summary": True,
                "is_demo": False,
                "finished_at": now_iso(),
            }
        )
        self.publish(session_id, "message", message)

    def snapshot(self, session_id: str) -> dict:
        return {
            "session": self.db.get_session(session_id),
            "members": self.db.list_members(session_id),
            "messages": self.db.list_messages(session_id),
        }
