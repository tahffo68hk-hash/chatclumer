"""Adapters against the real 2026-11-15 page DOM (fixtures/real_dom, built by scripts/make_dom_fixtures.py).

Each test serves the real "typed" page at its real URL, loads the extension scripts, and on the one
send click swaps in the real streaming and done DOM (and URL) captured from the same site.
These are real DOM snapshots without the sites' own JavaScript, so a pass shows the selectors and
state detection match the real markup; it is still not a live end-to-end run.
"""

import gzip

import pytest

pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.browser

from pathlib import Path

from playwright.sync_api import sync_playwright

from tests.ext_scripts import add_adapters

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "fixtures" / "real_dom"
PROMPT = "你好，请用一句话回答"

SITES = {
    "qwen": {"file": "qwen", "script": "guest.js", "send": "button.send-button"},
    "chatgpt": {"file": "chatgpt", "script": "guest.js", "send": "button[data-composer-submit]",
                "reply": "你好！很高兴为你服务。"},
    "wenxin": {"file": "wenxin", "script": "guest.js", "send": "span.ci-submit-button",
               "reply": "你好呀，我已经准备好啦，你可以直接说出具体的问题，我会用一句话为你给出清晰准确的回答~"},
    "zhipu": {"file": "chatglm", "script": "guest.js", "send": "div.enter.is-main-chat",
              "reply": "你好！很高兴见到你，我是智谱清言，有什么我可以帮助你的吗？", "done_url_suffix": "&cid=6af90ef1382279812cacd564"},
    "zai": {"file": "zai", "script": "guest.js", "send": "button#send-message-button",
            "reply": "你好！请问有什么我可以帮你的问题吗？"},
    "deepseek": {"file": "deepseek", "script": "deepseek.js", "send": "div[role='button'].ds-button--circle",
                 "reply": "你好！请问有什么我可以帮你的吗？"},
}


def load(name, state):
    raw = gzip.decompress((FIX / f"{name}-{state}.html.gz").read_bytes()).decode("utf-8")
    first, _, body = raw.partition("\n")
    url = first.replace("<!-- url:", "").replace("-->", "").strip()
    return url, body


def open_page(playwright, site):
    spec = SITES[site]
    url, html = load(spec["file"], "1-typed")
    browser = playwright.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page()

    def handle(route):
        if route.request.url.split("#")[0] == url and route.request.resource_type == "document":
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)
        else:
            route.abort()

    page.route("**/*", handle)
    page.goto(url, wait_until="domcontentloaded")
    page.evaluate(
        """() => {
          window.chrome = { runtime: { id: "room", sendMessage() {}, onMessage: { addListener() {}, removeListener() {} } } };
        }"""
    )
    add_adapters(page)
    page.add_script_tag(path=str(ROOT / "extension" / spec["script"]))
    page.add_script_tag(path=str(ROOT / "extension" / "content.js"))
    return browser, page


SWAP = """([sendSel, frames, startText]) => {
  window.__sends = 0;
  window.__writes = 0;
  window.__target = "";
  const proto = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value");
  // 写入次数 = 输入框从空变成非空的次数（execCommand 不经过 value setter，所以按 input 事件数）。
  const prev = new WeakMap();
  document.addEventListener("input", (event) => {
    const el = event.target;
    if (!(el instanceof HTMLTextAreaElement)) return;
    const now = proto.get.call(el);
    if (now && !prev.get(el)) window.__writes += 1;
    prev.set(el, now);
  }, true);
  const apply = (frame) => {
    const doc = new DOMParser().parseFromString(frame.html, "text/html");
    document.body.innerHTML = doc.body.innerHTML;
    // 真实页面发出后输入框是空的；导出里 textarea 的默认文字不代表当时的值。
    document.querySelectorAll("textarea").forEach((el) => { proto.set.call(el, frame.keep || ""); });
    if (frame.toast) document.body.insertAdjacentHTML("beforeend", frame.toast);
    const target = new URL(frame.url);
    if (target.origin === location.origin) history.pushState({}, "", target.pathname + target.search);
  };
  // 导出里没有站点脚本，type=submit 的发送键会让表单真的提交；真实页面由站点自己拦下。
  document.addEventListener("submit", (event) => event.preventDefault(), true);
  document.addEventListener("pointerdown", (event) => {
    if (!event.target.closest(sendSel)) return;
    window.__sends += 1;
    window.__target = event.target.tagName.toLowerCase() + (event.target.id ? "#" + event.target.id : "");
    frames.forEach((frame, index) => setTimeout(() => apply(frame), 300 + index * 900));
  }, true);
}"""


