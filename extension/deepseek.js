// 结构取自协调方实页 2026-11-15。本文件不是那次桌面验收，不能当成扩展端到端已通过。
const DEEPSEEK_DOM_SOURCE = "结构取自协调方实页 2026-11-15";

const DEEPSEEK_LOGIN_DETAIL = "DeepSeek 需要登录，请在该标签页登录一次后重试";

function deepseekVisible(el) {
  if (!el || el.hidden) return false;
  const view = el.ownerDocument && el.ownerDocument.defaultView;
  const style = view && view.getComputedStyle ? view.getComputedStyle(el) : null;
  if (style && (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0)) return false;
  return el.getClientRects().length > 0;
}

function deepseekNormalize(value) {
  return String(value || "")
    .normalize("NFKC")
    .replace(/[\u200b\u200c\u200d\ufeff]/g, "")
    .replace(/\u00a0/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function deepseekPoints(value) {
  return Array.from(deepseekNormalize(value));
}

function deepseekComposer(root) {
  const nodes = [...root.querySelectorAll("textarea[placeholder='Message DeepSeek']")];
  return nodes.find((el) => deepseekVisible(el)) || nodes[0] || null;
}

function deepseekSendScope(root) {
  return root.querySelector(".bf38813a") || null;
}

function deepseekSend(root) {
  const scope = deepseekSendScope(root);
  if (!scope) return null;
  const nodes = [...scope.querySelectorAll("div[role='button'].ds-button--circle")].filter((el) => {
    return !el.classList.contains("ds-button--capsule") && !el.closest(".ds-toggle-button");
  });
  return nodes[nodes.length - 1] || null;
}

function deepseekInStopState(el) {
  if (!el) return false;
  const label = `${el.getAttribute("aria-label") || ""}`;
  if (/stop|停止/i.test(label)) return true;
  if ([...el.classList].some((name) => /stop|loading|streaming/i.test(name))) return true;
  const icon = el.querySelector("svg");
  const iconClass = icon && typeof icon.getAttribute("class") === "string" ? icon.getAttribute("class") : "";
  return /stop|pause/i.test(iconClass);
}

function deepseekSendBlocked(el) {
  if (!el || !deepseekVisible(el) || deepseekInStopState(el)) return true;
  return el.classList.contains("ds-button--disabled") || el.getAttribute("aria-disabled") === "true";
}

function deepseekSendUsable(root) {
  const send = deepseekSend(root);
  if (!send || deepseekSendBlocked(send)) return null;
  return send;
}

function deepseekSendIdle(root) {
  const send = deepseekSend(root);
  return !(send && deepseekInStopState(send));
}

function deepseekPress(el) {
  const view = el.ownerDocument.defaultView || window;
  const init = { bubbles: true, cancelable: true, view };
  for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
    const Ctor = type.startsWith("pointer") && typeof view.PointerEvent === "function" ? view.PointerEvent : view.MouseEvent;
    el.dispatchEvent(new Ctor(type, init));
  }
}

function deepseekSetValue(composer, value) {
  const proto = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value");
  if (proto && proto.set) proto.set.call(composer, value);
  else composer.value = value;
  composer.dispatchEvent(new Event("input", { bubbles: true }));
}

function deepseekComposerText(node) {
  if (!node) return "";
  return deepseekNormalize(node.value || "");
}

function deepseekClearComposer(composer) {
  if (!composer) return;
  composer.focus();
  deepseekSetValue(composer, "");
}

function deepseekOnlyLoose(value) {
  return /^[\s\p{P}\p{S}]*$/u.test(String(value || ""));
}

function deepseekClose(expected, actual) {
  const left = deepseekPoints(expected);
  const right = deepseekPoints(actual);
  if (!left.length || !right.length) return false;
  let index = 0;
  const shared = Math.min(left.length, right.length);
  while (index < shared && left[index] === right[index]) index += 1;
  if (index / left.length < 0.95) return false;
  return deepseekOnlyLoose(left.slice(index).join("")) && deepseekOnlyLoose(right.slice(index).join(""));
}

function deepseekMatchState(composer, prompt) {
  const expected = deepseekNormalize(prompt);
  const actual = deepseekComposerText(composer);
  if (actual === expected || deepseekClose(expected, actual)) return "match";
  const compact = (value) => value.replace(/\s/g, "");
  if (expected && compact(actual) === compact(expected) + compact(expected)) return "duplicate";
  return "mismatch";
}

function deepseekDiffHint(expected, actual) {
  const left = deepseekPoints(expected);
  const right = deepseekPoints(actual);
  let index = 0;
  const shared = Math.min(left.length, right.length);
  while (index < shared && left[index] === right[index]) index += 1;
  const sample = (chars) => chars.slice(Math.max(0, index - 4), Math.max(0, index - 4) + 10).join("");
  return `第 ${index} 字不同，待发「${sample(left)}」，实际「${sample(right)}」`;
}

function deepseekDiagnosis(composer, prompt) {
  const expected = deepseekNormalize(prompt);
  const actual = deepseekComposerText(composer);
  const duplicate = deepseekMatchState(composer, prompt) === "duplicate";
  const lengths = `待发长度 ${deepseekPoints(expected).length}，实际长度 ${deepseekPoints(actual).length}，${duplicate ? "重复" : "不重复"}`;
  if (deepseekMatchState(composer, prompt) === "match") return lengths;
  return `${lengths}，${deepseekDiffHint(expected, actual)}`;
}

async function deepseekSettle(composer, prompt, shouldAbort) {
  const deadline = Date.now() + 1500;
  while (true) {
    if (shouldAbort && shouldAbort()) return "cancelled";
    const state = deepseekMatchState(composer, prompt);
    if (state === "match" || state === "duplicate") return state;
    if (Date.now() >= deadline) return state;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
}

async function deepseekCommitPrompt(root, prompt, shouldAbort) {
  const composer = deepseekComposer(root);
  if (!composer) return { ok: false, detail: "找不到输入框" };
  const text = String(prompt || "");
  deepseekClearComposer(composer);
  deepseekSetValue(composer, text);
  const state = await deepseekSettle(composer, text, shouldAbort);
  if (state === "match") return { ok: true };
  if (state === "cancelled") return { ok: false, detail: "cancelled" };
  deepseekClearComposer(composer);
  return { ok: false, detail: deepseekDiagnosis(composer, text) };
}

function deepseekUsers(root) {
  return [...root.querySelectorAll(".ds-message")].filter((node) => {
    return node.querySelector(".ds-collapsible-text") && !node.querySelector(".ds-assistant-message-main-content");
  });
}

function deepseekAssistants(root) {
  return [...root.querySelectorAll(".ds-message")].filter((node) => node.querySelector(".ds-assistant-message-main-content"));
}

function deepseekUserMatches(node, prompt) {
  const expected = deepseekNormalize(prompt).slice(0, 40);
  if (!expected) return false;
  const text = deepseekNormalize(node.innerText || node.textContent || "");
  return text.includes(expected);
}

async function deepseekDispatchSend(root, prompt, timeoutMs, shouldAbort) {
  const deadline = Date.now() + (timeoutMs == null ? 10000 : timeoutMs);
  if (shouldAbort && shouldAbort()) return { ok: false, detail: "cancelled", clicked: false };
  if (deepseekLogin(root)) return { ok: false, detail: deepseekLoginDetail(), clicked: false };
  const composer = deepseekComposer(root);
  if (!composer) return { ok: false, detail: "找不到输入框", clicked: false };
  const committed = await deepseekCommitPrompt(root, prompt, shouldAbort);
  if (!committed.ok) {
    const failed = deepseekComposer(root) || composer;
    if (committed.detail !== "cancelled" && failed) deepseekClearComposer(failed);
    const detail = committed.detail === "cancelled" || committed.detail === "找不到输入框"
      ? committed.detail
      : `输入框内容和待发文本不一致，没有点击发送。${committed.detail}`;
    return { ok: false, detail, clicked: false };
  }
  const startPath = ((root.defaultView && root.defaultView.location) || location).pathname || "";
  let clicked = false;
  while (Date.now() < deadline) {
    if (shouldAbort && shouldAbort()) {
      const live = deepseekComposer(root);
      if (!clicked && live) deepseekClearComposer(live);
      return { ok: false, detail: "cancelled", clicked };
    }
    const live = deepseekComposer(root);
    const ready = !!(live && deepseekMatchState(live, prompt) === "match");
    if (!clicked) {
      const send = deepseekSendUsable(root);
      if (ready && send) {
        deepseekPress(send);
        clicked = true;
      }
    } else if (deepseekConfirmed(root, prompt, startPath)) {
      return { ok: true, clicked: true };
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  const live = deepseekComposer(root) || composer;
  const note = deepseekDiagnosis(live, prompt);
  const matched = deepseekMatchState(live, prompt) === "match";
  const detail = clicked || matched
    ? `已填入，未发送。${note}`
    : `输入框内容和待发文本不一致，没有点击发送。${note}`;
  if (live) deepseekClearComposer(live);
  return { ok: false, detail, clicked };
}

function deepseekConfirmed(root, prompt, startPath) {
  const live = deepseekComposer(root);
  const cleared = !live || deepseekComposerText(live) === "";
  const path = ((root.defaultView && root.defaultView.location) || location).pathname || "";
  const moved = path.includes("/a/chat/s/") && path !== startPath;
  const found = deepseekUsers(root).some((node) => deepseekUserMatches(node, prompt));
  return cleared && (moved || found);
}

function deepseekShown(value) {
  return String(value || "").replace(/[\u200b\u200c\u200d\ufeff]/g, "").replace(/\u00a0/g, " ").trim();
}

function deepseekText(node) {
  if (!node) return "";
  const main = node.querySelector(".ds-assistant-message-main-content");
  if (!main) return "";
  const clone = main.cloneNode(true);
  clone.querySelectorAll("[data-citation-group], .ds-markdown-cite").forEach((el) => el.remove());
  return deepseekShown(clone.innerText || clone.textContent || "");
}

const DEEPSEEK_ACTION = "div[role='button'].ds-button--iconLabelTertiary";

function deepseekHoldsMessage(el) {
  return !!(el && (el.matches(".ds-message") || el.querySelector(".ds-message")));
}

// 0.3.1 只在 .ds-message 里面找操作栏。实页的复制/重新生成栏在消息外面（同一个虚拟列表项或紧随其后），
// 所以完成永远判不出来，只能等满 90 秒再按「可能未完整」读回。这里里外都找，遇到下一条消息就停。
function deepseekActionBar(node) {
  if (!node) return false;
  if (node.querySelector(DEEPSEEK_ACTION)) return true;
  const item = node.closest("[data-virtual-list-item-key]");
  const scopes = item && item !== node ? [node, item] : [node];
  for (const scope of scopes) {
    let sib = scope.nextElementSibling;
    while (sib && !deepseekHoldsMessage(sib)) {
      if (sib.matches(DEEPSEEK_ACTION) || sib.querySelector(DEEPSEEK_ACTION)) return true;
      sib = sib.nextElementSibling;
    }
  }
  if (item && item !== node && item.querySelectorAll(".ds-message").length === 1 && item.querySelector(DEEPSEEK_ACTION)) return true;
  return false;
}

function deepseekDone(node) {
  if (!node || !deepseekText(node)) return false;
  return deepseekActionBar(node);
}

// true：正在生成（明确的停止标记，或输入框为空而圆形按钮却可点，那就是停止键）。
// false：发送键回到空框时的禁用态。null：判断不了（找不到按钮，或用户自己在框里打字）。
function deepseekStreaming(root) {
  const send = deepseekSend(root);
  if (!send) return null;
  if (deepseekInStopState(send)) return true;
  if (send.classList.contains("ds-button--disabled") || send.getAttribute("aria-disabled") === "true") return false;
  const composer = deepseekComposer(root);
  if (!composer || deepseekComposerText(composer) === "") return true;
  return null;
}

// 停止时要点的按钮。名字或图标写着停止就点；只靠「空框却可点」推断时，还要求最后一条消息是 AI 的，
// 避免清空输入框后 React 还没重绘时误点发送。
function deepseekStopTarget(root) {
  const send = deepseekSend(root);
  if (!send) return null;
  if (deepseekInStopState(send)) return send;
  if (deepseekStreaming(root) !== true) return null;
  const messages = [...root.querySelectorAll(".ds-message")];
  const tail = messages[messages.length - 1];
  if (!tail || deepseekUsers(root).includes(tail)) return null;
  return send;
}

function deepseekNewReply(root, prompt) {
  const messages = [...root.querySelectorAll(".ds-message")];
  const users = new Set(deepseekUsers(root));
  let mine = -1;
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if (users.has(messages[i]) && deepseekUserMatches(messages[i], prompt)) {
      mine = i;
      break;
    }
  }
  if (mine < 0) return null;
  for (let i = mine + 1; i < messages.length; i += 1) {
    if (users.has(messages[i])) break;
    if (messages[i].querySelector(".ds-assistant-message-main-content")) return messages[i];
  }
  return null;
}

function deepseekPartial(node) {
  const text = deepseekText(node);
  if (!text) return "";
  return `${text}（可能未完整）`;
}

function deepseekTimeoutNote(root, beforeCount) {
  const items = deepseekAssistants(root);
  const send = deepseekSend(root);
  const klass = send ? [...send.classList].join(" ").slice(0, 80) : "";
  const streaming = deepseekStreaming(root);
  return `超时。AI ${beforeCount}→${items.length}，生成中 ${streaming === null ? "未知" : streaming ? "是" : "否"}，发送 class ${klass}`;
}

function deepseekLoginDetail() {
  return DEEPSEEK_LOGIN_DETAIL;
}

function deepseekLogin(root) {
  const loc = (root && root.location) || (root && root.defaultView && root.defaultView.location) || location;
  if (String(loc.pathname || "").includes("/sign_in")) return true;
  return [...root.querySelectorAll("input")].some((el) => {
    if (!deepseekVisible(el)) return false;
    const hint = `${el.getAttribute("placeholder") || ""} ${el.getAttribute("name") || ""} ${el.getAttribute("aria-label") || ""} ${el.type || ""}`;
    return /phone number|email address|password|手机|邮箱|密码/i.test(hint);
  });
}
