const DANGER = /升级|订阅|付费|支付|购买|删除|清空|注销|delete|upgrade|subscribe|remove|buy/i;

function labelOf(el) {
  return `${el.getAttribute("aria-label") || ""} ${el.innerText || ""}`.trim();
}

function dangerous(el) {
  return DANGER.test(labelOf(el));
}

function siteFrom(url) {
  if (url.startsWith("http://127.0.0.1:43124/fixture")) return "fixture";
  if (url.startsWith("https://gemini.google.com/")) return "gemini";
  if (url.startsWith("https://yuanbao.tencent.com/")) return "yuanbao";
  if (url.startsWith("https://chat.deepseek.com/")) return "deepseek";
  if (url.startsWith("https://www.doubao.com/")) return "doubao";
  if (url.startsWith("https://chatglm.cn/")) return "zhipu";
  if (url.startsWith("https://chat.qwen.ai/")) return "qwen";
  if (url.startsWith("https://chatgpt.com/") || url.startsWith("https://chat.openai.com/")) return "chatgpt";
  if (url.startsWith("https://wenxin.baidu.com/") || url.startsWith("https://yiyan.baidu.com/") || url.startsWith("https://chat.baidu.com/")) return "wenxin";
  if (url.startsWith("https://chat.z.ai/")) return "zai";
  return "";
}

const GUEST_SITE_IDS = ["qwen", "chatgpt", "wenxin", "zhipu", "zai"];

function guestSite(site) {
  return GUEST_SITE_IDS.includes(site) && typeof guestDispatchSend === "function";
}

function managedSite(site) {
  return site === "yuanbao" || site === "deepseek" || site === "doubao" || guestSite(site);
}

function siteDispatch(site) {
  if (site === "yuanbao" && typeof yuanbaoDispatchSend === "function") return yuanbaoDispatchSend;
  if (site === "deepseek" && typeof deepseekDispatchSend === "function") return deepseekDispatchSend;
  if (site === "doubao" && typeof doubaoDispatchSend === "function") return doubaoDispatchSend;
  if (guestSite(site)) return (root, prompt, timeoutMs, shouldAbort) => guestDispatchSend(site, root, prompt, timeoutMs, shouldAbort);
  return null;
}

