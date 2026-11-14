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
    assert "[contenteditable='true'][data-placeholder='Send Message']" in content
    assert "Stop Answering" in content
    assert "不会用整页文字代替回复" in content
    yuanbao = content.split("yuanbao:", 1)[1].split("zhipu:", 1)[0]
    assert "assistants: () => []" in yuanbao
    assert "innerText" not in yuanbao
    zhipu = content.split("zhipu:", 1)[1].split("};", 1)[0]
    assert "正文位置未验证" in zhipu
    assert "querySelector" not in zhipu or "composer: () => null" in zhipu
