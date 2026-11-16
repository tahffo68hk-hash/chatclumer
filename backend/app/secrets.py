"""Server-side secrets. Values never go to the frontend, git, or logs."""

from __future__ import annotations

import json
import os
import re
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


def _windows_dacl_sddl(path: Path) -> str:
    """用 icacls /save 读出文件 DACL 的 SDDL（带 SID，不受系统语言影响）。"""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        dump = Path(d) / "acl.txt"
        out = subprocess.run(["icacls", str(path), "/save", str(dump)], capture_output=True, check=False)
        if out.returncode != 0 or not dump.exists():
            return ""
        raw = dump.read_bytes()
    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-16-le", errors="replace")
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("D:"):
            return line
    return ""


def private_file_is_owner_only(path: Path) -> bool:
    if os.name != "nt":
        return (path.stat().st_mode & 0o777) == 0o600
    sddl = _windows_dacl_sddl(path)
    if not sddl.startswith("D:P"):  # 继承已关闭
        return False
    sid = _current_user_sid()
    me = {sid} | ({"LA"} if sid.endswith("-500") else set())
    # SYSTEM、管理员组、OWNER RIGHTS 本来就能读本机任何文件，允许保留；其他账户一律不行
    privileged = {"SY", "BA", "OW", "S-1-5-18", "S-1-5-32-544", "S-1-3-4"}
    aces = [a.split(";") for a in re.findall(r"\(([^)]*)\)", sddl)]
    if not aces or any(len(a) < 6 or a[0] != "A" or "ID" in a[1] for a in aces):
        return False
    trustees = {a[5] for a in aces}
    return bool(trustees & me) and trustees <= me | privileged


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
