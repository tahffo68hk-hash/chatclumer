const BACKEND = "http://127.0.0.1:43124";
importScripts("adapters/schema.js");
const seen = new Set();
const inflight = new Map();
const reported = new Set();

// 互相跳转的源算同一个绑定：文心三个域名，ChatGPT 两个域名。
const SAME_SITE = [
  ["https://wenxin.baidu.com", "https://chat.baidu.com", "https://yiyan.baidu.com"],
  ["https://chatgpt.com", "https://chat.openai.com"],
];

function sameSiteOrigin(a, b) {
  if (!a || !b) return false;
  if (a === b) return true;
  return SAME_SITE.some((group) => group.includes(a) && group.includes(b));
}

async function load() {
  return chrome.storage.local.get(["pairToken", "bindings"]);
}

async function remember(id) {
  seen.add(id);
  await chrome.storage.session.set({ seenIds: [...seen].slice(-80) });
}

async function beat(token, bindings) {
  const tabs = [];
  for (const [tabKey, binding] of Object.entries(bindings || {})) {
    let alive = false;
    try {
      const tab = await chrome.tabs.get(binding.tabId);
      alive = !!tab;
    } catch {
      alive = false;
    }
    const entry = { tab_key: tabKey, origin: binding.origin, alive };
    if (alive) {
      const health = await tabHealth(binding.tabId);
      if (health) entry.health = health;
    }
    tabs.push(entry);
  }
  if (!tabs.length) return;
  await fetch(`${BACKEND}/api/ext/tabs`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ tabs }),
  }).catch(() => {});
}

// 页面检查（不发送）：每 30 秒问一次绑定的标签页，结果随心跳交给本机后端，房间里能马上看到哪个角色坏了。
const healthAt = new Map();
const healthCache = new Map();

function tabHealth(tabId) {
  const last = healthAt.get(tabId) || 0;
  if (Date.now() - last < 30000) return Promise.resolve(healthCache.get(tabId) || null);
  healthAt.set(tabId, Date.now());
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(null), 1500);
    try {
      chrome.tabs.sendMessage(tabId, { type: "health" }, (result) => {
        clearTimeout(timer);
        if (chrome.runtime.lastError || !result) return resolve(null);
        healthCache.set(tabId, result);
        resolve(result);
      });
    } catch {
      clearTimeout(timer);
      resolve(null);
    }
  });
}

// 远端注册表：只是数据（选择器、正则文本、提示文字、开关）。结构校验通过、版本比内置新才缓存；任何失败都继续用内置。
const DEFAULT_REGISTRY_URL = "https://raw.githubusercontent.com/tahffo68hk-hash/chatclumer/main/extension/adapters/registry.json";
const REGISTRY_EVERY_MS = 6 * 60 * 60 * 1000;
let bundledRegistry = null;

async function loadBundledRegistry() {
  if (bundledRegistry) return bundledRegistry;
  const response = await fetch(chrome.runtime.getURL("adapters/registry.json"));
  bundledRegistry = await response.json();
  return bundledRegistry;
}

async function registryUrl() {
  const { registryUrl: saved } = await chrome.storage.local.get(["registryUrl"]);
  if (saved === "off") return "";
  return saved || DEFAULT_REGISTRY_URL;
}

async function refreshRegistry(force) {
  const url = await registryUrl();
  const { registryStatus } = await chrome.storage.local.get(["registryStatus"]);
  if (!url) {
    const status = { checked_at: new Date().toISOString(), ok: false, detail: "远端更新已关闭，只用内置注册表" };
    await chrome.storage.local.set({ registryStatus: status, registryRemote: null });
    return status;
  }
  if (!force && registryStatus && Date.now() - Date.parse(registryStatus.checked_at || 0) < REGISTRY_EVERY_MS) return registryStatus;
  const status = { checked_at: new Date().toISOString(), url, ok: false, detail: "" };
  try {
    if (!/^https:\/\//.test(url)) throw new Error("只接受 https 地址");
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10000);
    const response = await fetch(url, { cache: "no-cache", credentials: "omit", signal: controller.signal });
    clearTimeout(timer);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const text = await response.text();
    if (text.length > 96 * 1024) throw new Error("文件太大");
    const data = JSON.parse(text);
    const checked = ChatclumerRegistrySchema.validateRegistry(data, chrome.runtime.getManifest().version);
    if (!checked.ok) throw new Error(`结构不对：${checked.errors.slice(0, 3).join("；")}`);
    const bundled = await loadBundledRegistry();
    if (ChatclumerRegistrySchema.compareVersion(data.version, bundled.version) <= 0) {
      status.ok = true;
      status.version = bundled.version;
      status.detail = `远端 ${data.version} 不比内置 ${bundled.version} 新，用内置`;
      await chrome.storage.local.set({ registryStatus: status, registryRemote: null });
      return status;
    }
    status.ok = true;
    status.version = data.version;
    status.detail = `已缓存远端注册表 ${data.version}（内置 ${bundled.version}）`;
    await chrome.storage.local.set({ registryStatus: status, registryRemote: { data, url, fetched_at: status.checked_at } });
  } catch (err) {
    status.detail = `没有更新：${err && err.message ? err.message : err}。继续用之前的缓存或内置注册表`;
    await chrome.storage.local.set({ registryStatus: status });
  }
  return status;
}

