// node --test server/  —— 手机/局域网认证层的单测。用假的 req/res，直接给出 socket 地址。
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { COOKIE, FailLimiter, createMobileGate, isLoopback, lanAddresses, safeEqual, sessionValue } from "./mobile-auth.mjs";

const PORT = 43123;
const PHONE = "192.168.1.23";

function setup(opts = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cc-mobile-"));
  let t = 1_000_000;
  const limiter = new FailLimiter({ maxFails: 3, windowMs: 60_000, now: () => t });
  const gate = createMobileGate({ dataDir: dir, port: PORT, version: "9.9.9", lan: true, limiter, ...opts });
  const token = gate.store.read();
  return { dir, gate, token, limiter, tick: (ms) => { t += ms; } };
}

function call(gate, { ip = PHONE, url = "/", method = "GET", headers = {} } = {}) {
  const req = { url, method, headers: { host: `${ip}:${PORT}`, ...headers }, rawHeaders: [], socket: { remoteAddress: ip } };
  for (const [k, v] of Object.entries(req.headers)) req.rawHeaders.push(k, v);
  const res = { status: 0, headers: {}, body: "", writeHead(s, h) { this.status = s; this.headers = h || {}; }, end(b) { this.body = String(b ?? ""); } };
  const handled = gate.handle(req, res);
  return { handled, req, res, json: () => JSON.parse(res.body) };
}

test("token is generated on first LAN start, URL-safe, >=128 bit, file is private", () => {
  const { dir, token } = setup();
  assert.match(token, /^[A-Za-z0-9_-]{43}$/);
  const file = path.join(dir, "mobile_token.json");
  assert.ok(fs.existsSync(file));
  if (process.platform !== "win32") assert.equal(fs.statSync(file).mode & 0o077, 0);
});

test("loopback requests pass through unauthenticated", () => {
  const { gate } = setup();
  for (const ip of ["127.0.0.1", "::1", "::ffff:127.0.0.1"]) {
    const r = call(gate, { ip, url: "/backend/api/sessions" });
    assert.equal(r.handled, false, ip);
  }
});

test("non-loopback without credentials: 401 JSON for API/SSE, HTML page for pages", () => {
  const { gate } = setup();
  const api = call(gate, { url: "/backend/api/sessions" });
  assert.equal(api.res.status, 401);
  assert.equal(api.json().detail, "unauthorized");
  const sse = call(gate, { url: "/backend/api/sessions/x/events", headers: { accept: "text/event-stream" } });
  assert.equal(sse.res.status, 401);
  const page = call(gate, { url: "/", headers: { accept: "text/html" } });
  assert.equal(page.res.status, 401);
  assert.match(page.res.headers["Content-Type"], /text\/html/);
  assert.match(page.res.body, /手机连接/);
  const asset = call(gate, { url: "/_next/static/chunks/a.js" });
  assert.equal(asset.res.status, 401);
});

test("spoofed X-Forwarded-For from a phone does not count as loopback", () => {
  const { gate } = setup();
  const r = call(gate, { url: "/backend/api/sessions", headers: { "x-forwarded-for": "127.0.0.1", "x-real-ip": "127.0.0.1", forwarded: "for=127.0.0.1" } });
  assert.equal(r.res.status, 401);
});

test("pair sets HttpOnly SameSite=Lax cc_session cookie and redirects to /; cookie then works", () => {
  const { gate, token } = setup();
  const r = call(gate, { url: `/m/pair?token=${token}` });
  assert.equal(r.res.status, 302);
  assert.equal(r.res.headers.Location, "/");
  const cookie = r.res.headers["Set-Cookie"];
  assert.match(cookie, new RegExp(`^${COOKIE}=`));
  assert.match(cookie, /HttpOnly/);
  assert.match(cookie, /SameSite=Lax/);
  assert.match(cookie, /Max-Age=\d{6,}/);
  assert.ok(!cookie.includes(token), "cookie must not contain the raw token");
  const value = cookie.split(";")[0].split("=")[1];
  const ok = call(gate, { url: "/backend/api/sessions", headers: { cookie: `a=1; ${COOKIE}=${value}` } });
  assert.equal(ok.handled, false);
  assert.equal(ok.req.headers.cookie, "a=1", "cc_session is stripped before Next/backend");
});

