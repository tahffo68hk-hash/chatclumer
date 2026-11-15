// 结构取自协调方实页 2026-11-15。本文件不是那次桌面验收，不能当成扩展端到端已通过。
const DOUBAO_DOM_SOURCE = "结构取自协调方实页 2026-11-15";

const DOUBAO_LOGIN_DETAIL = "豆包需要登录，请在该标签页登录一次后重试";
const DOUBAO_BAN_DETAIL = "豆包当前网络地区不可用";

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

async function doubaoSettle(composer, prompt, shouldAbort) {
  const deadline = Date.now() + 1500;
  while (true) {
    if (shouldAbort && shouldAbort()) return "cancelled";
    const state = doubaoMatchState(composer, prompt);
    if (state === "match" || state === "duplicate") return state;
    if (Date.now() >= deadline) return state;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
}

async function doubaoCommitPrompt(root, prompt, shouldAbort) {
  const composer = doubaoComposer(root);
  if (!composer) return { ok: false, detail: "找不到输入框" };
  const text = String(prompt || "");
  const writers = [
    () => {
      doubaoClearComposer(composer);
      doubaoPlaceCaret(composer);
      document.execCommand("insertText", false, text);
      composer.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: text }));
    },
    () => {
      doubaoClearComposer(composer);
      doubaoPlaceCaret(composer);
      const before = doubaoComposerText(composer);
      composer.dispatchEvent(new InputEvent("beforeinput", { bubbles: true, cancelable: true, inputType: "insertText", data: text }));
      if (doubaoComposerText(composer) === before) {
        composer.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: text }));
      }
    },
  ];
  for (const write of writers) {
    write();
    const state = await doubaoSettle(composer, text, shouldAbort);
    if (state === "match") return { ok: true };
    if (state === "cancelled") return { ok: false, detail: "cancelled" };
    doubaoClearComposer(composer);
  }
  return { ok: false, detail: doubaoDiagnosis(composer, text) };
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
    if (committed.detail !== "cancelled") doubaoClearComposer(composer);
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
    const ready = doubaoMatchState(composer, prompt) === "match";
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
  const note = doubaoDiagnosis(composer, prompt);
  const matched = doubaoMatchState(composer, prompt) === "match";
  const detail = clicked || matched
    ? `已填入，未发送。${note}`
    : `输入框内容和待发文本不一致，没有点击发送。${note}`;
  doubaoClearComposer(composer);
  return { ok: false, detail, clicked };
}

function doubaoExcluded(el) {
  if (el.closest("[data-copy-ignore], [data-testid='suggest_message_item']")) return true;
  const host = el.closest("[data-plugin-identifier]");
  const ident = host ? host.getAttribute("data-plugin-identifier") || "" : "";
  return ident.includes("search_query_result_block");
}

function doubaoText(node) {
  if (!node) return "";
  const blocks = [...node.querySelectorAll("[data-testid='message_text_content']")].filter((el) => !doubaoExcluded(el));
  return doubaoNormalize(blocks.map((el) => el.innerText || el.textContent || "").join("\n"));
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
