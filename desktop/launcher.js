"use strict";

const list = document.querySelector("#sites");
const status = document.querySelector("#status");

function line(text) {
  const p = document.createElement("p");
  p.className = "home";
  p.textContent = text;
  return p;
}

async function render() {
  const state = await window.desktop.status();
  status.textContent = state.backend
    ? (state.paired ? "已与本机后端自动配对。不用抄配对码。" : "本机服务在运行，配对还没有完成。")
    : "本机服务没在运行。先运行 scripts/install.sh 或 scripts/start.sh，再用菜单「重新检查本机服务」。";
  const sites = await window.desktop.sites();
  list.replaceChildren();
  for (const site of sites) {
    const item = document.createElement("li");
    const title = document.createElement("strong");
    title.textContent = site.label;
    item.append(title, line(site.home));
    if (site.tabKeys && site.tabKeys.length) {
      item.append(line(`房间里已有绑定键：${site.tabKeys.join("、")}`));
    }
    const label = document.createElement("label");
    label.textContent = "绑定键（留空则用房间里唯一的键，否则用站点 id）";
    const input = document.createElement("input");
    input.value = site.tabKeys && site.tabKeys.length === 1 ? site.tabKeys[0] : site.id;
    label.append(input);
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "打开";
    button.addEventListener("click", async () => {
      const result = await window.desktop.open(site.id, input.value.trim());
      button.textContent = result && result.ok ? `已打开 · ${result.tabKey}` : "没有打开";
    });
    item.append(label, button);
    list.append(item);
  }
}

window.desktop.onRefresh(() => {
  render();
});
render();