test("bearer token works and is stripped before proxying", () => {
  const { gate, token } = setup();
  const r = call(gate, { url: "/backend/api/sessions", headers: { authorization: `Bearer ${token}`, "x-forwarded-for": "1.2.3.4" } });
  assert.equal(r.handled, false);
  assert.equal(r.req.headers.authorization, undefined);
  assert.equal(r.req.headers["x-forwarded-for"], undefined);
  assert.ok(!r.req.rawHeaders.includes(`Bearer ${token}`));
});

test("wrong token rejected; distinct wrong attempts are rate limited per IP, then window expires", () => {
  const { gate, token, tick } = setup();
  assert.equal(call(gate, { url: "/m/pair?token=nope1" }).res.status, 401);
  assert.equal(call(gate, { url: "/backend/api/x", headers: { authorization: "Bearer nope2" } }).res.status, 401);
  assert.equal(call(gate, { url: "/m/pair?token=nope3" }).res.status, 401);
  // 已到上限：即使给对口令也先拒绝
  const locked = call(gate, { url: `/m/pair?token=${token}` });
  assert.equal(locked.res.status, 429);
  assert.ok(Number(locked.res.headers["Retry-After"]) > 0);
  assert.equal(call(gate, { url: "/backend/api/x", headers: { authorization: `Bearer ${token}` } }).res.status, 429);
  // 别的 IP 不受影响
  assert.equal(call(gate, { ip: "192.168.1.99", url: `/m/pair?token=${token}` }).res.status, 302);
  tick(61_000);
  assert.equal(call(gate, { url: `/m/pair?token=${token}` }).res.status, 302);
});

test("repeating the same stale credential does not lock the phone out", () => {
  const { gate, token } = setup();
  for (let i = 0; i < 10; i++) call(gate, { url: "/", headers: { cookie: `${COOKIE}=stale` } });
  const r = call(gate, { url: "/", headers: { cookie: `${COOKIE}=stale`, accept: "text/html" } });
  assert.equal(r.res.status, 401);
  assert.match(r.res.headers["Set-Cookie"], /Max-Age=0/);
  assert.equal(call(gate, { url: `/m/pair?token=${token}` }).res.status, 302);
});

test("rotation invalidates old cookies and bearer", () => {
  const { gate, token } = setup();
  const oldCookie = sessionValue(token);
  gate.store.rotate();
  const fresh = gate.store.read();
  assert.notEqual(fresh, token);
  assert.equal(call(gate, { url: "/backend/api/x", headers: { cookie: `${COOKIE}=${oldCookie}` } }).res.status, 401);
  assert.equal(call(gate, { url: "/backend/api/x", headers: { authorization: `Bearer ${token}` } }).res.status, 401);
  assert.equal(call(gate, { url: "/backend/api/x", headers: { authorization: `Bearer ${fresh}` } }).handled, false);
});

test("ping shape, no secrets, auth flag reflects authorisation", () => {
  const { gate, token } = setup();
  const anon = call(gate, { url: "/m/ping" });
  assert.equal(anon.res.status, 200);
  assert.deepEqual(anon.json(), { app: "chatclumer", version: "9.9.9", auth: false });
  assert.deepEqual(call(gate, { url: "/m/ping", headers: { authorization: `Bearer ${token}` } }).json(), { app: "chatclumer", version: "9.9.9", auth: true });
  assert.equal(call(gate, { ip: "127.0.0.1", url: "/m/ping" }).json().auth, true);
  assert.ok(!anon.res.body.includes(token));
});

test("ping counts wrong bearer guesses toward the rate limit (no free oracle)", () => {
  const { gate, token } = setup();
  for (const g of ["g1", "g2", "g3"]) call(gate, { url: "/m/ping", headers: { authorization: `Bearer ${g}` } });
  assert.equal(call(gate, { url: "/m/ping", headers: { authorization: `Bearer ${token}` } }).json().auth, false);
});

