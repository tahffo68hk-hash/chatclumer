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
<div data-new-input-card>
  <div data-input-main-content="true">
    <div data-input-editor-area="true">
      <div id="search-bar">
        <div class="ql-container InputTextArea_hightLightTextAreaNew__fixture">
          <div class="ql-editor ql-blank" contenteditable="true" data-placeholder="Send Message" enterkeyhint="send"><p><br></p></div>
        </div>
      </div>
    </div>
  </div>
  <div data-input-bottom-toolbar="true" data-prevent-quill-blur="true">
    <div data-input-toolbar-right="true">
      <div data-new-input-control="send">
        <div id="yuanbao-send-btn" aria-label="Send" class="SendButton_sendButton__g3Lcb"><svg></svg></div>
      </div>
    </div>
  </div>
</div>
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
              const portal = document.createElement("div");
              portal.className = "t-dialog__position";
              portal.innerHTML = '<div class="t-dialog"><button class="hyc-login__close">关闭</button><div class="hyc-login__content">微信</div></div>';
              document.body.appendChild(portal);
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
    assert quiet["detail"].startswith("已填入，未发送")
    assert "待发长度" in quiet["detail"]
    assert "不重复" in quiet["detail"]


def test_editor_state_not_dom_text_enables_send_and_cards_are_not_clicked():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        page.set_content(
            """
            <div data-new-input-card>
              <div data-input-main-content="true">
                <div>
                  <div data-input-editor-area="true">
                    <div id="search-bar">
                      <div class="ql-container InputTextArea_hightLightTextAreaNew__hash">
                        <div class="ql-editor ql-blank" contenteditable="true" data-placeholder="Send Message" enterkeyhint="send"><p><br></p></div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
              <div data-input-bottom-toolbar="true" data-prevent-quill-blur="true">
                <div data-input-toolbar-right="true">
                  <button type="button" aria-label="Add" data-new-input-control="add-tools-trigger">Add</button>
                  <button type="button" aria-label="Switch model">Switch model</button>
                  <div data-new-input-control="send">
                    <div id="yuanbao-send-btn" aria-label="Send" class="SendButton_sendButton__g3Lcb SendButton_disabled__v1PnQ SendButton_sendNot__sUMPk"><svg></svg></div>
                  </div>
                </div>
              </div>
            </div>
            <div id="decoy-send" aria-label="Send">页外发送</div>
            <button type="button" data-recommend aria-label="发送">高层腰线层住宅优缺点有哪些？</button>
            <button type="button" data-recommend>做暖冬菌菇汤</button>
            """
        )
        page.evaluate(
            """() => {
              const editor = document.querySelector(".ql-editor");
              let model = "";
              window.__cards = 0;
              window.__sends = 0;
              window.__writes = 0;
              window.__paintToken = 0;
              window.__seq = [];
              const paint = () => {
                const send = document.querySelector("#yuanbao-send-btn");
                editor.classList.toggle("ql-blank", !model.trim());
                editor.innerHTML = model.trim() ? `<p>${model}</p>` : "<p><br></p>";
                send.className = model.trim()
                  ? "SendButton_sendButton__g3Lcb"
                  : "SendButton_sendButton__g3Lcb SendButton_disabled__v1PnQ SendButton_sendNot__sUMPk";
              };
              const arm = (send) => {
                window.__seq = [];
                for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
                  send.addEventListener(type, () => {
                    window.__seq.push(type);
                    if (window.__seq.join(",") !== "pointerdown,mousedown,pointerup,mouseup,click") return;
                    window.__seq = [];
                    if (!model.trim() || [...send.classList].some((name) => name.startsWith("SendButton_disabled"))) return;
                    window.__sends += 1;
                    const row = document.createElement("div");
                    row.className = "agent-chat__list__item--human";
                    row.textContent = model;
                    document.body.appendChild(row);
                  });
                }
              };
              arm(document.querySelector("#yuanbao-send-btn"));
              document.querySelectorAll("[data-recommend], [aria-label='Add'], [aria-label='Switch model'], #decoy-send").forEach((button) => {
                button.addEventListener("click", () => { window.__cards += 1; });
                button.addEventListener("pointerdown", () => { window.__cards += 1; });
              });
              editor.addEventListener("beforeinput", (event) => {
                if (event.inputType === "deleteContentBackward") {
                  window.__paintToken += 1;
                  model = "";
                  paint();
                }
                if (event.inputType === "insertText") {
                  window.__writes += 1;
                  model = `${model}${event.data || ""}`;
                  paint();
                }
              });
              document.execCommand = (command, _ui, value) => {
                if (command === "insertText") {
                  window.__writes += 1;
                  model = String(value || "");
                  editor.textContent = model;
                  const token = ++window.__paintToken;
                  setTimeout(() => {
                    if (token === window.__paintToken) paint();
                  }, 300);
                }
                return true;
              };
              editor.textContent = "请用一句话给一个读书建议。";
              window.__model = () => model;
              window.__arm = arm;
            }"""
        )
        untouched = page.evaluate(
            """() => {
              const send = document.querySelector("#yuanbao-send-btn");
              return send.className.includes("SendButton_disabled") && document.querySelector(".ql-editor").classList.contains("ql-blank");
            }"""
        )
        page.add_script_tag(path=str(ROOT / "extension" / "yuanbao.js"))
        sent = page.evaluate(
            """() => yuanbaoDispatchSend(document, "请用一句话给一个读书建议。", 800)"""
        )
        counts = page.evaluate(
            """() => ({
              cards: window.__cards,
              sends: window.__sends,
              model: window.__model(),
              blank: document.querySelector(".ql-editor").classList.contains("ql-blank"),
              writes: window.__writes,
            })"""
        )
        prefixes = page.evaluate(
            """() => {
              const send = document.querySelector("#yuanbao-send-btn");
              send.className = "SendButton_sendButton__zzzz SendButton_disabled__yyyy SendButton_sendNot__xxxx";
              const blocked = yuanbaoSendUsable(document) === null;
              send.className = "SendButton_sendButton__zzzz";
              const open = yuanbaoSendUsable(document) === send;
              send.className = "SendButton_sendButton__g3Lcb";
              return blocked && open;
            }"""
        )
        quiet = page.evaluate(
            """() => {
              const send = document.querySelector("#yuanbao-send-btn");
              const fresh = send.cloneNode(true);
              fresh.id = "yuanbao-send-btn";
              send.replaceWith(fresh);
              return yuanbaoDispatchSend(document, "请用一句话给一个读书建议。\\n", 250);
            }"""
        )
        cleared = page.evaluate("() => window.__model()")
        again = page.evaluate(
            """() => {
              window.__arm(document.querySelector("#yuanbao-send-btn"));
              return yuanbaoDispatchSend(document, "另一句建议。", 800);
            }"""
        )
        entered = page.evaluate(
            """() => {
              const send = document.querySelector("#yuanbao-send-btn");
              const fresh = send.cloneNode(true);
              fresh.id = "yuanbao-send-btn";
              send.replaceWith(fresh);
              const editor = document.querySelector(".ql-editor");
              editor.addEventListener("keydown", (event) => {
                window.__keyCode = event.keyCode;
                if (event.key !== "Enter" || event.keyCode !== 13) return;
                const row = document.createElement("div");
                row.className = "agent-chat__list__item--human";
                document.body.appendChild(row);
              });
              return yuanbaoDispatchSend(document, "用回车发送。", 1200);
            }"""
        )
        final_model = page.evaluate("() => window.__model()")
        key_code = page.evaluate("() => window.__keyCode")
        browser.close()
    assert untouched is True
    assert prefixes is True
    assert sent["ok"] is True
    assert counts["cards"] == 0
    assert counts["sends"] == 1
    assert counts["blank"] is False
    assert counts["model"] == "请用一句话给一个读书建议。"
    assert counts["writes"] == 1
    assert quiet["detail"].startswith("已填入，未发送")
    assert "待发长度" in quiet["detail"]
    assert "不重复" in quiet["detail"]
    assert cleared == ""
    assert again["ok"] is True
    assert entered["ok"] is True
    assert key_code == 13
    assert final_model == "用回车发送。"
    assert "残留" not in final_model


