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
  if (url.startsWith("https://chatglm.cn/")) return "zhipu";
  return "";
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
    login: () => typeof yuanbaoLogin === "function" && yuanbaoLogin(document),
  },
  zhipu: {
    composer: () => null,
    send: () => null,
    assistants: () => [],
    text: () => "",
    done: () => false,
    model: () => "",
    openNew: () => null,
    refuse: "智谱公开回复的正文位置未验证，不会发送，也不会用整页文字代替回复。",
  },
};

const sent = new Set(JSON.parse(sessionStorage.getItem("bridge-sent") || "[]"));
let busy = false;

function remember(id) {
  sent.add(id);
  sessionStorage.setItem("bridge-sent", JSON.stringify([...sent].slice(-40)));
}

function snapshot(adapter) {
  return adapter.assistants().map((node, index) => `${index}:${adapter.text(node)}`);
}

async function waitNew(adapter, before, signal) {
  let last = "";
  let stable = 0;
  const deadline = Date.now() + (adapter.onlyNew ? 80000 : 32000);
  while (Date.now() < deadline) {
    if (signal.cancelled) return cancelResult();
    if (adapter.login && adapter.login()) {
      clickSiteStop();
      return { status: "login", detail: "等待回复时页面停在登录，已停止，没有读取旧消息" };
    }
    const nodes = adapter.assistants();
    const fresh = adapter.onlyNew
      ? nodes.slice(before.length)
      : nodes.filter((_, index) => snapshot(adapter)[index] !== before[index] || index >= before.length);
    const node = fresh[fresh.length - 1];
    if (node && adapter.done(node)) {
      const text = adapter.text(node);
      if (text && text === last) stable += 1;
      else stable = 0;
      last = text;
      if (stable >= 2 && text) return { status: "complete", text };
    }
    const body = document.body ? document.body.innerText : "";
    if (/rate limit|too many requests|you've reached your|配额已用完|次数已用完|usage limit/i.test(body) && !node) {
      return { status: "rate_limit", detail: "页面出现限流提示，已停止" };
    }
    await new Promise((resolve) => setTimeout(resolve, 400));
  }
  return {
    status: "error",
    detail: adapter.onlyNew
      ? "超时"
      : "没有等到新的助手回复",
  };
}

function clickSiteStop() {
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

function reportPhase(job, phase) {
  try {
    chrome.runtime.sendMessage({ type: "job-progress", request_id: job.request_id, phase });
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
  if (adapter.login && adapter.login()) return { status: "login", detail: "页面停在登录或验证，没有点击发送", page_url: pageUrl };
  if (job.action === "cancel") return { status: "cancelled", page_url: pageUrl };
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
    if (signal.cancelled || job.action === "cancel") return { ...cancelResult(), page_url: pageUrl };
    if (site !== "yuanbao") fillComposer(box, job.prompt);
    remember(job.request_id);
    let posted = false;
    if (typeof yuanbaoDispatchSend === "function" && site === "yuanbao") {
      reportPhase(job, "filled");
      const outcome = await yuanbaoDispatchSend(document, job.prompt, 10000, () => signal.cancelled);
      if (signal.cancelled || outcome.detail === "cancelled") {
        if (!outcome.ok) clearIfUnsent(box, job.prompt);
        return { ...cancelResult(), page_url: pageUrl };
      }
      if (!outcome.ok) {
        clearIfUnsent(box, job.prompt);
        reportPhase(job, "unsent");
        return { status: "error", detail: outcome.detail, page_url: pageUrl };
      }
      posted = true;
      reportPhase(job, "waiting");
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
    const result = await waitNew(adapter, before, signal);
    if (result.status === "cancelled" && !posted) clearIfUnsent(box, job.prompt);
    if (result.detail === "超时") reportPhase(job, "timeout");
    if (result.status === "cancelled" && !String(result.detail || "").includes("停止")) {
      const stopped = clickSiteStop();
      result.detail = stopped
        ? "已点击源站停止"
        : "源站没有可确认的停止按钮，页面可能继续生成，本应用不会再发送";
    }
    result.model_label = adapter.model() || "未能核验精确 model ID";
    result.page_url = pageUrl;
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

if (!globalThis.__roomBridge) {
globalThis.__roomBridge = true;
const bridgeToken = {};
globalThis.__roomBridgeToken = bridgeToken;
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (globalThis.__roomBridgeToken !== bridgeToken) return;
  if (!extensionAlive()) return;
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
}
