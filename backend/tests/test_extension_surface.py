import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_optional_hosts_do_not_get_a_static_content_script():
    manifest = json.loads((ROOT / "extension" / "manifest.json").read_text())
    matches = [item for block in manifest["content_scripts"] for item in block["matches"]]
    assert matches == ["http://127.0.0.1:43124/fixture/*", "https://gemini.google.com/*"]
    assert "scripting" in manifest["permissions"]
    assert "https://yuanbao.tencent.com/*" in manifest["optional_host_permissions"]
    assert "https://chatglm.cn/*" in manifest["optional_host_permissions"]
    background = (ROOT / "extension" / "background.js").read_text()
    popup = (ROOT / "extension" / "popup.js").read_text()
    content = (ROOT / "extension" / "content.js").read_text()
    assert "registerContentScripts" in background
    assert "permissions.request" in popup
    yuanbao_js = (ROOT / "extension" / "yuanbao.js").read_text()
    assert "结构取自协调方实页 2026-11-15" in yuanbao_js
    assert ".agent-chat__list__item--ai" in yuanbao_js
    assert ".hyc-common-markdown__ref-list" in yuanbao_js
    assert "onlyNew: true" in content
    assert "document.body" not in yuanbao_js
    assert "yuanbaoDispatchSend" in yuanbao_js
    assert "已填入，未发送" in yuanbao_js
    assert "insertText" in yuanbao_js
    assert "#yuanbao-send-btn" in yuanbao_js
    assert "SendButton_disabled" in yuanbao_js
    assert "pointerdown" in yuanbao_js
    assert "data-recommend" in yuanbao_js
    assert "成员 ID 不存在" in popup
    assert "yuanbaoDispatchSend" in content
    assert "clearIfUnsent" in content
    remembered = popup.split("function rememberFields", 1)[1].split("}", 1)[0]
    assert "memberId" in remembered and "tabKey" in remembered
    assert "code" not in remembered
    zhipu = content.split("zhipu:", 1)[1].split("};", 1)[0]
    assert "正文位置未验证" in zhipu
    assert "querySelector" not in zhipu or "composer: () => null" in zhipu