def test_binding_and_heartbeat_do_not_click_recommendation_cards():
    background = (ROOT / "extension" / "background.js").read_text(encoding="utf-8")
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


def test_one_task_is_written_once_when_the_script_is_injected_twice():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        page.route(
            "https://yuanbao.tencent.com/chat",
            lambda route: route.fulfill(
                status=200,
                content_type="text/html",
                body="""
                <div data-new-input-card>
                  <div class="ql-editor ql-blank" contenteditable="true" data-placeholder="Send Message"><p><br></p></div>
                  <div id="yuanbao-send-btn" aria-label="Send" class="SendButton_sendButton__g3Lcb SendButton_disabled__v1PnQ SendButton_sendNot__sUMPk"></div>
                </div>
                """,
            ),
        )
        page.goto("https://yuanbao.tencent.com/chat")
        page.evaluate(
            """() => {
              const listeners = [];
              window.chrome = {
                runtime: {
                  id: "room-test",
                  onMessage: {
                    addListener(fn) { listeners.push(fn); },
                    removeListener() {},
                  },
                  sendMessage() {},
                  lastError: null,
                },
              };
              window.__listeners = listeners;
              window.__writes = 0;
              const editor = document.querySelector(".ql-editor");
              const send = document.querySelector("#yuanbao-send-btn");
              let model = "";
              const paint = () => {
                editor.classList.toggle("ql-blank", !model.trim());
                editor.textContent = model;
                send.className = model.trim()
                  ? "SendButton_sendButton__g3Lcb"
                  : "SendButton_sendButton__g3Lcb SendButton_disabled__late SendButton_sendNot__late";
              };
              document.execCommand = (command, _ui, value) => {
                if (command === "insertText") {
                  window.__writes += 1;
                  model = String(value || "");
                  editor.textContent = model;
                  const token = ++window.__paintToken;
                  setTimeout(() => {
                    if (token !== window.__paintToken) return;
                    paint();
                  }, 300);
                }
                return true;
              };
              window.__paintToken = 0;
              editor.addEventListener("beforeinput", (event) => {
                if (event.inputType === "insertText") {
                  window.__writes += 1;
                  model = `${model}${event.data || ""}`;
                  paint();
                }
                if (event.inputType === "deleteContentBackward") model = "";
              });
              send.addEventListener("pointerdown", () => {
                if ([...send.classList].some((name) => name.startsWith("SendButton_disabled"))) return;
                const row = document.createElement("div");
                row.className = "agent-chat__list__item--human";
                document.body.appendChild(row);
                const ai = document.createElement("div");
                ai.className = "agent-chat__list__item--ai";
                ai.innerHTML = '<div class="hyc-common-markdown hyc-content-md-done">收到</div><div class="agent-chat__toolbar">复制</div>';
                document.body.appendChild(ai);
              });
            }"""
        )
        page.add_script_tag(path=str(ROOT / "extension" / "yuanbao.js"))
        page.add_script_tag(path=str(ROOT / "extension" / "content.js"))
        page.add_script_tag(path=str(ROOT / "extension" / "content.js"))
        installed = page.evaluate("() => window.__listeners.length")
        outcome = page.evaluate(
            """() => new Promise((resolve) => {
              const replies = [];
              const job = { request_id: "job-once", site: "yuanbao", prompt: "请用一句话给一个读书建议。", action: "send" };
              const finish = () => resolve({ listeners: window.__listeners.length, writes: window.__writes, replies });
              if (!window.__listeners.length) {
                finish();
                return;
              }
              for (const listener of window.__listeners) {
                listener({ type: "run", job }, {}, (result) => {
                  replies.push(result && result.status);
                  if (replies.length >= window.__listeners.length) finish();
                });
              }
              setTimeout(finish, 5000);
            })"""
        )
        doubled = page.evaluate(
            """() => {
              const editor = document.querySelector(".ql-editor");
              const twice = "请用一句话给一个读书建议。请用一句话给一个读书建议。";
              document.execCommand = () => {
                editor.textContent = twice;
                return true;
              };
              editor.addEventListener("beforeinput", (event) => {
                if (event.inputType === "insertText") editor.textContent = twice;
              });
              editor.addEventListener("paste", () => { editor.textContent = twice; });
              return yuanbaoDispatchSend(document, "请用一句话给一个读书建议。", 800);
            }"""
        )
        browser.close()
    assert installed == 1
    assert outcome["writes"] == 1
    assert "读书建议" not in doubled["detail"]
    assert "重复" in doubled["detail"]
    assert "待发长度" in doubled["detail"]


