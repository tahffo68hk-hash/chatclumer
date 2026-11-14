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

document.getElementById("bind").addEventListener("click", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const origin = new URL(tab.url).origin;
  const allowed = ["http://127.0.0.1:43124", "https://gemini.google.com", "https://chat.qwen.ai", "https://chatgpt.com", "https://chat.openai.com", "https://claude.ai", "https://grok.com", "https://chat.deepseek.com", "https://yuanbao.tencent.com", "https://chatglm.cn", "https://www.doubao.com"];
  if (!allowed.includes(origin)) {
    document.getElementById("status").textContent = "这个站点不在允许列表";
    return;
  }
  const tabKey = document.getElementById("tabkey").value.trim();
  if (!tabKey) {
    document.getElementById("status").textContent = "先在房间里复制这个成员的绑定键";
    return;
  }
  chrome.runtime.sendMessage({ type: "save-binding", tab_key: tabKey, tabId: tab.id, origin }, () => {
    document.getElementById("status").textContent = `已绑定 ${origin}。不会扫描其他标签页。`;
  });
});