const adapters = {
  fixture: {
    composer: () => document.querySelector("#composer"),
    send: () => document.querySelector("#send"),
    assistants: () => [...document.querySelectorAll("#thread [data-role='assistant']")],
    text: (node) => (node.textContent || "").trim(),
    done: (node) => node.getAttribute("data-state") === "complete",
    model: () => (document.querySelector("#model-name")?.textContent || "").trim(),
    openNew: () => null,
  },
  gemini: {
    composer: () => document.querySelector("[aria-label='Enter a prompt for Gemini']")
      || document.querySelector("rich-textarea [contenteditable='true']"),
    send: () => [...document.querySelectorAll("button")].find((el) => {
      const label = el.getAttribute("aria-label") || "";
      return ["Send message", "Send", "发送", "发送消息"].includes(label) && !dangerous(el) && !el.disabled;
    }),
    assistants: () => [...document.querySelectorAll("model-response")],
    text: (node) => (node.innerText || "").replace(/^Gemini said\s*/i, "").trim(),
    done: (node) => {
      const stop = [...document.querySelectorAll("button")].some((el) => /^(Stop|停止)/i.test(el.getAttribute("aria-label") || ""));
      return !stop && !!(node && (node.innerText || "").trim());
    },
    model: () => {
      const button = [...document.querySelectorAll("button")].find((el) => (el.getAttribute("aria-label") || "").startsWith("Open mode picker"));
      return button ? button.innerText.trim() : "";
    },
    openNew: () => {
      const el = document.querySelector("[data-test-id='reset-button']");
      if (!el || dangerous(el)) return null;
      const text = (el.innerText || "").trim();
      return text === "New chat" || text === "新对话" ? el : null;
    },
  },
  yuanbao: {
    composer: () => (typeof yuanbaoComposer === "function" ? yuanbaoComposer(document) : null),
    send: () => (typeof yuanbaoSend === "function" ? yuanbaoSend(document) : null),
    assistants: () => (typeof yuanbaoAssistants === "function" ? yuanbaoAssistants(document) : []),
    text: (node) => (typeof yuanbaoText === "function" ? yuanbaoText(node) : ""),
    done: (node) => (typeof yuanbaoDone === "function" ? yuanbaoDone(node) : false),
    model: () => "",
    openNew: () => null,
    onlyNew: true,
    readCap: 90000,
    stableMs: 2500,
    replyNode: (prompt) => (typeof yuanbaoNewReply === "function" ? yuanbaoNewReply(document, prompt) : null),
    idle: () => typeof yuanbaoSendIdle !== "function" || yuanbaoSendIdle(document),
    partial: (node) => (typeof yuanbaoPartial === "function" ? yuanbaoPartial(node) : ""),
    timeoutDetail: (beforeCount) => (typeof yuanbaoTimeoutNote === "function" ? yuanbaoTimeoutNote(document, beforeCount) : "超时"),
    login: () => typeof yuanbaoLogin === "function" && yuanbaoLogin(document),
    loginDetail: () => (typeof yuanbaoLoginDetail === "function" ? yuanbaoLoginDetail() : "页面停在登录或验证，没有点击发送"),
  },
  deepseek: {
    composer: () => (typeof deepseekComposer === "function" ? deepseekComposer(document) : null),
    send: () => (typeof deepseekSend === "function" ? deepseekSend(document) : null),
    assistants: () => (typeof deepseekAssistants === "function" ? deepseekAssistants(document) : []),
    text: (node) => (typeof deepseekText === "function" ? deepseekText(node) : ""),
    done: (node) => (typeof deepseekDone === "function" ? deepseekDone(node) : false),
    model: () => "",
    openNew: () => null,
    onlyNew: true,
    readCap: 90000,
    stableMs: 2500,
    fallbackStableMs: 6000,
    staleMs: 15000,
    streaming: () => (typeof deepseekStreaming === "function" ? deepseekStreaming(document) : null),
    replyNode: (prompt) => (typeof deepseekNewReply === "function" ? deepseekNewReply(document, prompt) : null),
    idle: () => typeof deepseekSendIdle !== "function" || deepseekSendIdle(document),
    partial: (node) => (typeof deepseekPartial === "function" ? deepseekPartial(node) : ""),
    timeoutDetail: (beforeCount) => (typeof deepseekTimeoutNote === "function" ? deepseekTimeoutNote(document, beforeCount) : "超时"),
    login: () => typeof deepseekLogin === "function" && deepseekLogin(document),
    loginDetail: () => (typeof deepseekLoginDetail === "function" ? deepseekLoginDetail() : "页面停在登录或验证，没有点击发送"),
    stop: () => (typeof deepseekStopTarget === "function" ? deepseekStopTarget(document) : null),
  },
  doubao: {
    composer: () => (typeof doubaoComposer === "function" ? doubaoComposer(document) : null),
    send: () => (typeof doubaoSend === "function" ? doubaoSend(document) : null),
    assistants: () => (typeof doubaoNewReply === "function" ? [...document.querySelectorAll("[data-testid='receive_message']")] : []),
    text: (node) => (typeof doubaoText === "function" ? doubaoText(node) : ""),
    done: (node) => (typeof doubaoDone === "function" ? doubaoDone(node) : false),
    model: () => "",
    openNew: () => null,
    onlyNew: true,
    readCap: 90000,
    stableMs: 2500,
    replyNode: (prompt) => (typeof doubaoNewReply === "function" ? doubaoNewReply(document, prompt) : null),
    idle: () => typeof doubaoSendIdle !== "function" || doubaoSendIdle(document),
    partial: (node) => (typeof doubaoPartial === "function" ? doubaoPartial(node) : ""),
    timeoutDetail: (beforeCount) => (typeof doubaoTimeoutNote === "function" ? doubaoTimeoutNote(document, beforeCount) : "超时"),
    login: () => typeof doubaoLogin === "function" && doubaoLogin(document),
    loginDetail: () => (typeof doubaoLoginDetail === "function" ? doubaoLoginDetail(document) : "页面停在登录或验证，没有点击发送"),
    stop: () => (typeof doubaoStop === "function" ? doubaoStop(document) : null),
  },
};

