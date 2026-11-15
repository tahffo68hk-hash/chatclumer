"use strict";

const fs = require("fs");
const path = require("path");
const { sameSiteOrigin, sitesFromRegistry, RESUME_PATHS } = require("./sites");

const DEFAULT_REGISTRY_URL =
  "https://raw.githubusercontent.com/tahffo68hk-hash/chatclumer/main/extension/adapters/registry.json";
const REGISTRY_EVERY_MS = 6 * 60 * 60 * 1000;
const MAX_REGISTRY_BYTES = 96 * 1024;

function memoryStorage(initial) {
  const data = Object.assign({}, initial);
  return {
    get(key) {
      return data[key];
    },
    set(key, value) {
      data[key] = value;
    },
    dump() {
      return data;
    },
  };
}

class DesktopHost {
  constructor(options) {
    this.backend = String(options.backend || "http://127.0.0.1:43124").replace(/\/$/, "");
    this.fetchImpl = options.fetchImpl || globalThis.fetch.bind(globalThis);
    this.storage = options.storage || memoryStorage();
    this.extensionRoot = options.extensionRoot;
    this.version = options.version || "0.5.0";
    this.now = options.now || (() => Date.now());
    this.log = options.log || (() => {});
    this.views = options.views || { list: () => [], send: async () => null, health: async () => null };
    this.schema = options.schema || require(path.join(this.extensionRoot, "adapters", "schema.js"));
    this.bundled =
      options.bundled ||
      JSON.parse(fs.readFileSync(path.join(this.extensionRoot, "adapters", "registry.json"), "utf8"));
    this.token = this.storage.get("pairToken") || "";
    this.seen = new Set(this.storage.get("seenIds") || []);
    this.reported = new Set();
    this.inflight = new Map();
    this.healthAt = new Map();
    this.healthCache = new Map();
    this.registryRemote = this.storage.get("registryRemote") || null;
    this.registryStatus = this.storage.get("registryStatus") || null;
    this.members = [];
    this.backendUp = false;
  }

  siteList() {
    return sitesFromRegistry(this.bundled);
  }

  registryUrl() {
    const saved = this.storage.get("registryUrl");
    if (saved === "off") return "";
    return saved || DEFAULT_REGISTRY_URL;
  }

  async request(pathname, options = {}) {
    const headers = Object.assign({ Accept: "application/json" }, options.headers || {});
    if (options.auth !== false && this.token) headers.Authorization = `Bearer ${this.token}`;
    if (headers.Origin || headers.origin) throw new Error("桌面壳不能带 Origin");
    const response = await this.fetchImpl(this.backend + pathname, {
      method: options.method || "GET",
      headers,
      body: options.body,
      signal: options.signal,
    });
    const text = await response.text();
    let json = null;
    if (text) {
      try {
        json = JSON.parse(text);
      } catch {
        json = null;
      }
    }
    return { ok: response.ok, status: response.status, json, text };
  }

  async ping() {
    try {
      const res = await this.request("/api/health", { auth: false });
      this.backendUp = Boolean(res.ok && res.json && res.json.service === "multi-llm-chat-room");
    } catch {
      this.backendUp = false;
    }
    return this.backendUp;
  }

