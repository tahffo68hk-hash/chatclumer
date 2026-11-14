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
