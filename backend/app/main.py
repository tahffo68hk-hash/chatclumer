"""HTTP API for the multi-LLM chat room."""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .db import Database
from .engine import RoomEngine
from .providers import CATALOG, RoutedProvider
from .secrets import ALLOWED_SECRET_NAMES, SecretStore
from .util import reason_label, redact, status_label

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DEMO_MODEL = re.compile(r"^demo-[a-z0-9][a-z0-9._-]{0,80}$")
PROVIDERS = {
    "demo",
    "openai",
    "openrouter",
    "anthropic",
    "gemini",
    "ollama",
    "deepseek",
    "qwen",
    "openai_compatible",
    "xai",
}
MODES = {"independent", "free_chat", "debate", "summary"}

DEMO_MEMBERS = [
    {
        "nickname": "林知秋",
        "role_name": "质疑者",
        "persona": "专门寻找未验证事实、过度结论和说不通的地方。先引用再质疑，话短。",
        "provider": "demo",
        "model_id": "demo-synthesizer-v1",
    },
    {
        "nickname": "周衡",
        "role_name": "工程师",
        "persona": "关心最小实现、失败边界和代价。同一个演示模型的另一个角色。",
        "provider": "demo",
        "model_id": "demo-synthesizer-v1",
    },
    {
        "nickname": "苏晚",
        "role_name": "产品",
        "persona": "关心用户能否感知、取舍和下一步。不负责把分歧抹平。",
        "provider": "demo",
        "model_id": "demo-synthesizer-v1",
    },
]


class SessionIn(BaseModel):
    title: str = "未命名群聊"
    template: str | None = None
    mode: str = "free_chat"
    max_rounds: int = 3
    max_ai_messages: int = 10
    max_seconds: float = 120
    max_tokens: int | None = None
    max_cost_usd: float | None = None
    summary_mode: str = "local"
    summary_member_id: str | None = None
    cross_delay_ms: int = 120
    room_rule: str = ""
    stop_on_no_new_point: bool = True


class SettingsIn(BaseModel):
    title: str | None = None
    mode: str | None = None
    max_rounds: int | None = None
    max_ai_messages: int | None = None
    max_seconds: float | None = None
    max_tokens: int | None = None
    max_cost_usd: float | None = None
    summary_mode: str | None = None
    summary_member_id: str | None = None
    cross_delay_ms: int | None = None
    room_rule: str | None = None
    stop_on_no_new_point: bool | None = None
    clear_token_cap: bool = False
    clear_cost_cap: bool = False


class MemberIn(BaseModel):
    nickname: str
    role_name: str
    persona: str = ""
    provider: str
    model_id: str
    api_base: str | None = None
    api_key_env: str | None = None
    enabled: bool = True


class MessageIn(BaseModel):
    content: str
    reply_to_id: str | None = None
    mode: str | None = None


class RunIn(BaseModel):
    mode: str | None = None


class SecretIn(BaseModel):
    name: str
    value: str = ""


class AllowPaidIn(BaseModel):
    enabled: bool


class SimulateIn(BaseModel):
    session_id: str
    content: str = ""


def _check_limits(data: dict) -> None:
    if "mode" in data and data["mode"] is not None and data["mode"] not in MODES:
        raise HTTPException(400, "不支持的讨论模式")
    if "max_rounds" in data and data["max_rounds"] is not None and not 1 <= int(data["max_rounds"]) <= 8:
        raise HTTPException(400, "轮数上限需在 1 到 8 之间")
    if "max_ai_messages" in data and data["max_ai_messages"] is not None and not 1 <= int(data["max_ai_messages"]) <= 30:
        raise HTTPException(400, "AI 消息上限需在 1 到 30 之间")
    if "max_seconds" in data and data["max_seconds"] is not None and not 0.2 <= float(data["max_seconds"]) <= 300:
        raise HTTPException(400, "时间上限需在 0.2 到 300 秒之间")
    if data.get("max_tokens") is not None and int(data["max_tokens"]) < 1:
        raise HTTPException(400, "token 上限至少为 1")
    if data.get("max_cost_usd") is not None and float(data["max_cost_usd"]) < 0:
        raise HTTPException(400, "费用上限不能为负")
    if "summary_mode" in data and data["summary_mode"] not in {None, "local", "member"}:
        raise HTTPException(400, "总结方式只能是本地回顾或指定成员")
    if "cross_delay_ms" in data and data["cross_delay_ms"] is not None and not 0 <= int(data["cross_delay_ms"]) <= 5000:
        raise HTTPException(400, "发言间隔需在 0 到 5000 毫秒")


