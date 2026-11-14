// 结构取自协调方实页 2026-11-15。本文件不是那次桌面验收，不能当成扩展端到端已通过。
const YUANBAO_DOM_SOURCE = "结构取自协调方实页 2026-11-15";

const YUANBAO_LOGIN_DETAIL = "元宝需要登录（游客输入已被关闭），请在该标签页登录一次后重试";

function yuanbaoVisible(el) {
  if (!el || el.hidden) return false;
  const view = el.ownerDocument && el.ownerDocument.defaultView;
  const style = view && view.getComputedStyle ? view.getComputedStyle(el) : null;
  if (style && (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0)) return false;
  return el.getClientRects().length > 0;
}

function yuanbaoComposer(root) {
  const nodes = [
    ...root.querySelectorAll("#searchbar-editor .ql-editor[contenteditable='true']"),
    ...root.querySelectorAll("[data-new-input-card] .ql-editor[contenteditable='true']"),
    ...root.querySelectorAll("[contenteditable='true'][data-placeholder='Send Message']"),
    ...root.querySelectorAll("[contenteditable='true'][data-placeholder='发消息']"),
    ...root.querySelectorAll(".ql-editor[contenteditable='true']"),
  ];
  return nodes.find((el) => yuanbaoVisible(el)) || nodes[0] || null;
}

function yuanbaoControl(root, labels) {
  return [...root.querySelectorAll("[aria-label]")].find((el) => {
    return labels.has(el.getAttribute("aria-label") || "") && !el.hidden;
  }) || null;
}

function yuanbaoNormalize(value) {
  return String(value || "")
    .replace(/[\u200b\u200c\u200d\ufeff]/g, "")
    .replace(/\u00a0/g, " ")
    .replace(/[\r\n]+$/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function yuanbaoSendIn(scope) {
  if (!scope) return null;
  const nodes = [...scope.querySelectorAll("#yuanbao-send-btn")].filter((el) => !el.closest("[data-recommend]"));
  const classed = nodes.filter((el) => el.classList.length && yuanbaoVisible(el));
  if (classed[0]) return classed[0];
  const visible = nodes.filter((el) => yuanbaoVisible(el));
  if (visible[0]) return visible[0];
  const labeled = [...scope.querySelectorAll("[data-new-input-control='send'] [aria-label='Send'], [data-new-input-control='send'] [aria-label='发送']")].find((el) => {
    return yuanbaoVisible(el) && !el.closest("[data-recommend]");
  });
  return labeled || null;
}

function yuanbaoSend(root) {
  const composer = yuanbaoComposer(root);
  if (!composer) return null;
  const card = composer.closest("[data-new-input-card]") || composer.closest("#searchbar-editor");
  if (card) return yuanbaoSendIn(card);
  let node = composer.parentElement;
  while (node && node !== root.parentElement) {
    if (node.querySelector("[data-recommend]")) return null;
    const local = yuanbaoSendIn(node) || [...node.querySelectorAll("[aria-label='Send'], [aria-label='发送']")].find((el) => {
      return !el.hidden && !el.closest("[data-recommend]");
    });
    if (local) return local;
    node = node.parentElement;
  }
  return null;
}

function yuanbaoStop(root) {
  return yuanbaoControl(root, new Set(["Stop Answering", "停止回答"]));
}

function yuanbaoAssistants(root) {
  return [...root.querySelectorAll(".agent-chat__list__item--ai")];
}

function yuanbaoHumans(root) {
  return [...root.querySelectorAll(".agent-chat__list__item--human")];
}

function yuanbaoComposerText(node) {
  if (!node) return "";
  return yuanbaoNormalize(node.innerText || node.value || node.textContent || "");
}

function yuanbaoSendBlocked(el) {
  if (!el || !yuanbaoVisible(el) || el.disabled || el.getAttribute("aria-disabled") === "true") return true;
  return [...el.classList].some((name) => name.startsWith("SendButton_disabled") || name.startsWith("SendButton_sendNot"));
}

function yuanbaoSendUsable(root) {
  const send = yuanbaoSend(root);
  if (!send || yuanbaoSendBlocked(send)) return null;
  return send;
}

function yuanbaoPress(el) {
  const view = el.ownerDocument.defaultView || window;
  const init = { bubbles: true, cancelable: true, view };
  for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
    const Ctor = type.startsWith("pointer") && typeof view.PointerEvent === "function" ? view.PointerEvent : view.MouseEvent;
    el.dispatchEvent(new Ctor(type, init));
  }
}

function yuanbaoEnter(composer) {
  const event = new KeyboardEvent("keydown", { key: "Enter", code: "Enter", bubbles: true, cancelable: true });
  try {
    Object.defineProperty(event, "keyCode", { get() { return 13; } });
    Object.defineProperty(event, "which", { get() { return 13; } });
  } catch {
    /* 这个浏览器不允许改 keyCode */
  }
  composer.dispatchEvent(event);
}

function yuanbaoSame(node, prompt) {
  return yuanbaoComposerText(node) === yuanbaoNormalize(prompt);
}

function yuanbaoClearComposer(composer) {
  if (!composer) return;
  composer.focus();
  const selection = window.getSelection();
  const range = document.createRange();
  range.selectNodeContents(composer);
  selection.removeAllRanges();
  selection.addRange(range);
  document.execCommand("delete", false, null);
  composer.dispatchEvent(new InputEvent("beforeinput", { bubbles: true, cancelable: true, inputType: "deleteContentBackward" }));
  composer.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "deleteContentBackward" }));
}

