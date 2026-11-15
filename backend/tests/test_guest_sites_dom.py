"""Generic guest.js behaviour (walls, unsent-and-cleared) on small hand-made pages.

Per-site selectors are tested against the real DOM in test_real_dom.py; these pages only exercise the
gate and send-check logic.
"""

import pytest

pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.browser

from pathlib import Path

from playwright.sync_api import sync_playwright

from tests.ext_scripts import add_adapters

ROOT = Path(__file__).resolve().parents[2]
PROMPT = "用一句话介绍你自己"

SITES = {
    "qwen": {
        "url": "https://chat.qwen.ai/c/guest",
        "html": """
<div class="chat-messages"></div>
<div class="message-input-container"><textarea rows="1" class="message-input-textarea" placeholder="Ask Qwen"></textarea>
<div class="chat-prompt-send-button"><button class="send-button disabled " aria-label="Send" disabled>发</button></div></div>
<div class="other-btn" role="button">Thinking</div>
""",
        # JS snippets: enable(sendEl) on input, user(text) -> node html, reply html with {TEXT}, finish(node)
        "on_input": "const b=document.querySelector('.send-button'); if (box.value) { b.disabled=false; b.classList.remove('disabled'); } else { b.disabled=true; b.classList.add('disabled'); }",
        "send": ".send-button",
        "list": ".chat-messages",
        "user": '<div class="qwen-chat-message qwen-chat-message-user"><div class="chat-user-message-container"><p class="user-message-content">{TEXT}</p></div></div>',
        "reply": '<div class="qwen-chat-message qwen-chat-message-assistant"><div class="chat-response-message"><div class="qwen-chat-thinking-status-card">Thinking…</div><div class="response-message-content t2t phase-answer"><div class="custom-qwen-markdown"><div class="qwen-markdown"><p class="qwen-markdown-paragraph"><span class="qwen-markdown-text-node"></span></p></div></div></div></div></div>',
        "target": ".qwen-markdown-text-node",
        "streaming_on": "const b=document.querySelector('.send-button'); b.outerHTML='<button class=\"stop-button\" aria-label=\"Stop\" data-aes-exp=\"expInputStop\">停</button>';",
        "streaming_off": "document.querySelector('.stop-button').outerHTML='<button class=\"send-button disabled \" aria-label=\"Send\" disabled>发</button>';",
        "finish": "node.querySelector('.chat-response-message').insertAdjacentHTML('beforeend','<div class=\"response-message-footer\"><button aria-label=\"Copy\">c</button></div>');",
    },
    "chatgpt": {
        "url": "https://chatgpt.com/",
        "html": """
<ol class="thread"></ol>
<div data-composer-layout><div data-composer-editor-host><textarea id="mobile-composer-prompt" name="prompt" data-mobile-composer-prompt aria-label="Chat with ChatGPT" placeholder="Ask ChatGPT" rows="1"></textarea></div>
<button data-send-dictation disabled>mic</button>
<button class="send" data-variant="primary" data-icon-only disabled><svg><use href="#lightweight-composer-send"></use></svg></button></div>
""",
        "on_input": "const b=document.querySelector('button.send'); b.disabled=!box.value;",
        "send": "button.send",
        "list": ".thread",
        "user": '<li data-message-role="user"><div data-user-message-bubble><p data-user-message-copy>{TEXT}</p></div></li>',
        "reply": '<li data-message-role="assistant" id="a1"><h4 data-message-attribution aria-label="ChatGPT said:">ChatGPT said:</h4><div data-assistant-markdown data-assistant-markdown-root><div aria-busy="true"><section aria-label="DIL content"><p data-d-component="text"></p></section></div></div></li>',
        "target": "p[data-d-component='text']",
        "streaming_on": "",
        "streaming_off": "",
        "finish": "node.querySelector('[aria-busy]').setAttribute('aria-busy','false'); node.setAttribute('data-message-complete',''); node.setAttribute('data-assistant-content-started','');",
        "navigate": "/uc/guest-1",
    },
    "wenxin": {
        "url": "https://wenxin.baidu.com/?enter_type=yiyan_site",
        "html": """
<div id="conversation-flow-content" class="conversation-flow-content"></div>
<div id="ci-area"><textarea id="chat-textarea" class="ci-textarea ci-scroll-style" rows="1" maxlength="20000" placeholder="试试问我"></textarea>
<span class="ci-submit-button"><img id="ci-submit-button-ai" src="send-icon.svg"></span></div>
""",
        "on_input": "document.querySelector('#ci-submit-button-ai').classList.toggle('ci-submit-button-ai-active', !!box.value);",
        "send": "span.ci-submit-button",
        "list": "#conversation-flow-content",
        "user": '<div class="chat-qa-container"><div class="_question-wrapper_x"><div class="conversation-flow-question-container"><div class="cs-question-bubble cs-bubble"><div class="cs-question-pure-text">{TEXT}</div></div></div></div></div>',
        "reply": '<div class="_ai-entry_63lud_24"><div class="ai-entry-block ai-markdown"><div class="cosd-markdown"><div class="cosd-markdown-content"><div class="marklang"><div class="marklang-paragraph">正在思考</div></div></div></div></div></div>',
        "target": ".marklang-paragraph",
        "reply_into_last_user": True,
        "streaming_on": "",
        "streaming_off": "",
        "finish": "node.closest('.chat-qa-container').insertAdjacentHTML('beforeend','<div class=\"menu\"><span data-testid=\"menu-btn-copy\">复制</span></div>');",
        "navigate": "/search/123",
    },
    "zhipu": {
        "url": "https://chatglm.cn/main/alltoolsdetail?lang=zh",
        "html": """
<div class="conversation-list chatScrollContainer"></div>
<div class="input-box"><div class="input-wrap"><div class="input-box-inner"><div class="custom-placeholder">和我聊聊天吧</div><textarea rows="1" class="scroll-display-none" placeholder=""></textarea></div>
<div class="enter is-main-chat">➤</div></div></div>
""",
        "on_input": "",
        "send": "div.enter",
        "list": ".conversation-list",
        "user": '<div class="conversation-item" id="aaaaaaaaaaaaaaaaaaaaaaaa"><div class="conversation question" id="row-question-0"><div class="user-name">访客_123456</div><div id="row-question-p-0" class="question-txt"><span>{TEXT}</span></div></div></div>',
        "reply": '<div class="conversation answer"><div class="assistant-name">ChatGLM</div><div class="answer-content flex1"><div class="code-box"><div class="advance-thinking"><div class="answer-content-wrap text-advance-thinking-content"><div class="markdown-body md-body tl"><p>思考过程不要收</p></div></div></div><div class="answer-content-wrap"><div class="markdown-body md-body tl" id="t1"><p></p></div></div></div></div></div>',
        "target": "#t1 p",
        "reply_into_last_user": True,
        "streaming_on": "",
        "streaming_off": "",
        "finish": "node.closest('.conversation-item').insertAdjacentHTML('beforeend','<div class=\"interact-container\" id=\"interactContainer-1\"><span class=\"regenerate\">r</span><i class=\"shim copy canuse\"></i></div>');",
    },
    "zai": {
        "url": "https://chat.z.ai/",
        "html": """
<div id="messages-container"></div>
<div class="messageInputContainer"><textarea id="chat-input" data-slot="textarea-control" rows="2" placeholder="Send a Message" dir="auto"></textarea>
<button id="send-message-button" type="submit" aria-label="Send Message" data-slot="button" data-variant="primary" disabled>发</button></div>
<header><button>Log in</button><button>Sign in</button><span>Guest</span></header>
""",
        "on_input": "document.querySelector('#send-message-button').disabled=!box.value;",
        "send": "#send-message-button",
        "list": "#messages-container",
        "user": '<div class="user-message" id="message-u1"><div class="chat-user"><div data-user-bubble="true">{TEXT}</div><button aria-label="Copy">c</button></div></div>',
        "reply": '<div id="message-a1" class="message-a1"><div class="chat-assistant markdown-prose"><div class="thinking-chain-container"><button>Thought Process</button><p>想法不要收</p></div><div id="response-content-container"><div class="chat-markdown"><p class="_markdown-tokens-scope"><span></span></p></div></div></div></div>',
        "target": "._markdown-tokens-scope span",
        "streaming_on": "",
        "streaming_off": "",
        "finish": "node.insertAdjacentHTML('beforeend','<div><button aria-label=\"Copy\" data-slot=\"button\" data-variant=\"tertiary\">c</button><button aria-label=\"Regenerate\">r</button></div>');",
        "navigate": "/c/zai-1",
    },
}

