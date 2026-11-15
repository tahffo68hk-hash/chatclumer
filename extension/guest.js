// 游客站点适配器：Qwen、ChatGPT、文心、智谱清言、Z.ai。
// 结构取自协调方游客实页 2026-11-15（见 docs/WEB_ACCESS.md）。本文件不是那次桌面验收，不能当成扩展端到端已通过。
// 五个站的输入框都是普通 textarea，所以共用一套写入、单击、核对和读回逻辑，只是选择器不同。
const GUEST_DOM_SOURCE = "结构取自协调方游客实页 2026-11-15";

const GUEST_CAPTCHA = /drag the slider|slide to verify|向右滑动|拖动滑块|滑动完成验证|verify you are human|人机验证|安全验证|captcha/i;
const GUEST_LOGIN = /log ?in|sign ?up|sign ?in|登录|注册/i;
const GUEST_MODALS = "[role='dialog'], [aria-modal='true'], [class*='modal' i], [class*='dialog' i], [class*='captcha' i], [id*='captcha' i]";

const GUEST_SITES = {
  qwen: {
    label: "Qwen",
    composer: "textarea.message-input-textarea, textarea[placeholder='Ask Qwen']",
    send: "button.send-button[aria-label='Send'], .chat-prompt-send-button button.send-button",
    stop: "button.stop-button, button[aria-label='Stop'][data-aes-exp='expInputStop']",
    users: ".qwen-chat-message-user",
    assistants: ".qwen-chat-message-assistant",
    body: ".response-message-content.phase-answer",
    exclude: "[class*='thinking']",
    doneNear: ".response-message-footer button[aria-label='Copy'], button[class*='action-control-container-copy']",
    gates: [{ test: /confirm your age|确认.{0,6}年龄|年龄确认/i, detail: "需要先在页面上完成确认（Qwen 年龄确认），扩展不会替你点" }],
  },
  chatgpt: {
    label: "ChatGPT",
    composer: "textarea#mobile-composer-prompt, textarea[name='prompt'][data-mobile-composer-prompt], #prompt-textarea",
    sendFind: (root) => {
      const icon = [...root.querySelectorAll("button use")].find((use) => /lightweight-composer-send|composer-send/.test(use.getAttribute("href") || use.getAttribute("xlink:href") || ""));
      if (icon) return icon.closest("button");
      return root.querySelector("button[data-testid='send-button']")
        || [...root.querySelectorAll("[data-composer-layout] button[data-variant='primary']")].find((el) => !el.hasAttribute("data-send-dictation"))
        || null;
    },
    stopFind: (root) => {
      const icon = [...root.querySelectorAll("button use")].find((use) => /composer-stop/.test(use.getAttribute("href") || use.getAttribute("xlink:href") || ""));
      return (icon && icon.closest("button")) || root.querySelector("button[data-testid='stop-button'], button[aria-label='Stop streaming']");
    },
    users: "li[data-message-role='user'], [data-message-author-role='user']",
    assistants: "li[data-message-role='assistant'], [data-message-author-role='assistant']",
    body: "[data-assistant-markdown-root], .markdown",
    streamingIn: (node) => {
      if (node.querySelector("[aria-busy='true']")) return true;
      if (node.hasAttribute("data-message-complete")) return false;
      return null;
    },
    doneIn: (node) => node.hasAttribute("data-message-complete") && !node.querySelector("[aria-busy='true']"),
  },
  wenxin: {
    label: "文心",
    composer: "textarea#chat-textarea, #ci-area textarea.ci-textarea",
    send: "span.ci-submit-button",
    disabled: (el) => !el.querySelector(".ci-submit-button-ai-active"),
    users: ".cs-question-bubble",
    assistants: ".ai-entry-block.ai-markdown",
    body: ".cosd-markdown-content, .marklang",
    placeholderText: /^正在思考/,
    scope: ".chat-qa-container",
    doneNear: "[data-testid='menu-btn-copy']",
  },
  zhipu: {
    label: "智谱清言",
    composer: ".input-box-inner textarea, .input-wrap textarea",
    send: "div.enter.is-main-chat, .input-box div.enter",
    users: ".conversation.question",
    assistants: ".conversation.answer",
    body: ".answer-content-wrap .markdown-body",
    exclude: ".text-advance-thinking-content, .advance-thinking",
    scope: ".conversation-item",
    doneNear: ".interact-container .copy, .interact-container .regenerate",
  },
  zai: {
    label: "Z.ai",
    composer: "textarea#chat-input, textarea[placeholder='Send a Message']",
    send: "button#send-message-button, button[aria-label='Send Message']",
    stop: "button[aria-label='Stop'], button[aria-label='Stop generating']",
    emptyEnabledIsStop: true,
    users: ".user-message",
    assistants: ".chat-assistant",
    host: "div[id^='message-']",
    body: ".chat-markdown",
    exclude: ".thinking-chain-container",
    doneNear: "button[aria-label='Copy'], button[aria-label='Regenerate']",
  },
};

