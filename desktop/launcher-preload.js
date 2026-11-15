"use strict";

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("desktop", {
  sites: () => ipcRenderer.invoke("launcher:sites"),
  open: (siteId, tabKey) => ipcRenderer.invoke("launcher:open", { siteId, tabKey }),
  status: () => ipcRenderer.invoke("launcher:status"),
  onRefresh: (callback) => {
    if (typeof callback !== "function") return;
    ipcRenderer.on("launcher:refresh", () => callback());
  },
});
