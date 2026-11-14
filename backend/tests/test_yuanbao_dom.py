import pytest

pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.browser

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
# 结构取自协调方实页 2026-11-15。这是本地同结构夹具，不是元宝扩展端到端。
PAGE = """
<!-- 结构取自协调方实页 2026-11-15 -->
<div class="agent-chat__list__item agent-chat__list__item--human">
  <div class="agent-chat__bubble--human"><div class="hyc-content-text">旧问题</div></div>
</div>
<div class="agent-chat__list__item agent-chat__list__item--ai">
  <div class="agent-chat__bubble--ai">
    <div class="hyc-content-md hyc-content-md-done">
      <div class="hyc-common-markdown">旧答案不要读</div>
    </div>
    <div class="agent-chat__conv--ai__toolbar">复制</div>
  </div>
</div>
<div class="agent-chat__list__item agent-chat__list__item--ai agent-chat__list__item--last">
  <div class="agent-chat__bubble--ai">
    <div class="agent-chat__conv--ai__speech_show">
      <div class="agent-chat__speech-text">
        <div class="hyc-component-text">
          <div class="hyc-content-md">
            <div class="hyc-common-markdown">
              每天半小时就够。
              <div class="hyc-common-markdown__ref-list">引用10篇资料作为参考</div>
              <div class="hyc-card-box-process-list">思考过程不要收进正文</div>
              <div class="picture-card"><img alt="图"><button type="button">全屏查看</button></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
<div class="ql-editor" contenteditable="true" data-placeholder="Send Message"></div>
<div aria-label="Send"></div>
<div aria-label="Stop Answering" hidden></div>
"""


def test_yuanbao_reader_takes_only_the_new_ai_bubble():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        page.set_content(PAGE)
        page.add_script_tag(path=str(ROOT / "extension" / "yuanbao.js"))
        before = page.evaluate("yuanbaoAssistants(document).length")
        page.evaluate(
            """() => {
              const node = document.querySelector(".agent-chat__list__item--last .hyc-content-md");
              node.classList.add("hyc-content-md-done");
              const bar = document.createElement("div");
              bar.className = "agent-chat__toolbar";
              node.parentElement.appendChild(bar);
            }"""
        )
        read = page.evaluate(
            """(before) => {
              const fresh = yuanbaoAssistants(document).slice(before);
              const node = fresh[fresh.length - 1];
              return {
                source: YUANBAO_DOM_SOURCE,
                count: fresh.length,
                text: yuanbaoText(node),
                done: yuanbaoDone(node),
                send: yuanbaoSend(document).getAttribute("aria-label"),
              };
            }""",
            before - 1,
        )
        # before-1 simulates the count recorded before the new bubble existed
        stopped = page.evaluate(
            """() => {
              const stop = document.querySelector("[aria-label='Stop Answering']");
              stop.hidden = false;
              stop.addEventListener("click", () => { stop.dataset.clicked = "yes"; });
              yuanbaoStop(document).click();
              return stop.dataset.clicked;
            }"""
        )
        login = page.evaluate(
            """() => {
              const close = document.createElement("button");
              close.className = "hyc-login__close";
              document.body.appendChild(close);
              return yuanbaoLogin(document);
            }"""
        )
        browser.close()
    assert read["source"] == "结构取自协调方实页 2026-11-15"
    assert read["count"] == 1
    assert read["text"] == "每天半小时就够。"
    assert "引用" not in read["text"]
    assert "思考过程" not in read["text"]
    assert "全屏查看" not in read["text"]
    assert read["done"] is True
    assert read["send"] == "Send"
    assert stopped == "yes"
    assert login is True
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        page.set_content(
            """
            <div class="agent-chat__list__item--human">旧问题</div>
            <div class="ql-editor" contenteditable="true" data-placeholder="Send Message">请用一句话给一个读书建议。</div>
            <div aria-label="Send"></div>
            """
        )
        page.add_script_tag(path=str(ROOT / "extension" / "yuanbao.js"))
        page.evaluate(
            """() => {
              document.querySelector("[aria-label=Send]").addEventListener("click", () => {
                const row = document.createElement("div");
                row.className = "agent-chat__list__item agent-chat__list__item--human";
                document.body.appendChild(row);
              });
            }"""
        )
        sent = page.evaluate(
            """() => yuanbaoDispatchSend(document, "请用一句话给一个读书建议。", 500)"""
        )
        quiet = page.evaluate(
            """() => {
              const send = document.querySelector("[aria-label=Send]");
              send.replaceWith(send.cloneNode(true));
              return yuanbaoDispatchSend(document, "请用一句话给一个读书建议。", 200);
            }"""
        )
        browser.close()
    assert sent["ok"] is True
    assert quiet["ok"] is False
    assert quiet["detail"] == "已填入，未发送"