def frames_for(site, keep_text="", swap_user=""):
    spec = SITES[site]
    out = []
    for state in ("2-streaming", "3-done"):
        url, html = load(spec["file"], state)
        if state == "3-done" and spec.get("done_url_suffix") and "cid=" not in url:
            url += spec["done_url_suffix"]
        if swap_user:
            html = html.replace(PROMPT, swap_user)
        out.append({"url": url, "html": html, "keep": keep_text})
    return out


@pytest.mark.parametrize("site", ["chatgpt", "wenxin", "zhipu", "zai", "deepseek"])
def test_real_dom_send_is_confirmed_and_reply_is_read(site):
    spec = SITES[site]
    with sync_playwright() as playwright:
        browser, page = open_page(playwright, site)
        page.evaluate(SWAP, [spec["send"], frames_for(site), PROMPT])
        result = page.evaluate(
            """async ([site, prompt]) => {
              const started = Date.now();
              const result = await runJob({ request_id: "real-" + site, prompt, site, action: "run" });
              const box = document.querySelector("textarea");
              return { status: result.status, text: result.text, detail: result.detail || "", elapsed: Date.now() - started,
                       sends: window.__sends, writes: window.__writes, target: window.__target, empty: !box || box.value === "" };
            }""",
            [site, PROMPT],
        )
        browser.close()
    assert result["status"] == "complete", result
    assert result["text"] == spec["reply"]
    assert "可能未完整" not in result["text"]
    assert result["sends"] == 1
    assert result["writes"] == 1
    assert result["empty"] is True
    assert result["elapsed"] < 15000
    if site == "wenxin":
        assert result["target"] == "img#ci-submit-button-ai"


def test_real_dom_composer_left_filled_after_send_is_still_confirmed_and_cleared():
    # 文心、智谱在实页上发出后，扩展看到的输入框里还留着原文（0.4.1 因此误报「已填入，未发送」）。
    for site in ("wenxin", "zhipu"):
        spec = SITES[site]
        with sync_playwright() as playwright:
            browser, page = open_page(playwright, site)
            page.evaluate(SWAP, [spec["send"], frames_for(site, keep_text=PROMPT), PROMPT])
            result = page.evaluate(
                """async ([site, prompt]) => {
                  const out = await (site === "deepseek" ? deepseekDispatchSend(document, prompt, 10000) : guestDispatchSend(site, document, prompt, 10000));
                  const box = document.querySelector("textarea");
                  return { ok: out.ok, how: out.how || "", detail: out.detail || "", sends: window.__sends, empty: !box || box.value === "" };
                }""",
                [site, PROMPT],
            )
            browser.close()
        assert result["ok"] is True, (site, result)
        assert result["how"] in {"user", "url"}
        assert result["sends"] == 1
        assert result["empty"] is True


def test_real_dom_qwen_permission_toast_is_reported():
    spec = SITES["qwen"]
    url_stream, html_stream = load("qwen", "2-streaming")
    url_home, html_home = load("qwen", "3-done")
    toast = ('<div class="ant-message"><div class="ant-message-notice"><div class="ant-message-notice-content">'
             "You do not have permission to access this resource. Please contact your administrator for assistance."
             "</div></div></div>")
    frames = [
        {"url": url_stream, "html": html_stream, "keep": ""},
        {"url": url_home, "html": html_home, "keep": PROMPT, "toast": toast},
    ]
    with sync_playwright() as playwright:
        browser, page = open_page(playwright, "qwen")
        page.evaluate(SWAP, [spec["send"], frames, PROMPT])
        result = page.evaluate(
            """async (prompt) => {
              const result = await runJob({ request_id: "real-qwen", prompt, site: "qwen", action: "run" });
              const box = document.querySelector("textarea");
              return { status: result.status, detail: result.detail || "", sends: window.__sends, empty: box.value === "" };
            }""",
            PROMPT,
        )
        browser.close()
    assert result["status"] == "login"
    assert "千问游客发送被拒绝" in result["detail"]
    assert result["sends"] == 1
    assert result["empty"] is True


