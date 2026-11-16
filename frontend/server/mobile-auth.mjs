// 手机/局域网访问的认证层。只在自定义 Node 服务器里使用，那里能看到真实的 socket 地址。
// 不信任客户端发来的 X-Forwarded-For / X-Real-IP / Forwarded。
import { spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export const COOKIE = "cc_session";
const COOKIE_MAX_AGE = 400 * 24 * 3600; // Chrome 上限 400 天
const PUBLIC_PATHS = new Set(["/m/ping", "/m/pair", "/manifest.webmanifest", "/favicon.ico", "/apple-touch-icon.png", "/m/style.css"]);
const PUBLIC_PREFIXES = ["/icons/"];
const LOCAL_ONLY = new Set(["/m/info", "/m/rotate"]);
const STRIP_HEADERS = ["x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-forwarded-port", "x-real-ip", "forwarded"];

const WINDOWS_RESTRICT = `
$ErrorActionPreference = 'Stop'
$path = $env:CHAT_ROOM_PRIVATE_FILE
$acl = Get-Acl -LiteralPath $path
$acl.SetAccessRuleProtection($true, $false)
foreach ($rule in @($acl.Access)) { [void]$acl.RemoveAccessRule($rule) }
$me = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule($me, 'Modify', 'Allow')
[void]$acl.AddAccessRule($rule)
Set-Acl -LiteralPath $path -AclObject $acl
`;

const WINDOWS_CHECK = `
$ErrorActionPreference = 'Stop'
$path = $env:CHAT_ROOM_PRIVATE_FILE
$acl = Get-Acl -LiteralPath $path
if (-not $acl.AreAccessRulesProtected) { exit 2 }
$me = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$rules = @($acl.Access)
if ($rules.Count -ne 1) { exit 3 }
$sid = $rules[0].IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
if ($sid -ne $me) { exit 4 }
if ([string]$rules[0].AccessControlType -ne 'Allow') { exit 5 }
exit 0
`;

function powershell(script, file) {
  return spawnSync(
    "powershell",
    ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
    { env: { ...process.env, CHAT_ROOM_PRIVATE_FILE: file } },
  );
}

export function protectPrivateFile(file) {
  if (process.platform !== "win32") {
    fs.chmodSync(file, 0o600);
    return;
  }
  const result = powershell(WINDOWS_RESTRICT, file);
  if (result.status !== 0) throw new Error("没有收紧本机口令文件的权限");
}

export function fileIsOwnerOnly(file) {
  if (process.platform !== "win32") return (fs.statSync(file).mode & 0o077) === 0;
  return powershell(WINDOWS_CHECK, file).status === 0;
}

export function normalizeIp(addr) {
  if (!addr) return "";
  let ip = String(addr);
  if (ip.startsWith("::ffff:")) ip = ip.slice(7);
  return ip;
}

export function isLoopback(addr) {
  const ip = normalizeIp(addr);
  return ip === "::1" || /^127\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(ip);
}

function digest(value) {
  return crypto.createHash("sha256").update(String(value), "utf8").digest();
}

export function safeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || !a || !b) return false;
  // 先各自取摘要再比较，长度固定，比较时间不随内容变化。
  return crypto.timingSafeEqual(digest(a), digest(b));
}

export function newToken() {
  return crypto.randomBytes(32).toString("base64url"); // 256 bit，URL 安全
}

export function sessionValue(token) {
  return crypto.createHmac("sha256", token).update("cc_session:v1").digest("base64url");
}

export function mask(token) {
  if (!token) return "";
  return `${token.slice(0, 4)}…${token.slice(-2)}`;
}

function parseCookies(header) {
  const out = {};
  for (const part of String(header || "").split(";")) {
    const i = part.indexOf("=");
    if (i < 0) continue;
    const k = part.slice(0, i).trim();
    if (k) out[k] = part.slice(i + 1).trim();
  }
  return out;
}

function withoutCookie(header, name) {
  return String(header || "")
    .split(";")
    .map((p) => p.trim())
    .filter((p) => p && !p.startsWith(`${name}=`))
    .join("; ");
}

export class TokenStore {
  constructor(file) {
    this.file = file;
    this.cache = null;
    this.mtime = -1;
  }

