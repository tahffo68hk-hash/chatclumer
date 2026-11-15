// ChatCluster 前端服务器：包一层 Next，在能看到真实 socket 地址的地方做手机/局域网认证。
// 用法：node server/index.mjs [--dev] [-H 127.0.0.1] [-p 43123]
// 默认只监听 127.0.0.1。LAN=1（或 -H 0.0.0.0）时开放给局域网，但非本机请求必须先配对。
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import next from "next";
import { createMobileGate, isLoopback } from "./mobile-auth.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const frontendDir = path.resolve(here, "..");
const root = path.resolve(frontendDir, "..");

function arg(flag, fallback) {
  const i = process.argv.indexOf(flag);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}

const dev = process.argv.includes("--dev");
const host = arg("-H", process.env.LAN === "1" ? "0.0.0.0" : "127.0.0.1");
const port = Number(arg("-p", process.env.PORT || "43123"));
const lan = !isLoopback(host) && host !== "localhost";
const dataDir = process.env.CC_DATA_DIR || path.join(root, "backend", "data");

export function appVersion() {
  for (const file of [path.join(frontendDir, "package.json"), path.join(root, "extension", "manifest.json")]) {
    try {
      const v = JSON.parse(fs.readFileSync(file, "utf8")).version;
      if (v) return String(v);
    } catch { /* try next */ }
  }
  return "0.0.0";
}

const gate = createMobileGate({ dataDir, port, version: appVersion(), lan });
const app = next({ dev, dir: frontendDir, hostname: host === "0.0.0.0" ? "localhost" : host, port, turbopack: dev });
const handle = app.getRequestHandler();

await app.prepare();
const upgrade = typeof app.getUpgradeHandler === "function" ? app.getUpgradeHandler() : null;

const server = http.createServer((req, res) => {
  try {
    if (gate.handle(req, res)) return;
  } catch (err) {
    console.error("mobile gate error", err?.message || err);
    res.writeHead(500, { "Content-Type": "text/plain" });
    res.end("gate error");
    return;
  }
  handle(req, res);
});

server.on("upgrade", (req, socket, head) => {
  if (!gate.allowUpgrade(req)) {
    socket.write("HTTP/1.1 401 Unauthorized\r\nConnection: close\r\n\r\n");
    socket.destroy();
    return;
  }
  if (upgrade) upgrade(req, socket, head);
  else socket.destroy();
});

server.listen(port, host, () => {
  console.log(`ChatCluster frontend on http://${host}:${port} (${dev ? "dev" : "prod"})`);
  if (lan) {
    console.log("手机模式已开启：非本机请求必须先配对。在电脑上打开 http://127.0.0.1:" + port + " → 「手机连接」扫码。");
  }
});
