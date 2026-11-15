// 适配器注册表的结构校验。只接受数据：选择器、正则文本、提示文字和少数开关。
// 任何不认识的键、函数、过长的字符串都会让整份注册表被拒，不会执行远端代码（符合 MV3 规则）。
// 同一份文件在后台 service worker（importScripts）、内容脚本和测试（node）里共用。
(function (root) {
  const MAX_BYTES = 96 * 1024;
  const MAX_STR = 400;
  const MAX_LIST = 12;
  const ROLE_KEYS = ["composer", "send", "stop", "users", "user_text", "assistants", "host", "body", "exclude", "done_near", "messages", "column"];
  const FLAG_KEYS = { writer: ["native", "exec"], guard_other: "bool", wait_send_enabled: "bool", click_center: "bool", click_inner: "sel", send_after_input: "bool" };
  const SITE_KEYS = ["engine", "label", "origins", "roles", "disabled", "stop_find", "flags", "placeholder_text", "streaming", "done", "conv_url", "gates", "error_texts"];
  const COMMON_KEYS = ["dialogs", "toasts", "captcha_boxes", "captcha", "login", "not_login"];
  const TOP_KEYS = ["schema", "schema_version", "version", "min_extension", "source", "common", "sites"];

  function str(value, max) {
    return typeof value === "string" && value.length > 0 && value.length <= (max || MAX_STR);
  }

  function regexOk(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) return false;
    const keys = Object.keys(value);
    if (keys.some((k) => k !== "source" && k !== "flags")) return false;
    if (!str(value.source)) return false;
    const flags = value.flags == null ? "" : value.flags;
    if (typeof flags !== "string" || !/^[imsu]{0,4}$/.test(flags)) return false;
    try {
      new RegExp(value.source, flags);
    } catch {
      return false;
    }
    return true;
  }

  function selList(value) {
    return Array.isArray(value) && value.length > 0 && value.length <= MAX_LIST && value.every((s) => str(s));
  }

  function condOk(cond, depth) {
    if (depth > 4 || !cond || typeof cond !== "object" || Array.isArray(cond)) return false;
    const keys = Object.keys(cond);
    if (keys.length === 1 && (keys[0] === "has" || keys[0] === "self")) return str(cond[keys[0]]);
    if (keys.length === 1 && keys[0] === "not") return condOk(cond.not, depth + 1);
    if (keys.length === 1 && (keys[0] === "all" || keys[0] === "any")) {
      const list = cond[keys[0]];
      return Array.isArray(list) && list.length > 0 && list.length <= MAX_LIST && list.every((c) => condOk(c, depth + 1));
    }
    if (keys.every((k) => ["closest", "attr", "equals"].includes(k)) && keys.length === 3) {
      return str(cond.closest) && str(cond.attr, 80) && typeof cond.equals === "string" && cond.equals.length <= 120;
    }
    return false;
  }

  function versionParts(v) {
    return String(v || "").split(".").map((n) => Number(n) || 0);
  }

  function compareVersion(a, b) {
    const x = versionParts(a);
    const y = versionParts(b);
    for (let i = 0; i < Math.max(x.length, y.length); i += 1) {
      const d = (x[i] || 0) - (y[i] || 0);
      if (d) return d > 0 ? 1 : -1;
    }
    return 0;
  }

  function siteErrors(id, site) {
    const errors = [];
    const bad = (why) => errors.push(`${id}: ${why}`);
    if (!site || typeof site !== "object" || Array.isArray(site)) return [`${id}: 不是对象`];
    for (const key of Object.keys(site)) if (!SITE_KEYS.includes(key)) bad(`不认识的键 ${key}`);
    if (site.engine !== "guest" && site.engine !== "builtin") bad("engine 只能是 guest 或 builtin");
    if (!str(site.label, 40)) bad("label");
    if (!Array.isArray(site.origins) || !site.origins.length || !site.origins.every((o) => typeof o === "string" && /^https:\/\/[a-z0-9.-]+$/.test(o))) bad("origins 必须是 https 源");
    const roles = site.roles;
    if (!roles || typeof roles !== "object" || Array.isArray(roles)) bad("roles");
    else {
      for (const [key, list] of Object.entries(roles)) {
        if (!ROLE_KEYS.includes(key)) bad(`不认识的角色 ${key}`);
        else if (!selList(list)) bad(`角色 ${key} 必须是 1–${MAX_LIST} 个选择器`);
      }
      if (!roles.composer || !roles.send) bad("缺 composer 或 send");
      if (site.engine === "guest" && (!roles.users || !roles.assistants || !roles.body)) bad("guest 站点缺 users/assistants/body");
    }
    if (site.disabled !== undefined && !condOk(site.disabled, 0)) bad("disabled 规则");
    if (site.done !== undefined && !condOk(site.done, 0)) bad("done 规则");
    if (site.streaming !== undefined) {
      if (!Array.isArray(site.streaming) || site.streaming.length > MAX_LIST) bad("streaming");
      else site.streaming.forEach((rule, i) => {
        const keys = Object.keys(rule || {});
        if (keys.some((k) => k !== "when" && k !== "value") || typeof rule.value !== "boolean" || !condOk(rule.when, 0)) bad(`streaming[${i}]`);
      });
    }
    if (site.stop_find !== undefined) {
      if (!Array.isArray(site.stop_find) || !site.stop_find.length || site.stop_find.length > MAX_LIST) bad("stop_find");
      else site.stop_find.forEach((f, i) => {
        const keys = Object.keys(f || {});
        const ok = str(f && f.sel) && keys.every((k) => ["sel", "closest", "attr", "pattern"].includes(k))
          && (f.closest === undefined || str(f.closest))
          && ((f.attr === undefined && f.pattern === undefined) || (str(f.attr, 80) && regexOk(f.pattern)));
        if (!ok) bad(`stop_find[${i}]`);
      });
    }
    if (site.flags !== undefined) {
      if (!site.flags || typeof site.flags !== "object" || Array.isArray(site.flags)) bad("flags");
      else for (const [key, value] of Object.entries(site.flags)) {
        const rule = FLAG_KEYS[key];
        if (!rule) bad(`不认识的开关 ${key}`);
        else if (rule === "bool" && typeof value !== "boolean") bad(`开关 ${key}`);
        else if (rule === "sel" && !str(value)) bad(`开关 ${key}`);
        else if (Array.isArray(rule) && !rule.includes(value)) bad(`开关 ${key}`);
      }
    }
    for (const key of ["placeholder_text", "conv_url"]) if (site[key] !== undefined && !regexOk(site[key])) bad(key);
    // 发出之后才出现的报错（人机验证、发送失败等）：只是正则文本加回报文字，在等待回复时检查。
    if (site.error_texts !== undefined) {
      if (!Array.isArray(site.error_texts) || site.error_texts.length > MAX_LIST) bad("error_texts");
      else site.error_texts.forEach((e, i) => {
        const keys = Object.keys(e || {});
        if (keys.some((k) => !["pattern", "detail"].includes(k)) || !regexOk(e.pattern) || !str(e.detail, 200)) bad(`error_texts[${i}]`);
      });
    }
    if (site.gates !== undefined) {
      if (!Array.isArray(site.gates) || site.gates.length > MAX_LIST) bad("gates");
      else site.gates.forEach((g, i) => {
        const keys = Object.keys(g || {});
        if (keys.some((k) => !["pattern", "where", "detail"].includes(k)) || !regexOk(g.pattern) || !["toast", "dialog", "page"].includes(g.where) || !str(g.detail, 200)) bad(`gates[${i}]`);
      });
    }
    return errors;
  }

  // 返回 { ok, errors }。extensionVersion 给出时还检查 min_extension。
  function validateRegistry(data, extensionVersion) {
    const errors = [];
    let size = 0;
    try {
      size = JSON.stringify(data).length;
    } catch {
      return { ok: false, errors: ["无法序列化"] };
    }
    if (size > MAX_BYTES) return { ok: false, errors: [`太大（${size} 字节）`] };
    if (!data || typeof data !== "object" || Array.isArray(data)) return { ok: false, errors: ["不是对象"] };
    for (const key of Object.keys(data)) if (!TOP_KEYS.includes(key)) errors.push(`不认识的键 ${key}`);
    if (data.schema !== "chatclumer.adapters") errors.push("schema 不对");
    if (data.schema_version !== 1) errors.push("schema_version 只支持 1");
    if (typeof data.version !== "string" || !/^\d{4}\.\d{1,2}\.\d{1,2}\.\d{1,4}$/.test(data.version)) errors.push("version 格式应为 YYYY.M.D.N");
    if (data.min_extension !== undefined && !/^\d+\.\d+\.\d+$/.test(String(data.min_extension))) errors.push("min_extension");
    if (extensionVersion && data.min_extension && compareVersion(extensionVersion, data.min_extension) < 0) errors.push(`需要扩展 ${data.min_extension} 以上`);
    if (data.source !== undefined && !str(data.source, 200)) errors.push("source");
    const common = data.common;
    if (!common || typeof common !== "object") errors.push("common");
    else {
      for (const key of Object.keys(common)) if (!COMMON_KEYS.includes(key)) errors.push(`common 里不认识的键 ${key}`);
      for (const key of ["dialogs", "toasts", "captcha_boxes"]) if (!selList(common[key])) errors.push(`common.${key}`);
      for (const key of ["captcha", "login", "not_login"]) if (!regexOk(common[key])) errors.push(`common.${key}`);
    }
    if (!data.sites || typeof data.sites !== "object" || Array.isArray(data.sites) || !Object.keys(data.sites).length) errors.push("sites");
    else for (const [id, site] of Object.entries(data.sites)) {
      if (!/^[a-z0-9_]{2,24}$/.test(id)) errors.push(`站点名 ${id}`);
      errors.push(...siteErrors(id, site));
    }
    return { ok: errors.length === 0, errors };
  }

  // 远端检查结果的缓存还能不能用：扩展版本、内置注册表版本或远端地址变了，缓存的比较就过时了（0.5.1 实页上弹窗
  // 还显示「远端 .1 不比内置 .1 新」，而内置早已是 .2）。超过间隔也要重新检查。
  function registryCacheFresh(status, ctx) {
    if (!status || !ctx) return false;
    if (status.extension !== ctx.extension) return false;
    if (status.bundled !== ctx.bundled) return false;
    if ((status.url || "") !== (ctx.url || "")) return false;
    const at = Date.parse(status.checked_at || "");
    if (!Number.isFinite(at)) return false;
    return (ctx.now == null ? Date.now() : ctx.now) - at < ctx.everyMs;
  }

  const api = { validateRegistry, compareVersion, registryCacheFresh };
  root.ChatclumerRegistrySchema = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
