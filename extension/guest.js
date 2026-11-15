// 游客站点适配器：Qwen、ChatGPT、文心、智谱清言、Z.ai。
// 结构取自协调方游客实页 2026-11-15（见 docs/WEB_ACCESS.md）。本文件不是那次桌面验收，不能当成扩展端到端已通过。
// 五个站的输入框都是普通 textarea，所以共用一套写入、单击、核对和读回逻辑，只是选择器不同。
const GUEST_DOM_SOURCE = "结构取自 2026-11-15 实页 DOM 导出（dom-dumps）";

// 门槛只在真正打开的弹窗、提示条和验证框里找，不扫回复正文，也不看页头的登录按钮或内嵌的「登录获得更好体验」横幅。
const GUEST_DIALOGS = "[role='dialog'], [aria-modal='true'], dialog[open], .ant-modal";
const GUEST_TOASTS = "[role='alert'], [role='status'], .ant-message, .ant-notification, [class*='toast' i], [class*='notice' i]";
const GUEST_CAPTCHA_BOXES = "[class*='captcha' i], [id*='captcha' i], [id^='nc_'], [class*='nc-container'], [class*='verify' i]";
const GUEST_CAPTCHA = /drag the slider|slide to verify|向右滑动|拖动滑块|滑动完成验证|verify you are human|人机验证|安全验证/i;
const GUEST_LOGIN = /log in or sign up|sign up to continue|log in to continue|sign in to continue|登录后(继续|即可|使用)|请先登录|登录以继续|扫码登录|手机号登录|验证码登录|使用.{0,8}账号登录/i;
const GUEST_NOT_LOGIN = /personali[sz]ed|clear current chat/i;

