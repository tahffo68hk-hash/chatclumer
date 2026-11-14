const BACKEND = "http://127.0.0.1:43124";
const seen = new Set();

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
    tabs.push({ tab_key: tabKey, origin: binding.origin, alive });
  }
  if (!tabs.length) return;
  await fetch(`${BACKEND}/api/ext/tabs`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ tabs }),
  }).catch(() => {});
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
    if (!binding || binding.origin !== job.origin) {
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
    chrome.tabs.sendMessage(binding.tabId, { type: "run", job }, (result) => {
      const body = result || { status: "error", detail: chrome.runtime.lastError?.message || "标签页没有响应" };
      report(pairToken, job, body);
    });
  }
  await beat(pairToken, bindings);
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

async function ensureScript(origin, tabId) {
  if (STATIC_ORIGINS.has(origin)) return { ok: true, how: "manifest" };
  const pattern = `${origin}/*`;
  const allowed = await chrome.permissions.contains({ origins: [pattern] });
  if (!allowed) return { ok: false, detail: "主机权限未授予，没有注册内容脚本" };
  const id = scriptId(origin);
  const existing = await chrome.scripting.getRegisteredContentScripts({ ids: [id] });
  if (!existing.length) {
    await chrome.scripting.registerContentScripts([
      {
        id,
        matches: [pattern],
        js: ["yuanbao.js", "content.js"],
        runAt: "document_idle",
        persistAcrossSessions: true,
      },
    ]);
  }
  if (tabId) await chrome.scripting.executeScript({ target: { tabId }, files: ["yuanbao.js", "content.js"] });
  return { ok: true, how: "dynamic", id };
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
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

chrome.storage.session.get(["seenIds"]).then(({ seenIds }) => {
  for (const id of seenIds || []) seen.add(id);
  setInterval(poll, 1200);
  poll();
});