@pytest.mark.parametrize("name", ["qwen", "chatgpt", "wenxin", "chatglm", "zai"])
def test_real_dom_has_no_false_wall(name):
    site = "zhipu" if name == "chatglm" else name
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        page.route("**/*", lambda route: route.abort())
        gates = []
        for state in ("0-empty", "1-typed", "2-streaming", "3-done"):
            _, html = load(name, state)
            page.set_content(html, wait_until="domcontentloaded")
            add_adapters(page)
            page.add_script_tag(path=str(ROOT / "extension" / "guest.js"))
            gates.append(page.evaluate("(site) => guestGate(site, document)", site))
        browser.close()
    assert gates == [None, None, None, None]


def test_real_dom_chatgpt_send_button_is_the_submit_not_dictation():
    with sync_playwright() as playwright:
        browser, page = open_page(playwright, "chatgpt")
        result = page.evaluate(
            """() => {
              const send = guestSend("chatgpt", document);
              return { submit: send && send.hasAttribute("data-composer-submit"), dictation: send && send.hasAttribute("data-send-dictation") };
            }"""
        )
        browser.close()
    assert result == {"submit": True, "dictation": False}


def test_real_dom_wenxin_and_zhipu_write_with_exec_command_first():
    for site in ("wenxin", "zhipu"):
        with sync_playwright() as playwright:
            browser, page = open_page(playwright, site)
            result = page.evaluate(
                """async ([site, prompt]) => {
                  const calls = [];
                  const real = document.execCommand.bind(document);
                  document.execCommand = (cmd, ui, value) => { calls.push(cmd); return real(cmd, ui, value); };
                  const out = await guestCommitPrompt(site, document, prompt);
                  return { ok: out.ok, calls, value: document.querySelector("textarea").value };
                }""",
                [site, PROMPT],
            )
            browser.close()
        assert result == {"ok": True, "calls": ["insertText"], "value": PROMPT}, (site, result)


def test_real_dom_zhipu_unregistered_input_is_not_clicked():
    # 空页上没有站点脚本，发送键一直带 .empty：两种写法都试过后清空，不点击。
    url, html = load("chatglm", "0-empty")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        page.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)
                   if route.request.resource_type == "document" else route.abort())
        page.goto(url, wait_until="domcontentloaded")
        add_adapters(page)
        page.add_script_tag(path=str(ROOT / "extension" / "guest.js"))
        page.evaluate(SWAP, [SITES["zhipu"]["send"], [], PROMPT])
        result = page.evaluate(
            """async (prompt) => {
              const out = await guestDispatchSend("zhipu", document, prompt, 6000);
              return { ok: out.ok, detail: out.detail || "", sends: window.__sends, writes: window.__writes,
                       empty: document.querySelector("textarea").value === "" };
            }""",
            PROMPT,
        )
        browser.close()
    assert result["ok"] is False
    assert "没认到" in result["detail"]
    assert result["sends"] == 0
    assert result["writes"] == 2
    assert result["empty"] is True


def test_real_dom_wenxin_sending_other_text_stops():
    # 文心若把示例提示当问题发出，页面上的新用户消息不是待发文本：停下报错，不再点。
    spec = SITES["wenxin"]
    with sync_playwright() as playwright:
        browser, page = open_page(playwright, "wenxin")
        page.evaluate(SWAP, [spec["send"], frames_for("wenxin", swap_user="帮我写一首关于秋天的诗"), PROMPT])
        result = page.evaluate(
            """async (prompt) => {
              const out = await guestDispatchSend("wenxin", document, prompt, 10000);
              return { ok: out.ok, detail: out.detail || "", sends: window.__sends };
            }""",
            PROMPT,
        )
        browser.close()
    assert result["ok"] is False
    assert "示例提示" in result["detail"]
    assert result["sends"] == 1