NEW_LAYOUT = """
<div id="searchbar-editor"></div>
<button class="agent-dialogue__tool__login" type="button">Log In</button>
<div class="nick-info-name">Not logged in</div>
<div id="searchbar-editor" class="yb-input-box-textarea agent-input-text-area">
  <div id="search-bar">
    <div class="chat-input-editor ql-container">
      <div class="ql-editor" contenteditable="true" enterkeyhint="send" data-placeholder="Send Message"><p><br></p></div>
    </div>
  </div>
  <div class="style__text-area__end___ow95N">
    <div class="style__text-area__actions___S50n4">
      <a id="yuanbao-send-btn" hidden>旧的</a>
      <a id="yuanbao-send-btn" class="style__send-btn___RwTm5"><span class="icon-send">发送</span></a>
    </div>
  </div>
</div>
"""


def test_new_yuanbao_layout_sends_and_login_gate_does_not_click():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        page.set_content(NEW_LAYOUT)
        page.add_script_tag(path=str(ROOT / "extension" / "yuanbao.js"))
        page.evaluate(
            """() => {
              window.__loginClicks = 0;
              window.__sends = 0;
              const send = [...document.querySelectorAll("#yuanbao-send-btn")].find((el) => el.classList.contains("style__send-btn___RwTm5"));
              send.addEventListener("pointerdown", () => {
                window.__sends += 1;
                const row = document.createElement("div");
                row.className = "agent-chat__list__item--human";
                document.body.appendChild(row);
              });
            }"""
        )
        guest = page.evaluate(
            """() => ({
              blocked: yuanbaoLogin(document),
              tag: yuanbaoSend(document).tagName,
              klass: yuanbaoSend(document).className,
              placeholder: yuanbaoComposer(document).getAttribute("data-placeholder"),
            })"""
        )
        sent = page.evaluate(
            """() => yuanbaoDispatchSend(document, "请用一句话给一个读书建议。", 800)"""
        )
        gated = page.evaluate(
            """() => {
              document.querySelector(".ql-editor").setAttribute("data-placeholder", "Please log in before entering content");
              const portal = document.createElement("div");
              portal.className = "t-portal-wrapper";
              portal.innerHTML = '<div class="t-dialog__position t-dialog--center"><div class="t-dialog"><button class="hyc-login__close">关闭</button><div class="hyc-login__content">WeChat Phone QQ</div></div></div>';
              document.body.appendChild(portal);
              portal.querySelector(".hyc-login__close").addEventListener("click", () => { window.__loginClicks += 1; });
              portal.querySelector(".hyc-login__content").addEventListener("click", () => { window.__loginClicks += 1; });
              const blocked = yuanbaoLogin(document);
              const result = yuanbaoDispatchSend(document, "请用一句话给一个读书建议。", 400);
              return result.then((detail) => ({
                blocked,
                detail: detail.detail,
                clicked: detail.clicked,
                loginClicks: window.__loginClicks,
                stillOpen: !!document.querySelector(".t-dialog__position .hyc-login__content"),
                sends: window.__sends,
              }));
            }"""
        )
        header_only = page.evaluate(
            """() => {
              document.querySelector(".t-portal-wrapper").remove();
              document.querySelector(".ql-editor").setAttribute("data-placeholder", "Send Message");
              const header = yuanbaoLogin(document);
              document.querySelector(".ql-editor").setAttribute("data-placeholder", "请登录后输入内容");
              const chinese = yuanbaoLogin(document);
              document.querySelector(".ql-editor").setAttribute("data-placeholder", "Send Message");
              const panel = document.createElement("div");
              panel.className = "geetest_panel";
              panel.textContent = "验证";
              panel.style.display = "none";
              document.body.appendChild(panel);
              const hiddenCaptcha = yuanbaoLogin(document);
              panel.style.display = "block";
              const shownCaptcha = yuanbaoLogin(document);
              return { header, chinese, hiddenCaptcha, shownCaptcha };
            }"""
        )
        browser.close()
    assert guest["blocked"] is False
    assert guest["tag"] == "A"
    assert "style__send-btn" in guest["klass"]
    assert guest["placeholder"] == "Send Message"
    assert sent["ok"] is True
    assert gated["blocked"] is True
    assert gated["detail"] == "元宝需要登录（游客输入已被关闭），请在该标签页登录一次后重试"
    assert gated["clicked"] is False
    assert gated["loginClicks"] == 0
    assert gated["stillOpen"] is True
    assert gated["sends"] == 1
    assert header_only["header"] is False
    assert header_only["chinese"] is True
    assert header_only["hiddenCaptcha"] is False
    assert header_only["shownCaptcha"] is True


