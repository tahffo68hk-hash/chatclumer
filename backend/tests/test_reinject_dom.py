"""Repeated injection of the content scripts into the same document (0.5.1).

ensureScript, the popup page check and the diagnostic dump can all reach executeScript for a tab
that already has the scripts. Re-running a classic script that declares top-level const/let throws
"Identifier ... has already been declared"; these tests run every injected file twice (and once
mid-task) and require no page error, no extra message listener and an undisturbed job.
"""

import pytest

pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.browser

from pathlib import Path

from playwright.sync_api import sync_playwright

from tests.ext_scripts import ADAPTER_FILES, EXT
from tests.test_guest_sites_dom import DRIVER, PROMPT, SITES, WORDS

FILES = [*ADAPTER_FILES, "guest.js", "deepseek.js", "doubao.js", "yuanbao.js", "content.js"]
SOURCES = [(EXT / name).read_text(encoding="utf-8") for name in FILES]

STUB = """(version) => {
  window.__progress = []; window.__listeners = 0; window.__version = version;
  window.chrome = { runtime: {
    id: "room",
    getManifest() { return { version: window.__version }; },
    sendMessage(m) { window.__progress.push(m); },
    onMessage: { addListener() { window.__listeners += 1; }, removeListener() { window.__listeners -= 1; } },
  } };
}"""

INJECT = """(sources) => { for (const src of sources) { const s = document.createElement("script"); s.textContent = src; document.head.appendChild(s); s.remove(); } }"""


# 失效实例里再跑一遍 content.js：守卫放行（alive 为假时不跳过），但也不报「已声明」。
INJECT_PROBE = """(src) => { const s = document.createElement("script"); s.textContent = src; document.head.appendChild(s); s.remove(); return true; }"""


def _open(playwright, spec, version="0.5.1"):
    browser = playwright.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    body = '<meta charset="utf-8">' + spec["html"]
    page.route("https://**/*", lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=body))
    page.goto(spec["url"])
    page.evaluate(STUB, version)
    page.evaluate(INJECT, SOURCES)
    return browser, page, errors


def test_second_injection_is_a_no_op():
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, SITES["zai"])
        before = page.evaluate("() => { window.__token = globalThis.__roomBridgeToken; window.__api = globalThis.ChatclumerAdapters; return { n: window.__listeners }; }")
        page.evaluate(INJECT, SOURCES)
        page.evaluate(INJECT, SOURCES)
        after = page.evaluate(
            """() => ({ n: window.__listeners, token: globalThis.__roomBridgeToken === window.__token,
              same: globalThis.ChatclumerAdapters === window.__api,
              fns: [typeof runJob, typeof guestDispatchSend, typeof deepseekDispatchSend, typeof doubaoDispatchSend, typeof yuanbaoDispatchSend],
              loaded: globalThis.__chatclumerLoaded })"""
        )
        browser.close()
    assert errors == []
    assert before["n"] > 0
    assert after["n"] == before["n"]
    assert after["token"] is True and after["same"] is True
    assert after["fns"] == ["function"] * 5
    assert after["loaded"] == {k: "0.5.1" for k in ("guest", "deepseek", "doubao", "yuanbao", "content")}


def test_injection_during_an_active_task_does_not_disturb_it():
    spec = SITES["zai"]
    driver = DRIVER.replace(
        "const started = Date.now();",
        "const started = Date.now(); setTimeout(() => window.__inject(), 300); setTimeout(() => window.__inject(), 900);",
    )
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, spec)
        n = page.evaluate("() => window.__listeners")
        page.evaluate("(sources) => { window.__inject = () => (" + INJECT + ")(sources); }", SOURCES)
        result = page.evaluate(driver, ["zai", spec, PROMPT, WORDS])
        after = page.evaluate("() => window.__listeners")
        browser.close()
    assert errors == []
    assert after == n
    assert result["status"] == "complete", result
    assert result["text"] == "".join(WORDS)
    assert result["sends"] == 1
    assert result["writes"] == 1


def test_new_version_replaces_old_copy_without_syntax_error():
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, SITES["zai"], version="0.5.0")
        old = page.evaluate("() => { window.__token = globalThis.__roomBridgeToken; return { n: window.__listeners }; }")
        page.evaluate("() => { window.__version = '0.5.1'; }")
        page.evaluate(INJECT, SOURCES)
        new = page.evaluate(
            "() => ({ n: window.__listeners, token: globalThis.__roomBridgeToken === window.__token, ver: globalThis.ChatclumerAdapters.__version, loaded: globalThis.__chatclumerLoaded.content })"
        )
        browser.close()
    assert errors == []
    assert new["ver"] == "0.5.1" and new["loaded"] == "0.5.1"
    # 新版本装上了自己的监听；旧副本的监听因为令牌变了不再接活。
    assert new["token"] is False
    assert new["n"] > old["n"]


def test_orphaned_copy_is_replaced():
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, SITES["zai"])
        page.evaluate("() => { window.__token = globalThis.__roomBridgeToken; }")
        # 扩展重载后旧副本取不到 chrome.runtime.id；新实例注入时必须重新装，而不是被旧标记挡住。
        page.evaluate("() => { window.__dead = true; Object.defineProperty(chrome.runtime, 'id', { configurable: true, get() { return window.__dead ? undefined : 'room'; } }); }")
        skipped = page.evaluate(INJECT_PROBE, SOURCES[-1])
        page.evaluate("() => { window.__dead = false; }")
        page.evaluate(INJECT, SOURCES)
        new = page.evaluate("() => globalThis.__roomBridgeToken !== window.__token")
        browser.close()
    assert errors == []
    assert skipped is True
    assert new is True
