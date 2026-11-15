"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

// 内容脚本期待的最小 chrome.runtime。消息留在隔离世界里，不挂到网页自己的 window 上。
function createChrome(transport) {
  const listeners = [];
  const chrome = {
    runtime: {
      id: "chatclumer-desktop",
      lastError: null,
      getManifest() {
        return { version: transport.version || "0.5.0" };
      },
      sendMessage(message, callback) {
        Promise.resolve()
          .then(() => transport.send(message))
          .then((result) => {
            chrome.runtime.lastError = null;
            if (typeof callback === "function") callback(result);
          })
          .catch(() => {
            chrome.runtime.lastError = { message: "桌面壳消息失败" };
            if (typeof callback === "function") callback(undefined);
          });
      },
      onMessage: {
        addListener(fn) {
          listeners.push(fn);
        },
        removeListener(fn) {
          const index = listeners.indexOf(fn);
          if (index >= 0) listeners.splice(index, 1);
        },
      },
    },
  };

  function dispatch(message) {
    return new Promise((resolve) => {
      let settled = false;
      const sendResponse = (result) => {
        if (settled) return;
        settled = true;
        resolve(result === undefined ? null : result);
      };
      let waiting = false;
      for (const fn of listeners.slice()) {
        let keep = false;
        try {
          keep = fn(message, {}, sendResponse) === true;
        } catch {
          keep = false;
        }
        if (keep) {
          waiting = true;
          break;
        }
      }
      if (!waiting && !settled) resolve(null);
    });
  }

  return { chrome, dispatch };
}

function loadExtensionScripts(context, extensionRoot, files) {
  for (const rel of files) {
    const file = path.join(extensionRoot, rel);
    const code = fs.readFileSync(file, "utf8");
    vm.runInContext(code, context, { filename: file });
  }
}

module.exports = { createChrome, loadExtensionScripts };
