# ChatCluster

Several models. One shared timeline.

AI 群聊集合：一次提问后，多个模型先各自回答，再阅读已经公开的发言，选择回复、质疑或补充。这是一间聊天室，不是多 Agent 框架，也不替模型调用工具。

[![Python / FastAPI](https://img.shields.io/badge/Python-FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-15-111111?logo=nextdotjs&logoColor=white)](https://nextjs.org/)
[![Chrome MV3](https://img.shields.io/badge/Chrome-MV3-4285F4?logo=googlechrome&logoColor=white)](https://developer.chrome.com/docs/extensions/mv3/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue)](#许可证)

<p>
  <img src="docs/screenshots/desktop-discussion.png" alt="桌面上的多模型讨论：演示回复标明非真实模型" width="100%">
</p>

| 独立分支先各自回答，合并前可以预览将共享的公开答复 | 设置里可以切换深色、字号，并导出或生成本机配对码 |
| --- | --- |
| <img src="docs/screenshots/branches-preview.png" alt="独立分支与合并预览"> | <img src="docs/screenshots/settings-dark.png" alt="深色主题下的设置对话框"> |

扩展可以把房间里的公开答复写进已授权的网页标签。下面是 Gemini 游客页收到合并内容时的样子，不是应用自己的界面。

<p>
  <img src="docs/screenshots/gemini-bridge.png" alt="Gemini 游客页里由扩展写入的公开答复" width="100%">
</p>

2026-11-15 07:46，已登录的元宝标签完成第一轮发送和 A/B 读回之后，又把林知秋的公开答复转发了一次。房间读回的正文与页面一致，元宝上的用户气泡和房间任务都是 2，输入框是空的。游客输入仍要先在该标签页登录一次。

<p>
  <img src="docs/screenshots/yuanbao-forward-round3.png" alt="房间里元宝网页成员读回的第三轮转发，正文与已登录的元宝页面一致" width="100%">
</p>

## 特性

- **多模型群聊。** 同一条时间线上可以有多位成员。自由群聊会按提及和上下文决定下一轮谁开口，不是固定的全员轮询。
- **独立思考、合并、拆分。** 同一句问题可以先进入各自的独立分支，互不可见。勾选至少两人后，先预览将共享的公开答复，再合并成讨论组。没被勾上的历史不会默认传走。拆出去的人不再收到原组的新发言。页面不会声称模型忘掉了已经看见的内容。
- **网页 AI 和 API 混用。** 同一个房间里，网页成员和 API 成员可以一起讨论。
  - 网页成员：Chrome MV3 扩展只在你授权的标签页里读写可见界面，只和本机 `127.0.0.1:43124` 配对。可以用游客页，或由你在那个标签页里自己登录一次。扩展不读 Cookie，不取页面令牌，不关登录弹窗，也不绕过验证码。
  - API 成员：走 OpenAI 兼容接口，流式输出。内置 OpenAI、DeepSeek、通义（DashScope 兼容模式）、硅基流动、OpenRouter、本机 Ollama 的预设，也可以填自定义地址。密钥只存在本机后端。
- **适配器注册表（0.5.0）。** 各站的选择器和规则不写在代码里，而是放在带版本的 `extension/adapters/registry.json`，每个角色有按顺序回退的选择器。扩展会定时从仓库拉取新版，校验通过才启用。站点改版时改 JSON 即可，不用重装扩展。注册表只含数据，不执行远端代码。
- **页面检查与诊断快照。** 「检查当前页」不发送，只找输入框、发送键和消息容器，结果显示在扩展弹窗和房间的成员卡片上。适配一坏马上能看到。诊断快照只保留聊天栏结构，正文打码，用来写新选择器。
- **评测。** `backend/eval/` 用固定 10 道题比较单模型和群聊，输出 Markdown 和 JSON 报告。
- **收藏与导出。** 收藏记下讨论里的原话和备注，并写明这不是已核实事实，可导出 Markdown。房间也可以把当前公开消息导出为 Markdown 或 JSON，不含配对令牌或密钥。讨论结束时的总结默认是本地回顾，不额外请求模型。
- **分歧面板。** 只列出发言里显式的质疑或反驳。没有时显示「没有显式的质疑或反驳。这里不编共识。」
- **设置。** 浅色、深色或跟随系统，对话字号，以及本机配对码。配对码只在本机页面签发，粘贴到扩展后令牌留在扩展里。
- **默认演示。** 没有密钥时整间房使用合成回复，每一条都带「非真实模型」，不会伪装成 GPT、Claude、Gemini 或 Grok。`ALLOW_PAID_PROVIDERS` 默认为 `0`，可能计费的云端调用不会发出。

## 快速开始

需要 Python 3.10+ 和 Node.js 20+。默认只监听本机。

```bash
bash scripts/start.sh
```

- 页面：http://127.0.0.1:43123
- 后端：http://127.0.0.1:43124
- 停止：`bash scripts/stop.sh`。它只结束本次启动记下的进程树。端口若仍被其他进程占用，会报出 PID 并失败。

Windows 使用 `scripts/start.ps1` 和 `scripts/stop.ps1`，同样只绑定回环地址。这两份脚本在 Linux 上做过静态核对：缺少 Python 或 Node 会停并说明要装什么；启动前检查端口；就绪要看到 `multi-llm-chat-room`；停止只沿记下的进程树结束。本仓库没有在 Windows 上实际跑过它们。

只有在你接受无登录风险时才打开局域网前端：

```bash
LAN=1 bash scripts/start.sh
```

前端会监听 `0.0.0.0:43123` 并打印警告。后端仍在 `127.0.0.1`。不要把没有认证的服务暴露到公网。

**API 成员：** 添加成员时选一个提供方。API Base 留空就用预设地址；本机服务（Ollama、LM Studio，或任何 `127.0.0.1` 上的兼容接口）视为零费用。选 Ollama 时，页面会列出本机已有的模型。云端接口要先配好密钥，再在设置里打开「允许可能计费的调用」。

密钥：复制 [`.env.example`](.env.example) 里的名字到环境变量，或在页面「密钥」里写入服务器文件 `backend/data/secrets.json`（权限 600）。接口只返回是否已配置，不回显原文。`ALLOW_PAID_PROVIDERS=0` 是默认值。Ollama 只连接 `OLLAMA_BASE_URL`，不会下载模型。没有已知单价的云端模型不会按 0 美元放行。

## 浏览器扩展

1. 启动本机服务。用 Chrome 打开 `chrome://extensions`，打开开发者模式，加载已解压的 `extension/`。
2. 在房间「设置」里生成本机配对码，粘贴到扩展弹窗并配对。配对码五分钟内有效，用一次即失效。令牌不会写入聊天或导出文件。
3. 添加「网页会话」成员。打开「连接网页 AI」，填写来源、页面地址和绑定键。需要房间代发时再打开受控自动发送。
4. 在目标标签页的扩展弹窗里填写同一个成员 ID 和绑定键，绑定当前标签。元宝、智谱等站点会在这时请求主机权限，授予后才注入内容脚本。
5. 成员卡片先是「已配置，等待扩展绑定」。心跳到达后变为「已绑定标签页」，不用刷新房间。大约 20 秒没有心跳则是「掉线」。
6. 绑定后，扩展每 30 秒做一次页面检查，卡片上会显示「页面检查：输入框、发送键正常」或缺了什么。弹窗里也可以手动「检查当前页」，或「导出诊断快照」。
7. 扩展弹窗显示当前注册表的版本和来源。远端地址默认是本仓库的 `extension/adapters/registry.json`，可以改成自己的 https 地址，填 `off` 就关闭远端更新。

品牌版 Chrome 可能忽略命令行 `--load-extension`。请用上面的「加载已解压的扩展程序」。扩展版本见 `extension/manifest.json`。

## 站点支持状态

网页不显示单价时，费用记为未知，不会写成 0。设了费用上限的房间不会向网页发送。下表是已经核对过的状态，不是承诺每个站点都能自动发送。

| 站点 | 状态 |
| --- | --- |
| 本地夹具 | 扩展回路已通过。夹具不是真实模型。 |
| Gemini 游客 | 2026-11-15 扩展回路通过，页面显示 Flash-Lite。另一成员是演示模型。 |
| 元宝（登录后） | 已实页验证自动发送、读回、转发（扩展 0.2.9，2026-11-15 07:46）。第一轮发出一次并读回 A/B 的答案 1；第三轮把林知秋的公开答复转发一次，读回与页面一致。用户气泡与房间任务都是 2，没有多余发送，结束后输入框是空的。游客输入要先在该标签页登录一次。扩展不点偏好按钮。 |
| Qwen / Z.ai / 文心 / 智谱清言（游客，不用登录） | 扩展 0.4.2–0.4.4 实页已通过（2026-11-15）。共用 `extension/guest.js`，选择器在注册表里。文心的 wenxin.baidu.com、chat.baidu.com、yiyan.baidu.com 算同一个绑定。Qwen 若提示没有权限，回报「千问游客发送被拒绝，可能需要登录」；年龄确认弹窗不点。 |
| ChatGPT（游客） | 不可靠。游客额度用完后页面要求「Sign in to continue」，扩展写入前就识别并回报，不写入、不重试。 |
| DeepSeek / 豆包（要先登录） | 实页发送和读回已通过。DeepSeek 要放在单独的可见窗口里，后台标签页可能不渲染消息列表。未登录不发送。豆包地区不可用只回报，不绕过。 |
| 0.5.0 注册表版本 | 改成从注册表编译后，用同一批真实 DOM 测试回归过；实页还要再跑一遍（见下方路线）。 |
| Kimi / Grok / Copilot / Hugging Face Chat | 2026-11-15 试过：要登录才有回复，不当成游客站。 |
| 千问 qianwen.com（tongyi.com 跳转）/ 秘塔 metaso.cn | 首次发送出现滑块验证，不代做，未接入。 |
| Perplexity | 游客回复只有「注册并重复您的请求」，没有实际用处，未接入。 |
| duck.ai / you.com / phind.com | duck.ai 本机网络连不上；you.com 已无游客聊天；phind.com 已下线。 |
| Claude | 早前 403。没有重试，没有绕过。 |
| QQ / 微信 | `BLOCKED_EXTERNAL`。只保留官方机器人或公众号、企业微信的配置位。不连接个人 QQ 或个人微信，也不使用非官方自动化。详见 [`docs/QQ_WECHAT.md`](docs/QQ_WECHAT.md)。 |

更早的核对记录在 [`docs/WEB_ACCESS.md`](docs/WEB_ACCESS.md)。开发交接在 [`docs/MORNING_HANDOFF.md`](docs/MORNING_HANDOFF.md)。

## 架构

```mermaid
flowchart LR
  UI["Next.js<br/>127.0.0.1:43123"] --> API["FastAPI + SQLite<br/>127.0.0.1:43124"]
  API --> Bridge["本机回环桥<br/>任务 / 心跳 / 页面检查"]
  Bridge --> Ext["Chrome MV3 扩展"]
  Reg["适配器注册表 JSON<br/>内置 + 远端（校验后才用）"] --> Ext
  Ext --> Tabs["已授权的网页 AI 标签"]
  API --> Providers["OpenAI 兼容 API / Ollama<br/>默认不发出计费请求"]
  Eval["backend/eval<br/>单模型 vs 群聊"] --> API
```

- **前后端。** 浏览器里的页面把 `/backend` 转到本机 FastAPI。房间、成员、消息和扩展任务存在 SQLite。
- **扩展。** 轮询回环桥，只操作已绑定的标签页。各站的选择器和规则来自注册表：内置一份，远端一份。远端注册表只有在结构合法、版本更新、选择器都能解析时才启用，任何一项不满足都继续用内置。
- **页面检查。** 结果随心跳回到后端，显示在成员卡片上。
- **API 成员。** 和网页成员共用同一套调度。云端模型要另配密钥，并且只有在 `ALLOW_PAID_PROVIDERS=1` 时，才会考虑可能计费的接口。

## 和同类产品的取舍

详见 [`docs/COMPETITOR_APPROACHES.md`](docs/COMPETITOR_APPROACHES.md)。

| | ChatALL | GodMode | ChatHub | Cherry Studio / LobeHub | 本项目 |
| --- | --- | --- | --- | --- | --- |
| 网页 AI | 调网页私有接口 | 内嵌网页，写死的选择器 | 调网页私有接口，或用自己的 API Key | 基本不做 | 只操作可见页面，不读 Cookie、不调私有接口 |
| 适配坏了 | 发新版（仓库已归档） | 发新版 | 转向 API 和自营服务 | 不涉及 | 改注册表 JSON，扩展自动拉取；页面检查马上报出哪个角色坏了 |
| API | 有 | 少量 | 有 | 主力 | OpenAI 兼容 + Ollama，和网页成员同房 |
| 分发 | 桌面安装包 | 桌面安装包 | 扩展商店 + 网页 | 安装包 / Docker | 目前是本机脚本 + 解压加载扩展；一键安装和桌面壳的规格已写好，待实现 |

## 项目结构

```text
backend/          FastAPI、SQLite、调度和扩展桥
backend/eval/     评测：固定题集、单模型 vs 群聊、报告（自带的是模拟结果）
frontend/         Next.js 房间界面
extension/        Chrome MV3 内容脚本、后台和弹窗
extension/adapters/  适配器注册表（registry.json）、结构校验、运行时（页面检查、诊断快照）
scripts/          启动、停止和界面检查
docs/             站点记录、交接和截图
.env.example      环境变量名字，不含真实密钥
```

## 测试

普通后端套件不安装浏览器库也能收集。`skipped` 是可选浏览器测试，不能把它算进 passed。

```bash
cd backend && .venv/bin/pytest -q
```

不装 Playwright 时，项目自带的 venv 跑出 **52 passed, 6 skipped**（跳过的都是浏览器测试）。浏览器测试是在另一个装了 Playwright 的环境里跑的：真实 DOM 回放、注册表页面检查、远端注册表的接受与拒绝、诊断快照打码等。

改了 `extension/adapters/registry.json` 之后，要重新生成内置副本：

```bash
python3 scripts/build_registry.py
```

评测：

```bash
cd backend && .venv/bin/python -m eval.run_eval --mock --out eval/results/mock
```

浏览器测试需要开发依赖，以及 Chrome 或 Playwright 的 Chromium：

```bash
cd backend && .venv/bin/pip install -r requirements-dev.txt && .venv/bin/python -m playwright install chromium
cd backend && .venv/bin/pytest -q -m browser
```

类型检查和成员绑定界面：

```bash
cd frontend && npx tsc --noEmit && npm run build
backend/.venv/bin/python scripts/check_web_bind_ui.py
```

`check_web_bind_ui.py` 只检查成员对话框有没有把来源、地址、绑定键和自动发送写进 web-bind。它不打开 Gemini 或元宝。

## 安全与合规

- 扩展只读写已授权标签页上的可见界面。不读取 Cookie，不抽取页面里的令牌，不调用站点的私有 API。
- 远端注册表只是数据：选择器、正则文本、提示文字和少数开关。校验时，不认识的键、超长内容和无法解析的选择器都会导致整份拒绝，绝不执行远端代码。
- 诊断快照里的正文、`data-*` 里的文字、输入框内容、图片地址和链接都会去掉或打码，导出前不上传。
- API 密钥只存在本机后端（文件权限 600），不回显到前端，也不写进日志和数据库。
- 遇到登录、验证码、年龄确认或额度用尽就停。不关登录框，不替用户填写凭证，也不绕过验证。
- 配对码和配对令牌只留在本机。聊天记录、导出文件和应用日志不写令牌明文。
- 发到网页的文字会离开这台电脑。网页成员只有绑定了明确标签、打开受控自动发送，并且房间没有费用上限时才会发送。
- QQ 与微信在官方鉴权完成之前保持 `BLOCKED_EXTERNAL`。个人微信没有官方群机器人接口，本仓库拒绝非官方自动化。

## 路线

- **0.5.x：** 用 0.5.0 在实页上回归各站点。注册表改由数据驱动后，还没有实页跑过。远端注册表第一次真实更新的流程也要核对。
- **分发：** 一键安装脚本（`install.sh` / `install.ps1`）、带版本号的发布包，以及内嵌网页的桌面壳（参考 ChatALL、GodMode 的内置窗口，复用同一份注册表）。规格见 [`docs/COMPETITOR_APPROACHES.md`](docs/COMPETITOR_APPROACHES.md) 的交接一节。
- **评测：** 用真实成员（本机 Ollama 免费）跑一遍 `backend/eval`，替换自带的模拟结果。
- **站点：** 元宝游客输入仍要先登录。仍被挡住的站点只在可见页面可用之后再接，不换入口绕过。
- **QQ 与微信：** 只考虑官方机器人、公众号或企业微信，不做个人账号。

## 许可证

[MIT](LICENSE)。Copyright (c) 2026 zmjjyy。