// 游客站点共用 guest.js。每个站的选择器在 adapters/registry.json 里；没装 guest.js 时这些站一律不发送。
function guestAdapter(site) {
  const ready = () => typeof guestDispatchSend === "function";
  return {
    composer: () => (ready() ? guestComposer(site, document) : null),
    send: () => (ready() ? guestSend(site, document) : null),
    assistants: () => (ready() ? guestAssistants(site, document) : []),
    text: (node) => (ready() ? guestText(site, node) : ""),
    done: (node) => (ready() ? guestDone(site, node) : false),
    model: () => "",
    openNew: () => null,
    onlyNew: true,
    readCap: 90000,
    stableMs: 2500,
    fallbackStableMs: 6000,
    staleMs: 15000,
    streaming: (node) => (ready() ? guestStreaming(site, document, node) : null),
    replyNode: (prompt) => (ready() ? guestNewReply(site, document, prompt) : null),
    partial: (node) => (ready() ? guestPartial(site, node) : ""),
    timeoutDetail: (beforeCount) => (ready() ? guestTimeoutNote(site, document, beforeCount) : "超时"),
    login: () => ready() && !!guestGate(site, document),
    loginDetail: () => (ready() && guestGate(site, document)) || "页面停在登录或验证，没有点击发送",
    stop: () => (ready() ? guestStopTarget(site, document) : null),
    refuse: ready() ? "" : "游客站点适配器没有装上，不会发送，也不会用整页文字代替回复。",
  };
}

for (const site of GUEST_SITE_IDS) adapters[site] = guestAdapter(site);

const sent = new Set(JSON.parse(sessionStorage.getItem("bridge-sent") || "[]"));
let busy = false;

function remember(id) {
  sent.add(id);
  sessionStorage.setItem("bridge-sent", JSON.stringify([...sent].slice(-40)));
}

function snapshot(adapter) {
  return adapter.assistants().map((node, index) => `${index}:${adapter.text(node)}`);
}

function currentReply(adapter, before, prompt) {
  if (typeof adapter.replyNode === "function") return adapter.replyNode(prompt);
  const nodes = adapter.assistants();
  const fresh = adapter.onlyNew
    ? nodes.slice(before.length)
    : nodes.filter((_, index) => snapshot(adapter)[index] !== before[index] || index >= before.length);
  return fresh[fresh.length - 1] || null;
}

// 等下一次检查：最多 ms 毫秒，页面有 DOM 变化时提前醒来（至少隔 150 毫秒）。
// 后台标签页的定时器会被浏览器拉长，MutationObserver 不受影响，所以流式输出停下后能及时再看一眼。
function waitTick(ms) {
  return new Promise((resolve) => {
    const started = Date.now();
    let finished = false;
    let observer = null;
    let timer = null;
    let onVisible = null;
    const finish = () => {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      if (observer) observer.disconnect();
      if (onVisible) document.removeEventListener("visibilitychange", onVisible);
      resolve();
    };
    timer = setTimeout(finish, ms);
    try {
      if (typeof MutationObserver === "function" && document.body) {
        observer = new MutationObserver(() => {
          const left = 150 - (Date.now() - started);
          if (left <= 0) finish();
          else {
            clearTimeout(timer);
            timer = setTimeout(finish, left);
          }
        });
        observer.observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true });
      }
      if (typeof document.addEventListener === "function") {
        onVisible = () => finish();
        document.addEventListener("visibilitychange", onVisible);
      }
    } catch {
      /* 观察失败时只靠定时器 */
    }
  });
}

// 回复是否可以收尾。稳定时长都用 Date.now() 差值算，不数轮询次数。
// 适配器提供 streaming() 时：有完成标记或确认不在生成，文字稳定 stableMs；判断不了是否在生成，稳定 fallbackStableMs；
// 看起来仍在生成，稳定 staleMs 才收（防止停止键识别错把每轮都拖到 90 秒）。没有 streaming() 的站点照旧要求 done 且 idle。
function replySettled(adapter, node, text, stableFor, idle) {
  if (!node || !text) return false;
  const stableMs = adapter.stableMs || 800;
  if (typeof adapter.streaming !== "function") return adapter.done(node) && idle && stableFor >= stableMs;
  const streaming = adapter.streaming(node);
  const marked = adapter.done(node);
  if (streaming === true) return stableFor >= (adapter.staleMs || 15000);
  if (marked || streaming === false) return stableFor >= stableMs;
  return stableFor >= (adapter.fallbackStableMs || 6000);
}

