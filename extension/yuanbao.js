// 结构取自协调方实页 2026-11-15。本文件不是那次桌面验收，不能当成扩展端到端已通过。
const YUANBAO_DOM_SOURCE = "结构取自协调方实页 2026-11-15";

function yuanbaoComposer(root) {
  return root.querySelector("[contenteditable='true'][data-placeholder='Send Message']")
    || root.querySelector("[contenteditable='true'][data-placeholder='发消息']")
    || root.querySelector(".ql-editor[contenteditable='true']");
}

function yuanbaoControl(root, labels) {
  return [...root.querySelectorAll("[aria-label]")].find((el) => {
    return labels.has(el.getAttribute("aria-label") || "") && !el.hidden;
  }) || null;
}

function yuanbaoNormalize(value) {
  return String(value || "").replace(/[\u200b\u200c\u200d\ufeff]/g, "").replace(/\s+/g, " ").trim();
}

function yuanbaoSendIn(scope) {
  if (!scope) return null;
  const byId = scope.querySelector("#yuanbao-send-btn");
  if (byId && !byId.hidden && !byId.closest("[data-recommend]")) return byId;
  const labeled = [...scope.querySelectorAll("[data-new-input-control='send'] [aria-label='Send'], [data-new-input-control='send'] [aria-label='发送']")].find((el) => {
    return !el.hidden && !el.closest("[data-recommend]");
  });
  return labeled || null;
}

function yuanbaoSend(root) {
  const composer = yuanbaoComposer(root);
  if (!composer) return null;
  const card = composer.closest("[data-new-input-card]");
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
  if (!el || el.hidden || el.disabled || el.getAttribute("aria-disabled") === "true") return true;
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

function yuanbaoCommitPrompt(root, prompt) {
  const composer = yuanbaoComposer(root);
  if (!composer) return false;
  const text = String(prompt || "");
  yuanbaoClearComposer(composer);
  composer.focus();
  const selection = window.getSelection();
  const range = document.createRange();
  range.selectNodeContents(composer);
  range.collapse(false);
  selection.removeAllRanges();
  selection.addRange(range);
  document.execCommand("insertText", false, text);
  if (!yuanbaoSendUsable(root) || !yuanbaoSame(composer, text)) {
    composer.dispatchEvent(new InputEvent("beforeinput", { bubbles: true, cancelable: true, inputType: "insertText", data: text }));
    composer.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: text }));
  }
  if (!yuanbaoSendUsable(root) || !yuanbaoSame(composer, text)) {
    try {
      const data = new DataTransfer();
      data.setData("text/plain", text);
      composer.dispatchEvent(new ClipboardEvent("paste", { bubbles: true, cancelable: true, clipboardData: data }));
    } catch {
      /* 这个浏览器不接受合成粘贴事件 */
    }
  }
  return yuanbaoSame(composer, text);
}

async function yuanbaoDispatchSend(root, prompt, timeoutMs, shouldAbort) {
  const deadline = Date.now() + (timeoutMs == null ? 10000 : timeoutMs);
  if (shouldAbort && shouldAbort()) return { ok: false, detail: "cancelled", clicked: false };
  if (yuanbaoLogin(root)) return { ok: false, detail: "页面停在登录或验证，没有点击发送", clicked: false };
  const composer = yuanbaoComposer(root);
  if (!composer) return { ok: false, detail: "找不到输入框", clicked: false };
  const matched = yuanbaoCommitPrompt(root, prompt);
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
  const detail = clicked || matched ? "已填入，未发送" : "输入框内容和待发文本不一致，没有点击发送";
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

function yuanbaoLogin(root) {
  const overlay = root.querySelector(".hyc-login__close");
  if (overlay && !overlay.hidden) return true;
  const text = root.body ? root.body.innerText || "" : "";
  if (!/Log In with WeChat|微信登录|请输入手机号/.test(text)) return false;
  return !yuanbaoComposer(root);
}
