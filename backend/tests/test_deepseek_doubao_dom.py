import pytest

pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.browser

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]

DEEPSEEK_PAGE = """
<div class="ds-virtual-list-visible-items">
  <div data-virtual-list-item-key="1">
    <div class="ds-message">
      <div class="ds-collapsible-text"><span>旧问题</span></div>
    </div>
  </div>
</div>
<div class="ds-toggle-button" role="button" aria-pressed="false">DeepThink</div>
<div class="ds-toggle-button" role="button" aria-pressed="false">Search</div>
<div class="bf38813a">
  <div role="button" class="ds-button ds-button--capsule">附件</div>
  <textarea placeholder="Message DeepSeek" name="search" rows="2"></textarea>
  <div role="button" class="ds-button ds-button--primary ds-button--filled ds-button--circle ds-button--m ds-button--disabled">发送</div>
</div>
"""


def test_deepseek_sends_once_and_reads_only_the_answer():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        page.set_content(DEEPSEEK_PAGE)
        page.add_script_tag(path=str(ROOT / "extension" / "deepseek.js"))
        sent = page.evaluate(
            """async () => {
              window.__writes = 0;
              window.__extra = 0;
              const proto = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value");
              Object.defineProperty(HTMLTextAreaElement.prototype, "value", {
                configurable: true,
                get() { return proto.get.call(this); },
                set(next) {
                  if (next) window.__writes += 1;
                  proto.set.call(this, next);
                },
              });
              document.querySelectorAll(".ds-toggle-button, .ds-button--capsule").forEach((el) => {
                el.addEventListener("pointerdown", () => { window.__extra += 1; });
                el.addEventListener("click", () => { window.__extra += 1; });
              });
              const send = document.querySelector(".ds-button--circle");
              const box = document.querySelector("textarea");
              box.addEventListener("input", () => {
                if (box.value && !window.__hold) send.classList.remove("ds-button--disabled");
              });
              send.addEventListener("pointerdown", () => {
                window.__sends = (window.__sends || 0) + 1;
                const item = document.createElement("div");
                item.className = "ds-message";
                item.innerHTML = '<div class="ds-collapsible-text"><span></span></div>';
                item.querySelector("span").textContent = box.value;
                document.querySelector(".ds-virtual-list-visible-items").appendChild(item);
              });
              const outcome = await deepseekDispatchSend(document, "请用一句话给一个读书建议。", 2500);
              send.setAttribute("aria-label", "Stop");
              const streaming = deepseekSendIdle(document);
              send.removeAttribute("aria-label");
              const idle = deepseekSendIdle(document);
              const reply = document.createElement("div");
              reply.className = "ds-message";
              reply.innerHTML = `
                <div>Found 3 web pages</div>
                <div class="ds-thinking">思考过程不要收</div>
                <div class="ds-markdown ds-assistant-message-main-content">
                  <p class="ds-markdown-paragraph">每天半小时就够。</p>
                  <span data-citation-group><a class="ds-markdown-cite">引用</a></span>
                </div>
                <div class="ds-flex">
                  <div role="button" class="ds-button ds-button--iconLabelTertiary">复制</div>
                  <div role="button" class="ds-button ds-button--iconLabelTertiary">重新生成</div>
                </div>`;
              reply.querySelectorAll(".ds-flex [role='button']").forEach((el) => {
                el.addEventListener("click", () => { window.__extra += 1; });
              });
              document.querySelector(".ds-virtual-list-visible-items").appendChild(reply);
              const node = deepseekNewReply(document, "请用一句话给一个读书建议。");
              return {
                ok: outcome.ok,
                sends: window.__sends,
                writes: window.__writes,
                extra: window.__extra,
                streaming,
                idle,
                text: deepseekText(node),
                done: deepseekDone(node),
                source: DEEPSEEK_DOM_SOURCE,
              };
            }"""
        )
        blocked = page.evaluate(
            """async () => {
              window.__hold = true;
              const send = document.querySelector(".ds-button--circle");
              send.classList.add("ds-button--disabled");
              const box = document.querySelector("textarea");
              box.value = "";
              const outcome = await deepseekDispatchSend(document, "不要发出去。", 400);
              return { detail: outcome.detail, clicked: outcome.clicked, empty: box.value === "" };
            }"""
        )
        login = page.evaluate(
            """() => {
              const signIn = deepseekLogin({ location: { pathname: "/sign_in" }, querySelectorAll() { return []; } });
              const input = document.createElement("input");
              input.placeholder = "Phone number / email address";
              input.type = "text";
              document.body.appendChild(input);
              const visible = deepseekLogin(document);
              input.remove();
              return { signIn, visible, detail: deepseekLoginDetail() };
            }"""
        )
        browser.close()
    assert sent["ok"] is True
    assert sent["sends"] == 1
    assert sent["writes"] == 1
    assert sent["extra"] == 0
    assert sent["streaming"] is False
    assert sent["idle"] is True
    assert sent["text"] == "每天半小时就够。"
    assert "Found" not in sent["text"]
    assert "引用" not in sent["text"]
    assert "思考" not in sent["text"]
    assert sent["done"] is True
    assert sent["source"] == "结构取自协调方实页 2026-11-15"
    assert blocked["clicked"] is False
    assert "已填入，未发送" in blocked["detail"]
    assert blocked["empty"] is True
    assert login["signIn"] is True
    assert login["visible"] is True
    assert "DeepSeek 需要登录" in login["detail"]