def test_ab_reply_uses_answer_one_and_timeout_clears_the_composer():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        page.set_content(
            """
            <div class="agent-chat__list__item agent-chat__list__item--ai" id="old-ai">
              <div class="hyc-content-md hyc-content-md-done"><div class="hyc-common-markdown">旧答案</div></div>
              <div class="agent-chat__toolbar">复制</div>
            </div>
            <div class="agent-chat__list__item agent-chat__list__item--human">请用一句话给一个读书建议。</div>
            <div class="agent-chat__list__item agent-chat__list__item--ai" id="ab">
              <div class="agent-chat__bubble agent-chat__conv--ai--multiple agent-chat__conv--ai__multi_speech_show">
                <div class="agent-chat__conv--ai__multi_speech_tip">You are providing feedback on the new version of Yuanbao. Which answer do you prefer</div>
                <div>
                  <h4>Answer 1</h4>
                  <div class="hyc-content-md" id="answer-1">
                    <div class="hyc-common-markdown">先读这一句。</div>
                  </div>
                  <button type="button" class="prefer">I prefer this answer</button>
                </div>
                <div>
                  <h4>回答 2</h4>
                  <div class="hyc-content-md" id="answer-2">
                    <div class="hyc-common-markdown">另一句留在附注里。</div>
                  </div>
                  <button type="button" class="prefer">我更喜欢这个答案</button>
                </div>
              </div>
            </div>
            <div aria-label="Stop Answering" hidden>停止</div>
            <div data-new-input-card>
              <div class="ql-editor" contenteditable="true" data-placeholder="Send Message">第二轮转发</div>
              <div id="yuanbao-send-btn" aria-label="Send" class="SendButton_sendButton__g3Lcb">Send</div>
            </div>
            """
        )
        page.add_script_tag(path=str(ROOT / "extension" / "yuanbao.js"))
        page.evaluate(
            """() => {
              window.__prefers = 0;
              document.querySelectorAll(".prefer").forEach((button) => {
                button.addEventListener("click", () => { window.__prefers += 1; });
              });
            }"""
        )
        waiting = page.evaluate(
            """() => {
              const node = yuanbaoNewReply(document, "请用一句话给一个读书建议。");
              return { id: node && node.id, done: yuanbaoDone(node) };
            }"""
        )
        partial = page.evaluate(
            """() => {
              document.querySelector("#answer-1").classList.add("hyc-content-md-done");
              const node = yuanbaoNewReply(document, "请用一句话给一个读书建议。");
              const stop = document.querySelector("[aria-label='Stop Answering']");
              stop.hidden = false;
              const streaming = yuanbaoSendIdle(document);
              stop.hidden = true;
              const idle = yuanbaoSendIdle(document);
              return {
                id: node.id,
                done: yuanbaoDone(node),
                streaming,
                idle,
                text: yuanbaoText(node),
                prefers: window.__prefers,
                secondStillOpen: !document.querySelector("#answer-2").classList.contains("hyc-content-md-done"),
              };
            }"""
        )
        replaced = page.evaluate(
            """() => {
              const fresh = document.createElement("div");
              fresh.id = "ab-replaced";
              fresh.className = "agent-chat__list__item agent-chat__list__item--ai";
              fresh.innerHTML = document.querySelector("#ab").innerHTML;
              document.querySelector("#ab").replaceWith(fresh);
              const node = yuanbaoNewReply(document, "请用一句话给一个读书建议。");
              return node && node.id;
            }"""
        )
        single = page.evaluate(
            """() => {
              const node = document.createElement("div");
              node.className = "agent-chat__list__item agent-chat__list__item--ai";
              node.innerHTML = '<div class="hyc-content-md hyc-content-md-done"><div class="hyc-common-markdown">单独一句。</div></div><div class="agent-chat__toolbar">复制</div>';
              return { done: yuanbaoDone(node), text: yuanbaoText(node) };
            }"""
        )
        note = page.evaluate(
            """() => yuanbaoTimeoutNote(document, 1)"""
        )
        incomplete = page.evaluate(
            """() => yuanbaoPartial(yuanbaoNewReply(document, "请用一句话给一个读书建议。"))"""
        )
        cleared = page.evaluate(
            """() => {
              document.execCommand = () => true;
              const composer = yuanbaoComposer(document);
              composer.textContent = "林知秋 的公开答复：【演示回复】建议下一位由 元宝网页 补充";
              yuanbaoClearComposer(composer);
              return (composer.innerText || composer.textContent || "").replace(/\\s+/g, "").trim();
            }"""
        )
        browser.close()
    assert waiting["id"] == "ab"
    assert waiting["done"] is False
    assert partial["id"] == "ab"
    assert partial["done"] is True
    assert partial["secondStillOpen"] is True
    assert partial["streaming"] is False
    assert partial["idle"] is True
    assert partial["text"].startswith("先读这一句。")
    assert "（元宝给出了 A/B 两个答案，已取答案 1）" in partial["text"]
    assert "另一句" not in partial["text"]
    assert "Which answer" not in partial["text"]
    assert "prefer" not in partial["text"].lower()
    assert "更喜欢" not in partial["text"]
    assert partial["prefers"] == 0
    assert replaced == "ab-replaced"
    assert "先读这一句" not in note
    assert "AI 1→" in note
    assert "done 1" in note
    assert "可能未完整" in incomplete
    assert single["done"] is True
    assert single["text"] == "单独一句。"
    assert cleared == ""


