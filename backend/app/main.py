"""HTTP API for the multi-LLM chat room."""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from .db import Database
from .engine import RoomEngine
from .providers import CATALOG, RoutedProvider
from .secrets import ALLOWED_SECRET_NAMES, SecretStore
from .groups import share_plan
from .util import reason_label, redact, status_label
from .webbridge import SITE_STATUS, SITES, WebBridge, origin_of, site_for_origin

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
FIXTURE_HTML = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>本地网页夹具</title></head>
<body>
<p id="model-name">Fixture 本地</p>
<div id="thread"></div>
<textarea id="composer" placeholder="写一句"></textarea>
<button id="send" type="button">发送</button>
<button id="stop" type="button" aria-label="Stop response" hidden>停止</button>
<script>
const thread = document.getElementById("thread");
const stop = document.getElementById("stop");
let timer = null;
stop.addEventListener("click", () => {
  if (timer) clearInterval(timer);
  timer = null;
  stop.hidden = true;
  const bot = thread.querySelector("[data-role=assistant][data-state=streaming]");
  if (bot) bot.dataset.state = "stopped";
});
document.getElementById("send").addEventListener("click", () => {
  const text = document.getElementById("composer").value.trim();
  if (!text) return;
  document.getElementById("composer").value = "";
  const user = document.createElement("div");
  user.dataset.role = "user";
  user.textContent = text;
  thread.appendChild(user);
  const bot = document.createElement("div");
  bot.dataset.role = "assistant";
  bot.dataset.state = "streaming";
  bot.textContent = "";
  thread.appendChild(bot);
  stop.hidden = false;
  const reply = "夹具收到：" + text;
  let i = 0;
  timer = setInterval(() => {
    i += 2;
    bot.textContent = reply.slice(0, i);
    if (i >= reply.length) {
      clearInterval(timer);
      timer = null;
      stop.hidden = true;
      bot.dataset.state = "complete";
    }
  }, 80);
});
</script>
</body></html>"""
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
    "web",
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
    summary_provider: str | None = None
    summary_model_id: str | None = None
    cross_delay_ms: int = 120
    room_rule: str = ""
    stop_on_no_new_point: bool = True
    layout: str = "shared"


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
    summary_provider: str | None = None
    summary_model_id: str | None = None
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
    audience: str | None = None
    group_id: str | None = None
    target_member_id: str | None = None


class GroupIn(BaseModel):
    member_ids: list[str] = Field(default_factory=list)
    message_ids: list[str] | None = None
    carry: str = "fresh"
    web_memory: str = "rebind"


class BindIn(BaseModel):
    web_site: str
    web_origin: str
    web_tab_key: str
    web_model_label: str = ""
    web_conversation: str = ""
    web_auto: bool = False


class PairIn(BaseModel):
    code: str


class JobResultIn(BaseModel):
    request_id: str
    run_id: str | None = None
    group_id: str | None = None
    member_id: str
    context_version: int
    text: str = ""
    model_label: str = ""
    status: str
    page_url: str
    detail: str = ""


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
    if data.get("layout") not in {None, "shared", "branches"}:
        raise HTTPException(400, "布局只能是共享时间线或独立分支")
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
    if "summary_mode" in data and data["summary_mode"] not in {None, "local", "member", "provider"}:
        raise HTTPException(400, "总结方式只能是本地回顾、指定成员或指定总结模型")
    if data.get("summary_mode") == "provider":
        provider = (data.get("summary_provider") or "").strip()
        model_id = (data.get("summary_model_id") or "").strip()
        if provider not in PROVIDERS:
            raise HTTPException(400, "总结模型的提供方不支持")
        if provider == "demo":
            if not DEMO_MODEL.match(model_id):
                raise HTTPException(400, "演示总结的模型 ID 必须以 demo- 开头")
        elif not model_id or model_id.startswith("demo-"):
            raise HTTPException(400, "总结模型需要精确 model ID，不能用 demo- 伪装")
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
    elif provider == "web":
        if model_id not in {f"web:{site}" for site in SITES}:
            raise HTTPException(400, "网页成员要写成 web:站点，不能猜测底层模型 ID")
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
    routed = provider or RoutedProvider(secret_store)
    room = RoomEngine(database, routed)
    bridge = WebBridge(database)
    room.web = bridge
    if hasattr(routed, "web"):
        routed.web = bridge

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

    @app.get("/fixture/chat", response_class=HTMLResponse)
    def fixture_chat():
        return FIXTURE_HTML

    @app.get("/api/ext/sites")
    def ext_sites():
        return {"sites": SITE_STATUS}

    def _ext_same_machine(request: Request) -> None:
        origin = request.headers.get("origin")
        if not origin:
            return
        if origin.startswith("chrome-extension://"):
            return
        if origin in {"http://127.0.0.1:43123", "http://localhost:43123"}:
            return
        raise HTTPException(403, "配对接口拒绝这个网页来源")

    @app.post("/api/ext/code")
    def ext_code(request: Request):
        _ext_same_machine(request)
        return bridge.issue_code()

    @app.post("/api/ext/pair")
    def ext_pair(body: PairIn, request: Request):
        _ext_same_machine(request)
        token = bridge.pair(body.code)
        if not token:
            raise HTTPException(401, "配对码无效或已用过")
        return {"token": token}

    def _require_ext(authorization: str | None) -> None:
        if not bridge.authorized(authorization):
            raise HTTPException(401, "配对无效")

    @app.get("/api/ext/jobs")
    def ext_jobs(request: Request, authorization: str | None = Header(None)):
        _ext_same_machine(request)
        _require_ext(authorization)
        return {"jobs": bridge.claim_jobs()}

    @app.post("/api/ext/jobs/result")
    def ext_result(body: JobResultIn, request: Request, authorization: str | None = Header(None)):
        _ext_same_machine(request)
        _require_ext(authorization)
        return bridge.finish_job(body.model_dump())

    @app.post("/api/sessions/{session_id}/groups/preview")
    def preview_group(session_id: str, body: GroupIn):
        if not database.get_session(session_id):
            raise HTTPException(404, "找不到房间")
        if len(set(body.member_ids)) < 2:
            raise HTTPException(400, "至少选择两个分支")
        try:
            return share_plan(database, session_id, body.member_ids, body.message_ids)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/sessions/{session_id}/groups/merge")
    async def merge_group(session_id: str, body: GroupIn):
        if not database.get_session(session_id):
            raise HTTPException(404, "找不到房间")
        result = await room.merge_groups(session_id, body.member_ids, body.message_ids)
        if not result.get("ok"):
            raise HTTPException(400, result.get("error") or "无法合并")
        session = database.get_session(session_id)
        if session and session["status"] not in {"running", "paused", "stopped"}:
            await room.start(session_id)
        return result

    @app.post("/api/sessions/{session_id}/groups/{group_id}/split")
    async def split_group(session_id: str, group_id: str, body: GroupIn):
        result = await room.split_group(
            session_id, group_id, body.member_ids, body.carry, body.message_ids, body.web_memory
        )
        if not result.get("ok"):
            raise HTTPException(400, result.get("error") or "无法拆分")
        return result

    @app.post("/api/sessions/{session_id}/groups/{group_id}/stop")
    async def stop_group(session_id: str, group_id: str):
        group = database.get_group(group_id)
        if not group or group["session_id"] != session_id:
            raise HTTPException(404, "找不到小组")
        database.set_group_status(group_id, "stopped")
        database.bump_context(session_id)
        bridge.cancel_members(group["member_ids"], "group_stop")
        room._pulse_stale(session_id)
        room.publish_state(session_id)
        return {"ok": True, "group": database.get_group(group_id)}

    @app.post("/api/members/{member_id}/web-bind")
    def bind_web(member_id: str, body: BindIn):
        member = database.get_member(member_id)
        if not member:
            raise HTTPException(404, "找不到成员")
        origin = origin_of(body.web_origin if "://" in body.web_origin else "")
        if site_for_origin(origin) != body.web_site:
            raise HTTPException(400, "来源和站点不一致，拒绝绑定")
        if not body.web_tab_key.strip() or len(body.web_tab_key) > 80:
            raise HTTPException(400, "需要这个标签页自己的绑定键")
        tab_key = body.web_tab_key.strip()
        for other in database.list_members(member["session_id"]):
            if other["id"] != member_id and (other.get("web_tab_key") or "") == tab_key:
                raise HTTPException(400, "两个成员不能共用同一个网页标签")
        label = (body.web_model_label or "").strip() or "未能核验精确 model ID"
        updated = database.update_member(
            member_id,
            {
                "provider": "web",
                "model_id": f"web:{body.web_site}",
                "web_site": body.web_site,
                "web_origin": origin,
                "web_tab_key": body.web_tab_key.strip(),
                "web_model_label": label,
                "web_conversation": (body.web_conversation or "bound")[:80],
                "web_auto": body.web_auto,
            },
        )
        return updated

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
        return {
            "session": present_session(database, session),
            "members": database.list_members(session_id),
            "groups": database.list_groups(session_id),
            "sites": SITE_STATUS,
        }

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
        result = await room.ingest_message(
            session_id,
            body.content,
            body.reply_to_id,
            body.mode,
            audience=body.audience,
            group_id=body.group_id,
            target_member_id=body.target_member_id,
        )
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