def test_editor_state_not_dom_text_enables_send_and_cards_are_not_clicked():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        page.set_content(
            """
            <div id="composer-box">
              <div class="ql-editor" contenteditable="true" data-placeholder="发消息"></div>
              <button type="button" id="real-send" aria-label="Send" disabled>发送</button>
            </div>
            <button type="button" data-recommend aria-label="发送">高层腰线层住宅优缺点有哪些？</button>
            <button type="button" data-recommend>做暖冬菌菇汤</button>
            """
        )
        page.evaluate(
            """() => {
              const editor = document.querySelector(".ql-editor");
              const send = document.querySelector("#real-send");
              let model = "";
              window.__cards = 0;
              window.__sends = 0;
              document.querySelectorAll("[data-recommend]").forEach((button) => {
                button.addEventListener("click", () => { window.__cards += 1; });
              });
              send.addEventListener("click", () => {
                window.__sends += 1;
                if (!model.trim()) return;
                const row = document.createElement("div");
                row.className = "agent-chat__list__item--human";
                row.textContent = model;
                document.body.appendChild(row);
              });
              editor.addEventListener("beforeinput", (event) => {
                if (event.inputType === "deleteContentBackward") model = "";
                if (event.inputType === "insertText") model = event.data || "";
                editor.textContent = model;
              });
              editor.addEventListener("input", () => {
                const current = document.querySelector("#real-send");
                if (current) current.disabled = model.trim().length === 0;
              });
              document.execCommand = (command, _ui, value) => {
                if (command === "insertText") editor.textContent = String(value || "");
                return true;
              };
              editor.textContent = "请用一句话给一个读书建议。";
              window.__model = () => model;
            }"""
        )
        untouched = page.evaluate("() => document.querySelector('#real-send').disabled")
        page.add_script_tag(path=str(ROOT / "extension" / "yuanbao.js"))
        sent = page.evaluate(
            """() => yuanbaoDispatchSend(document, "请用一句话给一个读书建议。", 800)"""
        )
        counts = page.evaluate("() => ({ cards: window.__cards, sends: window.__sends, model: window.__model() })")
        quiet = page.evaluate(
            """() => {
              const send = document.querySelector("#real-send");
              const fresh = send.cloneNode(true);
              fresh.id = "real-send";
              send.replaceWith(fresh);
              return yuanbaoDispatchSend(document, "请用一句话给一个读书建议。\\n", 250);
            }"""
        )
        cleared = page.evaluate("() => window.__model()")
        again = page.evaluate(
            """() => {
              document.querySelector("#real-send").addEventListener("click", () => {
                window.__sends += 1;
                const row = document.createElement("div");
                row.className = "agent-chat__list__item--human";
                document.body.appendChild(row);
              });
              return yuanbaoDispatchSend(document, "另一句建议。", 800);
            }"""
        )
        final_model = page.evaluate("() => window.__model()")
        browser.close()
    assert untouched is True
    assert sent["ok"] is True
    assert counts["cards"] == 0
    assert counts["sends"] == 1
    assert counts["model"] == "请用一句话给一个读书建议。"
    assert quiet["detail"] == "已填入，未发送"
    assert cleared == ""
    assert again["ok"] is True
    assert final_model == "另一句建议。"
    assert "残留" not in final_model


def test_binding_and_heartbeat_do_not_click_recommendation_cards():
    background = (ROOT / "extension" / "background.js").read_text()
    beat = background.split("async function beat", 1)[1].split("async function poll", 1)[0]
    ensure = background.split("async function ensureScript", 1)[1].split("chrome.runtime.onMessage", 1)[0]
    assert ".click(" not in beat and "KeyboardEvent" not in beat and "dispatchEvent" not in beat
    assert ".click(" not in ensure and "KeyboardEvent" not in ensure and "dispatchEvent" not in ensure
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        page.clock.install()
        page.route(
            "http://127.0.0.1:43124/card-fixture",
            lambda route: route.fulfill(
                status=200,
                content_type="text/html",
                body="""
                <button type="button" data-recommend>高层腰线层住宅优缺点有哪些？</button>
                <button type="button" data-recommend aria-label="发送">做暖冬菌菇汤</button>
                <div id="composer-box"><div class="ql-editor" contenteditable="true" data-placeholder="发消息"></div></div>
                """,
            ),
        )
        page.goto("http://127.0.0.1:43124/card-fixture")
        page.evaluate(
            """() => {
              window.__cards = 0;
              document.querySelectorAll("[data-recommend]").forEach((button) => {
                button.addEventListener("click", () => { window.__cards += 1; });
              });
              window.chrome = {
                runtime: {
                  onMessage: { addListener() {}, removeListener() {} },
                  sendMessage() {},
                  lastError: null,
                },
              };
            }"""
        )
        page.add_script_tag(path=str(ROOT / "extension" / "yuanbao.js"))
        page.add_script_tag(path=str(ROOT / "extension" / "content.js"))
        page.clock.fast_forward(60_000)
        clicks = page.evaluate("() => window.__cards")
        installed = page.evaluate("() => globalThis.__roomBridge === true")
        browser.close()
    assert installed is True
    assert clicks == 0
