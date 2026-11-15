"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const path = require("path");
const { DesktopHost, memoryStorage } = require("../host");
const { GUEST_ORIGINS, scriptFiles, sameSiteOrigin } = require("../sites");

const ROOT = path.join(__dirname, "..", "..");
const EXT = path.join(ROOT, "extension");
const EXT_VERSION = JSON.parse(fs.readFileSync(path.join(EXT, "manifest.json"), "utf8")).version;

function jsonResponse(status, body) {
  const text = body == null ? "" : typeof body === "string" ? body : JSON.stringify(body);
  return {
    ok: status >= 200 && status < 300,
    status,
    async text() {
      return text;
    },
  };
}

function createBackend() {
  const state = {
    code: "pair-code-secret",
    token: "tokensecret0123456789abcdef0123456789abcdef",
    used: false,
    jobs: [],
    results: [],
    progress: [],
    tabs: [],
    calls: [],
  };
  async function fetchImpl(url, options = {}) {
    const headers = options.headers || {};
    state.calls.push({ url: String(url), method: options.method || "GET", headers, body: options.body || "" });
    assert.equal(headers.Origin, undefined);
    assert.equal(headers.origin, undefined);
    const target = new URL(url);
    const auth = headers.Authorization || "";
    const bearer = auth.startsWith("Bearer ") ? auth.slice(7) : "";
    if (target.pathname === "/api/health") {
      return jsonResponse(200, { ok: true, service: "multi-llm-chat-room" });
    }
    if (target.pathname === "/api/ext/code") {
      return jsonResponse(200, { code: state.code });
    }
    if (target.pathname === "/api/ext/pair") {
      const payload = JSON.parse(options.body || "{}");
      if (state.used || payload.code !== state.code) return jsonResponse(401, { detail: "配对码无效或已用过" });
      state.used = true;
      return jsonResponse(200, { token: state.token });
    }
    if (target.pathname === "/api/ext/members/desktop-probe") {
      return bearer === state.token ? jsonResponse(404, { detail: "成员 ID 不存在" }) : jsonResponse(401, { detail: "配对无效" });
    }
    if (target.pathname === "/api/sessions") return jsonResponse(200, [{ id: "room-1" }]);
    if (target.pathname === "/api/sessions/room-1") {
      return jsonResponse(200, {
        members: [
          { id: "m-web", provider: "web", web_tab_key: "room-key", web_origin: "https://chat.baidu.com", web_site: "wenxin" },
          { id: "m-api", provider: "openai", web_tab_key: "", web_origin: "" },
        ],
      });
    }
    if (bearer !== state.token) return jsonResponse(401, { detail: "配对无效" });
    if (target.pathname === "/api/ext/jobs") return jsonResponse(200, { jobs: state.jobs });
    if (target.pathname === "/api/ext/jobs/result") {
      state.results.push(JSON.parse(options.body));
      return jsonResponse(200, { ok: true });
    }
    if (target.pathname === "/api/ext/jobs/progress") {
      state.progress.push(JSON.parse(options.body));
      return jsonResponse(200, { ok: true });
    }
    if (target.pathname === "/api/ext/tabs") {
      state.tabs.push(JSON.parse(options.body));
      return jsonResponse(200, { ok: true, updated: 1 });
    }
    return jsonResponse(404, { detail: "missing" });
  }
  return { state, fetchImpl };
}

function hostWith(backend, views, extra) {
  const logs = [];
  const host = new DesktopHost({
    backend: backend.url || "http://127.0.0.1:43124",
    fetchImpl: backend.fetchImpl,
    storage: memoryStorage(),
    extensionRoot: EXT,
    version: EXT_VERSION,
    views,
    log: (line) => logs.push(String(line)),
    ...extra,
  });
  return { host, logs };
}

test("script files follow the extension background", () => {
  const background = fs.readFileSync(path.join(EXT, "background.js"), "utf8");
  for (const origin of GUEST_ORIGINS) assert.ok(background.includes(`"${origin}"`), origin);
  assert.deepEqual(scriptFiles("https://chat.deepseek.com").slice(-2), ["deepseek.js", "content.js"]);
  assert.deepEqual(scriptFiles("https://www.doubao.com").slice(-2), ["doubao.js", "content.js"]);
  assert.deepEqual(scriptFiles("https://yuanbao.tencent.com").slice(-2), ["yuanbao.js", "content.js"]);
  assert.equal(scriptFiles("https://chat.qwen.ai").includes("guest.js"), true);
  assert.equal(scriptFiles("https://chat.baidu.com").includes("guest.js"), true);
  assert.equal(scriptFiles("https://gemini.google.com").includes("guest.js"), false);
  assert.equal(scriptFiles("https://gemini.google.com").at(-1), "content.js");
  assert.equal(sameSiteOrigin("https://wenxin.baidu.com", "https://yiyan.baidu.com"), true);
  assert.equal(sameSiteOrigin("https://chat.qwen.ai", "https://chatgpt.com"), false);
});

