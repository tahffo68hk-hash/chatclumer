// 同一页面会被重复注入（绑定标签页、页面检查都会走 executeScript）。整份放在守卫里：
// 同一个活着的扩展实例已经装过就什么都不做——不重置进行中的任务，不重复挂监听，也不会再报「已声明」。
// 扩展重载后旧实例失效（chrome.runtime.id 取不到），或扩展版本变了，才会重新装一遍。
if ((function (key) {
  var done = (globalThis.__chatclumerLoaded = globalThis.__chatclumerLoaded || {});
  var alive = false;
  var ver = "";
  try {
    alive = !!(chrome.runtime && chrome.runtime.id);
    ver = (alive && chrome.runtime.getManifest && chrome.runtime.getManifest().version) || "";
  } catch (e) {
    alive = false;
  }
  // 记下装的是哪个版本：同版本、扩展还活着才跳过；升级后旧版本留下的标记不会挡住新代码。
  if (alive && done[key] && done[key] === (ver || true)) return false;
  done[key] = ver || true;
  return true;
})("doubao")) {
// 结构取自协调方实页 2026-11-15。本文件不是那次桌面验收，不能当成扩展端到端已通过。
var DOUBAO_DOM_SOURCE = "结构取自协调方实页 2026-11-15";

var DOUBAO_LOGIN_DETAIL = "豆包需要登录，请在该标签页登录一次后重试";
var DOUBAO_BAN_DETAIL = "豆包当前网络地区不可用";

function doubaoVisible(el) {
  if (!el || el.hidden || el.classList.contains("hidden")) return false;
  const view = el.ownerDocument && el.ownerDocument.defaultView;
  const style = view && view.getComputedStyle ? view.getComputedStyle(el) : null;
  if (style && (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0)) return false;
  return el.getClientRects().length > 0;
}

function doubaoNormalize(value) {
  return String(value || "")
    .normalize("NFKC")
    .replace(/[\u200b\u200c\u200d\ufeff]/g, "")
    .replace(/\u00a0/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function doubaoPoints(value) {
  return Array.from(doubaoNormalize(value));
}

function doubaoComposer(root) {
  const nodes = [...root.querySelectorAll("[data-testid='chat_input_input'] [contenteditable='true']")];
  return nodes.find((el) => doubaoVisible(el)) || nodes[0] || null;
}

function doubaoRawComposer(node) {
  if (!node) return "";
  const paragraphs = [...node.querySelectorAll("p")];
  if (paragraphs.length) return paragraphs.map((para) => para.innerText || para.textContent || "").join("\n");
  return node.innerText || node.textContent || "";
}

function doubaoComposerText(node) {
  return doubaoNormalize(doubaoRawComposer(node));
}

function doubaoSend(root) {
  return root.querySelector("button[data-testid='chat_input_send_button']");
}

function doubaoStop(root) {
  const el = root.querySelector("[data-testid='chat_input_local_break_button']");
  if (!el || !doubaoVisible(el)) return null;
  return el;
}

function doubaoSendBlocked(el) {
  if (!el || !doubaoVisible(el) || el.disabled) return true;
  if (el.getAttribute("aria-disabled") === "true") return true;
  if (el.getAttribute("data-disabled") === "true") return true;
  if (el.getAttribute("data-loading") === "true") return true;
  return false;
}

function doubaoSendUsable(root) {
  const send = doubaoSend(root);
  if (!send || doubaoSendBlocked(send)) return null;
  return send;
}

function doubaoSendIdle(root) {
  return !doubaoStop(root);
}

function doubaoPress(el) {
  const view = el.ownerDocument.defaultView || window;
  const init = { bubbles: true, cancelable: true, view };
  for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
    const Ctor = type.startsWith("pointer") && typeof view.PointerEvent === "function" ? view.PointerEvent : view.MouseEvent;
    el.dispatchEvent(new Ctor(type, init));
  }
}

function doubaoPlaceCaret(composer) {
  composer.focus();
  const selection = window.getSelection();
  const range = document.createRange();
  range.selectNodeContents(composer);
  range.collapse(false);
  selection.removeAllRanges();
  selection.addRange(range);
}

function doubaoClearComposer(composer) {
  if (!composer) return;
  composer.focus();
  try {
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(composer);
    selection.removeAllRanges();
    selection.addRange(range);
    document.execCommand("selectAll", false, null);
    document.execCommand("delete", false, null);
  } catch {
    /* 选择或删除失败时仍清掉可见文字 */
  }
  composer.dispatchEvent(new InputEvent("beforeinput", { bubbles: true, cancelable: true, inputType: "deleteContentBackward" }));
  composer.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "deleteContentBackward" }));
  if (doubaoComposerText(composer)) {
    composer.innerHTML = "<p class='is-empty'><br></p>";
    composer.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "deleteContentBackward" }));
  }
}

function doubaoOnlyLoose(value) {
  return /^[\s\p{P}\p{S}]*$/u.test(String(value || ""));
}