SITES["wenxin_chat_baidu"] = {**SITES["wenxin"], "url": "https://chat.baidu.com/", "site": "wenxin"}

WORDS = ["我是", "一个", "AI 助手，", "很高兴认识你。"]


def _open(playwright, spec):
    browser = playwright.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page()
    body = '<meta charset="utf-8">' + spec["html"]
    page.route("https://**/*", lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=body))
    page.goto(spec["url"])
    page.evaluate(
        """() => {
          window.__progress = [];
          window.chrome = { runtime: { id: "room", sendMessage(m) { window.__progress.push(m); }, onMessage: { addListener() {}, removeListener() {} } } };
        }"""
    )
    add_adapters(page)
    page.add_script_tag(path=str(ROOT / "extension" / "guest.js"))
    page.add_script_tag(path=str(ROOT / "extension" / "content.js"))
    return browser, page


DRIVER = """async ([site, spec, prompt, words]) => {
  window.__sends = 0; window.__writes = 0; window.__extra = 0;
  const box = document.querySelector("textarea");
  const proto = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value");
  Object.defineProperty(HTMLTextAreaElement.prototype, "value", {
    configurable: true,
    get() { return proto.get.call(this); },
    set(next) { if (next) window.__writes += 1; proto.set.call(this, next); },
  });
  box.addEventListener("input", () => { if (spec.on_input) new Function("box", spec.on_input)(box); });
  document.querySelectorAll("header button, .other-btn, [data-send-dictation]").forEach((el) => {
    el.addEventListener("pointerdown", () => { window.__extra += 1; });
    el.addEventListener("click", () => { window.__extra += 1; });
  });
  const list = document.querySelector(spec.list);
  document.addEventListener("pointerdown", (event) => {
    const send = event.target.closest(spec.send);
    if (!send) return;
    window.__sends += 1;
    const typed = box.value;
    if (spec.navigate) history.pushState({}, "", spec.navigate);
    list.insertAdjacentHTML("beforeend", spec.user.replace("{TEXT}", typed));
    proto.set.call(box, "");
    if (spec.on_input) new Function("box", spec.on_input)(box);
    setTimeout(() => {
      const host = spec.reply_into_last_user ? list.lastElementChild : list;
      host.insertAdjacentHTML("beforeend", spec.reply);
      const node = host.lastElementChild;
      if (spec.streaming_on) new Function(spec.streaming_on)();
      const target = node.querySelector(spec.target);
      let step = 0;
      const timer = setInterval(() => {
        if (step === 0) target.textContent = "";
        if (step < words.length) { target.textContent += words[step]; step += 1; return; }
        clearInterval(timer);
        if (spec.streaming_off) new Function(spec.streaming_off)();
        new Function("node", spec.finish)(node);
      }, 250);
    }, 200);
  }, true);
  const started = Date.now();
  const result = await runJob({ request_id: "job-" + site, prompt, site, action: "run" });
  return {
    status: result.status, text: result.text, detail: result.detail || "",
    elapsed: Date.now() - started, sends: window.__sends, writes: window.__writes, extra: window.__extra,
    empty: box.isConnected ? box.value === "" : true,
    source: GUEST_DOM_SOURCE,
  };
}"""