function yuanbaoPlaceCaret(composer) {
  composer.focus();
  const selection = window.getSelection();
  const range = document.createRange();
  range.selectNodeContents(composer);
  range.collapse(false);
  selection.removeAllRanges();
  selection.addRange(range);
}

function yuanbaoMatchState(composer, prompt) {
  const expected = yuanbaoNormalize(prompt);
  const actual = yuanbaoComposerText(composer);
  if (actual === expected) return "match";
  const compact = (value) => value.replace(/\s/g, "");
  if (expected && compact(actual) === compact(expected) + compact(expected)) return "duplicate";
  return "mismatch";
}

function yuanbaoDiagnosis(composer, prompt) {
  const expected = yuanbaoNormalize(prompt);
  const actual = yuanbaoComposerText(composer);
  const duplicate = yuanbaoMatchState(composer, prompt) === "duplicate";
  return `待发长度 ${expected.length}，实际长度 ${actual.length}，${duplicate ? "重复" : "不重复"}`;
}

async function yuanbaoSettle(composer, prompt, shouldAbort) {
  const deadline = Date.now() + 1500;
  while (true) {
    if (shouldAbort && shouldAbort()) return "cancelled";
    const state = yuanbaoMatchState(composer, prompt);
    if (state === "match" || state === "duplicate") return state;
    if (Date.now() >= deadline) return state;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
}

async function yuanbaoCommitPrompt(root, prompt, shouldAbort) {
  const composer = yuanbaoComposer(root);
  if (!composer) return { ok: false, detail: "找不到输入框" };
  const text = String(prompt || "");
  const writers = [
    () => {
      yuanbaoClearComposer(composer);
      yuanbaoPlaceCaret(composer);
      document.execCommand("insertText", false, text);
    },
    () => {
      yuanbaoClearComposer(composer);
      yuanbaoPlaceCaret(composer);
      const before = yuanbaoComposerText(composer);
      composer.dispatchEvent(new InputEvent("beforeinput", { bubbles: true, cancelable: true, inputType: "insertText", data: text }));
      if (yuanbaoComposerText(composer) === before) {
        composer.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: text }));
      }
    },
    () => {
      yuanbaoClearComposer(composer);
      yuanbaoPlaceCaret(composer);
      try {
        const data = new DataTransfer();
        data.setData("text/plain", text);
        composer.dispatchEvent(new ClipboardEvent("paste", { bubbles: true, cancelable: true, clipboardData: data }));
      } catch {
        /* 这个浏览器不接受合成粘贴事件 */
      }
    },
  ];
  for (const write of writers) {
    write();
    const state = await yuanbaoSettle(composer, text, shouldAbort);
    if (state === "match") return { ok: true };
    if (state === "cancelled") return { ok: false, detail: "cancelled" };
    yuanbaoClearComposer(composer);
  }
  return { ok: false, detail: yuanbaoDiagnosis(composer, text) };
}

