"""Chat-room scheduler. Model text is never a new user turn."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import time
from datetime import datetime, timedelta, timezone

from .db import Database
from .providers import GenRequest, ProviderError, render_prompt
from .summary import build_summary
from .util import excerpt, infer_new_point, mention_ids, new_id, now_iso, reason_label, redact, status_for

LIMITS = {"limit_messages", "limit_tokens", "limit_cost", "limit_time", "limit_rounds"}
HARD_STOP_SUMMARY = {"user_stop", "limit_time", "server_restart", "provider_failed", "engine_error"}


def discussion_cap(session: dict) -> int:
    cap = int(session["max_ai_messages"])
    if session.get("summary_mode") == "member" and session.get("summary_member_id") and cap >= 2:
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
            }
        )
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
            deadline = started + timedelta(seconds=float(session["max_seconds"]))
            self.db.insert_run(session_id, run_token, session["mode"], trigger_message_id)
            if not self.db.begin_run(session_id, run_token, session["mode"], started.isoformat(), deadline.isoformat()):
                return {"ok": False, "error": "could_not_start"}
            cancel = asyncio.Event()
            self.cancels[session_id] = cancel
            self.stales[session_id] = set()
            self.deadlines[session_id] = time.monotonic() + float(session["max_seconds"])
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
        step_key = f"{run_token}:v{version}:r{round_no}:{phase}:{member['id']}"
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
        request.prompt = render_prompt(request)
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
                "content": "",
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
            if stale.is_set() or self.db.get_session(session_id)["context_version"] != version:
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
            self.db.update_message(
                message["id"],
                content=text,
                status="complete",
                has_new_point=new_point,
                finished_at=now_iso(),
                prompt_tokens=request.usage.prompt_tokens,
                completion_tokens=request.usage.completion_tokens,
                cost_usd=request.usage.cost_usd,
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
        if not (session["status"] in {"finished", "stopped", "failed"} and session.get("end_reason")):
            if reason in {"independent_complete", "ok"} and not self.db.complete_ai_in_run(session_id, run_token):
                errors = [
                    item
                    for item in self.db.list_messages(session_id)
                    if item.get("run_token") == run_token and item["status"] == "error"
                ]
                if errors:
                    reason = "provider_failed"
            self.db.finish_session(session_id, run_token, status_for(reason), reason)
        session = self.db.get_session(session_id)
        await self._emit_summary(session_id, run_token, session.get("end_reason") or reason, cancel)
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
        if self._model_summary_allowed(session, reason, cancel, session_id):
            member = self.db.get_member(session["summary_member_id"])
            if member and member["enabled"] and member["session_id"] == session_id:
                code = await self._speak(
                    session_id,
                    run_token,
                    cancel,
                    member,
                    [member],
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
        self._write_local_summary(session_id, run_token, reason, "")

    def _model_summary_allowed(self, session: dict, reason: str, cancel: asyncio.Event, session_id: str) -> bool:
        if session.get("summary_mode") != "member" or not session.get("summary_member_id"):
            return False
        if reason in HARD_STOP_SUMMARY or cancel.is_set():
            return False
        deadline = self.deadlines.get(session_id)
        if deadline is not None and time.monotonic() >= deadline:
            return False
        if session["max_tokens"] is not None and session["run_tokens"] >= session["max_tokens"]:
            return False
        if session["max_cost_usd"] is not None and float(session["run_cost_usd"]) >= float(session["max_cost_usd"]) - 1e-9:
            return False
        if session["ai_message_count"] >= session["max_ai_messages"]:
            return False
        return True

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
        if "主要结论" in text and "分歧" in text and "下一步" in text:
            return
        replacement = build_summary(
            self.db.model_transcript(session_id),
            reason,
            note="成员输出没有完整六段结构，已改用本地回顾，没有再次请求。",
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