async function waitNew(adapter, before, signal, prompt) {
  let last = "";
  let changedAt = Date.now();
  let lastBodyCheck = 0;
  const deadline = Date.now() + (adapter.readCap || (adapter.onlyNew ? 90000 : 32000));
  while (Date.now() < deadline) {
    if (signal.cancelled) return cancelResult();
    if (adapter.login && adapter.login()) {
      clickSiteStop();
      const detail = typeof adapter.loginDetail === "function"
        ? adapter.loginDetail()
        : "等待回复时页面停在登录，已停止，没有读取旧消息";
      return { status: "login", detail };
    }
    const node = currentReply(adapter, before, prompt);
    const idle = typeof adapter.idle !== "function" || adapter.idle();
    const text = node ? adapter.text(node) : "";
    const now = Date.now();
    if (text !== last) {
      last = text;
      changedAt = now;
    }
    if (replySettled(adapter, node, text, now - changedAt, idle)) return { status: "complete", text };
    if (!node && now - lastBodyCheck >= 1500) {
      lastBodyCheck = now;
      const body = document.body ? document.body.innerText : "";
      if (/rate limit|too many requests|you've reached your|配额已用完|次数已用完|usage limit/i.test(body)) {
        return { status: "rate_limit", detail: "页面出现限流提示，已停止" };
      }
    }
    await waitTick(400);
  }
  const late = currentReply(adapter, before, prompt);
  const partial = late && typeof adapter.partial === "function" ? adapter.partial(late) : "";
  if (partial) return { status: "complete", text: partial };
  const detail = typeof adapter.timeoutDetail === "function"
    ? adapter.timeoutDetail(before.length)
    : (adapter.onlyNew ? "超时" : "没有等到新的助手回复");
  return { status: "error", detail };
}

function clickSiteStop() {
  const site = siteFrom(location.href);
  const adapter = adapters[site];
  if (adapter && typeof adapter.stop === "function") {
    const el = adapter.stop();
    if (!el) return false;
    if (typeof doubaoPress === "function" && site === "doubao") doubaoPress(el);
    else if (typeof guestPress === "function" && guestSite(site)) guestPress(el);
    else if (typeof deepseekPress === "function" && site === "deepseek") deepseekPress(el);
    else el.click();
    return true;
  }
  const labels = new Set(["Stop", "Stop response", "Stop Answering", "停止", "停止生成", "停止回答", "停止对话"]);
  const el = [...document.querySelectorAll("[aria-label]")].find((node) => {
    return labels.has(node.getAttribute("aria-label") || "") && !dangerous(node) && !node.hidden;
  });
  if (!el) return false;
  el.click();
  return true;
}

function cancelResult() {
  const stopped = clickSiteStop();
  return {
    status: "cancelled",
    detail: stopped
      ? "已点击源站停止"
      : "源站没有可确认的停止按钮，页面可能继续生成，本应用不会再发送",
    page_url: location.origin + location.pathname,
  };
}

function releaseComposer(box) {
  const site = siteFrom(location.href);
  if (site === "deepseek" && typeof deepseekClearComposer === "function") {
    deepseekClearComposer((typeof deepseekComposer === "function" && deepseekComposer(document)) || box);
    return;
  }
  if (guestSite(site)) {
    guestClearComposer(guestComposer(site, document) || box);
    return;
  }
  if (site === "doubao" && typeof doubaoClearComposer === "function") {
    doubaoClearComposer((typeof doubaoComposer === "function" && doubaoComposer(document)) || box);
    return;
  }
  if (typeof yuanbaoClearComposer !== "function") return;
  const composer = (typeof yuanbaoComposer === "function" && yuanbaoComposer(document)) || box;
  if (composer) yuanbaoClearComposer(composer);
}

function clearIfUnsent(box, prompt) {
  if (!box) return;
  const current = ("value" in box && !box.isContentEditable ? box.value : box.innerText || box.textContent || "").trim();
  if (current !== String(prompt || "").trim()) return;
  box.focus();
  if (box.isContentEditable) {
    if (typeof yuanbaoClearComposer === "function" && siteFrom(location.href) === "yuanbao") {
      yuanbaoClearComposer(box);
      return;
    }
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(box);
    selection.removeAllRanges();
    selection.addRange(range);
    document.execCommand("delete", false, null);
    box.dispatchEvent(new InputEvent("beforeinput", { bubbles: true, cancelable: true, inputType: "deleteContentBackward" }));
    box.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "deleteContentBackward" }));
    return;
  }
  box.value = "";
  box.dispatchEvent(new Event("input", { bubbles: true }));
}

function reportPhase(job, phase, note) {
  try {
    chrome.runtime.sendMessage({ type: "job-progress", request_id: job.request_id, phase, note: note || "" });
  } catch {
    /* 进度失败不改变发送结果 */
  }
}