def test_real_dom_chatgpt_sign_in_card_is_reported_before_writing():
    with sync_playwright() as playwright:
        browser, page = open_page(playwright, "chatgpt")
        page.evaluate(SWAP, [SITES["chatgpt"]["send"], [], PROMPT])
        page.evaluate(
            """() => document.body.insertAdjacentHTML("beforeend",
              '<div class="card"><h2>Sign in to continue</h2><p>Get smarter responses.</p></div>')"""
        )
        result = page.evaluate(
            """async (prompt) => {
              const job = await runJob({ request_id: "gpt-gate", prompt, site: "chatgpt", action: "run" });
              return { status: job.status, detail: job.detail || "", sends: window.__sends, writes: window.__writes };
            }""",
            PROMPT,
        )
        browser.close()
    assert result["status"] == "login"
    assert "ChatGPT 需要登录后才能继续" in result["detail"]
    assert result["sends"] == 0
    assert result["writes"] == 0


FRAMEWORK_GLM = """async ([prompt, trustedOnly]) => {
  // 模拟站点框架自己的输入状态：只有输入事件（可选：只认浏览器产生的 isTrusted 事件）才更新模型，
  // 发送键的 .empty 由模型驱动；点发送时模型为空就什么都不做——和真实站点「填了但没发出去」同一种失败形态。
  const box = document.querySelector("#search-input-box textarea");
  const icon = document.querySelector("#search-input-box .enter-icon-container");
  const send = document.querySelector("#search-input-box div.enter.is-main-chat");
  let model = "";
  const events = [];
  const render = () => icon.classList.toggle("empty", !model);
  box.addEventListener("input", (event) => {
    events.push(event.isTrusted ? "trusted" : "synthetic");
    if (trustedOnly && !event.isTrusted) return;
    model = box.value;
    render();
  });
  render();
  let clicks = 0, posted = [];
  send.addEventListener("click", () => {
    clicks += 1;
    if (!model) return;
    posted.push(model);
    document.body.insertAdjacentHTML("beforeend", '<div class="conversation-item"><div class="conversation question"><div class="question-txt"><span></span></div></div></div>');
    document.querySelector(".conversation-item:last-child .question-txt span").textContent = model;
    model = ""; box.value = ""; render();
  });
  const outcome = await guestDispatchSend("zhipu", document, prompt, 3000);
  return { ok: outcome.ok, detail: outcome.detail || "", clicks, posted, events, empty: box.value === "" };
}"""


def _open_state(playwright, site, state):
    spec = SITES[site]
    url, html = load(spec["file"], state)
    browser = playwright.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 860})
    page.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)
               if route.request.resource_type == "document" else route.abort())
    page.goto(url, wait_until="domcontentloaded")
    page.evaluate("""() => { window.chrome = { runtime: { id: "room", sendMessage() {}, onMessage: { addListener() {}, removeListener() {} } } }; }""")
    add_adapters(page)
    page.add_script_tag(path=str(ROOT / "extension" / spec["script"]))
    page.add_script_tag(path=str(ROOT / "extension" / "content.js"))
    page.evaluate("() => document.querySelectorAll('textarea').forEach((el) => { el.value = ''; })")
    return browser, page


@pytest.mark.parametrize("trusted_only", [False, True])
def test_real_dom_zhipu_framework_state_sees_the_write_before_the_one_click(trusted_only):
    with sync_playwright() as playwright:
        browser, page = _open_state(playwright, "zhipu", "0-empty")
        result = page.evaluate(FRAMEWORK_GLM, [PROMPT, trusted_only])
        browser.close()
    assert result["ok"] is True, result
    assert result["clicks"] == 1
    assert result["posted"] == [PROMPT]
    # 先清空（合成事件），再用 execCommand 写入：浏览器产生的 input 事件是 isTrusted 的，框架只认可信事件时也能看到文字。
    # 0.4.3 的 guest.js 在同一模型下事件序列完全相同（synthetic, trusted）。
    assert result["events"] == ["synthetic", "trusted"]