test("info/rotate are loopback-only, require loopback Host, rotate needs X-CC-Local", () => {
  const ifaces = { eth0: [{ family: "IPv4", address: "192.168.1.5", internal: false }], tailscale0: [{ family: "IPv4", address: "100.101.2.3", internal: false }] };
  const { gate, token } = setup({ ifaces });
  assert.equal(call(gate, { url: "/m/info", headers: { authorization: `Bearer ${token}` } }).res.status, 403);
  assert.equal(call(gate, { ip: "127.0.0.1", url: "/m/info", headers: { host: "evil.example:43123" } }).res.status, 403);
  const info = call(gate, { ip: "127.0.0.1", url: "/m/info", headers: { host: `127.0.0.1:${PORT}` } });
  assert.equal(info.res.status, 200);
  const body = info.json();
  assert.equal(body.addresses[0].base, "http://192.168.1.5:43123");
  assert.equal(body.addresses[0].app_payload, `chatclumer://pair?u=${encodeURIComponent("http://192.168.1.5:43123")}&t=${token}`);
  assert.equal(body.addresses[0].web_link, `http://192.168.1.5:43123/m/pair?token=${token}`);
  assert.equal(body.addresses[1].kind, "tailscale");
  assert.equal(call(gate, { ip: "127.0.0.1", url: "/m/rotate", method: "POST", headers: { host: `localhost:${PORT}` } }).res.status, 403);
  const rot = call(gate, { ip: "127.0.0.1", url: "/m/rotate", method: "POST", headers: { host: `localhost:${PORT}`, "x-cc-local": "1" } });
  assert.equal(rot.res.status, 200);
  assert.notEqual(gate.store.read(), token);
});

test("manifest and icons are public so Add-to-Home-Screen works before pairing", () => {
  const { gate } = setup();
  for (const url of ["/manifest.webmanifest", "/icons/icon-192.png", "/apple-touch-icon.png"]) {
    assert.equal(call(gate, { url }).handled, false, url);
  }
});

test("websocket upgrade (dev HMR) requires auth from non-loopback", () => {
  const { gate, token } = setup();
  const mk = (ip, headers = {}) => ({ headers, rawHeaders: [], socket: { remoteAddress: ip } });
  assert.equal(gate.allowUpgrade(mk(PHONE)), false);
  assert.equal(gate.allowUpgrade(mk("127.0.0.1")), true);
  assert.equal(gate.allowUpgrade(mk(PHONE, { cookie: `${COOKIE}=${sessionValue(token)}` })), true);
});

test("helpers: loopback detection, constant-time compare, address filtering", () => {
  assert.ok(isLoopback("127.0.0.1") && isLoopback("::1") && isLoopback("::ffff:127.0.0.5"));
  assert.ok(!isLoopback("192.168.1.2") && !isLoopback("0.0.0.0") && !isLoopback(""));
  assert.ok(safeEqual("abc", "abc") && !safeEqual("abc", "abd") && !safeEqual("", ""));
  const out = lanAddresses({
    docker0: [{ family: "IPv4", address: "172.17.0.1", internal: false }],
    lo: [{ family: "IPv4", address: "127.0.0.1", internal: true }],
    en0: [{ family: "IPv4", address: "10.0.0.8", internal: false }, { family: "IPv6", address: "fe80::1", internal: false }],
    wan: [{ family: "IPv4", address: "8.8.8.8", internal: false }],
  });
  assert.deepEqual(out.map((a) => a.ip), ["10.0.0.8"]);
});

test("non-LAN start does not create a token; pair then explains mobile mode is off", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cc-mobile-"));
  const gate = createMobileGate({ dataDir: dir, port: PORT, version: "1", lan: false });
  assert.equal(gate.store.read(), null);
  const r = call(gate, { url: "/m/pair?token=x" });
  assert.equal(r.res.status, 401);
  assert.match(r.res.body, /LAN=1/);
});
