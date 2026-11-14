import json

import httpx
import pytest

from app.providers import (
    GenRequest,
    ProviderError,
    RoutedProvider,
    parse_anthropic_data,
    parse_gemini_data,
    parse_ollama_data,
    parse_openai_data,
)
from app.secrets import SecretStore


def request_for(provider: str, model: str, base: str | None = None) -> GenRequest:
    return GenRequest(
        member_id="m",
        member_nickname="测试",
        role_name="工程师",
        persona="",
        provider=provider,
        model_id=model,
        api_base=base,
        api_key_env=None,
        round_number=1,
        phase="independent",
        mode="independent",
        transcript=[{"author_type": "user", "content": "你好"}],
        user_latest="你好",
        reply_to=None,
        suggest_next_nickname=None,
        room_rule="",
        prompt="请回答",
    )


def test_parsers():
    text, usage = parse_openai_data('{"choices":[{"delta":{"content":"你"}}],"usage":{"prompt_tokens":2,"completion_tokens":1}}')
    assert text == "你"
    assert usage["prompt_tokens"] == 2
    assert parse_openai_data("[DONE]") == ("", None)
    assert parse_anthropic_data('{"type":"content_block_delta","delta":{"type":"text_delta","text":"好"}}') == "好"
    assert parse_gemini_data('{"candidates":[{"content":{"parts":[{"text":"嗯"}]}}]}') == "嗯"
    chunk, done = parse_ollama_data('{"message":{"content":"本地"},"done":false}')
    assert chunk == "本地" and done is False


@pytest.mark.asyncio
async def test_openai_anthropic_gemini_ollama_mock_streams(tmp_path):
    secrets = SecretStore(str(tmp_path / "secrets.json"))
    secrets.set("OPENAI_API_KEY", "sk-test")
    secrets.set("ANTHROPIC_API_KEY", "ant-test")
    secrets.set("GEMINI_API_KEY", "gem-test")
    secrets.set_allow_paid(True)
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        auth = request.headers.get("authorization", "") + request.headers.get("x-api-key", "") + request.headers.get("x-goog-api-key", "")
        assert "sk-test" in auth or "ant-test" in auth or "gem-test" in auth or "/api/chat" in str(request.url)
        if request.url.path.endswith("/chat/completions"):
            body = 'data: {"choices":[{"delta":{"content":"你"}}]}\n\ndata: [DONE]\n\n'
        elif request.url.path.endswith("/messages"):
            body = 'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"安"}}\n\n'
        elif "streamGenerateContent" in str(request.url):
            body = 'data: {"candidates":[{"content":{"parts":[{"text":"谷"}]}}]}\n\n'
        else:
            body = '{"message":{"content":"羊"},"done":true}\n'
        return httpx.Response(200, text=body)

    transport = httpx.MockTransport(handler)

    def factory():
        return httpx.AsyncClient(transport=transport, trust_env=False)

    provider = RoutedProvider(secrets, client_factory=factory)
    import asyncio

    async def collect(req):
        cancel, stale = asyncio.Event(), asyncio.Event()
        parts = []
        async for chunk in provider.stream(req, cancel, stale):
            parts.append(chunk)
        return "".join(parts)

    assert await collect(request_for("openai", "gpt-4o-mini", "https://example.test/v1")) == "你"
    assert await collect(request_for("anthropic", "claude-sonnet-4-5", "https://example.test")) == "安"
    assert await collect(request_for("gemini", "gemini-2.5-flash", "https://example.test")) == "谷"
    assert await collect(request_for("ollama", "qwen2.5:7b", "http://127.0.0.1:11434")) == "羊"
    assert provider.network_calls == 4
    assert seen


@pytest.mark.asyncio
async def test_paid_and_free_router_guards(tmp_path):
    secrets = SecretStore(str(tmp_path / "secrets.json"))
    secrets.set("OPENAI_API_KEY", "sk-test")

    def factory():
        raise AssertionError("should not dial")

    provider = RoutedProvider(secrets, client_factory=factory)
    import asyncio

    cancel, stale = asyncio.Event(), asyncio.Event()
    with pytest.raises(ProviderError) as raised:
        async for _chunk in provider.stream(request_for("openai", "gpt-4o-mini"), cancel, stale):
            pass
    assert "计费" in str(raised.value)
    assert provider.network_calls == 0

    missing = RoutedProvider(SecretStore(str(tmp_path / "empty.json")), client_factory=factory)
    req = request_for("openrouter", "meta-llama/llama-3.2-3b-instruct:free", "https://openrouter.ai/api/v1")
    with pytest.raises(ProviderError) as raised:
        async for _chunk in missing.stream(req, cancel, stale):
            pass
    assert "OPENROUTER" in str(raised.value)
    assert "伪装" in str(raised.value)
