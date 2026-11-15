# 同类产品怎么解决「适配易碎」和「分发」（2026-11-15 调研）

只看公开仓库、README 和商店页面，没有安装或运行这些产品。星标数和最近推送时间取自 2026-11-15 的 GitHub API。

## 一览

| 产品 | 形态 | 怎么接网页 AI | 适配坏了怎么办 | 怎么分发 |
| --- | --- | --- | --- | --- |
| [ChatALL（齐叨）](https://github.com/ai-shifu/ChatALL)（原 sunner/ChatALL，约 1.65 万星，**仓库已归档**） | Electron 桌面应用 | 内置窗口里让用户登录，之后调用各站网页背后的接口（每站一个 `src/bots/*Bot.js`，例如 `QianWenBot.js` 带 xsrf 头请求 `qianwen.aliyun.com`） | 发新版本。README 自己写明网页接入“依赖逆向，经常坏”，并建议优先用 API | GitHub Releases 安装包（Windows exe、macOS dmg、deb、AppImage），另有 Homebrew 和 AUR |
| [GodMode](https://github.com/smol-ai/GodMode)（约 6.2 千星，最近推送 2024-07） | Electron 桌面应用 | 每站一个 webview，打开真实网页；每站一个 provider 文件，用 `executeJavaScript` 往 `div.ProseMirror` 写字、点按钮 | 手改 provider 里写死的选择器，再发版本 | GitHub Releases；README 提到系统常把未签名包标为“已损坏”，需要右键打开 |
| [ChatHub](https://github.com/chathub-dev/chathub)（开源版约 1.07 万星）/ [chathub.gg](https://doc.chathub.gg/overview/chrome-extension) | 浏览器扩展 + 网页版 + 手机 App | 开源版直接请求网页后端接口（例如 ChatGPT 的 `backend-api`，先取 `/api/auth/session` 的 access token）。商业版提供三种接法：用户自己的网页账号、用户自己的 API Key、ChatHub 自营的模型服务（订阅） | 越来越多地走 API 和自营服务：商业版卖“不用 API Key”的订阅，绕开网页的不稳定 | Chrome 网上应用店（约 20 万用户）；网页版不用安装 |
| [Cherry Studio](https://github.com/CherryHQ/cherry-studio)（约 5.35 万星，AGPL-3.0） | Electron 桌面应用 + 手机 App | 以 API 为主：在一个地方配置各家服务、Key 和模型，支持自定义兼容接口、Ollama、LM Studio。网页工具只当作“Mini Apps”打开，不自动化 | 基本不依赖网页结构，所以没有这个问题 | 官网下载桌面安装包 |
| [LobeHub（原 LobeChat）](https://github.com/lobehub/lobehub)（约 8.55 万星） | 网页应用（可自托管）+ 云服务 + 桌面版 | 只用 API：文档列出 40 多个模型服务和本地模型的接法 | 不涉及网页适配 | Docker Compose 或 Vercel 一键部署自托管，也有官方云 |

## 结论

1. **网页接入天生易碎，大家的共识是“能走 API 就走 API”。** ChatALL 的 README 直说网页接入依赖逆向、经常坏。ChatHub 商业版把重心转到 API 和自营服务。Cherry Studio、LobeHub 从一开始就只用 API。
2. **网页接入有两条路。**
   - 调网页背后的私有接口（ChatALL、ChatHub 开源版）：速度快，但要拿登录态或令牌，改版就坏，还可能违反服务条款。本项目不做：不读 Cookie、不调私有接口。
   - 像人一样操作可见页面（GodMode，本项目也是）：更稳妥，但选择器一改就坏。GodMode 把选择器写死在代码里，每次都要发新版。
3. **分发上，桌面应用（ChatALL、GodMode、Cherry Studio）都是打包好的安装包。** 好处是用户不用装扩展、不用配对。问题是未签名的包会被系统拦，GodMode 的 README 专门教用户怎么绕过“已损坏”提示。

## 本项目采用的方案（0.5.0）

- **适配器注册表（借鉴 GodMode 的“一站一配置”，但改成数据、能远端更新）。**
  - 选择器和站点规则从代码里搬到 `extension/adapters/registry.json`：带版本，每个角色有按顺序回退的选择器列表。
  - 扩展默认每 6 小时从 chatclumer 仓库拉一次新版注册表。只有结构校验通过、版本比内置新、所有选择器都能解析时才启用；否则继续用内置。
  - 注册表只含数据（选择器、正则文本、提示文字、开关），不执行远端代码，符合 MV3 规则。
  - 游客站（Qwen、ChatGPT、文心、智谱清言、Z.ai）改版时，如果只是选择器或规则变了，在仓库里改 JSON 即可，用户不用重装扩展。写入、点击、确认发出的流程在代码里，远端改不了。DeepSeek、豆包、元宝的条目目前只用于页面检查，它们改版仍要更新扩展。
  - 用到新开关的注册表要提高 `min_extension`，旧扩展会拒绝并继续用内置注册表。
  - 评测和测试只证明流程正确，不能证明群聊讨论比单模型更准确。
- **页面检查。** 不发送，只找输入框、发送键和消息容器；结果显示在扩展弹窗和房间的成员卡片上，适配一坏马上能看到。
- **诊断快照。** 只取聊天栏的结构，正文全部打码，方便写新选择器。
- **API 通道（借鉴 Cherry Studio 和 LobeHub）。** OpenAI 兼容接口，内置 OpenAI、DeepSeek、通义（DashScope 兼容模式）、硅基流动、OpenRouter 和本机 Ollama 的预设。密钥只存在本机后端，可以和网页成员混在同一个房间。
- **分发（交给另一个代理实现）。** 打包脚本、一键安装和桌面壳的规格见下一节。

## 桌面壳与打包交接规格（Desktop shell & packaging handoff）

这一节写给要实现安装脚本、发布包和桌面壳的人（或代理）。现有行为以代码为准；本节列出必须对接的接口。

### 1. 适配器注册表

- **位置。** 源文件是 `extension/adapters/registry.json`。`extension/adapters/registry.js` 是由 `scripts/build_registry.py` 生成的同内容数据赋值（`globalThis.CHATCLUMER_REGISTRY = {...}`），改 JSON 后要重新生成，`test_adapter_registry` 会检查两者一致。
- **对外读取。** 后端 `GET http://127.0.0.1:43124/api/adapters/registry` 返回内置注册表。远端默认地址是 `https://raw.githubusercontent.com/tahffo68hk-hash/chatclumer/main/extension/adapters/registry.json`。
- **顶层结构。**
  - `schema`：固定为 `"chatclumer.adapters"`。
  - `schema_version`：目前是 `1`。
  - `version`：`YYYY.M.D.N`，只接受比内置更新的版本。
  - `min_extension`：语义化版本号，客户端低于它就拒绝。
  - `common`：门槛用的弹窗、提示条、验证框选择器，以及验证码、登录、非登录三个正则。
  - `sites.<id>`：每个站点一项。
- **站点字段。**
  - `engine`：`guest` 或 `builtin`。guest 站完全由注册表驱动；builtin 站（DeepSeek、豆包、元宝）仍由各自的 js 驱动，注册表只用于页面检查。
  - `label`，以及 `origins`（只能是 https 源）。
  - `roles`：角色到有序选择器列表的映射。可用角色有 composer、send、stop、users、user_text、assistants、host、body、exclude、done_near、messages、column。单元素角色按顺序取第一个能命中的选择器；多元素角色取并集。
  - 规则：`disabled`、`done` 是条件；`streaming` 是 `[{when: 条件, value: true/false}]`，按顺序第一条命中的生效；`stop_find` 是 `[{sel, closest?, attr?, pattern?}]`。条件只有六种写法：`{has}`、`{self}`、`{closest, attr, equals}`、`{not}`、`{all}`、`{any}`。
  - `flags`：`writer`（native 或 exec）、`guard_other`、`wait_send_enabled`、`click_center`、`click_inner`。
  - 正则：`placeholder_text`、`conv_url`、`gates[].pattern`，写成 `{source, flags}`。
  - `gates`：`[{pattern, where: toast|dialog|page, detail}]`。
- **校验。** 以 `extension/adapters/schema.js` 为准：它导出 `validateRegistry(data, extensionVersion)` 和 `compareVersion`，能在 service worker、页面和 Node 里跑。出现不认识的键、超长字符串、超过 96 KB，都会整份拒绝。
- **运行时。** `extension/adapters/runtime.js` 提供 `ChatclumerAdapters`：`site(id)`、`common()`、`info()`、`useRemote(data, url)`、`health(id, root)`、`dump(id, root)`。`guest.js` 通过它把注册表编译成规格。

### 2. 桌面壳怎么复用（建议做法，尚未实现）

- **页面和窗口。** 每个网页 AI 用一个 `BrowserView` 或 `WebContentsView`。每站独立 `partition`（例如 `persist:qwen`），用户在里面自己登录。不读 Cookie，不调私有接口，遇到验证或登录墙只提示。
- **preload。** 每个站点视图的 preload 按顺序在页面主世界之外（`contextIsolation: true`）加载 `adapters/schema.js`、`adapters/registry.js`、`adapters/runtime.js`、`guest.js`（或 builtin 站对应的 js）和 `content.js`。
- **chrome.runtime 的替身。** 这些脚本假设有 `chrome.runtime.sendMessage` 和 `chrome.runtime.onMessage`。preload 需要用 `ipcRenderer` 提供一个最小替身：
  - `{type: "run", job}`：执行任务并回传结果；
  - `{type: "health"}` 和 `{type: "dump"}`；
  - `{type: "registry-get"}`：返回主进程缓存的远端注册表。
- **主进程。** 它替代 `extension/background.js`：
  - 轮询 `/api/ext/jobs`，按 `tab_key` 把任务转给对应视图；
  - 每 1.2 秒发一次心跳，带上页面检查结果；
  - 按第 1 节的规则拉取并校验远端注册表。
- **安全规则不能放宽。** 只写一次并核对；只点一次发送；10 秒内没发出就清空输入框；按任务号去重；最多读 90 秒；验证和登录只回报、不代做。
- **应用界面。** 直接加载 `http://127.0.0.1:43123`。

### 3. 配对与桥接协议（后端 127.0.0.1:43124，现有实现）

所有 `/api/ext/*` 请求都必须满足：没有 `Origin`，或者 `Origin` 是 `chrome-extension://…`、`http://127.0.0.1:43123`、`http://localhost:43123`；其他来源一律 403。桌面壳主进程用 Node 发请求时没有 `Origin`，可以通过。

| 接口 | 说明 |
| --- | --- |
| `POST /api/ext/code` | 签发一次性配对码，5 分钟有效。由应用界面调用，显示给用户 |
| `POST /api/ext/pair` `{code}` | 返回 `{token}`（48 位十六进制）。码只能用一次。之后所有请求都带 `Authorization: Bearer <token>`，后端只存令牌的哈希。桌面壳可以在主进程里自动完成“取码、配对”，不用用户抄码，前提是两步都只走本机地址 |
| `GET /api/ext/jobs` | 返回 `{jobs:[{request_id, run_id, group_id, member_id, context_version, group_generation, origin, site, tab_key, prompt, action: "send"\|"cancel", open_new}]}`。每个 tab_key 同时最多一个进行中的任务 |
| `POST /api/ext/jobs/result` | `{request_id, run_id, group_id, member_id, context_version, status: complete\|error\|login\|…, text, model_label, page_url, detail}`。`page_url` 必须和绑定的源同站，否则不接受。同一任务只接受一次 |
| `POST /api/ext/jobs/progress` | `{request_id, phase: filled\|waiting\|unsent\|timeout, note}` |
| `POST /api/ext/tabs` | 心跳：`{tabs:[{tab_key, origin, alive, health?}]}`。`health` 是 `ChatclumerAdapters.health()` 的结果，后端只保留检查字段（`clean_health`），不保存页面文字。大约 20 秒没有心跳，成员显示“掉线” |
| `GET /api/ext/members/{id}` | 绑定前确认成员存在，返回 `{id, provider, web_tab_key}` |

### 4. 安装脚本和发布包必须包含的内容

- **`scripts/install.sh`（Linux/macOS）和 `scripts/install.ps1`（Windows，用户用的是 Windows）。**
  1. 检查 Python ≥ 3.10 和 Node ≥ 20，缺了就给出安装提示，不要静默装系统包。
  2. 创建 `backend/.venv`，安装 `backend/requirements.txt`。
  3. 在 `frontend/` 下运行 `npm ci`。
  4. 调用现有的 `scripts/start.sh` 或 `start.ps1`，不要另起一套进程管理。
  5. 打印应用地址 `http://127.0.0.1:43123`，以及加载扩展的步骤：打开 `chrome://extensions`，开启开发者模式，点“加载已解压的扩展程序”，选 `extension/`（或发布包里解压出的扩展目录），然后在房间里取配对码、在扩展弹窗里配对。
  6. 默认只监听 127.0.0.1。`LAN=1` 的警告要保留。
  7. 不要把密钥写进脚本或日志。
- **发布包 `chatclumer-<version>.zip`。**
  - 带版本号的扩展 zip：`extension/` 全部文件，含 `adapters/`；版本号取 `manifest.json` 的 `version`。
  - 后端源码，不含 `.venv`、`backend/data/`、`__pycache__`。
  - 前端源码，不含 `node_modules`、`.next`；如果附带 `next build` 的产物，启动方式要改成 `next start`。
  - `scripts/`、`README.md`、`docs/`、`LICENSE`（如果有）。
  - `SHA256SUMS`。
  - 不能包含：`backend/data/`（数据库和 secrets.json）、`.run/`、`dom-dumps/`、任何令牌或配对码。
- **验收。** 在干净目录里解压，运行安装脚本，`/api/health` 返回 `service: multi-llm-chat-room`，扩展能加载，弹窗里的“检查当前页”能用。