function fillComposer(box, prompt) {
  const field = box.matches?.("[contenteditable='true']")
    ? box
    : box.querySelector?.("[contenteditable='true']") || box;
  field.focus();
  if ("value" in field && !field.isContentEditable) {
    field.value = prompt;
    field.dispatchEvent(new Event("input", { bubbles: true }));
    return;
  }
  const selection = window.getSelection();
  const range = document.createRange();
  range.selectNodeContents(field);
  selection.removeAllRanges();
  selection.addRange(range);
  document.execCommand("insertText", false, prompt);
  field.dispatchEvent(new InputEvent("input", { bubbles: true, data: prompt, inputType: "insertText" }));
}

async function runJob(job) {
  const pageUrl = location.origin + location.pathname;
  if (/accounts\.google\.com|challenge|just a moment/i.test(location.href)) {
    return { status: "login", detail: "页面停在登录或验证，已停止", page_url: pageUrl };
  }
  const site = siteFrom(location.href);
  const adapter = adapters[site];
  if (!adapter || site !== job.site) return { status: "error", detail: "当前页和任务站点不一致", page_url: pageUrl };
  if (adapter.refuse) return { status: "error", detail: adapter.refuse, page_url: pageUrl };
  if (!extensionAlive()) return { status: "error", detail: "扩展上下文已失效，这次不发送", page_url: pageUrl };
  if (adapter.login && adapter.login()) {
    const detail = typeof adapter.loginDetail === "function" ? adapter.loginDetail() : "页面停在登录或验证，没有点击发送";
    return { status: "login", detail, page_url: pageUrl };
  }
  if (job.action === "cancel") {
    releaseComposer();
    return { status: "cancelled", page_url: pageUrl };
  }
  if (busy) return { status: "error", detail: "这个标签页正在处理上一条", page_url: pageUrl };
  busy = true;
  const signal = { cancelled: false };
  const onCancel = (message) => {
    if (message && message.type === "cancel" && message.request_id === job.request_id) signal.cancelled = true;
  };
  chrome.runtime.onMessage.addListener(onCancel);
  try {
    if (job.open_new) {
      const opener = adapter.openNew();
      if (!opener) return { status: "error", detail: "站点没有可确认的新对话按钮，已阻塞，不会沿用旧会话假装失忆", page_url: pageUrl };
      opener.click();
      await new Promise((resolve) => setTimeout(resolve, 600));
    }
    const before = snapshot(adapter);
    const box = adapter.composer();
    if (!box) return { status: "error", detail: "找不到输入框", page_url: pageUrl };
    if (signal.cancelled || job.action === "cancel") {
      if (managedSite(site)) releaseComposer(box);
      return { ...cancelResult(), page_url: pageUrl };
    }
    const dispatch = siteDispatch(site);
    if (!dispatch) fillComposer(box, job.prompt);
    remember(job.request_id);
    let posted = false;
    if (dispatch) {
      reportPhase(job, "filled");
      const outcome = await dispatch(document, job.prompt, 10000, () => signal.cancelled);
      if (signal.cancelled || outcome.detail === "cancelled") {
        if (!outcome.ok) clearIfUnsent(box, job.prompt);
        releaseComposer(box);
        return { ...cancelResult(), page_url: pageUrl };
      }
      if (!outcome.ok) {
        const detail = String(outcome.detail || "");
        if (outcome.gate || detail.includes("需要登录") || detail.includes("豆包当前网络地区不可用")) {
          clearIfUnsent(box, job.prompt);
          return { status: "login", detail: outcome.detail, page_url: pageUrl };
        }
        clearIfUnsent(box, job.prompt);
        reportPhase(job, "unsent", outcome.detail);
        return { status: "error", detail: outcome.detail, page_url: pageUrl };
      }
      posted = true;
      reportPhase(job, "waiting");
      saveTask(job, "reading");
    } else {
      let send = null;
      for (let i = 0; i < 10; i += 1) {
        send = adapter.send();
        if (send && !dangerous(send)) break;
        send = null;
        await new Promise((resolve) => setTimeout(resolve, 200));
      }
      if (!send) return { status: "error", detail: "找不到安全的发送按钮", page_url: pageUrl };
      if (signal.cancelled) return { ...cancelResult(), page_url: pageUrl };
      send.click();
      posted = true;
    }
    const result = await waitNew(adapter, before, signal, job.prompt);
    if (result.status === "login" && managedSite(site)) {
      // 站点把发送退回、把原文放回输入框时（如 Qwen 无权限），清掉它，免得之后被误发。
      clearIfUnsent(adapter.composer(), job.prompt);
    }
    const timedOut = String(result.detail || "").startsWith("超时");
    if (result.status === "cancelled" || timedOut) {
      if (!posted) clearIfUnsent(box, job.prompt);
      if (managedSite(site)) releaseComposer(box);
    }
    if (timedOut) reportPhase(job, "timeout", result.detail);
    if (result.status === "cancelled" && !String(result.detail || "").includes("停止")) {
      const stopped = clickSiteStop();
      result.detail = stopped
        ? "已点击源站停止"
        : "源站没有可确认的停止按钮，页面可能继续生成，本应用不会再发送";
    }
    result.model_label = adapter.model() || "未能核验精确 model ID";
    result.page_url = pageUrl;
    if (result.status === "complete") clearTask(job.request_id);
    return result;
  } finally {
    chrome.runtime.onMessage.removeListener(onCancel);
    busy = false;
  }
}

