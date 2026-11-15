"""Installers, release archives, and the desktop-shell test runner."""

import importlib.util
import os
import re
import stat
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NODE = os.environ.get("NODE_BINARY") or __import__("shutil").which("node")


def _release():
    spec = importlib.util.spec_from_file_location("build_release", ROOT / "scripts" / "build_release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(args, env=None, check=False):
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(args, cwd=ROOT, env=merged, text=True, capture_output=True, check=check)


def _fake_bin(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text(body)
    path.chmod(0o755)


def test_install_sh_dry_run_checks_versions_and_prints_chinese_steps():
    script = ROOT / "scripts" / "install.sh"
    assert script.stat().st_mode & stat.S_IXUSR
    syntax = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert syntax.returncode == 0, syntax.stderr
    before = (ROOT / "backend" / ".venv").exists()
    result = _run(["bash", "scripts/install.sh", "--dry-run"])
    assert result.returncode == 0, result.stderr
    assert (ROOT / "backend" / ".venv").exists() is before
    out = result.stdout
    assert "不会创建虚拟环境" in out
    assert "npm ci" in out
    assert "scripts/start.sh" in out
    assert "http://127.0.0.1:43123" in out
    assert "chrome://extensions" in out
    assert "开发者模式" in out
    assert "加载已解压的扩展程序" in out
    assert "extension/" in out
    assert "配对码" in out
    assert "桌面壳" in out
    assert "原型" in out
    assert "默认只监听 127.0.0.1" in out
    assert "将监听 0.0.0.0" not in out
    text = script.read_text(encoding="utf-8")
    assert "pkexec" not in text
    assert re.search(r"^\s*sudo\b", text, re.M) is None
    lan = _run(["bash", "scripts/install.sh", "--dry-run"], env={"LAN": "1"})
    assert lan.returncode == 0, lan.stderr
    assert "警告：前端将监听 0.0.0.0。此服务没有登录认证，不要暴露到公网或做端口转发。" in lan.stdout
    assert "后端仍只绑定 127.0.0.1，浏览器通过前端反代访问。" in lan.stdout


def test_install_sh_refuses_old_python_node_and_missing_npm(tmp_path):
    old_py = tmp_path / "oldpy"
    old_py.mkdir()
    _fake_bin(old_py, "python3", "#!/bin/sh\nif [ \"$1\" = \"--version\" ]; then echo 'Python 3.9.2'; exit 0; fi\nexit 1\n")
    _fake_bin(old_py, "python", "#!/bin/sh\nif [ \"$1\" = \"--version\" ]; then echo 'Python 3.8.0'; exit 0; fi\nexit 1\n")
    refused = _run(["bash", "scripts/install.sh", "--dry-run"], env={"PATH": f"{old_py}:/usr/bin:/bin"})
    assert refused.returncode != 0
    assert "缺少 Python" in refused.stderr
    assert "3.10" in refused.stderr

    new_py = tmp_path / "newpy"
    new_py.mkdir()
    _fake_bin(new_py, "python3", "#!/bin/sh\nif [ \"$1\" = \"--version\" ]; then echo 'Python 3.12.1'; exit 0; fi\nexit 1\n")
    _fake_bin(new_py, "node", "#!/bin/sh\nif [ \"$1\" = \"--version\" ]; then echo 'v19.9.0'; exit 0; fi\nexit 1\n")
    old_node = _run(["bash", "scripts/install.sh", "--dry-run"], env={"PATH": f"{new_py}:/usr/bin:/bin"})
    assert old_node.returncode != 0
    assert "需要 20" in old_node.stderr

    ok = tmp_path / "ok"
    ok.mkdir()
    _fake_bin(ok, "python3", "#!/bin/sh\nif [ \"$1\" = \"--version\" ]; then echo 'Python 3.11.4'; exit 0; fi\nexit 1\n")
    _fake_bin(ok, "node", "#!/bin/sh\nif [ \"$1\" = \"--version\" ]; then echo 'v20.0.0'; exit 0; fi\nexit 1\n")
    missing_npm = _run(["bash", "scripts/install.sh", "--dry-run"], env={"PATH": f"{ok}:/usr/bin:/bin"})
    assert missing_npm.returncode != 0
    assert "缺少 npm" in missing_npm.stderr

    _fake_bin(ok, "npm", "#!/bin/sh\nexit 0\n")
    ready = _run(["bash", "scripts/install.sh", "--dry-run"], env={"PATH": f"{ok}:/usr/bin:/bin"})
    assert ready.returncode == 0, ready.stderr
    assert "Python Python 3.11.4" in ready.stdout or "Python 3.11.4" in ready.stdout
    assert "v20.0.0" in ready.stdout


def test_install_ps1_and_start_ps1_keep_the_documented_contract():
    install = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")
    start = (ROOT / "scripts" / "start.ps1").read_text(encoding="utf-8")
    stop = (ROOT / "scripts" / "stop.ps1").read_text(encoding="utf-8")
    assert "param(" in install and "[switch]$DryRun" in install
    for phrase in (
        "缺少 Python",
        "3.10",
        "缺少 Node.js",
        "需要 20",
        "缺少 npm",
        "npm ci",
        "start.ps1",
        "chrome://extensions",
        "开发者模式",
        "加载已解压的扩展程序",
        "127.0.0.1:43123",
        "配对码",
        "桌面壳",
        "原型",
        "不会创建虚拟环境",
        "已经在运行",
        "LAN",
        "没有登录认证",
    ):
        assert phrase in install, phrase
    assert "RunAsAdministrator" not in install
    assert "RunAs" not in install
    assert "sudo" not in install
    assert "其他进程占用" in start
    assert "multi-llm-chat-room" in start
    assert "警告：前端将监听 0.0.0.0。此服务没有登录认证，不要暴露到公网或做端口转发。" in start
    assert "后端仍只绑定 127.0.0.1" in start
    assert "Stop-Tree" in stop
    assert "没有结束该进程" in stop
    assert "taskkill" not in stop


def test_release_archive_omits_secrets_and_keeps_extension_loadable(tmp_path):
    module = _release()
    root = tmp_path / "src"
    (root / "extension" / "adapters").mkdir(parents=True)
    (root / "extension" / "manifest.json").write_text('{"version":"0.0.1","name":"x"}\n', encoding="utf-8")
    (root / "extension" / "background.js").write_text("/* bridge */\n", encoding="utf-8")
    (root / "extension" / "adapters" / "registry.json").write_text("{}\n", encoding="utf-8")
    (root / "backend" / "data").mkdir(parents=True)
    (root / "backend" / "data" / "secrets.json").write_text('{"OPENAI_API_KEY":"sk-secret"}\n', encoding="utf-8")
    (root / "backend" / "data" / "room.db").write_bytes(b"sqlite")
    (root / "backend" / ".venv" / "bin").mkdir(parents=True)
    (root / "backend" / ".venv" / "bin" / "python").write_text("venv", encoding="utf-8")
    (root / "backend" / "app").mkdir()
    (root / "backend" / "app" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (root / "frontend" / "node_modules" / "pkg").mkdir(parents=True)
    (root / "frontend" / "node_modules" / "pkg" / "index.js").write_text("x", encoding="utf-8")
    (root / "frontend" / "package.json").write_text("{}\n", encoding="utf-8")
    (root / ".run").mkdir()
    (root / ".run" / "instance.token").write_text("pair-token", encoding="utf-8")
    (root / "dom-dumps").mkdir()
    (root / "dom-dumps" / "page.html").write_text("<html>", encoding="utf-8")
    (root / ".env").write_text("OPENAI_API_KEY=sk-real\n", encoding="utf-8")
    (root / ".env.example").write_text("OPENAI_API_KEY=\n", encoding="utf-8")
    (root / "scripts").mkdir()
    (root / "scripts" / "install.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (root / "README.md").write_text("hi\n", encoding="utf-8")
    built = module.build_release(root, tmp_path / "out", version="v1.2.3")
    assert built["version"] == "1.2.3"
    sums = built["sums"].read_text(encoding="utf-8")
    assert built["app"].name in sums and built["extension"].name in sums
    with zipfile.ZipFile(built["extension"]) as archive:
        names = set(archive.namelist())
        assert "manifest.json" in names
        assert "adapters/registry.json" in names
        assert "extension/manifest.json" not in names
        assert not any("secret" in name or name.endswith(".db") for name in names)
    with zipfile.ZipFile(built["app"]) as archive:
        names = set(archive.namelist())
        blob = "\n".join(names)
        assert "extension/manifest.json" in names
        assert "scripts/install.sh" in names
        assert "README.md" in names
        assert ".env.example" in names
        assert "SHA256SUMS" in names
        assert "backend/app/main.py" in names
        assert "frontend/package.json" in names
        inside = archive.read("SHA256SUMS").decode("utf-8")
        assert "backend/app/main.py" in inside

        def forbidden(name: str) -> bool:
            parts = name.split("/")
            if "secrets.json" in parts or ".venv" in parts or "node_modules" in parts or ".run" in parts or "dom-dumps" in parts:
                return True
            if name.startswith("backend/data/"):
                return True
            if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
                return True
            return False

        assert not any(forbidden(name) for name in names)
        assert "sk-real" not in "\n".join(archive.read(name).decode("utf-8", "replace") for name in names if name.endswith((".py", ".sh", ".json", ".md", ".example")))


def test_real_tree_release_matches_the_handoff(tmp_path):
    module = _release()
    built = module.build_release(ROOT, tmp_path / "dist")
    import json as _json
    ext_version = _json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))["version"]
    assert built["version"] == ext_version
    lines = built["sums"].read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        digest, name = line.split()
        target = tmp_path / "dist" / name
        import hashlib
        assert hashlib.sha256(target.read_bytes()).hexdigest() == digest
    with zipfile.ZipFile(built["extension"]) as archive:
        manifest = archive.read("manifest.json").decode("utf-8")
        assert _json.loads(manifest)["version"] == ext_version
        assert "adapters/schema.js" in archive.namelist()
        assert "background.js" in archive.namelist()
    with zipfile.ZipFile(built["app"]) as archive:
        names = archive.namelist()
        for required in (
            "README.md",
            "LICENSE",
            "scripts/install.sh",
            "scripts/install.ps1",
            "scripts/start.sh",
            "scripts/start.ps1",
            "extension/adapters/registry.json",
            "desktop/main.js",
            "desktop/preload.js",
            "docs/DESKTOP.md",
            ".github/workflows/release.yml",
            "SHA256SUMS",
        ):
            assert required in names, required
        banned_parts = ("backend/data/", "/.venv/", "node_modules/", ".run/", "secrets.json", "dom-dumps/")
        blob = "\n".join(names)
        for part in banned_parts:
            assert part not in blob
        assert not any(name == ".env" or name.startswith(".env.") and name != ".env.example" for name in names)


def test_release_workflow_builds_on_tags_and_keeps_desktop_optional():
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert 'tags:' in text and '"v*"' in text
    assert "scripts/build_release.py" in text
    assert "gh release upload" in text
    assert "gh release create" in text
    assert "build_desktop" in text
    assert "electron-builder" in text
    assert "ghp_" not in text
    assert "secrets." not in text or "github.token" in text


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_desktop_host_and_preload_fixtures():
    env = os.environ.copy()
    cache = Path("/tmp/chatclumer-jsdom-25")
    if not (cache / "node_modules" / "jsdom").exists():
        subprocess.run(
            ["npm", "install", "--prefix", str(cache), "jsdom@25.0.1"],
            check=True,
            timeout=180,
        )
    env["NODE_PATH"] = str(cache / "node_modules")
    result = subprocess.run(
        [NODE, "--test", "desktop/test/host.test.js", "desktop/test/preload.test.js"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
