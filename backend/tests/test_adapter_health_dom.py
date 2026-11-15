"""Registry health check, remote override and sanitized dump against the real 2026-11-15 DOM fixtures."""

import copy
import gzip
import json
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.browser

from playwright.sync_api import sync_playwright

from tests.ext_scripts import add_adapters

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "fixtures" / "real_dom"
REG = json.loads((ROOT / "extension" / "adapters" / "registry.json").read_text(encoding="utf-8"))
PROMPT = "你好，请用一句话回答"
FILES = {"qwen": "qwen", "chatgpt": "chatgpt", "wenxin": "wenxin", "zhipu": "chatglm", "zai": "zai", "deepseek": "deepseek"}


def page_with(playwright, name, state):
    raw = gzip.decompress((FIX / f"{name}-{state}.html.gz").read_bytes()).decode("utf-8")
    _, _, html = raw.partition("\n")
    browser = playwright.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page()
    page.route("**/*", lambda route: route.abort())
    page.set_content(html, wait_until="domcontentloaded")
    add_adapters(page)
    page.add_script_tag(path=str(ROOT / "extension" / "guest.js"))
    return browser, page


@pytest.mark.parametrize("site", list(FILES))
def test_health_finds_composer_and_send_without_writing(site):
    with sync_playwright() as playwright:
        browser, page = page_with(playwright, FILES[site], "3-done")
        result = page.evaluate(
            """(site) => {
              const box = document.querySelector("textarea");
              const before = box ? box.value : null;
              let clicks = 0;
              document.addEventListener("click", () => { clicks += 1; }, true);
              const h = ChatclumerAdapters.health(site, document);
              return { h, clicks, same: (box ? box.value : null) === before };
            }""",
            site,
        )
        browser.close()
    health = result["h"]
    assert health["ok"] is True, health
    assert health["roles"]["composer"]["found"] >= 1 and health["roles"]["send"]["found"] >= 1
    assert health["registry"]["source"] == "bundled"
    assert result["clicks"] == 0 and result["same"] is True


def newer(mutate):
    data = copy.deepcopy(REG)
    data["version"] = "2099.1.1.1"
    mutate(data)
    return data


def test_remote_registry_fallback_list_and_breakage_are_reported():
    def broken(d):
        d["sites"]["zai"]["roles"]["composer"] = ["textarea#renamed-by-site"]

    def fallback(d):
        d["sites"]["zai"]["roles"]["composer"] = ["textarea#renamed-by-site", "textarea#chat-input"]

    with sync_playwright() as playwright:
        browser, page = page_with(playwright, "zai", "1-typed")
        out = page.evaluate(
            """([broken, fallback]) => {
              const a = ChatclumerAdapters.useRemote(broken, "https://example.test/r.json");
              const h1 = ChatclumerAdapters.health("zai", document);
              const missing = guestComposer("zai", document);
              const b = ChatclumerAdapters.useRemote(fallback, "https://example.test/r.json");
              const h2 = ChatclumerAdapters.health("zai", document);
              const found = guestComposer("zai", document);
              return { a: a.ok, b: b.ok, h1, h2, missing: !!missing, found: found && found.id };
            }""",
            [newer(broken), newer(fallback)],
        )
        browser.close()
    assert out["a"] is True and out["h1"]["ok"] is False and out["h1"]["missing"] == ["composer"]
    assert out["missing"] is False
    assert out["b"] is True and out["h2"]["ok"] is True and out["h2"]["roles"]["composer"]["index"] == 1
    assert out["found"] == "chat-input"
    assert out["h2"]["registry"]["source"].startswith("remote:")


def test_remote_registry_rejected_when_invalid_older_or_unparsable():
    older = copy.deepcopy(REG)
    older["sites"]["zai"]["roles"]["composer"] = ["textarea#nothing"]
    code = newer(lambda d: d["sites"]["zai"].__setitem__("onload", "fetch('//evil')"))
    unparsable = newer(lambda d: d["sites"]["zai"]["roles"].__setitem__("composer", ["textarea[[["]))
    with sync_playwright() as playwright:
        browser, page = page_with(playwright, "zai", "1-typed")
        out = page.evaluate(
            """(items) => items.map((data) => {
              const r = ChatclumerAdapters.useRemote(data, "https://example.test/r.json");
              return { ok: r.ok, detail: r.detail || "", source: ChatclumerAdapters.info().source,
                       composer: !!guestComposer("zai", document) };
            })""",
            [older, code, unparsable],
        )
        browser.close()
    for item in out:
        assert item["ok"] is False and item["source"] == "bundled" and item["composer"] is True
    assert "不比内置" in out[0]["detail"]
    assert "被拒" in out[1]["detail"]
    assert "无法解析" in out[2]["detail"]


@pytest.mark.parametrize("name,site", [("zai", "zai"), ("deepseek", "deepseek"), ("wenxin", "wenxin")])
def test_dump_keeps_structure_and_masks_chat_text(name, site):
    with sync_playwright() as playwright:
        browser, page = page_with(playwright, name, "3-done")
        page.evaluate("() => { const b = document.querySelector('textarea'); if (b) b.value = '私密草稿内容'; }")
        out = page.evaluate("(site) => ChatclumerAdapters.dump(site, document)", site)
        browser.close()
    html = out["html"]
    assert html.startswith("<!-- chatclumer-dump ")
    assert PROMPT not in html and "私密草稿内容" not in html
    assert "<script" not in html.lower() and " src=" not in html and " href=" not in html
    assert "▢" in html
    assert out["meta"]["health"]["ok"] is True
    # 结构还在：至少保留了注册表里的输入框选择器能命中的元素。
    sel = REG["sites"][site]["roles"]["composer"][0]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        check = browser.new_page()
        check.set_content(html.split("\n", 1)[1])
        assert check.evaluate("(sel) => !!document.querySelector(sel)", sel)
        browser.close()