function doubaoClose(expected, actual) {
  const left = doubaoPoints(expected);
  const right = doubaoPoints(actual);
  if (!left.length || !right.length) return false;
  let index = 0;
  const shared = Math.min(left.length, right.length);
  while (index < shared && left[index] === right[index]) index += 1;
  if (index / left.length < 0.95) return false;
  return doubaoOnlyLoose(left.slice(index).join("")) && doubaoOnlyLoose(right.slice(index).join(""));
}

function doubaoMatchState(composer, prompt) {
  const expected = doubaoNormalize(prompt);
  const actual = doubaoComposerText(composer);
  if (actual === expected || doubaoClose(expected, actual)) return "match";
  const compact = (value) => value.replace(/\s/g, "");
  if (expected && compact(actual) === compact(expected) + compact(expected)) return "duplicate";
  return "mismatch";
}

function doubaoDiffHint(expected, actual) {
  const left = doubaoPoints(expected);
  const right = doubaoPoints(actual);
  let index = 0;
  const shared = Math.min(left.length, right.length);
  while (index < shared && left[index] === right[index]) index += 1;
  const sample = (chars) => chars.slice(Math.max(0, index - 4), Math.max(0, index - 4) + 10).join("");
  return `第 ${index} 字不同，待发「${sample(left)}」，实际「${sample(right)}」`;
}

function doubaoDiagnosis(composer, prompt) {
  const expected = doubaoNormalize(prompt);
  const actual = doubaoComposerText(composer);
  const duplicate = doubaoMatchState(composer, prompt) === "duplicate";
  const lengths = `待发长度 ${doubaoPoints(expected).length}，实际长度 ${doubaoPoints(actual).length}，${duplicate ? "重复" : "不重复"}`;
  if (doubaoMatchState(composer, prompt) === "match") return lengths;
  return `${lengths}，${doubaoDiffHint(expected, actual)}`;
}

function doubaoFocus(composer) {
  if (!composer) return;
  composer.focus();
  doubaoPlaceCaret(composer);
}

function doubaoPaste(composer, text) {
  doubaoFocus(composer);
  try {
    const data = new DataTransfer();
    data.setData("text/plain", text);
    composer.dispatchEvent(new ClipboardEvent("paste", { bubbles: true, cancelable: true, clipboardData: data }));
  } catch {
    /* 这个浏览器不接受合成粘贴事件 */
  }
}

async function doubaoSettle(root, prompt, shouldAbort) {
  const deadline = Date.now() + 1500;
  while (true) {
    if (shouldAbort && shouldAbort()) return "cancelled";
    const composer = doubaoComposer(root);
    const state = composer ? doubaoMatchState(composer, prompt) : "mismatch";
    if (state === "match" || state === "duplicate") return state;
    if (Date.now() >= deadline) return state;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
}

async function doubaoCommitPrompt(root, prompt, shouldAbort) {
  const text = String(prompt || "");
  const writers = [
    (composer) => {
      doubaoFocus(composer);
      document.execCommand("insertText", false, text);
      composer.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: text }));
    },
    (composer) => {
      doubaoPaste(composer, text);
    },
    (composer) => {
      doubaoFocus(composer);
      const before = doubaoComposerText(composer);
      composer.dispatchEvent(new InputEvent("beforeinput", { bubbles: true, cancelable: true, inputType: "insertText", data: text }));
      const live = doubaoComposer(root) || composer;
      if (doubaoComposerText(live) === before) {
        live.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: text }));
      }
    },
  ];
  let saw = null;
  for (const write of writers) {
    let composer = doubaoComposer(root);
    if (!composer) return { ok: false, detail: "找不到输入框" };
    doubaoClearComposer(composer);
    composer = doubaoComposer(root);
    if (!composer) return { ok: false, detail: "找不到输入框" };
    doubaoFocus(composer);
    write(composer);
    saw = doubaoComposer(root) || composer;
    const state = await doubaoSettle(root, text, shouldAbort);
    if (state === "match") return { ok: true };
    if (state === "cancelled") return { ok: false, detail: "cancelled" };
    const leftover = doubaoComposer(root);
    if (leftover) doubaoClearComposer(leftover);
  }
  return { ok: false, detail: doubaoDiagnosis(saw || doubaoComposer(root), text) };
}

function doubaoUsers(root) {
  return [...root.querySelectorAll("[data-testid='send_message']")];
}

function doubaoUserMatches(node, prompt) {
  const expected = doubaoNormalize(prompt).slice(0, 40);
  if (!expected) return false;
  return doubaoNormalize(node.innerText || node.textContent || "").includes(expected);
}

