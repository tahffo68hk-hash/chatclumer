"use strict";

// 站点窗口的 preload。contextIsolation 打开，所以这些变量不属于网页主世界。
// sandbox 必须关掉，才能从磁盘读取同一份扩展脚本；nodeIntegration 仍然关闭，网页读不到 Node。
// 不读取 Cookie，不调用站点私有接口。写入、单击和未确认就清空，仍由扩展脚本自己做。

const { ipcRenderer } = require("electron");
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const { createChrome } = require("./boot");

const config = ipcRenderer.sendSync("preload:config") || {};
const extensionRoot = config.extensionRoot || "";
const version = config.version || "0.5.0";
const files = Array.isArray(config.files) ? config.files : [];

const bridge = createChrome({
  version,
  send(message) {
    return ipcRenderer.invoke("content-message", message);
  },
});

global.chrome = bridge.chrome;

ipcRenderer.on("host-message", async (_event, payload) => {
  let result = null;
  try {
    result = await bridge.dispatch(payload && payload.message);
  } catch {
    result = { status: "error", detail: "桌面壳页面脚本出错", page_url: "" };
  }
  ipcRenderer.send("host-reply", { id: payload && payload.id, result });
});

if (!extensionRoot || !files.length) {
  throw new Error("桌面壳 preload 缺少扩展脚本路径");
}

for (const rel of files) {
  const file = path.join(extensionRoot, rel);
  vm.runInThisContext(fs.readFileSync(file, "utf8"), { filename: file });
}