def test_multiline_forward_matches_across_quill_paragraphs():
    page_html = """
    <div data-new-input-card>
      <div class="ql-editor ql-blank" contenteditable="true" data-placeholder="Send Message"><p><br></p></div>
      <div id="yuanbao-send-btn" class="SendButton_sendButton__g3Lcb" aria-label="Send">Send</div>
    </div>
    <div class="agent-chat__list"></div>
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        page.set_content(page_html)
        page.add_script_tag(path=str(ROOT / "extension" / "yuanbao.js"))
        result = page.evaluate(
            """async () => {
              const prompt = "林知秋 的公开答复：【演示回复】建议下一位由 元宝网页 补充 😀\\n请只根据这句公开答复补充或质疑。";
              const editor = document.querySelector(".ql-editor");
              document.execCommand = (command, _ui, value) => {
                if (command !== "insertText") return true;
                editor.replaceChildren();
                String(value || "").split(/\\n+/).forEach((line) => {
                  const para = document.createElement("p");
                  para.textContent = line;
                  editor.appendChild(para);
                });
                editor.classList.remove("ql-blank");
                return true;
              };
              window.__sends = 0;
              document.querySelector("#yuanbao-send-btn").addEventListener("pointerdown", () => {
                window.__sends += 1;
                const item = document.createElement("div");
                item.className = "agent-chat__list__item--human";
                document.querySelector(".agent-chat__list").appendChild(item);
              });
              const sent = await yuanbaoDispatchSend(document, prompt, 2500);
              const joined = yuanbaoComposerText(editor);
              const first = editor.querySelector("p").innerText;
              const folded = document.createElement("div");
              folded.className = "ql-editor";
              const wide = document.createElement("p");
              wide.textContent = "林知秋 的公开答复：【演示回复】１";
              folded.appendChild(wide);
              const near = "甲".repeat(120) + "。";
              const nearNode = document.createElement("div");
              const nearPara = document.createElement("p");
              nearPara.textContent = "甲".repeat(120);
              nearNode.appendChild(nearPara);
              const shortNode = document.createElement("div");
              const shortPara = document.createElement("p");
              shortPara.textContent = "甲".repeat(40);
              shortNode.appendChild(shortPara);
              const dropped = "甲".repeat(40) + "后面整句都被丢掉了不要发送";
              const detail = yuanbaoDiagnosis(shortNode, dropped);
              const samples = [...detail.matchAll(/「([^」]*)」/g)].map((item) => [...item[1]].length);
              return {
                ok: sent.ok,
                sends: window.__sends,
                paragraphs: editor.querySelectorAll("p").length,
                firstShorter: [...first].length < [...joined].length,
                joinedHasEmoji: joined.includes("😀"),
                folded: yuanbaoMatchState(folded, "林知秋 的公开答复：【演示回复】1"),
                near: yuanbaoMatchState(nearNode, near),
                refused: yuanbaoMatchState(shortNode, dropped),
                detail,
                samples,
              };
            }"""
        )
        browser.close()
    assert result["ok"] is True
    assert result["sends"] == 1
    assert result["paragraphs"] == 2
    assert result["firstShorter"] is True
    assert result["joinedHasEmoji"] is True
    assert result["folded"] == "match"
    assert result["near"] == "match"
    assert result["refused"] == "mismatch"
    assert "第 40 字不同" in result["detail"]
    assert result["samples"]
    assert max(result["samples"]) <= 10