test("desktop sources do not extract cookies or reimplement the unsent phrase", () => {
  for (const name of ["main.js", "preload.js", "host.js", "boot.js", "launcher-preload.js", "sites.js"]) {
    const text = fs.readFileSync(path.join(__dirname, "..", name), "utf8");
    assert.equal(text.includes(".cookies"), false, name);
    assert.equal(text.includes("document.cookie"), false, name);
    assert.equal(text.includes("executeJavaScript"), false, name);
    assert.equal(text.includes("webRequest"), false, name);
    assert.equal(text.includes("setCertificateVerifyProc"), false, name);
    assert.equal(text.includes("已填入，未发送"), false, name);
  }
});

test("auto-pair, one send, heartbeat, and no secret in logs", async () => {
  const backend = createBackend();
  const prompt = "PROMPT-SECRET-句子";
  backend.state.jobs = [
    {
      request_id: "req-1",
      run_id: "run-1",
      group_id: "g1",
      member_id: "m1",
      context_version: 3,
      origin: "https://chat.qwen.ai",
      site: "qwen",
      tab_key: "qwen",
      prompt,
      action: "send",
    },
  ];
  const sent = [];
  const views = {
    list: () => [{ tabKey: "qwen", origin: "https://chat.qwen.ai", alive: true }],
    send: async (tabKey, message) => {
      sent.push(message);
      return { status: "complete", text: "回复", page_url: "https://chat.qwen.ai/c/abc", model_label: "页面" };
    },
    health: async () => ({ site: "qwen", ok: true, missing: [], roles: { composer: { found: 1, index: 0 } } }),
  };
  const { host, logs } = hostWith(backend, views);
  await host.tick();
  assert.equal(sent.length, 1);
  assert.equal(sent[0].type, "run");
  assert.equal(backend.state.results.length, 1);
  assert.equal(backend.state.results[0].status, "complete");
  assert.equal(backend.state.results[0].page_url, "https://chat.qwen.ai/c/abc");
  assert.equal(backend.state.tabs.length, 1);
  assert.equal(backend.state.tabs[0].tabs[0].health.site, "qwen");
  await host.tick();
  assert.equal(sent.length, 1);
  const blob = logs.join("\n");
  assert.equal(blob.includes(backend.state.token), false);
  assert.equal(blob.includes(backend.state.code), false);
  assert.equal(blob.includes(prompt), false);
  assert.equal(host.storage.dump().pairToken, backend.state.token);
  const authed = backend.state.calls.filter((call) => call.headers.Authorization);
  assert.ok(authed.length > 0);
  assert.ok(authed.every((call) => call.headers.Authorization === `Bearer ${backend.state.token}`));
});

test("same-site origin is accepted and a missing view is reported once", async () => {
  const backend = createBackend();
  backend.state.jobs = [
    {
      request_id: "req-wenxin",
      run_id: "run-w",
      group_id: "",
      member_id: "m2",
      context_version: 1,
      origin: "https://chat.baidu.com",
      site: "wenxin",
      tab_key: "wenxin",
      prompt: "hi",
      action: "send",
    },
    {
      request_id: "req-missing",
      run_id: "run-x",
      group_id: "",
      member_id: "m3",
      context_version: 1,
      origin: "https://chat.qwen.ai",
      site: "qwen",
      tab_key: "absent",
      prompt: "nope",
      action: "send",
    },
  ];
  const sent = [];
  const views = {
    list: () => [{ tabKey: "wenxin", origin: "https://wenxin.baidu.com", alive: true }],
    send: async (_tabKey, message) => {
      sent.push(message.type);
      return { status: "error", detail: "找不到输入框", page_url: "https://chat.baidu.com/" };
    },
    health: async () => null,
  };
  const { host } = hostWith(backend, views);
  await host.tick();
  assert.deepEqual(sent, ["run"]);
  const missing = backend.state.results.find((item) => item.request_id === "req-missing");
  assert.equal(missing.detail, "标签页绑定不匹配");
  assert.equal(missing.page_url, "https://chat.qwen.ai/");
});