async function poll() {
  const { pairToken, bindings } = await load();
  if (!pairToken) return;
  let payload;
  try {
    const response = await fetch(`${BACKEND}/api/ext/jobs`, {
      headers: { Authorization: `Bearer ${pairToken}` },
    });
    if (!response.ok) return;
    payload = await response.json();
  } catch {
    return;
  }
  for (const job of payload.jobs || []) {
    if (job.action !== "cancel" && seen.has(job.request_id)) continue;
    const binding = (bindings || {})[job.tab_key];
    if (!binding || !sameSiteOrigin(binding.origin, job.origin)) {
      await remember(job.request_id);
      await report(pairToken, job, { status: "error", detail: "标签页绑定不匹配", page_url: job.origin + "/" });
      continue;
    }
    if (job.action === "cancel") {
      if (seen.has(`cancel:${job.request_id}`)) continue;
      await remember(`cancel:${job.request_id}`);
      chrome.tabs.sendMessage(binding.tabId, { type: "cancel", request_id: job.request_id });
      continue;
    }
    await remember(job.request_id);
    inflight.set(binding.tabId, job);
    chrome.tabs.sendMessage(binding.tabId, { type: "run", job }, (result) => {
      if (chrome.runtime.lastError || !result) return;
      finishJob(pairToken, binding.tabId, job, result);
    });
  }
  await beat(pairToken, bindings);
}

function finishJob(token, tabId, job, result) {
  if (!job || reported.has(job.request_id)) return;
  if (result && result.detail === "这个标签页正在处理上一条") {
    job.resumeSent = false;
    return;
  }
  reported.add(job.request_id);
  inflight.delete(tabId);
  report(token, job, result);
}

// 首条消息会换地址的站点。整页跳转后内容脚本重新加载，这里按任务号让新页面接着读，不会再点发送。
const RESUME_PATHS = {
  deepseek: /\/a\/chat\/s\//,
  qwen: /\/c\//,
  chatgpt: /\/(c|uc)\//,
  wenxin: /\/search\/|chat\.baidu\.com\//,
  zai: /\/c\//,
  zhipu: /chatglm\.cn\//,
};

function resumeInflight(tabId, url) {
  const job = inflight.get(tabId);
  const pattern = job && RESUME_PATHS[job.site];
  if (!job || !pattern || reported.has(job.request_id) || job.resumeSent) return;
  if (url && !pattern.test(String(url))) return;
  job.resumeSent = true;
  load().then(({ pairToken }) => {
    if (!pairToken) return;
    chrome.tabs.sendMessage(tabId, { type: "resume", job }, (result) => {
      if (chrome.runtime.lastError || !result) {
        job.resumeSent = false;
        return;
      }
      finishJob(pairToken, tabId, job, result);
    });
  });
}

async function report(token, job, result) {
  await fetch(`${BACKEND}/api/ext/jobs/result`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      request_id: job.request_id,
      run_id: job.run_id,
      group_id: job.group_id,
      member_id: job.member_id,
      context_version: job.context_version,
      text: result.text || "",
      model_label: result.model_label || "",
      status: result.status || "error",
      page_url: result.page_url || `${job.origin}/`,
      detail: result.detail || "",
    }),
  }).catch(() => {});
}

const STATIC_ORIGINS = new Set(["http://127.0.0.1:43124", "https://gemini.google.com"]);

function scriptId(origin) {
  return `room-${origin.replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "").slice(0, 60)}`;
}

const GUEST_ORIGINS = new Set([
  "https://chat.qwen.ai",
  "https://chatgpt.com",
  "https://chat.openai.com",
  "https://wenxin.baidu.com",
  "https://yiyan.baidu.com",
  "https://chat.baidu.com",
  "https://chatglm.cn",
  "https://chat.z.ai",
]);

const ADAPTER_FILES = ["adapters/schema.js", "adapters/registry.js", "adapters/runtime.js"];

function scriptFiles(origin) {
  if (origin === "https://chat.deepseek.com") return [...ADAPTER_FILES, "deepseek.js", "content.js"];
  if (origin === "https://www.doubao.com") return [...ADAPTER_FILES, "doubao.js", "content.js"];
  if (origin === "https://yuanbao.tencent.com") return [...ADAPTER_FILES, "yuanbao.js", "content.js"];
  if (GUEST_ORIGINS.has(origin)) return [...ADAPTER_FILES, "guest.js", "content.js"];
  return [...ADAPTER_FILES, "content.js"];
}

