// 游客站点适配器：Qwen、ChatGPT、文心、智谱清言、Z.ai。
// 0.5.0 起选择器和站点规则不在代码里，而在 adapters/registry.json（数据，带版本，可从远端更新）。
// 这里把注册表编译成引擎用的规格：选择器列表按顺序回退，规则（has/self/closest/not/all/any）编译成判断函数。
// 五个站的输入框都是普通 textarea，所以共用一套写入、单击、核对和读回逻辑。
const GUEST_DOM_SOURCE = "结构取自 2026-11-15 实页 DOM 导出（dom-dumps），见 adapters/registry.json";

function guestRegistry() {
  return globalThis.ChatclumerAdapters || null;
}

function guestRx(value) {
  return value ? new RegExp(value.source, value.flags || "") : null;
}

function guestCond(cond) {
  if (!cond) return () => false;
  if (cond.has) return (node) => !!node.querySelector(cond.has);
  if (cond.self) return (node) => !!(node.matches && node.matches(cond.self));
  if (cond.not) {
    const inner = guestCond(cond.not);
    return (node) => !inner(node);
  }
  if (cond.all) {
    const list = cond.all.map(guestCond);
    return (node) => list.every((fn) => fn(node));
  }
  if (cond.any) {
    const list = cond.any.map(guestCond);
    return (node) => list.some((fn) => fn(node));
  }
  if (cond.closest) {
    return (node) => {
      const host = node.closest(cond.closest);
      return !!host && host.getAttribute(cond.attr) === cond.equals;
    };
  }
  return () => false;
}

function guestCompileSite(id, raw) {
  const roles = raw.roles || {};
  const join = (key) => (roles[key] ? roles[key].join(", ") : undefined);
  const flags = raw.flags || {};
  const spec = {
    id,
    label: raw.label,
    composerList: roles.composer || [],
    sendList: roles.send || [],
    composer: join("composer"),
    send: join("send"),
    stop: join("stop"),
    users: join("users"),
    userText: join("user_text"),
    assistants: join("assistants"),
    host: join("host"),
    body: join("body"),
    exclude: join("exclude"),
    doneNear: join("done_near"),
    writer: flags.writer || "native",
    guardOther: !!flags.guard_other,
    clickInner: flags.click_inner || undefined,
    clickCenter: !!flags.click_center,
    placeholderText: guestRx(raw.placeholder_text),
    convUrl: guestRx(raw.conv_url),
    gates: (raw.gates || []).map((g) => ({ test: guestRx(g.pattern), where: g.where, detail: g.detail })),
  };
  if (raw.disabled) spec.disabled = guestCond(raw.disabled);
  if (raw.stop_find) {
    const finders = raw.stop_find.map((f) => ({ sel: f.sel, closest: f.closest, attr: f.attr, test: guestRx(f.pattern) }));
    spec.stopFind = (root) => {
      for (const f of finders) {
        let el = root.querySelector(f.sel);
        if (!el) continue;
        if (f.attr && !f.test.test(el.getAttribute(f.attr) || "")) continue;
        if (f.closest) el = el.closest(f.closest);
        if (el) return el;
      }
      return null;
    };
  }
  if (raw.streaming) {
    const rules = raw.streaming.map((r) => ({ when: guestCond(r.when), value: r.value }));
    spec.streamingIn = (node) => {
      for (const rule of rules) if (rule.when(node)) return rule.value;
      return null;
    };
  }
  if (raw.done) spec.doneIn = guestCond(raw.done);
  if (flags.wait_send_enabled) {
    spec.registered = (root) => {
      const el = guestSend(id, root);
      return !!el && !guestDisabled(id, el);
    };
  }
  // 每个选择器都必须能解析，否则整站编译失败、改用内置注册表里的这一站。
  const all = [...Object.values(roles).flat(), spec.clickInner].filter(Boolean);
  for (const sel of all) document.createDocumentFragment().querySelector(sel);
  return spec;
}

const guestCompiled = new WeakMap();

function guestSpec(site) {
  const reg = guestRegistry();
  if (!reg) return null;
  const tryCompile = (raw) => {
    if (!raw || raw.engine !== "guest") return null;
    if (guestCompiled.has(raw)) return guestCompiled.get(raw);
    let spec = null;
    try {
      spec = guestCompileSite(site, raw);
    } catch {
      spec = null;
    }
    guestCompiled.set(raw, spec);
    return spec;
  };
  const bundledRaw = reg.bundled().sites ? reg.bundled().sites[site] : null;
  return tryCompile(reg.site(site)) || tryCompile(bundledRaw);
}

const guestCommonCache = new WeakMap();

// 门槛只在真正打开的弹窗、提示条和验证框里找，不扫回复正文，也不看页头的登录按钮或内嵌的「登录获得更好体验」横幅。
function guestCommon() {
  const reg = guestRegistry();
  const raw = reg ? reg.common() : {};
  if (guestCommonCache.has(raw)) return guestCommonCache.get(raw);
  const out = {
    dialogs: (raw.dialogs || []).join(", ") || "[role='dialog']",
    toasts: (raw.toasts || []).join(", ") || "[role='alert']",
    captchaBoxes: (raw.captcha_boxes || []).join(", ") || "[class*='captcha' i]",
    captcha: guestRx(raw.captcha) || /人机验证/,
    login: guestRx(raw.login) || /请先登录/,
    notLogin: guestRx(raw.not_login) || /$^/,
  };
  guestCommonCache.set(raw, out);
  return out;
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
  // 按注册表顺序回退：第一个能找到 textarea 的选择器为准。
  for (const sel of spec.composerList) {
    const nodes = [...root.querySelectorAll(sel)].filter((el) => el.tagName === "TEXTAREA");
    if (nodes.length) return nodes.find((el) => guestVisible(el)) || nodes[0];
  }
  return null;
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
  for (const sel of spec.sendList) {
    const nodes = [...root.querySelectorAll(sel)];
    if (nodes.length) return nodes.find((el) => guestVisible(el)) || nodes[0];
  }
  return null;
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
  const common = guestCommon();
  const read = (selector) => [...root.querySelectorAll(selector)]
    .filter((el) => guestVisible(el) && !(el.tagName === "DIALOG" && !el.open))
    .map((el) => (el.innerText || el.textContent || "").slice(0, 800));
  const dialogs = read(common.dialogs);
  const toasts = read(common.toasts);
  const heads = read("h1, h2, h3");
  const page = (spec.gates || []).some((gate) => gate.where === "page") ? guestPageTexts(site, root) : [];
  for (const gate of spec.gates || []) {
    const pool = gate.where === "toast" ? toasts.concat(dialogs) : gate.where === "page" ? dialogs.concat(heads, page) : dialogs.concat(heads);
    if (pool.some((text) => gate.test.test(text))) return gate.detail;
  }
  const captcha = dialogs.concat(read(common.captchaBoxes));
  if (captcha.some((text) => common.captcha.test(text))) return `${spec.label} 出现人机验证，需要你在页面上完成后再试，扩展不会代做`;
  if (dialogs.some((text) => common.login.test(text) && !common.notLogin.test(text))) return `${spec.label} 需要登录，请在该标签页登录一次后重试`;
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