let pending = null;

function extensionAlive() {
  try {
    return Boolean(chrome.runtime && chrome.runtime.id);
  } catch {
    return false;
  }
}

function claimJob(id) {
  if (!id) return true;
  if (sent.has(id)) return false;
  remember(id);
  return true;
}

const TASK_KEY = "bridge-active-task";

function saveTask(job, phase) {
  try {
    sessionStorage.setItem(TASK_KEY, JSON.stringify({
      request_id: job.request_id,
      prompt: job.prompt,
      site: job.site,
      phase,
    }));
  } catch {
    /* 会话存储不可用时，这一页刷新后不能续读 */
  }
}

function clearTask(id) {
  try {
    const raw = sessionStorage.getItem(TASK_KEY);
    if (!raw) return;
    const task = JSON.parse(raw);
    if (!id || task.request_id === id) sessionStorage.removeItem(TASK_KEY);
  } catch {
    sessionStorage.removeItem(TASK_KEY);
  }
}

function loadTask() {
  try {
    return JSON.parse(sessionStorage.getItem(TASK_KEY) || "null");
  } catch {
    return null;
  }
}

async function resumeJob(job) {
  const pageUrl = location.origin + location.pathname;
  const site = siteFrom(location.href);
  const adapter = adapters[site];
  if (!adapter || site !== job.site) return { status: "error", detail: "当前页和任务站点不一致", page_url: pageUrl };
  if (busy) return { status: "error", detail: "这个标签页正在处理上一条", page_url: pageUrl };
  busy = true;
  const signal = { cancelled: false };
  try {
    saveTask(job, "reading");
    const result = await waitNew(adapter, [], signal, job.prompt);
    if (result.status === "complete") clearTask(job.request_id);
    result.model_label = adapter.model() || "未能核验精确 model ID";
    result.page_url = pageUrl;
    return result;
  } finally {
    busy = false;
  }
}

if (!globalThis.__roomBridge) {
globalThis.__roomBridge = true;
const bridgeToken = {};
globalThis.__roomBridgeToken = bridgeToken;
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (globalThis.__roomBridgeToken !== bridgeToken) return;
  if (!extensionAlive()) return;
  if (message && message.type === "cancel") {
    releaseComposer();
    return;
  }
  if (message && message.type === "resume" && message.job) {
    resumeJob(message.job).then(sendResponse);
    return true;
  }
  if (!message || message.type !== "run") return;
  const requestId = message.job && message.job.request_id;
  if (requestId && !claimJob(requestId)) {
    sendResponse({ status: "error", detail: "这个请求已经提交过，刷新后不会再点发送", page_url: location.origin + location.pathname });
    return true;
  }
  if (busy) {
    if (pending) pending.sendResponse({ status: "error", detail: "这个标签页只保留下一条，更早的排队已取消", page_url: location.origin + location.pathname });
    pending = { job: message.job, sendResponse };
    return true;
  }
  runJob(message.job).then((result) => {
    sendResponse(result);
    const next = pending;
    pending = null;
    if (next) runJob(next.job).then(next.sendResponse);
  });
  return true;
});
const restored = loadTask();
if (restored && restored.request_id && siteFrom(location.href) === restored.site) {
  try {
    chrome.runtime.sendMessage({ type: "task-alive", job: restored });
  } catch {
    /* 后台不在时，下一次轮询仍会按任务号续上 */
  }
}
}
