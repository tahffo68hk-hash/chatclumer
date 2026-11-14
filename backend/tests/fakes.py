import asyncio
import time

from app.providers import ProviderError


class GateProvider:
    def __init__(self):
        self.order = []

    def preflight(self, req):
        return None

    async def stream(self, req, cancel, stale):
        slot = {"req": req, "go": asyncio.Event(), "started": asyncio.Event()}
        self.order.append(slot)
        slot["started"].set()
        while not slot["go"].is_set():
            if cancel.is_set() or stale.is_set():
                return
            await asyncio.sleep(0.01)
        if cancel.is_set() or stale.is_set():
            return
        yield f"已看到最新问题：{req.user_latest[:40]}"


class EchoProvider:
    def __init__(self, delay: float = 0.12):
        self.delay = delay
        self.prompts = []
        self.starts = []
        self.ends = []
        self.calls = 0

    async def stream(self, req, cancel, stale):
        self.calls += 1
        self.starts.append(time.monotonic())
        self.prompts.append(req.prompt)
        await asyncio.sleep(self.delay)
        if cancel.is_set() or stale.is_set():
            return
        self.ends.append(time.monotonic())
        if req.phase == "independent":
            yield f"UNIQUE_{req.member_nickname}"
        else:
            nick = (req.reply_to or {}).get("nickname") or "用户"
            yield f"我读了 @{nick}"


class CostProvider:
    def __init__(self, cost: float = 0.5, tokens: int = 8):
        self.cost = cost
        self.tokens = tokens
        self.calls = 0

    async def stream(self, req, cancel, stale):
        self.calls += 1
        req.usage.cost_usd = self.cost
        req.usage.cost_known = True
        req.usage.prompt_tokens = 4
        req.usage.completion_tokens = self.tokens
        yield "花费回答"


class SlowProvider:
    def __init__(self):
        self.calls = 0
        self.entered = asyncio.Event()

    async def stream(self, req, cancel, stale):
        self.calls += 1
        self.entered.set()
        await asyncio.sleep(5)
        yield "LATE"


class FlakyProvider:
    def __init__(self, bad: set[str]):
        self.bad = bad
        self.calls = []

    async def stream(self, req, cancel, stale):
        self.calls.append(req.member_nickname)
        if req.member_nickname in self.bad:
            raise ProviderError("upstream 503 sk-secretSHOULDNOTLEAK")
        yield "正常公开回答"


class ViewpointProvider:
    def __init__(self):
        self.calls = 0

    async def stream(self, req, cancel, stale):
        self.calls += 1
        if req.phase == "cross":
            yield "没有新的观点"
        else:
            yield f"独立看法 {req.member_nickname}"
