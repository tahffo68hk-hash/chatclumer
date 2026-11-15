// 注册表运行时：内置注册表 + 后台缓存的远端注册表（只是数据），页面检查和诊断导出。
// 页面检查只查找元素，不写入、不点击；诊断导出只留聊天栏的结构，文字一律打码。
(function () {
  if (globalThis.ChatclumerAdapters && globalThis.ChatclumerAdapters.__ready) return;
  const bundled = globalThis.CHATCLUMER_REGISTRY || { version: "0", sites: {}, common: {} };
  const schema = globalThis.ChatclumerRegistrySchema;
  let active = bundled;
  let source = "bundled";
  let note = "";

  function extensionVersion() {
    try {
      return chrome.runtime.getManifest().version;
    } catch {
      return "";
    }
  }

  function selectorOk(sel) {
    try {
      document.createDocumentFragment().querySelector(sel);
      return true;
    } catch {
      return false;
    }
  }

  function selectorsIn(value, out) {
    if (Array.isArray(value)) value.forEach((v) => selectorsIn(v, out));
    else if (value && typeof value === "object") {
      for (const [key, v] of Object.entries(value)) {
        if (["has", "self", "closest", "sel", "click_inner"].includes(key) && typeof v === "string") out.push(v);
        else if (key === "roles" || key === "common") selectorsIn(Object.values(v), out);
        else if (typeof v === "object") selectorsIn(v, out);
      }
    } else if (typeof value === "string") out.push(value);
    return out;
  }

  // 远端注册表：结构合法、版本比内置新、所有选择器都能解析，才会启用；否则继续用内置。
  function useRemote(data, url) {
    if (!schema) return { ok: false, detail: "缺少校验脚本" };
    const checked = schema.validateRegistry(data, extensionVersion());
    if (!checked.ok) {
      note = `远端注册表被拒：${checked.errors.slice(0, 3).join("；")}`;
      return { ok: false, detail: note };
    }
    if (schema.compareVersion(data.version, bundled.version) <= 0) {
      note = `远端注册表 ${data.version} 不比内置 ${bundled.version} 新，继续用内置`;
      return { ok: false, detail: note };
    }
    const sels = [];
    for (const site of Object.values(data.sites)) selectorsIn([site.roles, site.disabled, site.stop_find, site.streaming, site.done, site.flags], sels);
    selectorsIn([data.common.dialogs, data.common.toasts, data.common.captcha_boxes], sels);
    const broken = sels.filter((s) => !selectorOk(s));
    if (broken.length) {
      note = `远端注册表里有无法解析的选择器：${broken.slice(0, 3).join(" | ")}`;
      return { ok: false, detail: note };
    }
    active = data;
    source = url ? `remote:${url}` : "remote";
    note = "";
    return { ok: true, version: data.version };
  }

  function site(id) {
    return (active.sites && active.sites[id]) || (bundled.sites && bundled.sites[id]) || null;
  }

  function common() {
    return active.common || bundled.common || {};
  }

  function info() {
    return { version: active.version, source, bundled_version: bundled.version, note };
  }

  function visible(el) {
    if (!el) return false;
    const view = el.ownerDocument && el.ownerDocument.defaultView;
    const style = view && view.getComputedStyle ? view.getComputedStyle(el) : null;
    if (style && (style.display === "none" || style.visibility === "hidden")) return false;
    return el.getClientRects().length > 0;
  }

  const REQUIRED = ["composer", "send"];
  const CONVERSATION = ["users", "assistants", "messages", "body", "user_text"];

  // 页面检查（不发送）：逐个角色按顺序试选择器，报告第几个命中、命中几个。
  function health(id, root) {
    const scope = root || document;
    const spec = site(id);
    const base = { site: id, registry: info(), checked_at: new Date().toISOString(), url: location.origin + location.pathname };
    if (!spec) return { ...base, ok: false, missing: ["site"], roles: {}, detail: "注册表里没有这个站点" };
    const roles = {};
    for (const [role, list] of Object.entries(spec.roles || {})) {
      if (!REQUIRED.includes(role) && !CONVERSATION.includes(role)) continue;
      let hit = null;
      list.forEach((sel, index) => {
        if (hit) return;
        let nodes = [];
        try {
          nodes = [...scope.querySelectorAll(sel)];
        } catch {
          nodes = [];
        }
        if (nodes.length) hit = { found: nodes.length, index, selector: sel, visible: nodes.some(visible) };
      });
      roles[role] = hit || { found: 0, index: -1, selector: "", visible: false };
    }
    const missing = REQUIRED.filter((role) => !roles[role] || !roles[role].found);
    const empty = CONVERSATION.filter((role) => roles[role] && !roles[role].found);
    let gate = null;
    if (spec.engine === "guest" && typeof guestGate === "function") gate = guestGate(id, scope);
    const parts = [];
    if (missing.length) parts.push(`找不到：${missing.join("、")}`);
    if (empty.length) parts.push(`当前页面没有：${empty.join("、")}（新会话里正常）`);
    if (gate) parts.push(`门槛：${gate}`);
    return {
      ...base,
      label: spec.label,
      ok: missing.length === 0 && !gate,
      missing,
      empty,
      gate,
      roles,
      detail: parts.join("。") || "输入框、发送键都找到了",
    };
  }

  // 诊断导出：只取聊天栏（包含输入框和消息的最近公共祖先），去掉脚本、样式、图片地址和输入值，正文文字打码。
  const KEEP_ATTR = /^(class|id|role|type|disabled|contenteditable|placeholder|aria-[\w-]+|data-[\w-]+)$/i;
  const LABEL_HOSTS = "button, [role='button'], label, [aria-label]";

  function column(id, scope) {
    const spec = site(id);
    const first = (list) => {
      for (const sel of list || []) {
        try {
          const el = scope.querySelector(sel);
          if (el) return el;
        } catch {
          /* 忽略无效选择器 */
        }
      }
      return null;
    };
    if (spec && spec.roles && spec.roles.column) {
      const col = first(spec.roles.column);
      if (col) return col;
    }
    const composer = spec ? first(spec.roles.composer) : null;
    const message = spec ? first([...(spec.roles.assistants || []), ...(spec.roles.users || []), ...(spec.roles.messages || [])]) : null;
    if (composer && message) {
      let node = composer.parentElement;
      while (node && !node.contains(message)) node = node.parentElement;
      if (node && node !== document.documentElement) return node;
    }
    return scope.querySelector("main") || scope.body || scope;
  }

  function mask(text) {
    const n = Array.from(text).length;
    return n ? "▢".repeat(Math.min(n, 24)) + (n > 24 ? `…(${n})` : "") : "";
  }

  function dump(id, root) {
    const scope = root || document;
    const col = column(id, scope);
    const clone = col.cloneNode(true);
    clone.querySelectorAll("script, style, link, noscript, iframe, canvas, video, audio, picture source, template").forEach((el) => el.remove());
    clone.querySelectorAll("svg").forEach((el) => {
      el.innerHTML = "";
    });
    const all = [clone, ...clone.querySelectorAll("*")];
    for (const el of all) {
      if (!el.attributes) continue;
      for (const attr of [...el.attributes]) {
        if (!KEEP_ATTR.test(attr.name)) el.removeAttribute(attr.name);
        // data-* 里可能带正文（文心的 data-query 就是用户问题）：只留短的 ASCII 标识，比如状态值 GENERATING。
        else if (/^data-/i.test(attr.name) && !/^[\w.:-]{0,32}$/.test(attr.value)) el.setAttribute(attr.name, mask(attr.value));
        else if (/^(placeholder|aria-label)$/i.test(attr.name) && attr.value.length > 40) el.setAttribute(attr.name, mask(attr.value));
      }
      if (el.tagName === "TEXTAREA" || el.tagName === "INPUT") {
        el.textContent = "";
        el.removeAttribute("value");
      }
    }
    const comments = document.createTreeWalker(clone, 128);
    const dead = [];
    for (let c = comments.nextNode(); c; c = comments.nextNode()) dead.push(c);
    dead.forEach((c) => c.remove());
    const walker = document.createTreeWalker(clone, 4);
    const texts = [];
    let node = walker.nextNode();
    while (node) {
      texts.push(node);
      node = walker.nextNode();
    }
    for (const t of texts) {
      const raw = (t.nodeValue || "").trim();
      if (!raw) continue;
      const host = t.parentElement;
      const ui = host && host.closest && host.closest(LABEL_HOSTS) && Array.from(raw).length <= 16;
      t.nodeValue = ui ? raw : mask(raw);
    }
    const meta = {
      site: id,
      page: location.origin + location.pathname,
      saved_at: new Date().toISOString(),
      registry: info(),
      health: health(id, scope),
      note: "聊天栏结构快照。正文已打码，只保留按钮等短界面文字；没有 Cookie、输入值、图片地址和查询参数。",
    };
    const html = `<!-- chatclumer-dump ${JSON.stringify(meta).replace(/--/g, "- -")} -->\n${clone.outerHTML}`;
    return { html: html.slice(0, 2 * 1024 * 1024), meta };
  }

  globalThis.ChatclumerAdapters = { __ready: true, site, common, info, useRemote, health, dump, bundled: () => bundled };

  try {
    chrome.runtime.sendMessage({ type: "registry-get" }, (resp) => {
      void (chrome.runtime && chrome.runtime.lastError);
      if (resp && resp.data) useRemote(resp.data, resp.url);
    });
  } catch {
    /* 测试页或后台不在时只用内置注册表 */
  }

  try {
    chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
      if (!message || (message.type !== "health" && message.type !== "dump")) return undefined;
      const id = typeof siteFrom === "function" ? siteFrom(location.href) : message.site;
      if (message.type === "health") sendResponse(health(id || message.site || "", document));
      else sendResponse(dump(id || message.site || "", document));
      return true;
    });
  } catch {
    /* 同上 */
  }
})();
