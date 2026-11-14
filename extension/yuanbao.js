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

function yuanbaoSend(root) {
  return yuanbaoControl(root, new Set(["Send", "发送"]));
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
  return (node.innerText || node.value || node.textContent || "").trim();
}

function yuanbaoSendUsable(root) {
  const send = yuanbaoSend(root);
  if (!send || send.disabled || send.getAttribute("aria-disabled") === "true") return null;
  return send;
}

async function yuanbaoDispatchSend(root, prompt, timeoutMs, shouldAbort) {
  if (shouldAbort && shouldAbort()) return { ok: false, detail: "cancelled", clicked: false };
  if (yuanbaoLogin(root)) return { ok: false, detail: "页面停在登录或验证，没有点击发送", clicked: false };
  const composer = yuanbaoComposer(root);
  if (!composer) return { ok: false, detail: "找不到输入框", clicked: false };
  if (yuanbaoComposerText(composer) !== String(prompt || "").trim()) {
    return { ok: false, detail: "输入框内容和待发文本不一致，没有点击发送", clicked: false };
  }
  const before = yuanbaoHumans(root).length;
  const send = yuanbaoSendUsable(root);
  if (send) send.click();
  else {
    composer.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", bubbles: true, cancelable: true }));
  }
  const deadline = Date.now() + (timeoutMs == null ? 10000 : timeoutMs);
  while (Date.now() < deadline) {
    if (shouldAbort && shouldAbort()) return { ok: false, detail: "cancelled", clicked: true };
    if (yuanbaoHumans(root).length > before) return { ok: true, clicked: true };
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  return { ok: false, detail: "已填入，未发送", clicked: true };
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
