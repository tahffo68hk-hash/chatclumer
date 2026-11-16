"""Server-side secrets. Values never go to the frontend, git, or logs."""

from __future__ import annotations

import json
import os
import subprocess
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
    "SILICONFLOW_API_KEY",
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

_WINDOWS_CHECK = r"""
$ErrorActionPreference = 'Stop'
$path = $env:CHAT_ROOM_PRIVATE_FILE
$acl = Get-Acl -LiteralPath $path
if (-not $acl.AreAccessRulesProtected) { exit 2 }
$me = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$rules = @($acl.Access)
if ($rules.Count -ne 1) { exit 3 }
$sid = $rules[0].IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
if ($sid -ne $me) { exit 4 }
if ([string]$rules[0].AccessControlType -ne 'Allow') { exit 5 }
exit 0
"""


def _powershell(script: str, path: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["CHAT_ROOM_PRIVATE_FILE"] = str(path)
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        env=env,
        check=False,
    )


_CURRENT_SID: str | None = None


def _current_user_sid() -> str:
    """当前 Windows 用户的 SID，用 whoami 读取并缓存。"""
    global _CURRENT_SID
    if _CURRENT_SID is None:
        out = subprocess.run(
            ["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
        )
        sid = out.stdout.strip().rsplit(",", 1)[-1].strip().strip('"') if out.returncode == 0 else ""
        if not sid.startswith("S-"):
            raise OSError("没有收紧密钥文件权限：读不到当前用户")
        _CURRENT_SID = sid
    return _CURRENT_SID


def protect_private_file(path: Path) -> None:
    """POSIX 用 0600。Windows 的 chmod 不改变 ACL，所以用 icacls 去掉继承权限、只留当前用户修改权限。"""
    if os.name != "nt":
        os.chmod(path, 0o600)
        return
    sid = _current_user_sid()
    result = subprocess.run(
        ["icacls", str(path), "/inheritance:r", "/grant:r", f"*{sid}:(M)"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    if result.returncode != 0:
        # 只给出 icacls 的退出码，不带文件内容
        raise OSError(f"没有收紧密钥文件权限（icacls 退出码 {result.returncode}）")


def private_file_is_owner_only(path: Path) -> bool:
    if os.name != "nt":
        return (path.stat().st_mode & 0o777) == 0o600
    return _powershell(_WINDOWS_CHECK, path).returncode == 0


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
        protect_private_file(tmp)
        os.replace(tmp, self.path)
        protect_private_file(self.path)