def _check_member(data: dict) -> None:
    provider = data["provider"]
    model_id = (data.get("model_id") or "").strip()
    if provider not in PROVIDERS:
        raise HTTPException(400, "不支持的提供方")
    if not data.get("nickname", "").strip() or not data.get("role_name", "").strip():
        raise HTTPException(400, "需要昵称和角色")
    if provider == "demo":
        if not DEMO_MODEL.match(model_id):
            raise HTTPException(400, "演示成员的模型 ID 必须以 demo- 开头，不能写成真实模型")
    else:
        if not model_id or model_id.startswith("demo-"):
            raise HTTPException(400, "需要精确模型 ID，不能用 demo- 前缀伪装")
    if provider == "openai_compatible" and not (data.get("api_base") or "").strip():
        raise HTTPException(400, "OpenAI 兼容接口需要 API Base")
    env_name = data.get("api_key_env")
    if env_name and env_name not in ALLOWED_SECRET_NAMES:
        raise HTTPException(400, "密钥环境变量名不在允许列表里")


def present_session(db: Database, session: dict) -> dict:
    data = dict(session)
    data["status_label"] = status_label(data["status"])
    data["end_reason_label"] = reason_label(data.get("end_reason"))
    names = {item["id"]: item["nickname"] for item in db.list_members(data["id"])}
    data["speaking_nicknames"] = [names.get(item, item) for item in data.get("speaking_member_ids") or []]
    return data


def integration_status(secrets: SecretStore) -> dict:
    qq_configured = secrets.configured("QQ_APP_ID") and secrets.configured("QQ_BOT_TOKEN")
    wecom = secrets.configured("WECOM_CORP_ID") and secrets.configured("WECOM_AGENT_SECRET")
    oa = secrets.configured("WECHAT_OA_APPID") and secrets.configured("WECHAT_OA_TOKEN")
    return {
        "qq": {
            "state": "CONFIGURED_UNVERIFIED" if qq_configured else "BLOCKED_EXTERNAL",
            "delivery": "BLOCKED_EXTERNAL",
            "detail": "仅保留官方机器人配置与本地命令模拟。没有完成开放平台鉴权，不能说真实 QQ 群已接通。",
        },
        "wechat": {
            "state": "BLOCKED_EXTERNAL",
            "delivery": "BLOCKED_EXTERNAL",
            "official_account_configured": oa,
            "wecom_configured": wecom,
            "personal_wechat": "refused",
            "detail": "不实现个人微信非官方自动化。公众号与企业微信只保留配置位，默认不向外发送。",
        },
    }