  async ensurePaired() {
    if (this.token) {
      // 用一个不存在的成员探测令牌。不要 GET /api/ext/jobs，那会把排队任务标成发送中。
      const probe = await this.request("/api/ext/members/desktop-probe");
      if (probe.status !== 401) return this.token;
      this.token = "";
      this.storage.set("pairToken", "");
    }
    const issued = await this.request("/api/ext/code", { method: "POST" });
    if (!issued.ok || !issued.json || !issued.json.code) {
      throw new Error(`取配对码失败（HTTP ${issued.status}）`);
    }
    const paired = await this.request("/api/ext/pair", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code: issued.json.code }),
    });
    if (!paired.ok || !paired.json || !paired.json.token) {
      throw new Error(`自动配对失败（HTTP ${paired.status}）`);
    }
    this.token = paired.json.token;
    this.storage.set("pairToken", this.token);
    this.log("已与本机后端配对");
    return this.token;
  }

  remember(id) {
    this.seen.add(id);
    const ids = [...this.seen].slice(-80);
    this.seen = new Set(ids);
    this.storage.set("seenIds", ids);
  }

  async poll() {
    let payload = await this.request("/api/ext/jobs");
    if (payload.status === 401) {
      this.token = "";
      this.storage.set("pairToken", "");
      await this.ensurePaired();
      payload = await this.request("/api/ext/jobs");
    }
    if (!payload.ok || !payload.json) return;
    const byKey = new Map(this.views.list().map((view) => [view.tabKey, view]));
    for (const job of payload.json.jobs || []) {
      if (job.action !== "cancel" && this.seen.has(job.request_id)) continue;
      const view = byKey.get(job.tab_key);
      if (!view || !sameSiteOrigin(view.origin, job.origin)) {
        this.remember(job.request_id);
        await this.report(job, { status: "error", detail: "标签页绑定不匹配", page_url: `${job.origin}/` });
        continue;
      }
      if (job.action === "cancel") {
        const cancelId = `cancel:${job.request_id}`;
        if (this.seen.has(cancelId)) continue;
        this.remember(cancelId);
        await this.views.send(view.tabKey, { type: "cancel", request_id: job.request_id });
        continue;
      }
      this.remember(job.request_id);
      this.inflight.set(view.tabKey, job);
      const result = await this.views.send(view.tabKey, { type: "run", job });
      if (!result) continue;
      await this.finishJob(view.tabKey, job, result);
    }
  }

  async finishJob(tabKey, job, result) {
    if (!job || this.reported.has(job.request_id)) return;
    if (result && result.detail === "这个标签页正在处理上一条") {
      job.resumeSent = false;
      return;
    }
    this.reported.add(job.request_id);
    this.inflight.delete(tabKey);
    await this.report(job, result || {});
  }

  async report(job, result) {
    await this.request("/api/ext/jobs/result", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        request_id: job.request_id,
        run_id: job.run_id,
        group_id: job.group_id,
        member_id: job.member_id,
        context_version: job.context_version,
        text: (result && result.text) || "",
        model_label: (result && result.model_label) || "",
        status: (result && result.status) || "error",
        page_url: (result && result.page_url) || `${job.origin}/`,
        detail: (result && result.detail) || "",
      }),
    });
  }

  async cachedHealth(view) {
    const last = this.healthAt.get(view.tabKey) || 0;
    if (this.now() - last < 30000 && this.healthCache.has(view.tabKey)) return this.healthCache.get(view.tabKey);
    const health = await this.views.health(view.tabKey);
    if (!health) return this.healthCache.get(view.tabKey) || null;
    this.healthAt.set(view.tabKey, this.now());
    this.healthCache.set(view.tabKey, health);
    return health;
  }

  async beat() {
    const tabs = [];
    for (const view of this.views.list()) {
      const entry = { tab_key: view.tabKey, origin: view.origin, alive: !!view.alive };
      if (view.alive) {
        const health = await this.cachedHealth(view);
        if (health) entry.health = health;
      }
      tabs.push(entry);
    }
    if (!tabs.length) return;
    await this.request("/api/ext/tabs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tabs }),
    });
  }

  async tick() {
    await this.ensurePaired();
    await this.poll();
    await this.beat();
  }

  async onNavigated(tabKey, url) {
    const job = this.inflight.get(tabKey);
    const pattern = job && RESUME_PATHS[job.site];
    if (!job || !pattern || this.reported.has(job.request_id) || job.resumeSent) return;
    if (url && !pattern.test(String(url))) return;
    job.resumeSent = true;
    const result = await this.views.send(tabKey, { type: "resume", job });
    if (!result) {
      job.resumeSent = false;
      return;
    }
    await this.finishJob(tabKey, job, result);
  }

  async onContentMessage(message) {
    if (!message || typeof message !== "object") return null;
    if (message.type === "registry-get") {
      const remote = this.registryRemote;
      return remote && remote.data ? { data: remote.data, url: remote.url } : null;
    }
    if (message.type === "job-progress") {
      if (!this.token) return null;
      await this.request("/api/ext/jobs/progress", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          request_id: message.request_id,
          phase: message.phase,
          note: message.note || "",
        }),
      });
      return null;
    }
    if (message.type === "task-alive" && message.job) {
      for (const [tabKey, job] of this.inflight) {
        if (job.request_id === message.job.request_id) await this.onNavigated(tabKey, "");
      }
      return null;
    }
    return null;
  }

  async refreshRegistry(force) {
    const url = this.registryUrl();
    if (!url) {
      const status = { checked_at: new Date(this.now()).toISOString(), ok: false, detail: "远端更新已关闭，只用内置注册表" };
      this.registryStatus = status;
      this.registryRemote = null;
      this.storage.set("registryStatus", status);
      this.storage.set("registryRemote", null);
      return status;
    }
    if (!force && this.registryStatus && this.now() - Date.parse(this.registryStatus.checked_at || 0) < REGISTRY_EVERY_MS) {
      return this.registryStatus;
    }
    const status = { checked_at: new Date(this.now()).toISOString(), url, ok: false, detail: "" };
    try {
      if (!/^https:\/\//.test(url)) throw new Error("只接受 https 地址");
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 10000);
      let response;
      try {
        response = await this.fetchImpl(url, { cache: "no-store", signal: controller.signal });
      } finally {
        clearTimeout(timer);
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const text = await response.text();
      if (text.length > MAX_REGISTRY_BYTES) throw new Error("文件太大");
      const data = JSON.parse(text);
      const checked = this.schema.validateRegistry(data, this.version);
      if (!checked.ok) throw new Error(`结构不对：${checked.errors.slice(0, 3).join("；")}`);
      if (this.schema.compareVersion(data.version, this.bundled.version) <= 0) {
        status.ok = true;
        status.version = this.bundled.version;
        status.detail = `远端 ${data.version} 不比内置 ${this.bundled.version} 新，用内置`;
        this.registryRemote = null;
        this.storage.set("registryRemote", null);
      } else {
        status.ok = true;
        status.version = data.version;
        status.detail = `已缓存远端注册表 ${data.version}（内置 ${this.bundled.version}）`;
        this.registryRemote = { data, url, fetched_at: status.checked_at };
        this.storage.set("registryRemote", this.registryRemote);
      }
    } catch (err) {
      status.detail = `没有更新：${err && err.message ? err.message : err}。继续用之前的缓存或内置注册表`;
    }
    this.registryStatus = status;
    this.storage.set("registryStatus", status);
    return status;
  }

  async refreshMembers() {
    const listed = await this.request("/api/sessions", { auth: false });
    if (!listed.ok || !Array.isArray(listed.json)) {
      this.members = [];
      return [];
    }
    const members = [];
    for (const session of listed.json) {
      if (!session || !session.id) continue;
      const detail = await this.request(`/api/sessions/${encodeURIComponent(session.id)}`, { auth: false });
      if (!detail.ok || !detail.json) continue;
      for (const member of detail.json.members || []) {
        if (member && member.provider === "web" && member.web_tab_key && member.web_origin) {
          members.push({
            id: member.id,
            web_tab_key: member.web_tab_key,
            web_origin: member.web_origin,
            web_site: member.web_site || "",
          });
        }
      }
    }
    this.members = members;
    return members;
  }

  tabKeysFor(origin) {
    const keys = [];
    for (const member of this.members || []) {
      if (sameSiteOrigin(member.web_origin, origin) && !keys.includes(member.web_tab_key)) keys.push(member.web_tab_key);
    }
    return keys;
  }

  suggestTabKey(origin) {
    const keys = this.tabKeysFor(origin);
    return keys.length === 1 ? keys[0] : "";
  }
}

module.exports = { DesktopHost, memoryStorage, DEFAULT_REGISTRY_URL };
