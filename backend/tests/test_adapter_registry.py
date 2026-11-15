"""Adapter registry (0.5.0): data-only JSON, schema validation, bundled copy in sync, health in the heartbeat."""

import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.webbridge import clean_health

ROOT = Path(__file__).resolve().parents[2]
REG = ROOT / "extension" / "adapters" / "registry.json"
SCHEMA = ROOT / "extension" / "adapters" / "schema.js"
NODE = shutil.which("node")


def registry():
    return json.loads(REG.read_text(encoding="utf-8"))


def validate(data, ext="0.5.1"):
    script = (
        "const s=require(process.argv[1]);let d='';process.stdin.on('data',c=>d+=c).on('end',()=>{"
        "console.log(JSON.stringify(s.validateRegistry(JSON.parse(d),process.argv[2])))})"
    )
    out = subprocess.run([NODE, "-e", script, str(SCHEMA), ext], input=json.dumps(data), capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_bundled_registry_js_matches_json():
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_registry

    assert (ROOT / "extension" / "adapters" / "registry.js").read_text(encoding="utf-8") == build_registry.render()


def test_registry_covers_every_adapted_site():
    data = registry()
    assert data["schema"] == "chatclumer.adapters" and data["schema_version"] == 1
    assert set(data["sites"]) == {"qwen", "chatgpt", "wenxin", "zhipu", "zai", "deepseek", "doubao", "yuanbao"}
    for site in data["sites"].values():
        assert site["roles"]["composer"] and site["roles"]["send"]
    manifest = json.loads((ROOT / "extension" / "manifest.json").read_text())
    assert manifest["version"] == data["min_extension"]


def test_guest_js_has_no_inline_selectors_left():
    guest = (ROOT / "extension" / "guest.js").read_text()
    for marker in ("textarea#chat-textarea", "qwen-chat-message-user", "data-composer-submit", "row-answer-", "chat-markdown"):
        assert marker not in guest


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_schema_accepts_bundled_and_rejects_bad_data():
    assert validate(registry()) == {"ok": True, "errors": []}
    bad = []
    a = registry(); a["sites"]["qwen"]["script"] = "alert(1)"; bad.append(a)  # 不认识的键（可能的代码）
    b = registry(); b["sites"]["qwen"]["conv_url"] = {"source": "(", "flags": ""}; bad.append(b)
    c = registry(); c["version"] = "latest"; bad.append(c)
    d = registry(); d["sites"]["zai"]["origins"] = ["http://chat.z.ai"]; bad.append(d)
    e = registry(); e["sites"]["zai"]["roles"]["composer"] = []; bad.append(e)
    f = registry(); f["sites"]["zai"]["flags"] = {"writer": "eval"}; bad.append(f)
    g = registry(); g["sites"]["zai"]["done"] = {"has": ".x", "eval": "1"}; bad.append(g)
    h = registry(); h["sites"]["zai"]["roles"]["body"] = ["x" * 1000]; bad.append(h)
    i = registry(); i["filler"] = "x" * 200000; bad.append(i)
    for item in bad:
        assert validate(item)["ok"] is False
    assert validate(registry(), ext="0.4.4")["ok"] is False
    assert validate(registry(), ext="0.5.0")["ok"] is False  # min_extension 0.5.1（send_after_input 是 0.5.1 才认识的开关）
    j = registry(); j["sites"]["qwen"]["flags"]["send_after_input"] = "yes"; bad.append(j)
    assert validate(j)["ok"] is False


def test_clean_health_keeps_only_check_fields():
    raw = {
        "site": "qwen", "ok": False, "missing": ["send"], "empty": ["users"], "gate": None, "detail": "找不到：send",
        "roles": {"composer": {"found": 1, "index": 0, "selector": "textarea"}, "secret": {"found": 9}},
        "registry": {"version": "2026.11.15.1", "source": "bundled"},
        "checked_at": "2026-11-15T05:00:00Z", "page_text": "用户的私人聊天",
    }
    clean = clean_health(raw)
    assert "page_text" not in clean and "secret" not in clean["roles"]
    assert clean["roles"]["composer"] == {"found": 1, "index": 0}
    assert clean["registry_version"] == "2026.11.15.1"
    assert clean_health("nope") is None
    deferred = clean_health({**raw, "ok": True, "missing": [], "deferred": ["send", "page_text"]})
    assert deferred["ok"] is True and deferred["deferred"] == ["send"]


def test_heartbeat_health_shows_on_the_member_and_registry_is_served(tmp_path):
    app = create_app(str(tmp_path / "room.db"), str(tmp_path / "secrets.json"))
    client = TestClient(app)
    room = client.post("/api/sessions", json={"title": "检查", "max_rounds": 1, "max_seconds": 30}).json()
    body = {"nickname": "网页甲", "role_name": "读者", "persona": "", "provider": "web", "model_id": "web:fixture",
            "web_site": "fixture", "web_origin": "http://127.0.0.1:43124/fixture/chat", "web_tab_key": "k1", "web_auto": True}
    assert client.post(f"/api/sessions/{room['id']}/members/web", json=body).status_code == 200
    code = client.post("/api/ext/code").json()["code"]
    token = client.post("/api/ext/pair", json={"code": code}).json()["token"]
    health = {"site": "fixture", "ok": False, "missing": ["send"], "roles": {"send": {"found": 0, "index": -1}},
              "registry": {"version": "2026.11.15.1"}, "detail": "找不到：send"}
    beat = client.post("/api/ext/tabs", headers={"Authorization": f"Bearer {token}"},
                       json={"tabs": [{"tab_key": "k1", "origin": "http://127.0.0.1:43124", "alive": True, "health": health}]})
    assert beat.status_code == 200
    member = client.get(f"/api/sessions/{room['id']}").json()["members"][0]
    assert member["web_health"]["ok"] is False and member["web_health"]["missing"] == ["send"]
    served = client.get("/api/adapters/registry").json()
    assert served["version"] == registry()["version"]