function guestSpec(site) {
  return GUEST_SITES[site] || null;
}

function guestVisible(el) {
  if (!el || el.hidden) return false;
  const view = el.ownerDocument && el.ownerDocument.defaultView;
  const style = view && view.getComputedStyle ? view.getComputedStyle(el) : null;
  if (style && (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0)) return false;
  return el.getClientRects().length > 0;
}

function guestNormalize(value) {
  return String(value || "")
    .normalize("NFKC")
    .replace(/[\u200b\u200c\u200d\ufeff]/g, "")
    .replace(/\u00a0/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function guestPoints(value) {
  return Array.from(guestNormalize(value));
}

function guestComposer(site, root) {
  const spec = guestSpec(site);
  if (!spec) return null;
  const nodes = [...root.querySelectorAll(spec.composer)].filter((el) => el.tagName === "TEXTAREA");
  return nodes.find((el) => guestVisible(el)) || nodes[0] || null;
}

function guestComposerText(node) {
  return node ? guestNormalize(node.value || "") : "";
}

function guestSetValue(composer, value) {
  const view = composer.ownerDocument.defaultView || window;
  const proto = Object.getOwnPropertyDescriptor(view.HTMLTextAreaElement.prototype, "value");
  if (proto && proto.set) proto.set.call(composer, value);
  else composer.value = value;
  composer.dispatchEvent(new Event("input", { bubbles: true }));
}

function guestClearComposer(composer) {
  if (!composer) return;
  composer.focus();
  guestSetValue(composer, "");
}

function guestSend(site, root) {
  const spec = guestSpec(site);
  if (!spec) return null;
  if (spec.sendFind) return spec.sendFind(root);
  const nodes = [...root.querySelectorAll(spec.send)];
  return nodes.find((el) => guestVisible(el)) || nodes[0] || null;
}

function guestStop(site, root) {
  const spec = guestSpec(site);
  if (!spec) return null;
  const el = spec.stopFind ? spec.stopFind(root) : (spec.stop ? root.querySelector(spec.stop) : null);
  return el && guestVisible(el) ? el : null;
}

function guestDisabled(site, el) {
  const spec = guestSpec(site);
  if (!el) return true;
  if (spec && spec.disabled && spec.disabled(el)) return true;
  if (el.disabled || el.hasAttribute("disabled")) return true;
  if (el.getAttribute("aria-disabled") === "true" || el.getAttribute("data-disabled") === "true") return true;
  return [...el.classList].some((name) => /(^|-)disabled?$|^is-disabled$/i.test(name));
}

function guestSendUsable(site, root) {
  if (guestStop(site, root)) return null;
  const send = guestSend(site, root);
  if (!send || !guestVisible(send) || guestDisabled(site, send)) return null;
  const label = `${send.getAttribute("aria-label") || ""} ${send.innerText || ""}`;
  if (/stop|停止|升级|订阅|付费|upgrade|subscribe/i.test(label)) return null;
  return send;
}

function guestPress(el) {
  const view = el.ownerDocument.defaultView || window;
  const init = { bubbles: true, cancelable: true, view };
  for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
    const Ctor = type.startsWith("pointer") && typeof view.PointerEvent === "function" ? view.PointerEvent : view.MouseEvent;
    el.dispatchEvent(new Ctor(type, init));
  }
}

function guestOnlyLoose(value) {
  return /^[\s\p{P}\p{S}]*$/u.test(String(value || ""));
}

function guestClose(expected, actual) {
  const left = guestPoints(expected);
  const right = guestPoints(actual);
  if (!left.length || !right.length) return false;
  let index = 0;
  const shared = Math.min(left.length, right.length);
  while (index < shared && left[index] === right[index]) index += 1;
  if (index / left.length < 0.95) return false;
  return guestOnlyLoose(left.slice(index).join("")) && guestOnlyLoose(right.slice(index).join(""));
}

function guestMatchState(composer, prompt) {
  const expected = guestNormalize(prompt);
  const actual = guestComposerText(composer);
  if (actual === expected || guestClose(expected, actual)) return "match";
  const compact = (value) => value.replace(/\s/g, "");
  if (expected && compact(actual) === compact(expected) + compact(expected)) return "duplicate";
  return "mismatch";
}

function guestDiagnosis(composer, prompt) {
  const left = guestPoints(prompt);
  const right = guestPoints(guestComposerText(composer));
  const state = guestMatchState(composer, prompt);
  const lengths = `待发长度 ${left.length}，实际长度 ${right.length}，${state === "duplicate" ? "重复" : "不重复"}`;
  if (state === "match") return lengths;
  let index = 0;
  const shared = Math.min(left.length, right.length);
  while (index < shared && left[index] === right[index]) index += 1;
  const sample = (chars) => chars.slice(Math.max(0, index - 4), Math.max(0, index - 4) + 10).join("");
  return `${lengths}，第 ${index} 字不同，待发「${sample(left)}」，实际「${sample(right)}」`;
}

async function guestCommitPrompt(site, root, prompt, shouldAbort) {
  const composer = guestComposer(site, root);
  if (!composer) return { ok: false, detail: "找不到输入框" };
  const text = String(prompt || "");
  guestClearComposer(composer);
  guestSetValue(composer, text);
  const deadline = Date.now() + 1500;
  while (true) {
    if (shouldAbort && shouldAbort()) return { ok: false, detail: "cancelled" };
    const live = guestComposer(site, root) || composer;
    const state = guestMatchState(live, text);
    if (state === "match") return { ok: true };
    if (state === "duplicate" || Date.now() >= deadline) {
      const detail = guestDiagnosis(live, text);
      guestClearComposer(live);
      return { ok: false, detail };
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
}

// 页面上的门槛：站点自己的确认框、人机验证、登录或注册卡片。只看弹窗类容器和标题，不扫回复正文。
function guestGate(site, root) {
  const spec = guestSpec(site);
  if (!spec) return null;
  const containers = [...root.querySelectorAll(`${GUEST_MODALS}, h1, h2, h3`)].filter((el) => guestVisible(el));
  const texts = containers.map((el) => (el.innerText || el.textContent || "").slice(0, 600));
  for (const gate of spec.gates || []) {
    if (texts.some((text) => gate.test.test(text))) return gate.detail;
  }
  const modalTexts = containers.filter((el) => el.matches(GUEST_MODALS)).map((el) => (el.innerText || el.textContent || "").slice(0, 600));
  if (modalTexts.some((text) => GUEST_CAPTCHA.test(text))) return `${spec.label} 出现人机验证，需要你在页面上完成后再试，扩展不会代做`;
  if (modalTexts.some((text) => GUEST_LOGIN.test(text))) return `${spec.label} 需要登录，请在该标签页登录一次后重试`;
  const loc = (root && root.defaultView && root.defaultView.location) || (typeof location !== "undefined" ? location : null);
  if (loc && /\/auth\/|\/login|\/sign_?in/i.test(loc.pathname || "")) return `${spec.label} 需要登录，请在该标签页登录一次后重试`;
  return null;
}

function guestHost(site, el) {
  const spec = guestSpec(site);
  return (spec && spec.host && el.closest(spec.host)) || el;
}

function guestUsers(site, root) {
  const spec = guestSpec(site);
  return spec ? [...root.querySelectorAll(spec.users)] : [];
}

function guestAssistants(site, root) {
  const spec = guestSpec(site);
  return spec ? [...root.querySelectorAll(spec.assistants)].map((el) => guestHost(site, el)) : [];
}

function guestUserMatches(node, prompt) {
  const expected = guestNormalize(prompt).slice(0, 40);
  if (!expected) return false;
  return guestNormalize(node.innerText || node.textContent || "").includes(expected);
}

// 最后一条和 prompt 相符的用户消息之后、下一条用户消息之前的第一条助手消息。
function guestNewReply(site, root, prompt) {
  const spec = guestSpec(site);
  if (!spec) return null;
  const all = [...root.querySelectorAll(`${spec.users}, ${spec.assistants}`)];
  const isUser = (el) => el.matches(spec.users);
  let mine = -1;
  for (let i = all.length - 1; i >= 0; i -= 1) {
    if (isUser(all[i]) && guestUserMatches(all[i], prompt)) {
      mine = i;
      break;
    }
  }
  if (mine < 0) return null;
  for (let i = mine + 1; i < all.length; i += 1) {
    if (isUser(all[i])) break;
    return guestHost(site, all[i]);
  }
  return null;
}

function guestShown(value) {
  return String(value || "").replace(/[\u200b\u200c\u200d\ufeff]/g, "").replace(/\u00a0/g, " ").trim();
}

function guestText(site, node) {
  const spec = guestSpec(site);
  if (!spec || !node) return "";
  let bodies = [...node.querySelectorAll(spec.body)];
  if (spec.exclude) bodies = bodies.filter((el) => !el.closest(spec.exclude));
  bodies = bodies.filter((el) => !bodies.some((other) => other !== el && other.contains(el)));
  const strip = `button, [data-citation-group], sup.citation${spec.exclude ? `, ${spec.exclude}` : ""}`;
  const text = guestShown(bodies.map((el) => {
    if (!el.querySelector(strip)) return el.innerText || el.textContent || "";
    const clone = el.cloneNode(true);
    clone.querySelectorAll(strip).forEach((part) => part.remove());
    return clone.innerText || clone.textContent || "";
  }).join("\n"));
  if (spec.placeholderText && spec.placeholderText.test(text)) return "";
  return text;
}

function guestHoldsMessage(site, el) {
  const spec = guestSpec(site);
  const sel = `${spec.users}, ${spec.assistants}`;
  return !!(el && (el.matches(sel) || el.querySelector(sel)));
}

// 完成标记可能在消息里面、同一外框里，或紧跟在消息后面（遇到下一条消息就停）。
function guestNear(site, node, selector) {
  if (!node || !selector) return false;
  if (node.querySelector(selector)) return true;
  const spec = guestSpec(site);
  const scope = spec.scope && node.closest(spec.scope);
  if (scope && scope !== node && scope.querySelectorAll(spec.assistants).length <= 1 && scope.querySelector(selector)) return true;
  let sib = node.nextElementSibling;
  while (sib && !guestHoldsMessage(site, sib)) {
    if (sib.matches(selector) || sib.querySelector(selector)) return true;
    sib = sib.nextElementSibling;
  }
  return false;
}

function guestDone(site, node) {
  const spec = guestSpec(site);
  if (!spec || !node || !guestText(site, node)) return false;
  if (spec.doneIn) return spec.doneIn(node);
  return guestNear(site, node, spec.doneNear);
}

// true 正在生成，false 确认结束，null 判断不了。
function guestStreaming(site, root, node) {
  const spec = guestSpec(site);
  if (!spec) return null;
  if (guestStop(site, root)) return true;
  if (node && spec.streamingIn) {
    const inner = spec.streamingIn(node);
    if (inner !== null) return inner;
  }
  const send = guestSend(site, root);
  if (!send) return null;
  const composer = guestComposer(site, root);
  const empty = !composer || guestComposerText(composer) === "";
  if (!empty) return null;
  if (guestDisabled(site, send)) return spec.stop || spec.stopFind || spec.emptyEnabledIsStop ? false : null;
  return spec.emptyEnabledIsStop ? true : null;
}

function guestConfirmed(site, root, prompt, before, startPath) {
  const live = guestComposer(site, root);
  const cleared = !live || guestComposerText(live) === "";
  const users = guestUsers(site, root);
  const found = users.length > before && users.slice(before).some((node) => guestUserMatches(node, prompt));
  const path = ((root.defaultView && root.defaultView.location) || location).pathname || "";
  return cleared && (found || path !== startPath);
}

async function guestDispatchSend(site, root, prompt, timeoutMs, shouldAbort) {
  const deadline = Date.now() + (timeoutMs == null ? 10000 : timeoutMs);
  if (!guestSpec(site)) return { ok: false, detail: "没有这个站点的适配器", clicked: false };
  if (shouldAbort && shouldAbort()) return { ok: false, detail: "cancelled", clicked: false };
  const gate = guestGate(site, root);
  if (gate) return { ok: false, detail: gate, clicked: false, gate: true };
  if (!guestComposer(site, root)) return { ok: false, detail: "找不到输入框", clicked: false };
  if (guestStreaming(site, root, null) === true) return { ok: false, detail: "页面上一条还在生成，没有写入", clicked: false };
  const committed = await guestCommitPrompt(site, root, prompt, shouldAbort);
  if (!committed.ok) {
    const detail = committed.detail === "cancelled" || committed.detail === "找不到输入框"
      ? committed.detail
      : `输入框内容和待发文本不一致，没有点击发送。${committed.detail}`;
    return { ok: false, detail, clicked: false };
  }
  const before = guestUsers(site, root).length;
  const startPath = ((root.defaultView && root.defaultView.location) || location).pathname || "";
  let clicked = false;
  while (Date.now() < deadline) {
    const live = guestComposer(site, root);
    if (shouldAbort && shouldAbort()) {
      if (!clicked && live) guestClearComposer(live);
      return { ok: false, detail: "cancelled", clicked };
    }
    const blocked = guestGate(site, root);
    if (blocked) {
      if (live) guestClearComposer(live);
      return { ok: false, detail: blocked, clicked, gate: true };
    }
    if (!clicked) {
      const ready = !!(live && guestMatchState(live, prompt) === "match");
      const send = guestSendUsable(site, root);
      if (ready && send) {
        guestPress(send);
        clicked = true;
      }
    } else if (guestConfirmed(site, root, prompt, before, startPath)) {
      return { ok: true, clicked: true };
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  const live = guestComposer(site, root);
  const note = live ? guestDiagnosis(live, prompt) : "输入框已不在";
  const matched = !!(live && guestMatchState(live, prompt) === "match");
  const detail = clicked || matched
    ? `已填入，未发送。${note}`
    : `输入框内容和待发文本不一致，没有点击发送。${note}`;
  if (live) guestClearComposer(live);
  return { ok: false, detail, clicked };
}

function guestPartial(site, node) {
  const text = guestText(site, node);
  return text ? `${text}（可能未完整）` : "";
}

function guestTimeoutNote(site, root, beforeCount) {
  const streaming = guestStreaming(site, root, null);
  return `超时。AI ${beforeCount}→${guestAssistants(site, root).length}，生成中 ${streaming === null ? "未知" : streaming ? "是" : "否"}`;
}

function guestStopTarget(site, root) {
  return guestStop(site, root);
}