async function yuanbaoDispatchSend(root, prompt, timeoutMs, shouldAbort) {
  const deadline = Date.now() + (timeoutMs == null ? 10000 : timeoutMs);
  if (shouldAbort && shouldAbort()) return { ok: false, detail: "cancelled", clicked: false };
  if (yuanbaoLogin(root)) return { ok: false, detail: yuanbaoLoginDetail(), clicked: false };
  const composer = yuanbaoComposer(root);
  if (!composer) return { ok: false, detail: "找不到输入框", clicked: false };
  const committed = await yuanbaoCommitPrompt(root, prompt, shouldAbort);
  if (!committed.ok) {
    if (committed.detail !== "cancelled") yuanbaoClearComposer(composer);
    const detail = committed.detail === "cancelled" || committed.detail === "找不到输入框"
      ? committed.detail
      : `输入框内容和待发文本不一致，没有点击发送。${committed.detail}`;
    return { ok: false, detail, clicked: false };
  }
  const matched = true;
  const before = yuanbaoHumans(root).length;
  let clicked = false;
  let pressedAt = 0;
  let entered = false;
  while (Date.now() < deadline) {
    if (shouldAbort && shouldAbort()) {
      if (!clicked) yuanbaoClearComposer(composer);
      return { ok: false, detail: "cancelled", clicked };
    }
    const ready = matched && yuanbaoSame(composer, prompt) && !composer.classList.contains("ql-blank");
    if (!clicked) {
      const send = yuanbaoSendUsable(root);
      if (ready && send) {
        yuanbaoPress(send);
        clicked = true;
        pressedAt = Date.now();
      }
    } else if (yuanbaoHumans(root).length > before) {
      return { ok: true, clicked: true };
    } else if (!entered && pressedAt && Date.now() - pressedAt >= 500) {
      yuanbaoEnter(composer);
      entered = true;
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  const note = yuanbaoDiagnosis(composer, prompt);
  const detail = clicked || yuanbaoSame(composer, prompt)
    ? `已填入，未发送。${note}`
    : `输入框内容和待发文本不一致，没有点击发送。${note}`;
  if (!clicked || yuanbaoHumans(root).length === before) yuanbaoClearComposer(composer);
  return { ok: false, detail, clicked };
}

function yuanbaoText(node) {
  const md = node.querySelector(".hyc-common-markdown");
  if (!md) return "";
  const clone = md.cloneNode(true);
  clone.querySelectorAll(".hyc-common-markdown__ref-list, .hyc-card-box-process-list").forEach((el) => el.remove());
  clone.querySelectorAll("img").forEach((img) => {
    const card = img.parentElement;
    if (card && card !== clone && /全屏查看|View full screen/i.test(card.textContent || "")) card.remove();
  });
  return (clone.innerText || clone.textContent || "").replace(/\s+/g, " ").trim();
}

function yuanbaoDone(node) {
  const finished = node.querySelector(".hyc-content-md-done");
  const toolbar = node.querySelector(".agent-chat__conv--ai__toolbar, .agent-chat__toolbar");
  return !!(finished && toolbar);
}

function yuanbaoLoginDetail() {
  return YUANBAO_LOGIN_DETAIL;
}

function yuanbaoLogin(root) {
  const scope = root && root.querySelector ? root : document;
  const dialog = [...scope.querySelectorAll(".t-dialog__position")].find((box) => {
    return yuanbaoVisible(box) && box.querySelector(".hyc-login__content, .hyc-login__close");
  });
  if (dialog) return true;
  const composer = yuanbaoComposer(scope);
  const placeholder = composer ? composer.getAttribute("data-placeholder") || "" : "";
  if (/log ?in|登录/i.test(placeholder)) return true;
  return [...scope.querySelectorAll("#tcaptcha_iframe, .tcaptcha-transform, .geetest_panel")].some((el) => yuanbaoVisible(el));
}