DOUBAO_PAGE = """
<div data-testid="message-list">
  <div data-testid="union_message">
    <div data-testid="message-block-container">
      <div data-testid="send_message" data-message-role="user">
        <div data-testid="message_text_content">旧问题</div>
      </div>
    </div>
  </div>
</div>
<div data-testid="chat_input_input">
  <div class="tiptap ProseMirror" contenteditable="true">
    <p class="is-empty" data-placeholder="发消息或按住空格说话..."><br></p>
  </div>
</div>
<div class="send-btn-wrapper"></div>
<div data-testid="chat_input_local_break_button" class="hidden">停止</div>
<div data-testid="suggest_message_item">建议问题不要点</div>
"""


def test_doubao_sends_once_reads_body_and_detects_login_or_region_ban():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        page.set_content(DOUBAO_PAGE)
        page.add_script_tag(path=str(ROOT / "extension" / "doubao.js"))
        sent = page.evaluate(
            """async () => {
              window.__writes = 0;
              window.__sends = 0;
              window.__extra = 0;
              const editor = document.querySelector("[contenteditable='true']");
              document.execCommand = (command, _ui, value) => {
                if (command !== "insertText") return true;
                window.__writes += 1;
                const para = editor.querySelector("p");
                para.textContent = String(value || "");
                para.classList.remove("is-empty");
                return true;
              };
              editor.addEventListener("input", () => {
                if (!doubaoComposerText(editor) || document.querySelector("[data-testid='chat_input_send_button']")) return;
                const button = document.createElement("button");
                button.id = "flow-end-msg-send";
                button.setAttribute("data-testid", "chat_input_send_button");
                button.textContent = "发送";
                button.addEventListener("pointerdown", () => {
                  window.__sends += 1;
                  const item = document.createElement("div");
                  item.setAttribute("data-testid", "send_message");
                  item.setAttribute("data-message-role", "user");
                  const body = document.createElement("div");
                  body.setAttribute("data-testid", "message_text_content");
                  body.textContent = editor.innerText;
                  item.appendChild(body);
                  document.querySelector("[data-testid='message-list']").appendChild(item);
                });
                document.querySelector(".send-btn-wrapper").appendChild(button);
              });
              document.querySelector("[data-testid='suggest_message_item']").addEventListener("pointerdown", () => {
                window.__extra += 1;
              });
              const outcome = await doubaoDispatchSend(document, "请用一句话给一个读书建议。", 2500);
              const reply = document.createElement("div");
              reply.setAttribute("data-testid", "receive_message");
              reply.setAttribute("data-message-role", "assistant");
              reply.innerHTML = `
                <div data-plugin-identifier="search_query_result_block" data-copy-ignore="true">
                  <div data-testid="message_text_content" data-streaming="false">搜索结果不要收</div>
                </div>
                <div data-plugin-identifier="block_type:10000">
                  <div data-testid="message_text_content" data-streaming="false">每天半小时就够。</div>
                </div>
                <div data-testid="suggest_message_item">接着问这个</div>
                <div data-testid="message_action_bar"><button data-testid="message_action_copy">复制</button></div>`;
              reply.querySelector("[data-testid='message_action_copy']").addEventListener("click", () => { window.__extra += 1; });
              reply.querySelector("[data-testid='suggest_message_item']").addEventListener("click", () => { window.__extra += 1; });
              document.querySelector("[data-testid='message-list']").appendChild(reply);
              const node = doubaoNewReply(document, "请用一句话给一个读书建议。");
              const streaming = reply.querySelector("[data-plugin-identifier='block_type:10000'] [data-testid='message_text_content']");
              streaming.setAttribute("data-streaming", "true");
              const stop = document.querySelector("[data-testid='chat_input_local_break_button']");
              stop.classList.remove("hidden");
              const busy = { done: doubaoDone(node), idle: doubaoSendIdle(document), stop: !!doubaoStop(document) };
              streaming.setAttribute("data-streaming", "false");
              stop.classList.add("hidden");
              return {
                ok: outcome.ok,
                sends: window.__sends,
                writes: window.__writes,
                extra: window.__extra,
                text: doubaoText(node),
                done: doubaoDone(node),
                idle: doubaoSendIdle(document),
                partial: doubaoPartial(node),
                busy,
                source: DOUBAO_DOM_SOURCE,
              };
            }"""
        )
        gates = page.evaluate(
            """() => {
              const dialog = document.createElement("div");
              dialog.setAttribute("role", "dialog");
              dialog.textContent = "使用豆包或飞书账号登录";
              document.body.appendChild(dialog);
              const login = doubaoLogin(document);
              const loginDetail = doubaoLoginDetail(document);
              dialog.remove();
              const banRoot = { location: { pathname: "/security/doubao-region-ban" }, querySelectorAll() { return []; } };
              return {
                login,
                loginDetail,
                ban: doubaoLogin(banRoot),
                banDetail: doubaoLoginDetail(banRoot),
              };
            }"""
        )
        browser.close()
    assert sent["ok"] is True
    assert sent["sends"] == 1
    assert sent["writes"] == 1
    assert sent["extra"] == 0
    assert sent["text"] == "每天半小时就够。"
    assert "搜索" not in sent["text"]
    assert "接着问" not in sent["text"]
    assert sent["done"] is True
    assert sent["idle"] is True
    assert sent["busy"]["done"] is False
    assert sent["busy"]["idle"] is False
    assert sent["busy"]["stop"] is True
    assert "可能未完整" in sent["partial"]
    assert sent["source"] == "结构取自协调方实页 2026-11-15"
    assert gates["login"] is True
    assert "豆包需要登录" in gates["loginDetail"]
    assert gates["ban"] is True
    assert gates["banDetail"] == "豆包当前网络地区不可用"
