"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const path = require("path");
const zlib = require("zlib");
const { JSDOM } = require("jsdom");
const { createChrome, loadExtensionScripts } = require("../boot");
const { scriptFiles } = require("../sites");

const ROOT = path.join(__dirname, "..", "..");
const EXT = path.join(ROOT, "extension");
const FIX = path.join(ROOT, "backend", "tests", "fixtures", "real_dom");

const FIXTURES = [
  ["qwen-1-typed.html.gz", "qwen"],
  ["chatgpt-1-typed.html.gz", "chatgpt"],
  ["wenxin-1-typed.html.gz", "wenxin"],
  ["chatglm-1-typed.html.gz", "zhipu"],
  ["zai-1-typed.html.gz", "zai"],
  ["deepseek-1-typed.html.gz", "deepseek"],
];

function loadFixture(name) {
  const raw = zlib.gunzipSync(fs.readFileSync(path.join(FIX, name))).toString("utf8");
  const split = raw.indexOf("\n");
  const url = raw.slice(0, split).replace("<!-- url:", "").replace("-->", "").trim();
  return { url, html: raw.slice(split + 1) };
}

function bootFixture(name) {
  const { url, html } = loadFixture(name);
  const dom = new JSDOM(html, { url, contentType: "text/html", runScripts: "outside-only" });
  const context = dom.getInternalVMContext();
  const bridge = createChrome({
    version: "0.5.0",
    send: async () => null,
  });
  context.chrome = bridge.chrome;
  const origin = new URL(url).origin;
  loadExtensionScripts(context, EXT, scriptFiles(origin));
  return { context, bridge, url, origin };
}

test("preload health sees composer and send on real DOM fixtures", async () => {
  for (const [file, site] of FIXTURES) {
    const { bridge } = bootFixture(file);
    const health = await bridge.dispatch({ type: "health" });
    assert.equal(health.site, site, file);
    assert.ok(health.roles.composer.found > 0, `${file} composer`);
    assert.ok(health.roles.send.found > 0, `${file} send`);
    assert.equal(health.registry.version.length > 0, true);
  }
});

test("a repeated request is not sent again", async () => {
  const { context, bridge } = bootFixture("qwen-1-typed.html.gz");
  let clicks = 0;
  context.document.addEventListener("click", () => {
    clicks += 1;
  }, true);
  const job = { request_id: "once", site: "not-qwen", prompt: "你好", action: "send" };
  const first = await bridge.dispatch({ type: "run", job });
  const second = await bridge.dispatch({ type: "run", job });
  assert.equal(first.status, "error");
  assert.match(first.detail, /当前页和任务站点不一致/);
  assert.match(second.detail, /已经提交过/);
  assert.equal(clicks, 0);
});

test("qwen fixture: one write does not confirm, so the composer is cleared", async () => {
  const { context } = bootFixture("qwen-1-typed.html.gz");
  let clicks = 0;
  context.document.addEventListener("click", () => {
    clicks += 1;
  }, true);
  const prompt = "你好，请用一句话回答";
  const result = await context.guestDispatchSend("qwen", context.document, prompt, 700, () => false);
  assert.equal(result.ok, false);
  assert.match(result.detail, /已填入，未发送/);
  assert.ok(clicks <= 1, `clicked ${clicks} times`);
  const composer = context.document.querySelector("textarea.message-input-textarea, textarea[placeholder='Ask Qwen']");
  assert.ok(composer);
  assert.equal(composer.value, "");
});