const GUEST_SITES = {
  qwen: {
    label: "Qwen",
    composer: "textarea.message-input-textarea, textarea[placeholder='Ask Qwen']",
    send: "button.send-button[aria-label='Send']",
    stop: "button.stop-button[aria-label='Stop'], button[data-aes-exp='expInputStop']",
    users: ".qwen-chat-message-user",
    userText: "p.user-message-content",
    assistants: ".qwen-chat-message-assistant",
    body: ".response-message-content.phase-answer, .response-message-content .qwen-markdown",
    exclude: "[class*='thinking']",
    streamingIn: (node) => (node.querySelector(".response-loading") ? true : null),
    doneNear: ".response-message-footer button[aria-label='Copy'], button[class*='action-control-container-copy']",
    convUrl: /\/c\/(?!new-chat)[\w-]{8,}/,
    gates: [
      { test: /do not have permission to access this resource|没有权限访问/i, where: "toast", detail: "千问游客发送被拒绝，可能需要登录（页面提示没有权限）。扩展没有重发" },
      { test: /confirm your age|确认.{0,6}年龄|年龄确认/i, where: "dialog", detail: "需要先在页面上完成确认（Qwen 年龄确认），扩展不会替你点" },
    ],
  },
  chatgpt: {
    label: "ChatGPT",
    composer: "textarea#mobile-composer-prompt, textarea[name='prompt'][data-mobile-composer-prompt]",
    send: "button[data-composer-submit]",
    // 同一个按钮在生成时换成停止（data-stop-label="Stop generating"）。
    stopFind: (root) => {
      const el = root.querySelector("button[data-composer-submit]");
      if (el && /stop/i.test(el.getAttribute("aria-label") || "")) return el;
      return root.querySelector("button[data-testid='stop-button'], button[aria-label='Stop generating']");
    },
    users: "li[data-message-role='user']",
    userText: "[data-user-message-copy]",
    assistants: "li[data-message-role='assistant']",
    body: "[data-assistant-markdown-root]",
    streamingIn: (node) => {
      if (node.querySelector("[aria-busy='true']")) return true;
      if (node.hasAttribute("data-message-complete")) return false;
      return null;
    },
    doneIn: (node) => node.hasAttribute("data-message-complete") && !node.querySelector("[aria-busy='true']"),
    convUrl: /\/(c|uc)\/[\w-]{8,}/,
    gates: [
      { test: /sign in to continue|log in to continue/i, where: "page", detail: "ChatGPT 需要登录后才能继续（游客额度可能用完）。扩展没有写入，也不会重试" },
    ],
  },
  wenxin: {
    label: "文心",
    composer: "textarea#chat-textarea",
    send: "span.ci-submit-button",
    // 文心的发送图标在空框时也是 active，没有可靠的「站点已认到文字」标记；点击落在图标上（人点到的就是它）。
    disabled: (el) => !el.querySelector("img#ci-submit-button-ai"),
    writer: "exec",
    guardOther: true,
    clickInner: "img#ci-submit-button-ai",
    stopFind: (root) => {
      const icon = root.querySelector("span.ci-submit-button img.ci-submit-pause");
      return icon ? icon.closest("span.ci-submit-button") : null;
    },
    users: ".cs-question-bubble",
    userText: ".cs-question-pure-text",
    assistants: ".conversation-flow-answer-container",
    body: ".ai-entry-block.ai-markdown .cosd-markdown-content, .ai-entry-block.ai-markdown .marklang",
    placeholderText: /^正在思考/,
    streamingIn: (node) => {
      const pair = node.closest(".chat-qa-container[data-chat-status]");
      const status = pair ? pair.getAttribute("data-chat-status") : "";
      if (status === "GENERATING") return true;
      if (status === "COMPLETE") return false;
      return null;
    },
    doneIn: (node) => {
      const pair = node.closest(".chat-qa-container[data-chat-status]");
      return !!pair && pair.getAttribute("data-chat-status") === "COMPLETE";
    },
    convUrl: /\/search\/\d+/,
  },
  zhipu: {
    label: "智谱清言",
    composer: "#search-input-box textarea, .input-box-inner textarea",
    send: "#search-input-box div.enter.is-main-chat, div.enter.is-main-chat",
    // 空框时 .enter-icon-container 带 empty；站点认到文字后才去掉（实页 DOM 0-empty 与 1-typed 的差别）。
    disabled: (el) => el.classList.contains("searching") || !!el.querySelector(".enter-icon-container.empty"),
    writer: "exec",
    guardOther: true,
    registered: (root) => {
      const el = root.querySelector("#search-input-box div.enter.is-main-chat, div.enter.is-main-chat");
      return !!el && !el.classList.contains("searching") && !el.querySelector(".enter-icon-container.empty");
    },
    clickCenter: true,
    stopFind: (root) => root.querySelector("div.enter.is-main-chat.searching"),
    users: ".conversation.question",
    userText: ".question-txt",
    assistants: ".answer[id^='row-answer-']",
    body: ".answer-content-wrap .markdown-body",
    exclude: ".text-advance-thinking-content, .advance-thinking",
    streamingIn: (node) => {
      if (node.querySelector(".answer-loading")) return true;
      if (node.querySelector(".interact-container .copy, .interact-container .regenerate")) return false;
      return null;
    },
    doneIn: (node) => !node.querySelector(".answer-loading") && !!node.querySelector(".interact-container .copy, .interact-container .regenerate"),
    convUrl: /[?&]cid=/,
  },
  zai: {
    label: "Z.ai",
    composer: "textarea#chat-input",
    send: "button#send-message-button",
    stop: "button[aria-label='Stop'][data-slot='button']",
    users: ".user-message",
    userText: "[data-user-bubble]",
    assistants: ".chat-assistant",
    host: "div[id^='message-']",
    body: ".chat-markdown",
    exclude: ".thinking-chain-container",
    streamingIn: (node) => (node.querySelector("._common-loading") ? true : null),
    doneNear: "button[aria-label='Copy'], button[aria-label='Regenerate']",
    convUrl: /\/c\/[\w-]{8,}/,
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
  // Tailwind 的 disabled:xxx / aria-disabled:xxx 只是样式变体，不代表当前禁用。
  return [...el.classList].some((name) => !name.includes(":") && /(^|-)disabled?$|^is-disabled$/i.test(name));
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

function guestWriteNative(composer, text) {
  composer.focus();
  guestSetValue(composer, text);
}

function guestWriteExec(composer, text) {
  composer.focus();
  if (typeof composer.select === "function") composer.select();
  const doc = composer.ownerDocument || document;
  let done = false;
  try {
    done = doc.execCommand("insertText", false, text);
  } catch {
    done = false;
  }
  return done;
}

function guestWriteComposed(composer, text) {
  composer.focus();
  composer.dispatchEvent(new CompositionEvent("compositionstart", { bubbles: true, data: "" }));
  const view = composer.ownerDocument.defaultView || window;
  const proto = Object.getOwnPropertyDescriptor(view.HTMLTextAreaElement.prototype, "value");
  if (proto && proto.set) proto.set.call(composer, text);
  else composer.value = text;
  composer.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: text }));
  composer.dispatchEvent(new CompositionEvent("compositionend", { bubbles: true, data: text }));
  composer.dispatchEvent(new Event("change", { bubbles: true }));
}