def test_qwen_age_confirm_is_reported_not_clicked():
    spec = SITES["qwen"]
    with sync_playwright() as playwright:
        browser, page = _open(playwright, spec)
        result = page.evaluate(
            """async ([spec, prompt]) => {
              window.__continue = 0;
              const box = document.querySelector("textarea");
              box.addEventListener("input", () => new Function("box", spec.on_input)(box));
              document.addEventListener("pointerdown", (event) => {
                if (!event.target.closest(".send-button")) return;
                document.body.insertAdjacentHTML("beforeend", '<div role="dialog" class="age-modal"><h3>Confirm your age to continue</h3><select><option>2000</option></select><button class="go">Continue</button></div>');
                document.querySelector(".go").addEventListener("click", () => { window.__continue += 1; });
              }, true);
              const result = await runJob({ request_id: "age-job", prompt, site: "qwen", action: "run" });
              return { status: result.status, detail: result.detail, cont: window.__continue, empty: box.value === "" };
            }""",
            [spec, PROMPT],
        )
        browser.close()
    assert result["status"] == "login"
    assert "需要先在页面上完成确认" in result["detail"]
    assert result["cont"] == 0
    assert result["empty"] is True


def test_login_or_captcha_wall_stops_before_writing():
    with sync_playwright() as playwright:
        browser, page = _open(playwright, SITES["chatgpt"])
        result = page.evaluate(
            """async (prompt) => {
              const box = document.querySelector("textarea");
              document.body.insertAdjacentHTML("beforeend", '<div role="dialog" id="wall">Log in or sign up to get smarter responses</div>');
              const login = await runJob({ request_id: "wall-1", prompt, site: "chatgpt", action: "run" });
              document.querySelector("#wall").textContent = "Please drag the slider to verify";
              const captcha = await runJob({ request_id: "wall-2", prompt, site: "chatgpt", action: "run" });
              return { login, captcha, empty: box.value === "" };
            }""",
            PROMPT,
        )
        browser.close()
    assert result["login"]["status"] == "login"
    assert "需要登录" in result["login"]["detail"]
    assert result["captcha"]["status"] == "login"
    assert "人机验证" in result["captcha"]["detail"]
    assert result["empty"] is True


def test_guest_send_that_never_lands_reports_filled_not_sent_and_clears():
    with sync_playwright() as playwright:
        browser, page = _open(playwright, SITES["zai"])
        result = page.evaluate(
            """async (prompt) => {
              const box = document.querySelector("textarea");
              box.addEventListener("input", () => { document.querySelector("#send-message-button").disabled = !box.value; });
              let clicks = 0;
              document.querySelector("#send-message-button").addEventListener("pointerdown", () => { clicks += 1; });
              const outcome = await guestDispatchSend("zai", document, prompt, 1200);
              return { ok: outcome.ok, detail: outcome.detail, clicks, empty: box.value === "" };
            }""",
            PROMPT,
        )
        browser.close()
    assert result["ok"] is False
    assert "已填入，未发送" in result["detail"]
    assert "已点过一次发送（button#send-message-button" not in result["detail"]  # 标签只含标签名和类名
    assert "已点过一次发送（button" in result["detail"]
    assert PROMPT not in result["detail"]
    assert result["clicks"] == 1
    assert result["empty"] is True