async function ensureScript(origin, tabId) {
  if (STATIC_ORIGINS.has(origin)) return { ok: true, how: "manifest" };
  const pattern = `${origin}/*`;
  const allowed = await chrome.permissions.contains({ origins: [pattern] });
  if (!allowed) return { ok: false, detail: "主机权限未授予，没有注册内容脚本" };
  const id = scriptId(origin);
  const files = scriptFiles(origin);
  const existing = await chrome.scripting.getRegisteredContentScripts({ ids: [id] });
  const current = existing[0];
  const same = current && Array.isArray(current.js) && current.js.join(",") === files.join(",");
  if (!same) {
    if (current) await chrome.scripting.unregisterContentScripts({ ids: [id] });
    await chrome.scripting.registerContentScripts([
      {
        id,
        matches: [pattern],
        js: files,
        runAt: "document_idle",
        persistAcrossSessions: true,
      },
    ]);
  }
  if (tabId) {
    // 已经注册过的站点，页面加载时脚本就在了；再 executeScript 会把同一批文件跑第二遍。先问一下，已装好就不再注入。
    let loaded = false;
    try {
      const [probe] = await chrome.scripting.executeScript({
        target: { tabId },
        func: (ver) => !!(globalThis.__chatclumerLoaded && globalThis.__chatclumerLoaded.content === ver && globalThis.ChatclumerAdapters && globalThis.ChatclumerAdapters.__version === ver),
        args: [chrome.runtime.getManifest().version],
      });
      loaded = !!(probe && probe.result);
    } catch {
      loaded = false;
    }
    if (!loaded) await chrome.scripting.executeScript({ target: { tabId }, files });
    return { ok: true, how: loaded ? "already" : "dynamic", id };
  }
  return { ok: true, how: "dynamic", id };
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "task-alive" && message.job) {
    const job = message.job;
    for (const [tabId, active] of inflight.entries()) {
      if (active.request_id === job.request_id) resumeInflight(tabId, "");
    }
    return;
  }
  if (message?.type === "job-progress") {
    load().then(async ({ pairToken }) => {
      if (!pairToken) return;
      await fetch(`${BACKEND}/api/ext/jobs/progress`, {
        method: "POST",
        headers: { Authorization: `Bearer ${pairToken}`, "Content-Type": "application/json" },
        body: JSON.stringify({ request_id: message.request_id, phase: message.phase, note: message.note || "" }),
      }).catch(() => {});
    });
    return;
  }
  if (message?.type === "registry-get") {
    chrome.storage.local.get(["registryRemote"]).then(({ registryRemote }) => {
      sendResponse(registryRemote && registryRemote.data ? { data: registryRemote.data, url: registryRemote.url } : null);
    });
    return true;
  }
  if (message?.type === "registry-refresh") {
    refreshRegistry(true).then(sendResponse);
    return true;
  }
  if (message?.type === "registry-set-url") {
    const url = String(message.url || "").trim();
    if (url && url !== "off" && !/^https:\/\/[^\s]+$/.test(url)) {
      sendResponse({ ok: false, detail: "只接受 https 地址，或填 off 关闭远端更新" });
      return true;
    }
    chrome.storage.local.set({ registryUrl: url }).then(() => refreshRegistry(true)).then(sendResponse);
    return true;
  }
  if (message?.type === "ensure-script") {
    ensureScript(message.origin, message.tabId).then(sendResponse).catch((err) => {
      sendResponse({ ok: false, detail: err?.message || "内容脚本没有装上" });
    });
    return true;
  }
  if (message?.type === "save-binding") {
    chrome.storage.local.get(["bindings"]).then(({ bindings }) => {
      const next = bindings || {};
      next[message.tab_key] = { tabId: message.tabId, origin: message.origin };
      chrome.storage.local.set({ bindings: next }).then(() => sendResponse({ ok: true }));
    });
    return true;
  }
  return undefined;
});

chrome.tabs.onUpdated.addListener((tabId, info, tab) => {
  if (!inflight.has(tabId)) return;
  const url = info.url || (tab && tab.url) || "";
  if (info.url || info.status === "complete") resumeInflight(tabId, url);
});

chrome.storage.session.get(["seenIds"]).then(({ seenIds }) => {
  for (const id of seenIds || []) seen.add(id);
  setInterval(poll, 1200);
  poll();
  refreshRegistry(false).catch(() => {});
  setInterval(() => refreshRegistry(false).catch(() => {}), 30 * 60 * 1000);
});