// 写入顺序：已在实页跑通的站（Qwen、Z.ai、ChatGPT）仍先用原生 setter；文心、智谱先用 execCommand('insertText')，
// 它触发的 beforeinput/input 是浏览器自己发的，框架认。每次都先清空、只写一次、再按 NFKC 核对；不一致就清空换下一种。
function guestWriters(site) {
  const spec = guestSpec(site);
  return spec && spec.writer === "exec"
    ? [guestWriteExec, guestWriteComposed]
    : [guestWriteNative, guestWriteExec];
}

async function guestSettle(site, root, composer, text, shouldAbort) {
  const spec = guestSpec(site);
  const deadline = Date.now() + 1500;
  while (true) {
    if (shouldAbort && shouldAbort()) return { state: "cancelled" };
    const live = guestComposer(site, root) || composer;
    const state = guestMatchState(live, text);
    const registered = !spec.registered || spec.registered(root);
    if (state === "match" && registered) return { state: "match", live };
    if (state === "duplicate" || Date.now() >= deadline) {
      return { state: state === "match" ? "unregistered" : state, live };
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
}

async function guestCommitPrompt(site, root, prompt, shouldAbort) {
  const text = String(prompt || "");
  let last = null;
  for (const write of guestWriters(site)) {
    const composer = guestComposer(site, root);
    if (!composer) return { ok: false, detail: "找不到输入框" };
    guestClearComposer(composer);
    write(composer, text);
    const settled = await guestSettle(site, root, composer, text, shouldAbort);
    if (settled.state === "cancelled") return { ok: false, detail: "cancelled" };
    if (settled.state === "match") return { ok: true };
    last = settled;
    if (settled.live) guestClearComposer(settled.live);
  }
  if (last && last.state === "unregistered") {
    return { ok: false, detail: "文字已写进输入框，但站点的发送键一直没有变成可点（站点没认到这次输入）" };
  }
  return { ok: false, detail: guestDiagnosis((last && last.live) || guestComposer(site, root), text) };
}

// 点哪里：文心点发送图标本身；智谱点发送键中心处的元素；其余站点点按钮本身。事件都会冒泡到外层按钮，仍只点一次。
function guestClickTarget(site, send) {
  const spec = guestSpec(site);
  if (spec && spec.clickInner) {
    const inner = send.querySelector(spec.clickInner);
    if (inner) return inner;
  }
  if (spec && spec.clickCenter) {
    const doc = send.ownerDocument || document;
    const rect = send.getBoundingClientRect();
    const hit = rect.width && rect.height ? doc.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2) : null;
    if (hit && send.contains(hit)) return hit;
  }
  return send;
}

// 页面上能看见的短句（卡片、标题、提示），不含聊天消息里的文字。只给声明了 where: "page" 的门槛用。
function guestPageTexts(site, root) {
  const spec = guestSpec(site);
  const doc = root.ownerDocument || root;
  const body = doc.body;
  if (!body) return [];
  const skip = `${spec.users}, ${spec.assistants}, textarea, button`;
  const out = [];
  const walker = doc.createTreeWalker(body, 4);
  let node = walker.nextNode();
  while (node && out.length < 20) {
    const text = (node.nodeValue || "").trim();
    if (text && text.length < 160 && /sign in|log in|登录/i.test(text)) {
      const host = node.parentElement;
      if (host && !host.closest(skip) && guestVisible(host)) out.push(text);
    }
    node = walker.nextNode();
  }
  return out;
}

// 页面上的门槛：站点自己的提示（Qwen 无权限提示、年龄确认）、人机验证、登录或注册弹窗。
function guestGate(site, root) {
  const spec = guestSpec(site);
  if (!spec) return null;
  const read = (selector) => [...root.querySelectorAll(selector)]
    .filter((el) => guestVisible(el) && !(el.tagName === "DIALOG" && !el.open))
    .map((el) => (el.innerText || el.textContent || "").slice(0, 800));
  const dialogs = read(GUEST_DIALOGS);
  const toasts = read(GUEST_TOASTS);
  const heads = read("h1, h2, h3");
  const page = (spec.gates || []).some((gate) => gate.where === "page") ? guestPageTexts(site, root) : [];
  for (const gate of spec.gates || []) {
    const pool = gate.where === "toast" ? toasts.concat(dialogs) : gate.where === "page" ? dialogs.concat(heads, page) : dialogs.concat(heads);
    if (pool.some((text) => gate.test.test(text))) return gate.detail;
  }
  const captcha = dialogs.concat(read(GUEST_CAPTCHA_BOXES));
  if (captcha.some((text) => GUEST_CAPTCHA.test(text))) return `${spec.label} 出现人机验证，需要你在页面上完成后再试，扩展不会代做`;
  if (dialogs.some((text) => GUEST_LOGIN.test(text) && !GUEST_NOT_LOGIN.test(text))) return `${spec.label} 需要登录，请在该标签页登录一次后重试`;
  const loc = (root && root.defaultView && root.defaultView.location) || (typeof location !== "undefined" ? location : null);
  if (loc && /^\/(auth|login|sign_?in)(\/|$)/i.test(loc.pathname || "")) return `${spec.label} 需要登录，请在该标签页登录一次后重试`;
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

function guestUserText(site, node) {
  const spec = guestSpec(site);
  const part = spec && spec.userText ? node.querySelector(spec.userText) : null;
  const el = part || node;
  return guestNormalize(el.innerText || el.textContent || "");
}

function guestUserMatches(node, prompt, site) {
  const expected = guestNormalize(prompt).slice(0, 40);
  if (!expected) return false;
  if (site && guestUserText(site, node).includes(expected)) return true;
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
    if (isUser(all[i]) && guestUserMatches(all[i], prompt, site)) {
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
  if (empty && guestDisabled(site, send) && (spec.stop || spec.stopFind)) return false;
  return null;
}

function guestHref(root) {
  const loc = (root.defaultView && root.defaultView.location) || location;
  return String(loc.href || "");
}

function guestSnapshot(site, root) {
  return {
    users: new Set(guestUsers(site, root)),
    assistants: new Set(guestAssistants(site, root)),
    href: guestHref(root),
  };
}

// 发出去了吗？下面任何一条成立就算：
// 1. 出现了新的、文字与待发内容相符的用户消息（按 NFKC 规范化后比较）；
// 2. 地址换成了这个站的会话地址；
// 3. 点击后输入框被站点清空，并且出现了新的助手消息。
// 明显是另一段话：非空，既不含待发文本开头，也不是待发文本的前缀（防止气泡还在逐字渲染时误判）。
function guestOtherText(text, prompt) {
  const expected = guestNormalize(prompt);
  if (!text || text.length < 4) return false;
  if (text.includes(expected.slice(0, 12))) return false;
  if (expected.startsWith(text)) return false;
  return true;
}

function guestConfirmed(site, root, prompt, before) {
  const spec = guestSpec(site);
  const fresh = guestUsers(site, root).filter((node) => !before.users.has(node));
  if (fresh.some((node) => guestUserMatches(node, prompt, site))) return "user";
  // 页面发出了别的文字（例如文心把输入框里的示例提示当成问题发了出去）。
  if (spec.guardOther && fresh.some((node) => guestOtherText(guestUserText(site, node), prompt))) return "other";
  const href = guestHref(root);
  if (spec.convUrl && href !== before.href && spec.convUrl.test(href) && !spec.convUrl.test(before.href)) return "url";
  const live = guestComposer(site, root);
  const cleared = !live || guestComposerText(live) === "";
  const fresher = guestAssistants(site, root).some((node) => !before.assistants.has(node));
  if (cleared && fresher) return "assistant";
  return "";
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
  const before = guestSnapshot(site, root);
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
        guestPress(guestClickTarget(site, send));
        clicked = true;
      }
    } else {
      const how = guestConfirmed(site, root, prompt, before);
      if (how === "other") {
        const left = guestComposer(site, root);
        if (left) guestClearComposer(left);
        return { ok: false, detail: "页面发出的内容和待发文本不一致（可能发了输入框里的示例提示），已停止，不会再试", clicked: true, gate: true };
      }
      if (how) {
        // 已经发出。站点若没清空输入框，这里清掉，免得之后被误发第二次。
        const left = guestComposer(site, root);
        if (left && guestMatchState(left, prompt) === "match") guestClearComposer(left);
        return { ok: true, clicked: true, how };
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  const live = guestComposer(site, root);
  const note = live ? guestDiagnosis(live, prompt) : "输入框已不在";
  const matched = !!(live && guestMatchState(live, prompt) === "match");
  const idle = !clicked && matched ? "发送键一直不可点。" : "";
  const detail = clicked || matched
    ? `已填入，未发送。${idle}${note}`
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
