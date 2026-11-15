"use strict";

// ChatClumer 桌面壳原型。
// 打开已有的本机页面，并为注册表里的每个网页 AI 开一个独立窗口（WebContentsView + 持久分区）。
// 主进程代替扩展的 background.js：本机自动配对、轮询任务、1.2 秒心跳、校验远端注册表。
// 不读取 Cookie，不抽取令牌，不调用站点私有接口，不绕过登录、验证码或证书错误。
// 写入和点击仍由 extension/ 里的同一批脚本完成。尚未在真实网站上验证。

const { app, BrowserWindow, WebContentsView, ipcMain, Menu } = require("electron");
const fs = require("fs");
const path = require("path");
const { DesktopHost } = require("./host");
const { scriptFiles } = require("./sites");

const windows = new Map();
const preloadConfigs = new Map();
let host = null;
let appWindow = null;
let launcherWindow = null;
let loopsStarted = false;
let replySeq = 1;
const pendingReplies = new Map();

function findExtension() {
  const candidates = [
    process.env.CHATCLUMER_EXTENSION,
    path.join(process.resourcesPath || "", "extension"),
    path.join(__dirname, "..", "extension"),
  ].filter(Boolean);
  for (const dir of candidates) {
    if (fs.existsSync(path.join(dir, "adapters", "registry.json"))) return dir;
  }
  throw new Error("找不到 extension/adapters/registry.json");
}

