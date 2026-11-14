const BACKEND = "http://127.0.0.1:43124";

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
const ALLOWED = ["http://127.0.0.1:43124", "https://gemini.google.com", "https://chat.qwen.ai", "https://chatgpt.com", "https://chat.openai.com", "https://claude.ai", "https://grok.com", "https://chat.deepseek.com", "https://yuanbao.tencent.com", "https://chatglm.cn", "https://www.doubao.com"];

document.getElementById("bind").addEventListener("click", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const origin = new URL(tab.url).origin;
  if (!ALLOWED.includes(origin)) {
    document.getElementById("status").textContent = "这个站点不在允许列表";
    return;
  }
  const tabKey = document.getElementById("tabkey").value.trim();
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
    document.getElementById("status").textContent = `已绑定 ${origin}。${how}不会扫描其他标签页。`;
  });
});