test("cancel is delivered once and progress is forwarded", async () => {
  const backend = createBackend();
  backend.state.jobs = [
    {
      request_id: "req-c",
      run_id: "run-c",
      group_id: "",
      member_id: "m1",
      context_version: 1,
      origin: "https://chat.qwen.ai",
      site: "qwen",
      tab_key: "qwen",
      prompt: "",
      action: "cancel",
    },
  ];
  const sent = [];
  const views = {
    list: () => [{ tabKey: "qwen", origin: "https://chat.qwen.ai", alive: true }],
    send: async (_tabKey, message) => {
      sent.push(message);
      return null;
    },
    health: async () => null,
  };
  const { host } = hostWith(backend, views);
  await host.tick();
  await host.tick();
  assert.equal(sent.length, 1);
  assert.equal(sent[0].type, "cancel");
  await host.onContentMessage({ type: "job-progress", request_id: "req-c", phase: "unsent", note: "已填入，未发送" });
  assert.equal(backend.state.progress[0].phase, "unsent");
});

test("resume follows a conversation url and does not send again", async () => {
  const backend = createBackend();
  const { host } = hostWith(backend, {
    list: () => [],
    send: async () => ({ status: "complete", text: "续上", page_url: "https://chat.qwen.ai/c/new" }),
    health: async () => null,
  });
  host.token = backend.state.token;
  host.inflight.set("qwen", { request_id: "req-r", run_id: "run-r", group_id: "", member_id: "m", context_version: 1, origin: "https://chat.qwen.ai", site: "qwen" });
  await host.onNavigated("qwen", "https://chat.qwen.ai/");
  assert.equal(backend.state.results.length, 0);
  await host.onNavigated("qwen", "https://chat.qwen.ai/c/new");
  assert.equal(backend.state.results.length, 1);
  assert.equal(backend.state.results[0].text, "续上");
  await host.onNavigated("qwen", "https://chat.qwen.ai/c/new");
  assert.equal(backend.state.results.length, 1);
});

test("remote registry is cached only when newer and valid", async () => {
  const bundled = JSON.parse(fs.readFileSync(path.join(EXT, "adapters", "registry.json"), "utf8"));
  const calls = [];
  const fetchImpl = async (url) => {
    calls.push(String(url));
    if (String(url).startsWith("http://")) throw new Error("should not fetch http");
    const data = structuredClone(bundled);
    data.version = "2099.1.1.1";
    return jsonResponse(200, data);
  };
  const host = new DesktopHost({
    fetchImpl,
    storage: memoryStorage(),
    extensionRoot: EXT,
    version: EXT_VERSION,
    views: { list: () => [], send: async () => null, health: async () => null },
  });
  const newer = await host.refreshRegistry(true);
  assert.equal(newer.ok, true);
  assert.equal(host.registryRemote.data.version, "2099.1.1.1");

  host.storage.set("registryUrl", "off");
  const off = await host.refreshRegistry(true);
  assert.match(off.detail, /远端更新已关闭/);
  assert.equal(host.registryRemote, null);

  host.storage.set("registryUrl", "http://example.test/registry.json");
  const insecure = await host.refreshRegistry(true);
  assert.match(insecure.detail, /只接受 https/);
  assert.equal(calls.some((url) => url.startsWith("http://")), false);

  host.storage.set("registryUrl", "https://example.test/registry.json");
  const staleFetch = async () => jsonResponse(200, bundled);
  host.fetchImpl = staleFetch;
  const stale = await host.refreshRegistry(true);
  assert.match(stale.detail, /不比内置/);
  assert.equal(host.registryRemote, null);

  host.fetchImpl = async () => jsonResponse(200, "x".repeat(97 * 1024));
  const huge = await host.refreshRegistry(true);
  assert.match(huge.detail, /文件太大/);

  const broken = structuredClone(bundled);
  broken.version = "2099.1.1.2";
  broken.sites.qwen.script = "alert(1)";
  host.fetchImpl = async () => jsonResponse(200, broken);
  const rejected = await host.refreshRegistry(true);
  assert.match(rejected.detail, /结构不对/);
  assert.equal(host.registryRemote, null);
});

test("member tab keys are suggested only when unique", async () => {
  const backend = createBackend();
  const { host } = hostWith(backend, { list: () => [], send: async () => null, health: async () => null });
  await host.refreshMembers();
  assert.equal(host.suggestTabKey("https://yiyan.baidu.com"), "room-key");
  assert.deepEqual(host.tabKeysFor("https://chat.qwen.ai"), []);
  host.members.push({ id: "m2", web_tab_key: "other", web_origin: "https://wenxin.baidu.com", web_site: "wenxin" });
  assert.equal(host.suggestTabKey("https://chat.baidu.com"), "");
});
