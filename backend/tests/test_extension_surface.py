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
    assert "deepseekDispatchSend" in content
    assert "doubaoDispatchSend" in content
    deepseek_js = (ROOT / "extension" / "deepseek.js").read_text()
    doubao_js = (ROOT / "extension" / "doubao.js").read_text()
    assert "结构取自协调方实页 2026-11-15" in deepseek_js
    assert "textarea[placeholder='Message DeepSeek']" in deepseek_js
    assert ".bf38813a" in deepseek_js
    assert "ds-assistant-message-main-content" in deepseek_js
    assert "document.body" not in deepseek_js
    assert "豆包当前网络地区不可用" in doubao_js
    assert "chat_input_send_button" in doubao_js
    assert "chat_input_local_break_button" in doubao_js
    assert "document.body" not in doubao_js
    assert 'origin === "https://chat.deepseek.com"' in background
    assert 'origin === "https://www.doubao.com"' in background
    assert "https://chat.deepseek.com" in popup
    assert "https://www.doubao.com" in popup
    assert "clearIfUnsent" in content
    remembered = popup.split("function rememberFields", 1)[1].split("}", 1)[0]
    assert "memberId" in remembered and "tabKey" in remembered
    assert "code" not in remembered
    guest = (ROOT / "extension" / "guest.js").read_text()
    registry = json.loads((ROOT / "extension" / "adapters" / "registry.json").read_text())
    for site in ("qwen", "chatgpt", "wenxin", "zhipu", "zai"):
        assert registry["sites"][site]["engine"] == "guest"
    assert "document.body" not in guest
    assert "已填入，未发送" in guest
    assert any("需要先在页面上完成确认" in g["detail"] for g in registry["sites"]["qwen"]["gates"])
    assert "adapters/registry.js" in background and "adapters/runtime.js" in background
    assert "guestDispatchSend" in content
    assert "guest.js" in background
    for origin in ("https://chat.qwen.ai", "https://chatgpt.com", "https://wenxin.baidu.com", "https://chat.baidu.com", "https://chatglm.cn", "https://chat.z.ai"):
        assert f"{origin}/*" in manifest["optional_host_permissions"]
        assert origin in popup
    assert manifest["version"] == "0.5.1"
    assert 'url.startsWith("https://chat.baidu.com/")) return "wenxin"' in content
    assert '"https://chat.baidu.com",' in background
