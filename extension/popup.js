const BACKEND = "http://127.0.0.1:43124";

chrome.storage.local.get(["memberId", "tabKey"]).then(({ memberId, tabKey }) => {
  if (memberId) document.getElementById("member").value = memberId;
  if (tabKey) document.getElementById("tabkey").value = tabKey;
});

function rememberFields() {
  chrome.storage.local.set({
    memberId: document.getElementById("member").value.trim(),
    tabKey: document.getElementById("tabkey").value.trim(),
  });
}

document.getElementById("member").addEventListener("change", rememberFields);
document.getElementById("tabkey").addEventListener("change", rememberFields);

document.getElementById("pair").addEventListener("click", async () => {
  const code = document.getElementById("code").value.trim();
  const response = await fetch(`${BACKEND}/api/ext/pair`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
  const data = await response.json();
  if (!response.ok) {
    document.getElementById("paired").textContent = "配对失败";
    return;
  }
  await chrome.storage.local.set({ pairToken: data.token });
  document.getElementById("paired").textContent = "已配对。令牌只留在这个浏览器里。";
  document.getElementById("code").value = "";
});

const STATIC_ORIGINS = new Set(["http://127.0.0.1:43124", "https://gemini.google.com"]);
const ALLOWED = ["http://127.0.0.1:43124", "https://gemini.google.com", "https://chat.qwen.ai", "https://chatgpt.com", "https://chat.openai.com", "https://claude.ai", "https://grok.com", "https://chat.deepseek.com", "https://yuanbao.tencent.com", "https://chatglm.cn", "https://www.doubao.com", "https://wenxin.baidu.com", "https://yiyan.baidu.com", "https://chat.baidu.com", "https://chat.z.ai"];

document.getElementById("bind").addEventListener("click", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const origin = new URL(tab.url).origin;
  if (!ALLOWED.includes(origin)) {
    document.getElementById("status").textContent = "这个站点不在允许列表";
    return;
  }
  rememberFields();
  const memberId = document.getElementById("member").value.trim();
  const tabKey = document.getElementById("tabkey").value.trim();
  if (!memberId) {
    document.getElementById("status").textContent = "先填写成员 ID";
    return;
  }
  const { pairToken } = await chrome.storage.local.get(["pairToken"]);
  if (!pairToken) {
    document.getElementById("status").textContent = "先配对";
    return;
  }
  const found = await fetch(`${BACKEND}/api/ext/members/${encodeURIComponent(memberId)}`, {
    headers: { Authorization: `Bearer ${pairToken}` },
  });
  if (found.status === 404) {
    document.getElementById("status").textContent = "成员 ID 不存在";
    return;
  }
  if (!tabKey) {
    document.getElementById("status").textContent = "先在房间里复制这个成员的绑定键";
    return;
  }
  if (!STATIC_ORIGINS.has(origin)) {
    const granted = await chrome.permissions.request({ origins: [`${origin}/*`] });
    if (!granted) {
      document.getElementById("status").textContent = "没有授予这个站点，内容脚本不会注入";
      return;
    }
  }
  const ready = await chrome.runtime.sendMessage({ type: "ensure-script", origin, tabId: tab.id });
  if (!ready?.ok) {
    document.getElementById("status").textContent = ready?.detail || "内容脚本没有装上";
    return;
  }
  chrome.runtime.sendMessage({ type: "save-binding", tab_key: tabKey, tabId: tab.id, origin }, () => {
    const how = ready.how === "dynamic" ? "已为这个站点注册内容脚本。" : "这个站点使用清单里的内容脚本。";
    document.getElementById("status").textContent = `已绑定 ${origin}。${how}房间要等扩展心跳后才显示已绑定标签页。`;
  });
});

// 页面检查和诊断快照：都在当前标签页里执行，先确认内容脚本已装上（需要该站点的主机权限）。
async function currentTabReady() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const origin = new URL(tab.url).origin;
  if (!ALLOWED.includes(origin)) return { error: "这个站点不在允许列表" };
  if (!STATIC_ORIGINS.has(origin)) {
    const granted = await chrome.permissions.request({ origins: [`${origin}/*`] });
    if (!granted) return { error: "没有授予这个站点，无法检查" };
  }
  const ready = await chrome.runtime.sendMessage({ type: "ensure-script", origin, tabId: tab.id });
  if (!ready?.ok) return { error: ready?.detail || "内容脚本没有装上" };
  return { tab, origin };
}

function describeHealth(h) {
  if (!h) return "页面没有回应";
  const lines = [`${h.label || h.site}：${h.ok ? "通过" : "有问题"}（注册表 ${h.registry?.version || "?"}，${h.registry?.source || ""}）`, h.detail || ""];
  for (const [role, r] of Object.entries(h.roles || {})) {
    lines.push(`  ${role}: ${r.found ? `命中 ${r.found} 个（第 ${r.index + 1} 个选择器）` : "没找到"}`);
  }
  if (h.registry?.note) lines.push(h.registry.note);
  return lines.join("\n");
}

document.getElementById("health").addEventListener("click", async () => {
  const out = document.getElementById("health-out");
  const ready = await currentTabReady();
  if (ready.error) {
    out.textContent = ready.error;
    return;
  }
  chrome.tabs.sendMessage(ready.tab.id, { type: "health" }, (h) => {
    out.textContent = chrome.runtime.lastError ? "页面没有回应" : describeHealth(h);
  });
});

document.getElementById("dump").addEventListener("click", async () => {
  const out = document.getElementById("health-out");
  const ready = await currentTabReady();
  if (ready.error) {
    out.textContent = ready.error;
    return;
  }
  chrome.tabs.sendMessage(ready.tab.id, { type: "dump" }, (result) => {
    if (chrome.runtime.lastError || !result || !result.html) {
      out.textContent = "没有拿到快照";
      return;
    }
    const blob = new Blob([result.html], { type: "text/html" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `chatclumer-dump-${result.meta.site || "site"}-${Date.now()}.html`;
    a.click();
    out.textContent = `已导出 ${result.meta.site} 聊天栏快照（正文已打码）。\n${describeHealth(result.meta.health)}`;
  });
});

function showRegistry(status) {
  const el = document.getElementById("registry");
  const version = chrome.runtime.getManifest().version;
  el.textContent = status
    ? `扩展 ${version}。${status.detail || ""}（${status.checked_at || ""}）`
    : `扩展 ${version}。还没有检查过远端注册表。`;
}

chrome.storage.local.get(["registryStatus", "registryUrl"]).then(({ registryStatus, registryUrl }) => {
  showRegistry(registryStatus);
  document.getElementById("registry-url").value = registryUrl || "";
  document.getElementById("registry-url").placeholder = "默认：chatclumer 仓库里的 registry.json";
});

document.getElementById("registry-save").addEventListener("click", async () => {
  const url = document.getElementById("registry-url").value.trim();
  const status = await chrome.runtime.sendMessage({ type: "registry-set-url", url });
  showRegistry(status);
});