function fileStorage(file) {
  let data = {};
  try {
    data = JSON.parse(fs.readFileSync(file, "utf8"));
  } catch {
    data = {};
  }
  function save() {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    const tmp = `${file}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(data));
    fs.chmodSync(tmp, 0o600);
    fs.renameSync(tmp, file);
    try {
      fs.chmodSync(file, 0o600);
    } catch {
      /* Windows 上 chmod 可能无效，文件仍只在本机用户目录。 */
    }
  }
  return {
    get(key) {
      return data[key];
    },
    set(key, value) {
      data[key] = value;
      save();
    },
  };
}

function callPage(webContents, message, timeoutMs) {
  const id = replySeq++;
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      pendingReplies.delete(id);
      resolve(null);
    }, timeoutMs);
    pendingReplies.set(id, (result) => {
      clearTimeout(timer);
      pendingReplies.delete(id);
      resolve(result);
    });
    if (!webContents || webContents.isDestroyed()) {
      clearTimeout(timer);
      pendingReplies.delete(id);
      resolve(null);
      return;
    }
    webContents.send("host-message", { id, message });
  });
}

const views = {
  list() {
    const items = [];
    for (const item of windows.values()) {
      items.push({
        tabKey: item.tabKey,
        origin: item.origin,
        alive: item.alive && item.webContents && !item.webContents.isDestroyed(),
      });
    }
    return items;
  },
  send(tabKey, message) {
    const item = windows.get(tabKey);
    if (!item || !item.webContents || item.webContents.isDestroyed()) return Promise.resolve(null);
    const timeout = message && (message.type === "run" || message.type === "resume") ? 130000 : 5000;
    return callPage(item.webContents, message, timeout);
  },
  health(tabKey) {
    const item = windows.get(tabKey);
    if (!item || !item.alive || !item.webContents || item.webContents.isDestroyed() || item.webContents.isLoading()) {
      return Promise.resolve(null);
    }
    return callPage(item.webContents, { type: "health" }, 1500);
  },
};

function cleanTabKey(value) {
  const text = String(value || "").trim();
  if (!text || text.length > 80 || /[\r\n\u0000]/.test(text)) return "";
  return text;
}

function allowPopup(url) {
  return /^https?:\/\//i.test(url);
}

function openPlainPopup(parent, partition, url) {
  const child = new BrowserWindow({
    parent,
    width: 480,
    height: 720,
    title: "登录或验证（桌面壳不代填）",
    webPreferences: {
      partition,
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  child.loadURL(url);
}

function wireSiteContents(webContents, parent, item) {
  webContents.setBackgroundThrottling(false);
  webContents.setWindowOpenHandler(({ url }) => {
    if (allowPopup(url)) openPlainPopup(parent, item.partition, url);
    return { action: "deny" };
  });
  const resume = (_event, url) => {
    if (host) host.onNavigated(item.tabKey, url || webContents.getURL()).catch(() => {});
  };
  webContents.on("did-navigate", resume);
  webContents.on("did-finish-load", () => {
    item.alive = true;
    resume(null, webContents.getURL());
  });
  webContents.on("destroyed", () => {
    item.alive = false;
  });
}

function openSiteWindow(site, tabKey) {
  const existing = windows.get(tabKey);
  if (existing && existing.win && !existing.win.isDestroyed()) {
    existing.win.show();
    existing.win.focus();
    return existing;
  }
  const origin = site.origins[0];
  const partition = `persist:${site.id}`;
  const title = `${site.label} · 绑定键 ${tabKey} · 原型`;
  const preload = path.join(__dirname, "preload.js");
  const webPreferences = {
    preload,
    partition,
    contextIsolation: true,
    nodeIntegration: false,
    sandbox: false,
    webSecurity: true,
    backgroundThrottling: false,
  };
  const item = { tabKey, origin, siteId: site.id, partition, alive: true, win: null, webContents: null };

  if (typeof WebContentsView === "function") {
    const win = new BrowserWindow({
      width: 1100,
      height: 800,
      title,
      webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true },
    });
    const view = new WebContentsView({ webPreferences });
    win.contentView.addChildView(view);
    const layout = () => {
      const [width, height] = win.getContentSize();
      view.setBounds({ x: 0, y: 0, width: Math.max(width, 0), height: Math.max(height, 0) });
    };
    win.on("resize", layout);
    win.on("ready-to-show", layout);
    layout();
    item.win = win;
    item.webContents = view.webContents;
    windows.set(tabKey, item);
    const viewId = view.webContents.id;
    preloadConfigs.set(viewId, {
      extensionRoot: host.extensionRoot,
      version: host.version,
      files: scriptFiles(origin),
    });
    wireSiteContents(view.webContents, win, item);
    win.on("closed", () => {
      item.alive = false;
      windows.delete(tabKey);
      preloadConfigs.delete(viewId);
    });
    view.webContents.loadURL(site.home);
    return item;
  }

  const win = new BrowserWindow({ width: 1100, height: 800, title, webPreferences });
  item.win = win;
  item.webContents = win.webContents;
  windows.set(tabKey, item);
  const contentsId = win.webContents.id;
  preloadConfigs.set(contentsId, {
    extensionRoot: host.extensionRoot,
    version: host.version,
    files: scriptFiles(origin),
  });
  wireSiteContents(win.webContents, win, item);
  win.on("closed", () => {
    item.alive = false;
    windows.delete(tabKey);
    preloadConfigs.delete(contentsId);
  });
  win.loadURL(site.home);
  return item;
}

function openAppWindow() {
  if (appWindow && !appWindow.isDestroyed()) {
    appWindow.show();
    appWindow.focus();
  } else {
    appWindow = new BrowserWindow({
      width: 1200,
      height: 800,
      title: "ChatClumer",
      webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true },
    });
  }
  if (host && host.backendUp) appWindow.loadURL("http://127.0.0.1:43123");
  else appWindow.loadFile(path.join(__dirname, "offline.html"));
}

function openLauncher() {
  if (launcherWindow && !launcherWindow.isDestroyed()) {
    launcherWindow.show();
    launcherWindow.focus();
    return;
  }
  launcherWindow = new BrowserWindow({
    width: 460,
    height: 720,
    title: "网页 AI（原型）",
    webPreferences: {
      preload: path.join(__dirname, "launcher-preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  launcherWindow.loadFile(path.join(__dirname, "launcher.html"));
  launcherWindow.on("closed", () => {
    launcherWindow = null;
  });
}

function installMenu() {
  Menu.setApplicationMenu(
    Menu.buildFromTemplate([
      {
        label: "原型",
        submenu: [
          { label: "打开应用", click: () => openAppWindow() },
          { label: "网页 AI", click: () => openLauncher() },
          {
            label: "重新检查本机服务",
            click: () => {
              connectLoop().then((up) => {
                if (up) openAppWindow();
                if (launcherWindow && !launcherWindow.isDestroyed()) launcherWindow.webContents.send("launcher:refresh");
              });
            },
          },
          { type: "separator" },
          { label: "退出", role: "quit" },
        ],
      },
    ])
  );
}

function installIpc() {
  ipcMain.on("preload:config", (event) => {
    event.returnValue = preloadConfigs.get(event.sender.id) || null;
  });
  ipcMain.on("host-reply", (_event, payload) => {
    const done = payload && pendingReplies.get(payload.id);
    if (done) done(payload.result);
  });
  ipcMain.handle("content-message", (_event, message) => (host ? host.onContentMessage(message) : null));
  ipcMain.handle("launcher:status", () => ({
    prototype: true,
    paired: Boolean(host && host.token),
    backend: Boolean(host && host.backendUp),
  }));
  ipcMain.handle("launcher:sites", async () => {
    if (host && host.backendUp) {
      try {
        await host.refreshMembers();
      } catch {
        /* 房间列表失败时仍可手动填写绑定键 */
      }
    }
    return host.siteList().map((site) => ({
      id: site.id,
      label: site.label,
      home: site.home,
      origins: site.origins,
      tabKeys: host.tabKeysFor(site.origins[0]),
    }));
  });
  ipcMain.handle("launcher:open", async (_event, body) => {
    const siteId = String((body && body.siteId) || "");
    const site = host.siteList().find((item) => item.id === siteId);
    if (!site || !site.origins.length) return { ok: false, detail: "没有这个站点" };
    let tabKey = cleanTabKey(body && body.tabKey);
    if (!tabKey) {
      if (host.backendUp) {
        try {
          await host.refreshMembers();
        } catch {
          /* 用站点 id */
        }
      }
      tabKey = host.suggestTabKey(site.origins[0]) || site.id;
    }
    openSiteWindow(site, tabKey);
    return { ok: true, tabKey };
  });
}

async function connectLoop() {
  const up = await host.ping();
  if (!up) return false;
  try {
    await host.ensurePaired();
  } catch (err) {
    host.log(err && err.message ? err.message : "自动配对失败");
  }
  if (!loopsStarted) {
    loopsStarted = true;
    setInterval(() => {
      host.tick().catch((err) => host.log(err && err.message ? err.message : "桥接失败"));
    }, 1200);
    host.refreshRegistry(false).catch(() => {});
    setInterval(() => host.refreshRegistry(false).catch(() => {}), 30 * 60 * 1000);
  }
  return true;
}

async function start() {
  const extensionRoot = findExtension();
  const manifest = JSON.parse(fs.readFileSync(path.join(extensionRoot, "manifest.json"), "utf8"));
  host = new DesktopHost({
    extensionRoot,
    version: manifest.version,
    storage: fileStorage(path.join(app.getPath("userData"), "bridge-state.json")),
    views,
    log(line) {
      console.log(line);
    },
  });
  installIpc();
  installMenu();
  await connectLoop();
  openAppWindow();
  openLauncher();
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (appWindow && !appWindow.isDestroyed()) {
      appWindow.show();
      appWindow.focus();
    }
  });
  app.on("window-all-closed", () => app.quit());
  app.whenReady().then(start).catch((err) => {
    console.error(err && err.message ? err.message : "桌面壳没有启动");
    app.quit();
  });
}
