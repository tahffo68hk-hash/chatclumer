"use strict";

// 和 extension/background.js 保持一致：哪些源算同一个绑定，每个源要加载哪些脚本。
// 桌面壳不复制各站的选择器；选择器只在 extension/adapters/registry.json。

const ADAPTER_FILES = ["adapters/schema.js", "adapters/registry.js", "adapters/runtime.js"];

const GUEST_ORIGINS = [
  "https://chat.qwen.ai",
  "https://chatgpt.com",
  "https://chat.openai.com",
  "https://wenxin.baidu.com",
  "https://yiyan.baidu.com",
  "https://chat.baidu.com",
  "https://chatglm.cn",
  "https://chat.z.ai",
];

const SAME_SITE = [
  ["https://wenxin.baidu.com", "https://chat.baidu.com", "https://yiyan.baidu.com"],
  ["https://chatgpt.com", "https://chat.openai.com"],
];

const RESUME_PATHS = {
  deepseek: /\/a\/chat\/s\//,
  qwen: /\/c\//,
  chatgpt: /\/(c|uc)\//,
  wenxin: /\/search\/|chat\.baidu\.com\//,
  zai: /\/c\//,
  zhipu: /chatglm\.cn\//,
};

function sameSiteOrigin(a, b) {
  if (!a || !b) return false;
  if (a === b) return true;
  return SAME_SITE.some((group) => group.includes(a) && group.includes(b));
}

function scriptFiles(origin) {
  if (origin === "https://chat.deepseek.com") return [...ADAPTER_FILES, "deepseek.js", "content.js"];
  if (origin === "https://www.doubao.com") return [...ADAPTER_FILES, "doubao.js", "content.js"];
  if (origin === "https://yuanbao.tencent.com") return [...ADAPTER_FILES, "yuanbao.js", "content.js"];
  if (GUEST_ORIGINS.includes(origin)) return [...ADAPTER_FILES, "guest.js", "content.js"];
  return [...ADAPTER_FILES, "content.js"];
}

function sitesFromRegistry(data) {
  const sites = data && data.sites ? data.sites : {};
  return Object.entries(sites).map(([id, site]) => ({
    id,
    label: site.label || id,
    engine: site.engine || "",
    origins: Array.isArray(site.origins) ? site.origins.slice() : [],
    home: (Array.isArray(site.origins) && site.origins[0] ? site.origins[0] : "https://invalid.invalid") + "/",
  }));
}

module.exports = {
  ADAPTER_FILES,
  GUEST_ORIGINS,
  SAME_SITE,
  RESUME_PATHS,
  sameSiteOrigin,
  scriptFiles,
  sitesFromRegistry,
};
