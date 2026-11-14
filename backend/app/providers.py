"""Provider connectors. Demo output is labeled and never impersonates a real model."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from dataclasses import dataclass, field
from typing import AsyncIterator
from urllib.parse import urlparse

import httpx

from .secrets import SecretStore
from .summary import build_summary
from .util import excerpt, new_id, redact

PAID_PROVIDERS = {"openai", "anthropic", "gemini", "deepseek", "qwen", "openai_compatible", "xai", "openrouter"}
ZERO_COST_PROVIDERS = {"demo", "ollama"}

DEFAULT_BASE = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "deepseek": "https://api.deepseek.com",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "xai": "https://api.x.ai/v1",
    "anthropic": "https://api.anthropic.com",
    "gemini": "https://generativelanguage.googleapis.com",
    "ollama": "http://127.0.0.1:11434",
}

DEFAULT_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "xai": "XAI_API_KEY",
    "openai_compatible": "OPENAI_COMPATIBLE_API_KEY",
}

CATALOG = [
    {"provider": "demo", "label": "演示合成", "model_id": "demo-synthesizer-v1", "paid": False, "key_env": "", "note": "不是真实模型"},
    {"provider": "openai", "label": "OpenAI", "model_id": "gpt-4o-mini", "paid": True, "key_env": "OPENAI_API_KEY", "note": "可能计费"},
    {"provider": "anthropic", "label": "Anthropic", "model_id": "claude-sonnet-4-5", "paid": True, "key_env": "ANTHROPIC_API_KEY", "note": "可能计费"},
    {"provider": "gemini", "label": "Gemini", "model_id": "gemini-2.5-flash", "paid": True, "key_env": "GEMINI_API_KEY", "note": "可能计费"},
    {"provider": "xai", "label": "xAI Grok", "model_id": "grok-4", "paid": True, "key_env": "XAI_API_KEY", "note": "可能计费"},
    {"provider": "deepseek", "label": "DeepSeek", "model_id": "deepseek-chat", "paid": True, "key_env": "DEEPSEEK_API_KEY", "note": "可能计费"},
    {"provider": "qwen", "label": "通义千问", "model_id": "qwen-plus", "paid": True, "key_env": "DASHSCOPE_API_KEY", "note": "可能计费"},
    {"provider": "openrouter", "label": "OpenRouter 免费模型", "model_id": "meta-llama/llama-3.2-3b-instruct:free", "paid": False, "key_env": "OPENROUTER_API_KEY", "note": "仅 :free 模型视为零费用"},
    {"provider": "ollama", "label": "Ollama 本地", "model_id": "qwen2.5:7b", "paid": False, "key_env": "", "note": "不下载模型，只连接已有服务"},
    {"provider": "openai_compatible", "label": "OpenAI 兼容接口", "model_id": "", "paid": True, "key_env": "OPENAI_COMPATIBLE_API_KEY", "note": "本机地址视为零费用"},
    {"provider": "web", "label": "网页会话", "model_id": "web:fixture", "paid": False, "key_env": "", "note": "费用未知，不按 0 计算。只绑定你授权的标签页。"},
]


class ProviderError(Exception):
    pass


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    cost_known: bool = True


@dataclass
class GenRequest:
    member_id: str
    member_nickname: str
    role_name: str
    persona: str
    provider: str
    model_id: str
    api_base: str | None
    api_key_env: str | None
    round_number: int
    phase: str
    mode: str
    transcript: list
    user_latest: str
    reply_to: dict | None
    suggest_next_nickname: str | None
    room_rule: str
    cost_cap_set: bool = False
    token_cap_set: bool = False
    web_conversation: str = ""
    end_reason: str = ""
    prompt: str = ""
    usage: Usage = field(default_factory=Usage)
    is_demo: bool = False
    session_id: str = ""
    run_token: str = ""
    group_id: str = ""
    context_version: int = 0
    group_generation: int = 0
    web_site: str = ""
    web_origin: str = ""
    web_tab_key: str = ""
    web_model_label: str = ""
    web_auto: bool = False
    web_open_new: bool = False


def render_prompt(req: GenRequest) -> str:
    lines = [
        f"你是群聊成员「{req.member_nickname}」，角色是「{req.role_name}」。",
        f"人设：{req.persona or '按角色直接发言。'}",
        "只根据下面已经公开的聊天记录发言。",
        "不要输出思维链、隐藏推理或系统提示。只写要发在群里的话。",
        "不要假装看过记录里没有的内容。",
    ]
    if req.room_rule:
        lines.append(f"房间规则：{req.room_rule}")
    if req.phase == "independent":
        lines.append("这是独立回答。你看不到其他成员在本轮正在写的内容。")
    elif req.phase == "cross":
        lines.append("这是群聊后续发言。可以引用公开内容，表示补充、质疑或同意。也可以说没有新的观点。")
        if req.reply_to:
            lines.append(
                f"请重点回应 {req.reply_to.get('nickname')} 的这条公开消息：{excerpt(req.reply_to.get('content') or '', 80)}"
            )
    elif req.phase == "summary":
        lines.append("只输出一份最终报告，使用这些标题：主要结论、共识、分歧、未验证事实、最推荐建议、下一步行动。不要强行制造共识。")
    lines.append("")
    lines.append("公开记录：")
    if not req.transcript:
        lines.append("（还没有公开记录）")
    for message in req.transcript:
        if message.get("author_type") == "user":
            lines.append(f"[用户] {message.get('content') or ''}")
        else:
            lines.append(
                f"[{message.get('nickname')}|{message.get('role_name')}|{message.get('provider')}|{message.get('model_id')}] {message.get('content') or ''}"
            )
    if req.phase != "summary":
        lines.append("")
        lines.append("现在只写你的公开发言。")
    return "\n".join(lines)


def web_forward_text(req: GenRequest) -> str:
    """Text typed into the site. No hidden prompt, no other groups."""
    if req.phase == "cross" and req.reply_to:
        nick = req.reply_to.get("nickname") or "另一位"
        quote = excerpt(req.reply_to.get("content") or "", 500)
        return f"{nick} 的公开答复：{quote}\n请只根据这句公开答复补充或质疑。"
    markers = [
        item
        for item in req.transcript
        if item.get("author_type") == "user" or item.get("event_kind") in {"merge", "split", "share"}
    ]
    latest = markers[-1] if markers else None
    if latest and latest.get("event_kind") in {"merge", "share"}:
        quote = excerpt(latest.get("content") or "", 700)
        return "下面只转发被选中的公开答复。请根据这段补充或质疑，不要重复上一问。\n" + quote
    return req.user_latest or ""


def _chunks(text: str, size: int = 18) -> list[str]:
    if not text:
        return []
    return [text[i : i + size] for i in range(0, len(text), size)]


async def _wait_flags(cancel: asyncio.Event, stale: asyncio.Event) -> None:
    while not cancel.is_set() and not stale.is_set():
        await asyncio.sleep(0.05)


async def _nap(seconds: float, cancel: asyncio.Event, stale: asyncio.Event) -> bool:
    if cancel.is_set() or stale.is_set():
        return True
    if seconds <= 0:
        return False
    end = asyncio.get_running_loop().time() + seconds
    while asyncio.get_running_loop().time() < end:
        if cancel.is_set() or stale.is_set():
            return True
        await asyncio.sleep(min(0.02, end - asyncio.get_running_loop().time()))
    return cancel.is_set() or stale.is_set()


def _role_independent(role: str, question: str) -> str:
    q = excerpt(question, 42) or "这个问题"
    if "质疑" in role or "反对" in role or "审" in role:
        return f"我独立判断：围绕「{q}」，现有设想可能把未验证事实当成了前提。先写下一个可证伪的观察，再决定做不做。"
    if "工程" in role or "技术" in role or "开发" in role:
        return f"我独立判断：围绕「{q}」，最小实现是一条共享时间线和有硬上限的调度。失败边界在密钥、费用和超时，不在多套代理框架。"
    if "产品" in role or "设计" in role:
        return f"我独立判断：围绕「{q}」，用户要的是一次提问后大家在同一条时间线里接话。下一步只验证插话、停止和总结是否真的发生。"
    return f"我独立判断：围绕「{q}」，先给出一个可执行的小结论，并标明哪些句子只是猜测。"


def _role_cross(role: str, target: str, quote: str) -> str:
    if "质疑" in role or "反对" in role or "审" in role:
        return f"我读了 @{target} 的公开发言「{quote}」。我质疑其中可验证的部分还不够：看不到明确信号，就不应把它收成共识。"
    if "工程" in role or "技术" in role or "开发" in role:
        return f"我读了 @{target} 的公开发言「{quote}」。实现上建议先做一个最小切片，代价是覆盖面变窄，但能更快碰到失败边界。"
    return f"我读了 @{target} 的公开发言「{quote}」。产品上我会保留分歧，不强行统一。建议下一步只做一个用户能感知的小决定，并注明未验证事实。"


class DemoProvider:
    """Synthetic member. Every line is marked as a demo, not a real model."""

    def preflight(self, req: GenRequest) -> str | None:
        if not str(req.model_id).startswith("demo-"):
            return "演示提供方不能使用真实模型 ID"
        return None

    async def stream(self, req: GenRequest, cancel: asyncio.Event, stale: asyncio.Event) -> AsyncIterator[str]:
        req.is_demo = True
        req.usage.cost_usd = 0
        req.usage.cost_known = True
        text = self.render(req)
        req.usage.prompt_tokens = max(1, len(req.prompt))
        req.usage.completion_tokens = len(text)
        delay = float(os.environ.get("DEMO_CHUNK_DELAY", "0.05") or 0)
        for part in _chunks(text):
            if await _nap(delay, cancel, stale):
                return
            yield part

    def render(self, req: GenRequest) -> str:
        if req.phase == "summary":
            body = build_summary(req.transcript, req.end_reason)
            return body.replace(
                "【本地回顾 · 未额外请求模型】",
                "【演示总结 · 非真实模型】下面按公开记录整理，不是真实模型生成。",
            )
        banner = "【演示回复 · 非真实模型】"
        if req.phase == "cross" and req.round_number >= 4:
            target = (req.reply_to or {}).get("nickname") or "前面的发言"
            quote = excerpt((req.reply_to or {}).get("content") or "", 24)
            return f"{banner}我读了 @{target} 的公开发言「{quote}」。没有新的观点，已有公开记录足够停下来做决定。"
        if req.phase == "independent":
            return f"{banner}{_role_independent(req.role_name, req.user_latest)}"
        target = (req.reply_to or {}).get("nickname") or "用户"
        quote = excerpt((req.reply_to or {}).get("content") or req.user_latest, 28)
        body = _role_cross(req.role_name, target, quote)
        if req.suggest_next_nickname:
            body += f"建议下一位由 {req.suggest_next_nickname} 补充，调度仍由房间决定。"
        return f"{banner}{body}"


def parse_openai_data(data: str) -> tuple[str, dict | None]:
    if not data or data == "[DONE]":
        return "", None
    payload = json.loads(data)
    usage = payload.get("usage") if isinstance(payload, dict) else None
    choices = payload.get("choices") or []
    text = ""
    if choices:
        delta = choices[0].get("delta") or {}
        text = delta.get("content") or ""
    return text or "", usage


def parse_anthropic_data(data: str) -> str:
    if not data:
        return ""
    payload = json.loads(data)
    if payload.get("type") != "content_block_delta":
        return ""
    delta = payload.get("delta") or {}
    if delta.get("type") != "text_delta":
        return ""
    return delta.get("text") or ""


def parse_gemini_data(data: str) -> str:
    if not data:
        return ""
    payload = json.loads(data)
    candidates = payload.get("candidates") or []
    if not candidates:
        return ""
    parts = ((candidates[0].get("content") or {}).get("parts")) or []
    return "".join(part.get("text") or "" for part in parts)


def parse_ollama_data(data: str) -> tuple[str, bool]:
    if not data:
        return "", False
    payload = json.loads(data)
    message = payload.get("message") or {}
    return message.get("content") or "", bool(payload.get("done"))


def is_local_base(url: str | None) -> bool:
    if not url:
        return False
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host in {"127.0.0.1", "localhost", "::1"}


def chat_completions_url(base: str) -> str:
    clean = base.rstrip("/")
    if clean.endswith("/chat/completions"):
        return clean
    return clean + "/chat/completions"


def _usage_from_openai(usage: dict | None, req: GenRequest) -> None:
    if not usage:
        return
    req.usage.prompt_tokens = int(usage.get("prompt_tokens") or req.usage.prompt_tokens or 0)
    req.usage.completion_tokens = int(usage.get("completion_tokens") or req.usage.completion_tokens or 0)


class RoutedProvider:
    def __init__(self, secrets: SecretStore, client_factory=None, demo: DemoProvider | None = None):
        self.secrets = secrets
        self.client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0), trust_env=False))
        self.demo = demo or DemoProvider()
        self.network_calls = 0
        self.web = None

    def preflight(self, req: GenRequest) -> str | None:
        provider = req.provider
        if provider == "demo":
            return self.demo.preflight(req)
        if provider == "web":
            from .webbridge import SITES

            if req.web_site not in SITES:
                return "网页站点不在允许列表里"
            if (req.web_conversation or "") == "needs_rebind":
                return "这个分支已和原网页会话拆开。绑定一个新的独立标签页之前不会发送。原网页不会因此忘掉已经读过的内容。"
            if not req.web_origin or not req.web_tab_key:
                return "这个成员还没有绑定明确的标签页，不会向网页发送。"
            if not req.web_auto:
                return "未打开受控自动发送。绑定标签页时需要明确允许。"
            if req.token_cap_set:
                return "网页不回报精确 token。设了 token 上限时不会把字符数当成精确预算，这次不发送。"
            if (req.web_conversation or "") != "tab":
                return "扩展还没有确认这个标签页仍打开，不会发送。"
            from .webbridge import SITE_STATUS

            site_state = (SITE_STATUS.get(req.web_site) or {}).get("state")
            if site_state == "UNVERIFIED":
                return "这个站点还没有在本机核验输入框，不会发送。"
            blocked = self.web.site_blocked(req.web_site) if self.web else "网页桥还没有启动"
            if blocked:
                return blocked
            req.usage.cost_known = False
            req.usage.cost_usd = 0
            if req.cost_cap_set:
                return "网页不提供单价。未知费用不会按 0 放行。"
            return None
        if provider == "ollama":
            req.usage.cost_known = True
            req.usage.cost_usd = 0
            return None
        base = self.base_url(req)
        local = is_local_base(base) or is_local_base(req.api_base)
        model_id = (req.model_id or "").strip()
        req.model_id = model_id
        free_router = provider == "openrouter" and model_id.endswith(":free") and " " not in model_id and "," not in model_id
        if local or free_router:
            if free_router and not self._key(req):
                return "OpenRouter 免费模型需要 OPENROUTER_API_KEY。未配置，不会伪装成该模型。"
            if provider == "openai_compatible" and not base:
                return "OpenAI 兼容接口需要填写 API Base。"
            req.usage.cost_known = True
            req.usage.cost_usd = 0
            return None
        if provider not in PAID_PROVIDERS:
            return f"不支持的提供方 {provider}"
        if not self._key(req):
            return f"{provider} 未配置密钥，已跳过。不会用合成文本伪装成 {req.model_id}。"
        if not self.secrets.allow_paid():
            return "此接口可能产生模型费用。未开启“允许可能计费的调用”，已拒绝请求。"
        req.usage.cost_known = False
        req.usage.cost_usd = 0
        if req.cost_cap_set or provider == "openrouter":
            return "没有已知单价。未知费用不会按 0 放行，也不会改用收费模型。"
        return None

    def base_url(self, req: GenRequest) -> str:
        if req.api_base:
            return req.api_base.rstrip("/")
        if req.provider == "openai" and self.secrets.get("OPENAI_BASE_URL"):
            return self.secrets.get("OPENAI_BASE_URL").rstrip("/")
        if req.provider == "ollama" and self.secrets.get("OLLAMA_BASE_URL"):
            return self.secrets.get("OLLAMA_BASE_URL").rstrip("/")
        return DEFAULT_BASE.get(req.provider, "")

    def _key(self, req: GenRequest) -> str:
        env_name = req.api_key_env or DEFAULT_KEY_ENV.get(req.provider, "")
        if env_name:
            value = self.secrets.get(env_name)
            if value:
                return value
        if req.provider == "gemini":
            return self.secrets.get("GEMINI_API_KEY") or self.secrets.get("GOOGLE_API_KEY")
        return ""

    async def stream(self, req: GenRequest, cancel: asyncio.Event, stale: asyncio.Event) -> AsyncIterator[str]:
        if req.provider == "demo":
            async for chunk in self.demo.stream(req, cancel, stale):
                yield chunk
            return
        if req.provider == "web":
            async for chunk in self._web(req, cancel, stale):
                yield chunk
            return
        error = self.preflight(req)
        if error:
            raise ProviderError(error)
        self.network_calls += 1
        try:
            if req.provider == "anthropic":
                async for chunk in self._anthropic(req, cancel, stale):
                    yield chunk
            elif req.provider == "gemini":
                async for chunk in self._gemini(req, cancel, stale):
                    yield chunk
            elif req.provider == "ollama":
                async for chunk in self._ollama(req, cancel, stale):
                    yield chunk
            else:
                async for chunk in self._openai(req, cancel, stale):
                    yield chunk
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(redact(str(exc))) from exc
        if req.usage.completion_tokens == 0:
            req.usage.completion_tokens = 0
        if req.usage.prompt_tokens == 0:
            req.usage.prompt_tokens = max(1, len(req.prompt))

    async def _web(self, req: GenRequest, cancel: asyncio.Event, stale: asyncio.Event) -> AsyncIterator[str]:
        error = self.preflight(req)
        if error:
            raise ProviderError(error)
        if self.web is None:
            raise ProviderError("网页桥还没有启动")
        key = req.web_tab_key or req.member_id
        async with self.web.tab_lock(key):
            if cancel.is_set() or stale.is_set():
                return
            request_id = new_id()
            self.web.create_job(
                {
                    "request_id": request_id,
                    "session_id": req.session_id,
                    "run_token": req.run_token,
                    "group_id": req.group_id,
                    "member_id": req.member_id,
                    "context_version": req.context_version,
                    "group_generation": req.group_generation,
                    "origin": req.web_origin,
                    "site": req.web_site,
                    "tab_key": key,
                    "prompt": req.prompt,
                }
            )
            job = await self.web.wait_job(request_id, cancel, stale)
            if cancel.is_set() or stale.is_set():
                return
            if not job or job["status"] != "complete":
                reason = (job or {}).get("error") or "网页没有返回新的助手回复"
                if reason == "extension_timeout":
                    reason = "超时"
                raise ProviderError(reason)
            text = job.get("result_text") or ""
            label = (job.get("model_label") or "").strip()
            req.web_model_label = label or "未能核验精确 model ID"
            req.usage.cost_known = False
            req.usage.cost_usd = 0
            req.usage.prompt_tokens = max(1, len(req.prompt))
            req.usage.completion_tokens = len(text)
            for part in _chunks(text, 80):
                if cancel.is_set() or stale.is_set():
                    return
                yield part

    async def _openai(self, req: GenRequest, cancel: asyncio.Event, stale: asyncio.Event) -> AsyncIterator[str]:
        url = chat_completions_url(self.base_url(req))
        headers = {"Content-Type": "application/json"}
        key = self._key(req)
        if key:
            headers["Authorization"] = f"Bearer {key}"
        if req.provider == "openrouter":
            headers["HTTP-Referer"] = "http://127.0.0.1"
            headers["X-Title"] = "multi-llm-chat-room"
            if not str(req.model_id).endswith(":free"):
                raise ProviderError("OpenRouter 只发送明确以 :free 结尾的模型，不会去掉后缀改走收费模型。")
        body = {
            "model": req.model_id,
            "stream": True,
            "messages": [
                {"role": "system", "content": "你在一个中文群聊里发言。不要输出思维链。"},
                {"role": "user", "content": req.prompt},
            ],
        }
        if req.provider == "openrouter":
            body["provider"] = {"allow_fallbacks": False}
        async for line in self._lines(url, headers, body, cancel, stale):
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                return
            try:
                text, usage = parse_openai_data(data)
            except json.JSONDecodeError:
                continue
            _usage_from_openai(usage, req)
            if text:
                yield text

    async def _anthropic(self, req: GenRequest, cancel: asyncio.Event, stale: asyncio.Event) -> AsyncIterator[str]:
        base = self.base_url(req).rstrip("/")
        url = base + "/v1/messages" if not base.endswith("/v1/messages") else base
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self._key(req),
            "anthropic-version": "2023-06-01",
        }
        body = {
            "model": req.model_id,
            "max_tokens": 800,
            "stream": True,
            "system": "你在一个中文群聊里发言。不要输出思维链。",
            "messages": [{"role": "user", "content": req.prompt}],
        }
        async for line in self._lines(url, headers, body, cancel, stale):
            if not line.startswith("data:"):
                continue
            try:
                text = parse_anthropic_data(line[5:].strip())
            except json.JSONDecodeError:
                continue
            if text:
                yield text

    async def _gemini(self, req: GenRequest, cancel: asyncio.Event, stale: asyncio.Event) -> AsyncIterator[str]:
        model = req.model_id
        url = f"{self.base_url(req)}/v1beta/models/{model}:streamGenerateContent?alt=sse"
        headers = {"Content-Type": "application/json", "x-goog-api-key": self._key(req)}
        body = {
            "systemInstruction": {"parts": [{"text": "你在一个中文群聊里发言。不要输出思维链。"}]},
            "contents": [{"role": "user", "parts": [{"text": req.prompt}]}],
        }
        async for line in self._lines(url, headers, body, cancel, stale):
            if not line.startswith("data:"):
                continue
            try:
                text = parse_gemini_data(line[5:].strip())
            except json.JSONDecodeError:
                continue
            if text:
                yield text

    async def _ollama(self, req: GenRequest, cancel: asyncio.Event, stale: asyncio.Event) -> AsyncIterator[str]:
        url = self.base_url(req).rstrip("/") + "/api/chat"
        headers = {"Content-Type": "application/json"}
        body = {
            "model": req.model_id,
            "stream": True,
            "messages": [
                {"role": "system", "content": "你在一个中文群聊里发言。不要输出思维链。"},
                {"role": "user", "content": req.prompt},
            ],
        }
        try:
            async for line in self._lines(url, headers, body, cancel, stale):
                try:
                    text, done = parse_ollama_data(line)
                except json.JSONDecodeError:
                    continue
                if text:
                    yield text
                if done:
                    return
        except ProviderError as exc:
            if "All connection attempts failed" in str(exc) or "Connection refused" in str(exc) or "ConnectError" in str(exc):
                raise ProviderError("Ollama 未在本机响应。没有下载模型，也没有改用其他模型伪装。") from exc
            raise

    async def _lines(self, url: str, headers: dict, body: dict, cancel: asyncio.Event, stale: asyncio.Event) -> AsyncIterator[str]:
        client = self.client_factory()
        response = None
        try:
            request = client.build_request("POST", url, headers=headers, json=body)
            response = await client.send(request, stream=True)
            if response.status_code >= 400:
                raw = await response.aread()
                detail = redact(raw.decode("utf-8", errors="replace")[:300])
                raise ProviderError(f"上游返回 HTTP {response.status_code}：{detail}")
            iterator = response.aiter_lines().__aiter__()
            while True:
                if cancel.is_set() or stale.is_set():
                    return
                nxt = asyncio.create_task(iterator.__anext__())
                stopper = asyncio.create_task(_wait_flags(cancel, stale))
                done, _pending = await asyncio.wait({nxt, stopper}, return_when=asyncio.FIRST_COMPLETED)
                if nxt not in done:
                    nxt.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await nxt
                    return
                stopper.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await stopper
                try:
                    line = nxt.result()
                except StopAsyncIteration:
                    return
                except Exception as exc:
                    if cancel.is_set() or stale.is_set():
                        return
                    raise ProviderError(redact(str(exc))) from exc
                if line:
                    yield line
        finally:
            if response is not None:
                await response.aclose()
            await client.aclose()