async function doubaoDispatchSend(root, prompt, timeoutMs, shouldAbort) {
  const deadline = Date.now() + (timeoutMs == null ? 10000 : timeoutMs);
  if (shouldAbort && shouldAbort()) return { ok: false, detail: "cancelled", clicked: false };
  if (doubaoLogin(root)) return { ok: false, detail: doubaoLoginDetail(root), clicked: false };
  const composer = doubaoComposer(root);
  if (!composer) return { ok: false, detail: "找不到输入框", clicked: false };
  const committed = await doubaoCommitPrompt(root, prompt, shouldAbort);
  if (!committed.ok) {
    const live = doubaoComposer(root) || composer;
    if (committed.detail !== "cancelled" && live) doubaoClearComposer(live);
    const detail = committed.detail === "cancelled" || committed.detail === "找不到输入框"
      ? committed.detail
      : `输入框内容和待发文本不一致，没有点击发送。${committed.detail}`;
    return { ok: false, detail, clicked: false };
  }
  const before = doubaoUsers(root).length;
  let clicked = false;
  while (Date.now() < deadline) {
    if (shouldAbort && shouldAbort()) {
      if (!clicked) doubaoClearComposer(composer);
      return { ok: false, detail: "cancelled", clicked };
    }
    const live = doubaoComposer(root);
    const ready = !!(live && doubaoMatchState(live, prompt) === "match");
    if (!clicked) {
      const send = doubaoSendUsable(root);
      if (ready && send) {
        doubaoPress(send);
        clicked = true;
      }
    } else if (doubaoUsers(root).length > before && doubaoUserMatches(doubaoUsers(root).at(-1), prompt)) {
      return { ok: true, clicked: true };
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  const live = doubaoComposer(root) || composer;
  const note = doubaoDiagnosis(live, prompt);
  const matched = doubaoMatchState(live, prompt) === "match";
  const detail = clicked || matched
    ? `已填入，未发送。${note}`
    : `输入框内容和待发文本不一致，没有点击发送。${note}`;
  if (live) doubaoClearComposer(live);
  return { ok: false, detail, clicked };
}

function doubaoExcluded(el) {
  if (el.closest("[data-copy-ignore], [data-testid='suggest_message_item']")) return true;
  const host = el.closest("[data-plugin-identifier]");
  const ident = host ? host.getAttribute("data-plugin-identifier") || "" : "";
  return ident.includes("search_query_result_block");
}

function doubaoShown(value) {
  return String(value || "").replace(/[\u200b\u200c\u200d\ufeff]/g, "").replace(/\u00a0/g, " ").trim();
}

function doubaoText(node) {
  if (!node) return "";
  const blocks = [...node.querySelectorAll("[data-testid='message_text_content']")].filter((el) => !doubaoExcluded(el));
  return doubaoShown(blocks.map((el) => el.innerText || el.textContent || "").join("\n"));
}

function doubaoDone(node) {
  if (!node || !doubaoText(node)) return false;
  const bodies = [...node.querySelectorAll("[data-testid='message_text_content']")].filter((el) => !doubaoExcluded(el));
  if (!bodies.length || bodies.some((el) => el.getAttribute("data-streaming") !== "false")) return false;
  return !!node.querySelector("[data-testid='message_action_bar']");
}

function doubaoNewReply(root, prompt) {
  const users = doubaoUsers(root);
  const mine = [...users].reverse().find((node) => doubaoUserMatches(node, prompt));
  if (!mine) return null;
  const all = [...root.querySelectorAll("[data-testid='send_message'], [data-testid='receive_message']")];
  const index = all.indexOf(mine);
  for (let i = index + 1; i < all.length; i += 1) {
    if (all[i].getAttribute("data-testid") === "receive_message") return all[i];
  }
  return null;
}

function doubaoPartial(node) {
  const text = doubaoText(node);
  if (!text) return "";
  return `${text}（可能未完整）`;
}

function doubaoTimeoutNote(root, beforeCount) {
  const items = [...root.querySelectorAll("[data-testid='receive_message']")];
  const stop = doubaoStop(root);
  const streaming = [...root.querySelectorAll("[data-testid='message_text_content']")].filter((el) => el.getAttribute("data-streaming") === "true").length;
  return `超时。AI ${beforeCount}→${items.length}，streaming ${streaming}，停止 ${stop ? "可见" : "无"}`;
}

function doubaoBanned(root) {
  const loc = (root && root.location) || (root && root.defaultView && root.defaultView.location) || location;
  return String(loc.pathname || loc.href || "").includes("/security/doubao-region-ban");
}

function doubaoLoginDetail(root) {
  if (doubaoBanned(root || document)) return DOUBAO_BAN_DETAIL;
  return DOUBAO_LOGIN_DETAIL;
}

function doubaoLogin(root) {
  if (doubaoBanned(root)) return true;
  return [...root.querySelectorAll("h1, h2, h3, h4, [role='dialog'], [aria-modal='true'], button, div, span, p")].some((el) => {
    if (!doubaoVisible(el)) return false;
    const own = [...el.childNodes].filter((node) => node.nodeType === 3).map((node) => node.textContent || "").join("").trim();
    if (own.includes("使用豆包或飞书账号登录")) return true;
    const role = el.getAttribute("role");
    if ((role === "dialog" || el.getAttribute("aria-modal") === "true") && (el.textContent || "").includes("使用豆包或飞书账号登录")) return true;
    return false;
  });
}

// 块里的 async 函数不会自动成为全局函数，显式挂到全局，供其他内容脚本调用。
globalThis.doubaoSettle = doubaoSettle;
globalThis.doubaoCommitPrompt = doubaoCommitPrompt;
globalThis.doubaoDispatchSend = doubaoDispatchSend;
}