def create_app(db_path: str | None = None, secrets_path: str | None = None, provider=None) -> FastAPI:
    database = Database(db_path or str(DATA / "chat.db"))
    secret_store = SecretStore(secrets_path or str(DATA / "secrets.json"))
    room = RoomEngine(database, provider or RoutedProvider(secret_store))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await app.state.engine.recover()
        yield
        await app.state.engine.shutdown()

    app = FastAPI(title="多模型群聊", lifespan=lifespan)
    app.state.db = database
    app.state.secrets = secret_store
    app.state.engine = room
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health():
        return {"ok": True, "service": "multi-llm-chat-room"}

    @app.get("/api/catalog")
    def catalog():
        return {"providers": CATALOG, "modes": sorted(MODES)}

    @app.get("/api/secrets/status")
    def secret_status():
        return secret_store.public_status()

    @app.put("/api/secrets")
    def put_secret(body: SecretIn):
        if body.name not in ALLOWED_SECRET_NAMES:
            raise HTTPException(400, "不接受这个配置名")
        secret_store.set(body.name, body.value.strip())
        return {"ok": True, "name": body.name, "configured": secret_store.configured(body.name)}

    @app.put("/api/runtime/allow-paid")
    def allow_paid(body: AllowPaidIn):
        secret_store.set_allow_paid(body.enabled)
        return {"ok": True, "allow_paid": secret_store.allow_paid()}

    @app.get("/api/integrations/status")
    def integrations():
        return integration_status(secret_store)

    @app.post("/api/integrations/qq/simulate")
    async def qq_simulate(body: SimulateIn):
        session = database.get_session(body.session_id)
        if not session:
            raise HTTPException(404, "找不到房间")
        text = body.content.strip()
        command, _, arg = text.partition(" ")
        command = command.lower()
        reply = "支持 /start /status /stop /result。这是本地模拟，没有发到 QQ。"
        if command in {"/start", "start"}:
            if not arg.strip():
                reply = "用法：/start 你的问题"
            else:
                result = await room.ingest_message(body.session_id, arg.strip(), mode="free_chat")
                reply = "已在本地房间开始。" if result.get("ok") else str(result.get("error"))
        elif command in {"/status", "status"}:
            current = database.get_session(body.session_id)
            reply = f"状态 {status_label(current['status'])} {reason_label(current.get('end_reason'))}".strip()
        elif command in {"/stop", "stop"}:
            await room.stop(body.session_id)
            reply = "已请求停止。"
        elif command in {"/result", "result"}:
            summaries = [item for item in database.list_messages(body.session_id) if item["is_summary"]]
            reply = summaries[-1]["content"][:800] if summaries else "还没有最终报告。"
        return {
            "external_delivery": "BLOCKED_EXTERNAL",
            "qq_state": integration_status(secret_store)["qq"]["state"],
            "simulated": True,
            "reply": reply,
        }

    @app.post("/api/integrations/wechat/simulate")
    def wechat_simulate(body: SimulateIn):
        if not database.get_session(body.session_id):
            raise HTTPException(404, "找不到房间")
        return {
            "external_delivery": "BLOCKED_EXTERNAL",
            "state": "BLOCKED_EXTERNAL",
            "personal_wechat": "refused",
            "reply": "没有向外发送。个人微信自动化已拒绝；公众号/企业微信缺少已验证权限。",
        }

    @app.get("/api/sessions")
    def list_sessions():
        return [present_session(database, item) for item in database.list_sessions()]

    @app.post("/api/sessions")
    def create_session(body: SessionIn):
        payload = body.model_dump()
        template = payload.pop("template")
        _check_limits(payload)
        session = database.create_session(**payload)
        if template == "demo":
            for item in DEMO_MEMBERS:
                database.create_member(session_id=session["id"], **item)
        return present_session(database, database.get_session(session["id"]))

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str):
        session = database.get_session(session_id)
        if not session:
            raise HTTPException(404, "找不到房间")
        return {"session": present_session(database, session), "members": database.list_members(session_id)}

    @app.patch("/api/sessions/{session_id}")
    def patch_session(session_id: str, body: SettingsIn):
        session = database.get_session(session_id)
        if not session:
            raise HTTPException(404, "找不到房间")
        data = body.model_dump(exclude_unset=True)
        if session["status"] in {"running", "paused"}:
            extra = set(data) - {"mode"}
            if extra:
                raise HTTPException(409, "讨论进行中，先暂停或停止再改上限")
        if data.pop("clear_token_cap", False):
            data["max_tokens"] = None
        if data.pop("clear_cost_cap", False):
            data["max_cost_usd"] = None
        _check_limits(data)
        if data.get("summary_member_id"):
            member = database.get_member(data["summary_member_id"])
            if not member or member["session_id"] != session_id:
                raise HTTPException(400, "总结成员不在这个房间")
        updated = database.update_settings(session_id, data)
        return present_session(database, updated)

    @app.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str):
        if not database.get_session(session_id):
            raise HTTPException(404, "找不到房间")
        await room.stop(session_id)
        task = room.tasks.get(session_id)
        if task and not task.done():
            with contextlib.suppress(asyncio.TimeoutError, Exception):
                await asyncio.wait_for(task, timeout=2)
        database.delete_session(session_id)
        return {"ok": True}

    @app.post("/api/sessions/{session_id}/members")
    def add_member(session_id: str, body: MemberIn):
        if not database.get_session(session_id):
            raise HTTPException(404, "找不到房间")
        data = body.model_dump()
        data["nickname"] = data["nickname"].strip()
        data["model_id"] = data["model_id"].strip()
        _check_member(data)
        if database.nickname_taken(session_id, data["nickname"]):
            raise HTTPException(409, "这个房间里已有同名成员")
        try:
            return database.create_member(session_id=session_id, **data)
        except Exception as exc:
            raise HTTPException(400, redact(str(exc))) from exc

    @app.patch("/api/members/{member_id}")
    def patch_member(member_id: str, body: MemberIn):
        current = database.get_member(member_id)
        if not current:
            raise HTTPException(404, "找不到成员")
        data = body.model_dump()
        data["nickname"] = data["nickname"].strip()
        data["model_id"] = data["model_id"].strip()
        _check_member(data)
        if database.nickname_taken(current["session_id"], data["nickname"], exclude=member_id):
            raise HTTPException(409, "这个房间里已有同名成员")
        return database.update_member(member_id, data)

    @app.delete("/api/members/{member_id}")
    def remove_member(member_id: str):
        if not database.get_member(member_id):
            raise HTTPException(404, "找不到成员")
        database.delete_member(member_id)
        return {"ok": True}

    @app.get("/api/sessions/{session_id}/messages")
    def list_messages(session_id: str):
        if not database.get_session(session_id):
            raise HTTPException(404, "找不到房间")
        return database.list_messages(session_id)

    @app.post("/api/sessions/{session_id}/messages")
    async def post_message(session_id: str, body: MessageIn):
        if not database.get_session(session_id):
            raise HTTPException(404, "找不到房间")
        if body.mode and body.mode not in MODES:
            raise HTTPException(400, "不支持的讨论模式")
        result = await room.ingest_message(session_id, body.content, body.reply_to_id, body.mode)
        if not result.get("ok"):
            raise HTTPException(400, result.get("error") or "无法发送")
        return result

    @app.post("/api/sessions/{session_id}/run")
    async def run_session(session_id: str, body: RunIn):
        if not database.get_session(session_id):
            raise HTTPException(404, "找不到房间")
        if body.mode and body.mode not in MODES:
            raise HTTPException(400, "不支持的讨论模式")
        return await room.start(session_id, mode=body.mode)

    @app.post("/api/sessions/{session_id}/pause")
    async def pause_session(session_id: str):
        if not database.get_session(session_id):
            raise HTTPException(404, "找不到房间")
        result = await room.pause(session_id)
        if not result.get("ok"):
            raise HTTPException(409, "当前没有在运行")
        return result

    @app.post("/api/sessions/{session_id}/resume")
    async def resume_session(session_id: str):
        if not database.get_session(session_id):
            raise HTTPException(404, "找不到房间")
        result = await room.resume(session_id)
        if not result.get("ok"):
            raise HTTPException(409, "当前没有暂停")
        return result

    @app.post("/api/sessions/{session_id}/stop")
    async def stop_session(session_id: str):
        if not database.get_session(session_id):
            raise HTTPException(404, "找不到房间")
        return await room.stop(session_id)

    @app.get("/api/sessions/{session_id}/events")
    async def events(session_id: str):
        if not database.get_session(session_id):
            raise HTTPException(404, "找不到房间")

        async def generate():
            queue = room.subscribe(session_id)
            try:
                snapshot = room.snapshot(session_id)
                snapshot["session"] = present_session(database, snapshot["session"])
                yield f"event: snapshot\ndata: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
                while True:
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=12)
                    except asyncio.TimeoutError:
                        yield "event: ping\ndata: {}\n\n"
                        continue
                    data = item["data"]
                    if item["event"] == "session" and isinstance(data, dict):
                        data = present_session(database, data)
                    yield f"event: {item['event']}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            finally:
                room.unsubscribe(session_id, queue)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


app = create_app()