  read() {
    let st;
    try {
      st = fs.statSync(this.file);
    } catch {
      this.cache = null;
      this.mtime = -1;
      return null;
    }
    if (st.mtimeMs !== this.mtime || !this.cache) {
      try {
        const data = JSON.parse(fs.readFileSync(this.file, "utf8"));
        this.cache = typeof data.token === "string" && data.token.length >= 22 ? data : null;
      } catch {
        this.cache = null;
      }
      this.mtime = st.mtimeMs;
    }
    return this.cache?.token || null;
  }

  write(token) {
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    const tmp = `${this.file}.${process.pid}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify({ token, created_at: new Date().toISOString() }) + "\n", { mode: 0o600 });
    fs.renameSync(tmp, this.file);
    protectPrivateFile(this.file);
    this.cache = null;
    this.mtime = -1;
    return this.read();
  }

  ensure() {
    return this.read() || this.write(newToken());
  }

  rotate() {
    return this.write(newToken());
  }
}

// 每个 IP 在窗口内最多提交 maxFails 个「不同的」错误凭证。重复提交同一个旧凭证（例如口令轮换后
// 手机上残留的旧 cookie）不再累计，避免手机自己把自己锁住；猜测不同值才会累计。
export class FailLimiter {
  constructor({ maxFails = 10, windowMs = 10 * 60 * 1000, now = () => Date.now() } = {}) {
    this.maxFails = maxFails;
    this.windowMs = windowMs;
    this.now = now;
    this.map = new Map();
  }

  entry(ip) {
    const t = this.now();
    let e = this.map.get(ip);
    if (e) e.fails = e.fails.filter((f) => t - f.at < this.windowMs);
    if (!e) {
      if (this.map.size > 5000) this.map.clear();
      e = { fails: [] };
      this.map.set(ip, e);
    }
    return e;
  }

  blocked(ip) {
    const e = this.entry(ip);
    if (e.fails.length < this.maxFails) return 0;
    const retry = this.windowMs - (this.now() - e.fails[0].at);
    return Math.max(1, Math.ceil(retry / 1000));
  }

  fail(ip, value) {
    const e = this.entry(ip);
    const key = digest(value).toString("hex").slice(0, 16);
    if (!e.fails.some((f) => f.key === key)) e.fails.push({ key, at: this.now() });
  }

  reset(ip) {
    this.map.delete(ip);
  }
}

export function lanAddresses(ifaces = os.networkInterfaces()) {
  const out = [];
  for (const [name, list] of Object.entries(ifaces || {})) {
    if (/^(docker|br-|veth|virbr|vmnet|vboxnet|lo)/i.test(name)) continue;
    for (const item of list || []) {
      const fam = item.family === 4 ? "IPv4" : item.family;
      if (fam !== "IPv4" || item.internal) continue;
      const ip = item.address;
      const [a, b] = ip.split(".").map(Number);
      let kind = null;
      if (a === 100 && b >= 64 && b <= 127) kind = "tailscale";
      else if (a === 10 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168)) kind = "lan";
      if (kind) out.push({ ip, iface: name, kind: /tailscale|utun/i.test(name) && kind === "lan" ? "lan" : kind });
    }
  }
  out.sort((x, y) => (x.kind === y.kind ? x.ip.localeCompare(y.ip) : x.kind === "lan" ? -1 : 1));
  return out;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

export function lockedPage(message) {
  return `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#1b1916"><link rel="manifest" href="/manifest.webmanifest"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
<title>需要配对 · ChatCluster</title>
<style>body{margin:0;min-height:100dvh;display:grid;place-items:center;background:#efe8dc;color:#1c1915;font:16px/1.6 -apple-system,system-ui,"PingFang SC","Microsoft YaHei",sans-serif}
main{max-width:360px;margin:24px;padding:24px;border-radius:16px;background:#f7f3eb;box-shadow:0 1px 3px #0002}
h1{font-size:20px;margin:0 0 8px}p{margin:8px 0;color:#4b443b}form{display:grid;gap:8px;margin-top:16px}
input{font:inherit;padding:10px;border:1px solid #d6c9b6;border-radius:10px;background:#fff}button{font:inherit;padding:10px;border:0;border-radius:10px;background:#9a3412;color:#fff}
small{color:#6b6258}</style></head>
<body><main><h1>请先在电脑上扫码</h1>
<p>${escapeHtml(message)}</p>
<p>在电脑上打开 ChatCluster，点「手机连接」，用手机相机或 ChatCluster 安卓 App 扫描二维码。</p>
<form method="get" action="/m/pair" id="f"><input name="token" id="t" autocomplete="off" placeholder="或粘贴配对链接 / 口令" aria-label="配对链接或口令"><button type="submit">连接</button></form>
<small>iPhone 从主屏幕打开时和 Safari 不共享登录状态，可以在这里粘贴配对链接。</small>
<script>document.getElementById("f").addEventListener("submit",function(e){var v=document.getElementById("t").value.trim();var m=v.match(/[?&](?:token|t)=([^&#\\s]+)/);if(m){document.getElementById("t").value=decodeURIComponent(m[1]);}});</script>
</main></body></html>`;
}

export function createMobileGate({ dataDir, port, version, lan = false, limiter = new FailLimiter(), ifaces = null }) {
  const store = new TokenStore(path.join(dataDir, "mobile_token.json"));
  if (lan) store.ensure();
  const localHosts = new Set([`127.0.0.1:${port}`, `localhost:${port}`, `[::1]:${port}`]);

  function send(res, status, body, headers = {}) {
    res.writeHead(status, { "Cache-Control": "no-store", ...headers });
    res.end(body);
  }

  function json(res, status, obj, headers = {}) {
    send(res, status, JSON.stringify(obj), { "Content-Type": "application/json; charset=utf-8", ...headers });
  }

  function wantsHtml(req, pathname) {
    if (pathname.startsWith("/backend/") || pathname.startsWith("/_next/") || pathname.startsWith("/m/")) return false;
    return /text\/html/.test(String(req.headers.accept || "")) || req.method === "GET" && !/\.[a-z0-9]+$/i.test(pathname);
  }

  // 看这次请求是否已授权。返回 { ok, via, bad }，bad 是本次提交的错误凭证（用于限流计数）。
  function authorise(req) {
    const token = store.read();
    const auth = String(req.headers.authorization || "");
    const bearer = /^Bearer\s+(.+)$/i.exec(auth)?.[1]?.trim();
    const cookie = parseCookies(req.headers.cookie)[COOKIE];
    if (bearer) {
      if (token && safeEqual(bearer, token)) return { ok: true, via: "bearer" };
      return { ok: false, bad: bearer };
    }
    if (cookie) {
      if (token && safeEqual(cookie, sessionValue(token))) return { ok: true, via: "cookie" };
      return { ok: false, bad: cookie, staleCookie: true };
    }
    return { ok: false };
  }

  function scrub(req, via) {
    for (const h of STRIP_HEADERS) delete req.headers[h];
    if (via === "bearer") delete req.headers.authorization;
    if (req.headers.cookie) {
      const rest = withoutCookie(req.headers.cookie, COOKIE);
      if (rest) req.headers.cookie = rest;
      else delete req.headers.cookie;
    }
    if (Array.isArray(req.rawHeaders)) {
      const out = [];
      for (let i = 0; i + 1 < req.rawHeaders.length; i += 2) {
        const k = req.rawHeaders[i].toLowerCase();
        if (STRIP_HEADERS.includes(k)) continue;
        if (k === "authorization" && via === "bearer") continue;
        if (k === "cookie") {
          if (req.headers.cookie) out.push(req.rawHeaders[i], req.headers.cookie);
          continue;
        }
        out.push(req.rawHeaders[i], req.rawHeaders[i + 1]);
      }
      try { req.rawHeaders.splice(0, req.rawHeaders.length, ...out); } catch { /* read-only on some versions */ }
    }
  }

  function info() {
    const token = store.read();
    const addrs = lanAddresses(ifaces || undefined).map((a) => ({ ...a, base: `http://${a.ip}:${port}` }));
    return {
      lan,
      port,
      version,
      has_token: Boolean(token),
      token: lan ? token : null,
      addresses: addrs.map((a) => ({
        ...a,
        app_payload: lan && token ? `chatclumer://pair?u=${encodeURIComponent(a.base)}&t=${token}` : null,
        web_link: lan && token ? `${a.base}/m/pair?token=${token}` : null,
      })),
    };
  }

  // 返回 true 表示已经写好响应；false 表示放行给 Next。
  function handle(req, res) {
    const ip = normalizeIp(req.socket?.remoteAddress);
    const local = isLoopback(ip);
    const url = new URL(req.url || "/", "http://x");
    const pathname = url.pathname;

    if (pathname === "/m/ping") {
      let a = local;
      if (!local) {
        // ping 也计入限流，否则能被当作无限次的口令校验接口。
        const r = authorise(req);
        if (!r.ok && r.bad) limiter.fail(ip, r.bad);
        a = r.ok && !limiter.blocked(ip);
      }
      json(res, 200, { app: "chatclumer", version, auth: Boolean(a) }, { "Access-Control-Allow-Origin": "*" });
      return true;
    }

    if (pathname === "/m/pair") {
      const wait = limiter.blocked(ip);
      if (wait) {
        send(res, 429, lockedPage(`尝试次数过多，请 ${Math.ceil(wait / 60)} 分钟后再试。`), { "Content-Type": "text/html; charset=utf-8", "Retry-After": String(wait) });
        return true;
      }
      const given = (url.searchParams.get("token") || "").trim();
      const token = store.read();
      if (token && given && safeEqual(given, token)) {
        limiter.reset(ip);
        send(res, 302, "", {
          Location: "/",
          "Set-Cookie": `${COOKIE}=${sessionValue(token)}; Path=/; Max-Age=${COOKIE_MAX_AGE}; HttpOnly; SameSite=Lax`,
          "Referrer-Policy": "no-referrer",
        });
        return true;
      }
      if (given) limiter.fail(ip, given);
      send(res, 401, lockedPage(token ? "配对链接无效或已失效（电脑上可能换过口令）。" : "电脑还没有开启手机模式（用 LAN=1 启动）。"), {
        "Content-Type": "text/html; charset=utf-8",
        "Referrer-Policy": "no-referrer",
      });
      return true;
    }

    if (LOCAL_ONLY.has(pathname)) {
      const host = String(req.headers.host || "").toLowerCase();
      // 只允许电脑本机访问；Host 也必须是回环地址，防 DNS 重绑定读到口令。
      if (!local || !localHosts.has(host)) {
        json(res, 403, { detail: "只能在电脑本机打开" });
        return true;
      }
      if (pathname === "/m/info" && req.method === "GET") {
        json(res, 200, info());
        return true;
      }
      if (pathname === "/m/rotate" && req.method === "POST") {
        if (req.headers["x-cc-local"] !== "1") {
          json(res, 403, { detail: "缺少本机请求标记" });
          return true;
        }
        store.rotate();
        limiter.map.clear();
        json(res, 200, info());
        return true;
      }
      json(res, 405, { detail: "method not allowed" });
      return true;
    }

    if (local) {
      scrub(req, null);
      return false;
    }

    if (PUBLIC_PATHS.has(pathname) || PUBLIC_PREFIXES.some((p) => pathname.startsWith(p))) {
      scrub(req, null);
      return false;
    }

    const wait = limiter.blocked(ip);
    const result = authorise(req);
    if (result.ok && !wait) {
      scrub(req, result.via);
      return false;
    }
    if (!result.ok && result.bad) limiter.fail(ip, result.bad);
    const extra = {};
    if (result.staleCookie) extra["Set-Cookie"] = `${COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax`;
    const retry = wait || limiter.blocked(ip);
    const status = retry && (result.bad || result.ok) ? 429 : 401;
    if (status === 429) extra["Retry-After"] = String(retry);
    if (wantsHtml(req, pathname)) {
      send(res, status, lockedPage(status === 429 ? "尝试次数过多，请稍后再试。" : "这台电脑上的 ChatCluster 需要先配对才能访问。"), { "Content-Type": "text/html; charset=utf-8", ...extra });
    } else {
      json(res, status, { detail: status === 429 ? "too many attempts" : "unauthorized" }, { "WWW-Authenticate": "Bearer", ...extra });
    }
    return true;
  }

  function allowUpgrade(req) {
    const ip = normalizeIp(req.socket?.remoteAddress);
    if (isLoopback(ip)) return true;
    if (limiter.blocked(ip)) return false;
    const r = authorise(req);
    if (!r.ok && r.bad) limiter.fail(ip, r.bad);
    if (r.ok) scrub(req, r.via);
    return r.ok;
  }

  return { handle, allowUpgrade, info, store, limiter };
}
