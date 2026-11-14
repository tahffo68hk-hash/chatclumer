"""Server-side secrets. Values never go to the frontend, git, or logs."""

from __future__ import annotations

import json
import os
from pathlib import Path

ALLOWED_SECRET_NAMES = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "OPENROUTER_API_KEY",
    "DEEPSEEK_API_KEY",
    "DASHSCOPE_API_KEY",
    "XAI_API_KEY",
    "OPENAI_COMPATIBLE_API_KEY",
    "OLLAMA_BASE_URL",
    "QQ_APP_ID",
    "QQ_BOT_TOKEN",
    "QQ_BOT_SECRET",
    "WECOM_CORP_ID",
    "WECOM_AGENT_SECRET",
    "WECOM_AGENT_ID",
    "WECHAT_OA_APPID",
    "WECHAT_OA_TOKEN",
)

ALLOW_PAID_NAME = "ALLOW_PAID_PROVIDERS"


class SecretStore:
    def __init__(self, path: str):
        self.path = Path(path)
        self.values: dict[str, str] = {}
        self.load()

    def load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = {}
            if isinstance(data, dict):
                self.values = {str(k): str(v) for k, v in data.items() if v}
        else:
            self.values = {}

    def get(self, name: str) -> str:
        env = os.environ.get(name, "")
        if env:
            return env
        return self.values.get(name, "")

    def configured(self, name: str) -> bool:
        return bool(self.get(name))

    def allow_paid(self) -> bool:
        return self.get(ALLOW_PAID_NAME).strip().lower() in {"1", "true", "yes", "on"}

    def set(self, name: str, value: str) -> None:
        if name not in ALLOWED_SECRET_NAMES and name != ALLOW_PAID_NAME:
            raise ValueError("不接受这个配置名")
        if value:
            self.values[name] = value
        else:
            self.values.pop(name, None)
        self._write()

    def set_allow_paid(self, enabled: bool) -> None:
        self.set(ALLOW_PAID_NAME, "1" if enabled else "")

    def public_status(self) -> dict:
        items = []
        for name in ALLOWED_SECRET_NAMES:
            items.append({"name": name, "configured": self.configured(name)})
        return {"secrets": items, "allow_paid": self.allow_paid()}

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.values, ensure_ascii=False, indent=2)
        tmp = self.path.with_suffix(".json.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.write("\n")
        except Exception:
            os.close(fd)
            raise
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)
        os.chmod(self.path, 0o600)