GLM_TARGET = """async ([prompt, mode, oldRegistry]) => {
  if (oldRegistry) {
    // 0.5.1 的注册表：智谱只有 click_center，没有 click_inner。
    const reg = JSON.parse(JSON.stringify(ChatclumerAdapters.bundled()));
    reg.version = "2099.1.1.1";
    delete reg.sites.zhipu.flags.click_inner;
    ChatclumerAdapters.useRemote(reg, "test");
  }
  const send = document.querySelector("#search-input-box div.enter.is-main-chat");
  const icon = send.querySelector(".enter-icon-container");
  const box = document.querySelector("#search-input-box textarea");
  // 实页里发送键是小圆钮；导出没有站点 CSS 时它被排成整行宽，中心点总落在内层上。这里给出实页的形状。
  send.style.cssText = "position: fixed; right: 24px; bottom: 24px; width: 32px; height: 32px; padding: 0;";
  icon.style.cssText = "width: 32px; height: 32px;";
  if (mode === "overlay") {
    // 浮层（提示气泡、悬浮工具条等）盖住了发送键中心。
    document.body.insertAdjacentHTML("beforeend", '<div id="cover" style="position: fixed; right: 0; bottom: 0; width: 120px; height: 120px; z-index: 99999;"></div>');
  } else if (mode === "offscreen") {
    send.style.bottom = "-200px";  // 小窗口或输入区滚出视口：elementFromPoint 返回 null
  } else if (mode === "noinner") {
    icon.className = "";  // 注册表里的内层选择器找不到时，退回中心点命中
  }
  const targets = [];
  let model = "";
  box.addEventListener("input", () => { model = box.value; icon.classList.toggle("empty", !model); });
  icon.classList.add("empty");
  document.addEventListener("pointerdown", (event) => { if (send.contains(event.target)) targets.push(event.target === icon ? "inner" : event.target === send ? "outer" : event.target.tagName.toLowerCase()); }, true);
  // 实页站点把点击处理挂在内层图标上：点外层不会发出。
  icon.addEventListener("click", () => {
    if (!model) return;
    document.body.insertAdjacentHTML("beforeend", '<div class="conversation question"><div class="question-txt"><span></span></div></div>');
    document.querySelector(".conversation.question:last-child span").textContent = model;
    model = ""; box.value = ""; icon.classList.add("empty");
  });
  const outcome = await guestDispatchSend("zhipu", document, prompt, 2500);
  return { ok: outcome.ok, detail: outcome.detail || "", targets };
}"""


@pytest.mark.parametrize("mode", ["plain", "overlay", "offscreen"])
def test_real_dom_zhipu_clicks_the_inner_icon_even_when_centre_hit_fails(mode):
    with sync_playwright() as playwright:
        browser, page = _open_state(playwright, "zhipu", "0-empty")
        result = page.evaluate(GLM_TARGET, [PROMPT, mode, False])
        browser.close()
    assert result["targets"] == ["inner"], result
    assert result["ok"] is True, result


@pytest.mark.parametrize("mode", ["overlay", "offscreen"])
def test_real_dom_zhipu_old_registry_falls_back_to_outer_and_says_why(mode):
    # 复现 0.5.1 实页的失败形态：中心点命中失败 → 点了外层 div.enter.is-main-chat → 只点一次，回报「已填入，未发送」并写明原因。
    with sync_playwright() as playwright:
        browser, page = _open_state(playwright, "zhipu", "0-empty")
        result = page.evaluate(GLM_TARGET, [PROMPT, mode, True])
        browser.close()
    assert result["targets"] == ["outer"]
    assert result["ok"] is False
    assert "div.enter.is-main-chat" in result["detail"]
    why = "被其他元素盖住" if mode == "overlay" else "不在视口内"
    assert why in result["detail"]


def test_real_dom_zhipu_without_inner_uses_centre_hit():
    with sync_playwright() as playwright:
        browser, page = _open_state(playwright, "zhipu", "0-empty")
        result = page.evaluate(
            """async (prompt) => {
              const send = document.querySelector("#search-input-box div.enter.is-main-chat");
              send.style.cssText = "position: fixed; right: 24px; bottom: 24px; width: 32px; height: 32px; padding: 0;";
              const icon = send.querySelector(".enter-icon-container");
              icon.className = "";
              icon.style.cssText = "width: 32px; height: 32px;";
              const t = guestPickTarget("zhipu", send);
              return { how: t.how, inside: send.contains(t.el) && t.el !== send };
            }""",
            PROMPT,
        )
        browser.close()
    assert result == {"how": "中心点命中", "inside": True}
