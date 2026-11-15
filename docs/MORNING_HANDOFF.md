# 明早交接

## 位置与 Git HEAD

代码在当前工作区根目录，本地分支 `main`。没有推送、没有部署、没有公开发布。

源码 zip 不含 `.git`。核对本包对应的提交：

```bash
git rev-parse HEAD
git log -1 --oneline
git status --short
```

工作区干净时，`git rev-parse HEAD` 必须等于本文件「当前提交」一节里写下的完整哈希。不一致就以 git 为准，不要用旧包。

本机预览只在这台机器上：

- 页面 http://127.0.0.1:43123
- 后端 http://127.0.0.1:43124

没有对外预览地址。协调方请用源码包在自己的电脑启动。

## 启动

```bash
bash scripts/start.sh
```

停止：`bash scripts/stop.sh`。Windows 用 `scripts/start.ps1` 和 `scripts/stop.ps1`。脚本会先检查 `node`、`npm` 和 `py`/`python`，缺了就停并说明要装 Python 3.11+ 与 Node.js 22。前后端都只绑定 `127.0.0.1`。`LAN=1 bash scripts/start.sh` 才会让前端听 `0.0.0.0`，并打印无登录警告。

启动把后端和前端各自放进新会话，只在子进程上写下 `CHAT_ROOM_RUN` 标记。停止只向带这个标记的进程及其子进程发信号，不会按端口或进程名去结束别的服务。43123 或 43124 上如果已经有其他进程，启动立刻退出并写明 PID，不会干等健康检查，也不会把那个进程的 HTTP 200 当成就绪。就绪必须是本项目的 `/api/health` 和前端反代都返回 `"service":"multi-llm-chat-room"`。停止后若端口仍被占用，脚本退出码为 1，并说明自己没有结束那个 PID。旧版 `stop.sh` 只杀掉当时记下的父进程，`npx` 拉起的 `next dev` 和 `next-server` 会留下来；那种没有标记的旧进程，新脚本同样不会代为结束。

## 已完成（P0）

- 中文三栏房间。窄屏底栏单列。
- 成员可增删停用。各自 provider、精确 model id、昵称、角色。演示三人共用 `demo-synthesizer-v1`。
- 自由群聊、独立回答、交叉辩论、只总结。
- 每房间一个调度。插话升上下文版本，过时结果标 `stale_context`。AI 输出不会再触发。刷新不重开。
- 默认上限 3 轮、10 条 AI 消息、120 秒。到限不再发请求。消息条数、token、费用、时间四项硬上限覆盖讨论和总结请求。
- 连接器：OpenAI 兼容、Anthropic、Gemini、Ollama。没有密钥不会伪装。
- 可配置总结模型：设置里选「指定总结模型」，填 provider 和精确 model id。讨论少占 1 条消息额度留给这一次综合。无凭证、已停止、超时、失败、token/费用/时间/条数不够时，改写明确标记的本地回顾，不再发总结请求。

## 总结怎么区分

- 默认仍是本地规则摘录。徽章「本地回顾」，正文开头是「【本地回顾 · 未额外请求模型】按公开句子摘录，不是模型重新综合。」
- 「指定成员总结」在不是用户停止/超时/失败、并且还剩额度、token、费用和时间时，只再请求那一个成员一次。六段不全就改回本地回顾，不再发第二次。
- 「指定总结模型」走真实 provider 路径（OpenAI 兼容、Anthropic、Gemini、Ollama、OpenRouter）。预检失败（没有密钥、模型 ID 为空、DEMO 以外的演示 ID）只写本地回顾，正文说明未调用、不会伪装成那个模型。
- 演示总结若真的走到 demo provider，正文仍以「【演示回复 · 非真实模型】」开头，徽章是「演示总结」，不冒充真实模型。
- 这次环境没有密钥、没有打开付费开关，浏览器回归看到的是本地回顾，不是收费模型综合。

## 依赖安全

协调方首版 zip 的 `npm install` 报 14 项（2 high、10 moderate、2 low）。本环境对当时的 lockfile 核对后，两项 high 是：

- `postcss` ≤ 8.5.22（随 `next@15.5.29` 带入 8.4.31）。审计建议的唯一修复是升到 Next 16。
- `sharp` ≤ 0.35.5-rc.1（安装的是 0.34.5，Next 的可选依赖）。

没有执行 `npm audit fix --force`，也没有升 Next 16。在 `frontend/package.json` 用 overrides 钉住可运行版本：`postcss@8.5.33`、`sharp@0.35.5`。`npm ls` 确认 Next 15.5.29 实际用的是这两个版本。修复后再跑 `npm audit`：critical 0、high 0、moderate 9、low 2，合计 11。

剩下的 11 项只在开发工具链里，聊天页面运行时不会加载：

- `deepmerge` / `@shadcn/registry` / `shadcn`：shadcn CLI 合并注册表时的原型污染。修法是 shadcn 大版本。运行中的 Next 页面不调用这条路径。
- `minimatch`、`typescript-eslint`、`ts-morph`：ESLint / shadcn CLI 的 ReDoS。修法要动 eslint 工具链大版本。浏览器包不包含这些模块。

缓解：不要在生产机上对不可信输入跑 `shadcn` 或 eslint。不要为清掉这 11 项去 `--force`。

## 不要当成已经完成的事

- 自由群聊不是固定全员轮询：首轮在没有 token/费用上限时并发独立回答；之后每轮通常只点一位（提及 +100、上一位建议 +40、刚说过的人 -35）。提示词带已公开记录。演示模板在被点到时总会写一段话，不会自己弃权。真实模型可以写出「没有新的观点」，之后调度可以不再点他。调度在发请求之前决定本轮谁不开口，模型不能零请求弃权。
- 没有单价的 OpenRouter 模型（不是明确的 `:free` 结尾）直接拒绝，不会按 0 美元放行，也不会去掉后缀改走收费模型。`:free` 请求关闭 OpenRouter fallback。这次没有真实调用。
- QQ / 微信仍是 `BLOCKED_EXTERNAL`。本轮没有做 P1。
- 分组和网页桥已经接到房间里。独立分支、合并预览、拆分可以在页面上操作。网页成员只有绑定了明确标签、打开受控自动发送、并且房间没有费用上限时才会发送。Gemini 的游客回路通过了；Qwen 停在年龄确认；元宝游客输入从 2026-11-15 起要先在标签页登录一次，登录后的自动发送、读回和转发已在 07:46 用扩展 0.2.9 核对；智谱游客可用但扩展不自动点发送；DeepSeek 和豆包已按 2026-11-15 的登录页结构接入，实页还没有再核对；ChatGPT、Claude 是 BLOCKED；Grok 是登录墙。详见 `WEB_ACCESS.md`。不要把夹具或被挡住的站点说成已经接通。

## 哪些能用

| 能力 | 状态 |
| --- | --- |
| 演示群讨论、互评、@、暂停/继续、运行中停止、本地回顾 | 现在可用，标明非真实模型 |
| 指定总结模型 | 代码路径和单测已接上。本机无密钥，浏览器里仍是本地回顾 |
| 有单价表之外的云端模型 | 需要密钥。设了费用上限、或 OpenRouter 不是 `:free` 时，未知价格拒绝请求 |
| `:free` OpenRouter | 需要 `OPENROUTER_API_KEY`，模型 ID 必须以 `:free` 结尾 |
| Ollama | 只连接已有服务，不下载模型 |
| QQ / 个人微信 | 未接通 |
| 独立分支、合并预览、拆分 | 页面可用。演示回复仍标明非真实模型 |
| 本地夹具网页成员 | 扩展 → 本机桥 → 房间已跑通。夹具不是真实模型 |
| Gemini 游客网页 | 2026-11-15 01:30 CST 扩展回路通过，页面显示 Flash-Lite。另一成员是演示模型 |
| 元宝网页（登录后） | 已实页验证自动发送、读回、转发（扩展 0.2.9，2026-11-15 07:46）。游客输入仍要先登录 |
| 智谱网页 | 游客页可以人工使用。扩展不自动点击发送 |
| 设置 | 房间标题旁的「设置」：浅色/深色/跟随系统、字号、导出、本机配对码 |
| 收藏和分歧 | 收藏卡片写明不是已核实事实。分歧只列显式质疑或反驳，没有就空着，不编共识 |
| 网页成员表单 | 来源、页面地址、绑定键、受控自动发送会写入 web-bind。卡片上可复制成员 ID 和绑定键 |
| Qwen 网页 | 停在年龄确认，没有读到回复 |
| ChatGPT / Claude 网页 | BLOCKED，没有绕过 |
| DeepSeek / 豆包网页 | 扩展 0.3.0 已按 2026-11-15 08:30 的只读 DOM 接入。实页发送和读回还没有再核对。未登录不发送 |
| Grok 网页 | 登录墙，没有当成游客 |

## 三分钟试用

1. `bash scripts/start.sh`，打开 http://127.0.0.1:43123 。
2. 点「演示群」，看橙色横幅。设置里应有「指定总结模型（占用 1 条额度）」。
3. 发一句。看独立回答，再看时间线上的「我读了 @」。演示回复带「非真实模型」。
4. 运行中点「停止」。状态应变成「已停止」，结束原因是「用户停止」，而不是轮数上限。
5. 默认总结徽章是「本地回顾」。刷新后不会自己重开。

## 分组与网页验收

记录里的 UTC 已换成北京时间。2026-11-14T17:30:36Z 是 2026-11-15 01:30:36 CST。清单如下。

- 旧的 21 个测试仍在。本机装了 Playwright 时，`cd backend && .venv/bin/pytest -q` 是 46 passed。其中 10 条是浏览器测试。没有 Playwright 时是 36 passed, 10 skipped。skipped 不是 passed。安装见 `backend/requirements-dev.txt`。
- DeepSeek 与豆包的适配器在扩展 0.3.0。来源名是成员表单里的「DeepSeek」和「豆包」。实页发送和读回还没有再核对。
- 元宝（登录后）在 2026-11-15 07:46 用扩展 0.2.9 实页核对通过：第一轮发送并读回 A/B 的答案 1；第三轮把林知秋的公开答复转发一次，读回与页面一致。元宝用户气泡与房间任务都是 2，没有多余发送，结束后输入框是空的。游客输入仍要先登录。此前第三轮曾因换行被拆段而报 145 对 128，没有发送。
- 浏览器：`backend/.venv/bin/python scripts/check_branch_ui.py` 通过。预览里有勾选的两人，没有未勾选的第三人；合并后能选择发给哪一组；拆分后刷新，状态不是进行中。
- 扩展：品牌版 Chrome 157 不接受 `--load-extension`。Chrome for Testing 加载 `extension/` 后，`scripts/check_web_bridge.py` 的夹具和 Gemini 都是 passed。夹具第二次提交含「公开答复」，停止后仍是 2 条用户气泡，房间里有 2 条完成回复，模型名是「Fixture 本地」。
- Gemini：https://gemini.google.com/app ，游客，页面显示 Flash-Lite。扩展先发送「请用中文给两条简短读书建议，每条一句话。」，房间记下两条建议；合并后再把选中的公开答复发进同一个页面，房间记下第二条回复；停止后 4 秒内没有新的助手消息。没有点登录、订阅或模式切换。
- 更早一次 Gemini 转发被测试脚本提前停止，房间把那条标成 cancelled，页面上也没有形成可用回复。上面这条 passed 是修正等待之后重跑的，不是绕过限制。
- Qwen：https://chat.qwen.ai/ 手动点了一次 Send，随后出现确认年龄。没有填出生年，没有点 Continue，没有读到回复。这一条不是扩展端到端。
- ChatGPT、Claude、DeepSeek、Grok 沿用早前结果，本轮没有重试，也没有换入口。

截图：

- [分支预览](screenshots/branches-preview.png)
- [分支桌面](screenshots/branches-desktop.png)
- [分支窄屏](screenshots/branches-mobile.png)
- [夹具扩展回路](screenshots/fixture-bridge.png)
- [Gemini 扩展回路](screenshots/gemini-bridge.png)
- [Qwen 停在年龄确认](screenshots/qwen-manual.png)
- [设置，深色](screenshots/settings-dark.png)
- [设置，窄屏](screenshots/settings-mobile.png)
- [元宝登录后第三轮转发读回](screenshots/yuanbao-forward-round3.png)
- [本机元宝发送后回到登录](screenshots/yuanbao-vm-guest.png)
- [协调方人工停止元宝，不是扩展回路](screenshots/yuanbao-guest-stop-manual.webp)
- [网页成员绑定字段](screenshots/web-bind-member.png)

## 实际测试

北京时间 2026-11-15 00:41 CST 前后，在本机执行。

- `cd backend && .venv/bin/pytest -q` → 当时 `21 passed`。分组完成后重跑是 `26 passed`。
- `cd frontend && npx tsc --noEmit` 通过
- `cd frontend && npm run build` 通过（Next.js 15.5.29）
- 浏览器回归：演示房间能看到「指定总结模型」选项；发送后正文含「非真实模型」；结束后状态「已停止」，并出现「本地回顾」

此前验收脚本 `backend/.venv/bin/python scripts/browser_accept.py` 结果仍然有效：

```
stop ok messages=7 reason=user_stop
pause/resume ok
mention only 周衡
member persisted
```

单测覆盖：mock 的 OpenAI 兼容总结模型恰好请求一次，六段标题都在，`is_demo` 为假，消息条数不越限；用户停止、token 预算为 1、以及没有密钥时都不发总结请求，并保留本地回顾标记。输入 token 超过上限时 0 次请求；token 上限下首轮不会并发打出第二个请求。OpenRouter 非 `:free` 在有费用上限时不联网；`:free` 请求体模型 ID 不变，且 `allow_fallbacks` 为 false。

`bash scripts/test_lifecycle.sh` 在本机通过：孙子进程占着的端口会随标记一起释放，旁边另一个端口上的服务还在；其他服务占着 43123 并返回 HTTP 200 时，`start.sh` 立即失败且不杀掉它；接着真实执行 start → stop（43123 与 43124 都释放）→ start → stop，两次停止后都没有残留监听。

`scripts/start.ps1` 和 `scripts/stop.ps1` 在这台 Linux 上没有 PowerShell，没有实际跑起来。静态核对：缺 Python/Node 会停并提示；启动前检查端口；就绪要看到 `multi-llm-chat-room`；停止只沿记下的进程树往下结束，不用 `taskkill` 按映像名清理，端口仍被占用时退出失败。

截图在包内，相对本文件：

- [运行中停止前](screenshots/stop-while-running.png)
- [停止后没有新消息](screenshots/stopped-no-new-messages.png)
- [已暂停](screenshots/paused.png)
- [已继续](screenshots/resumed.png)
- [只点到周衡](screenshots/mention-zhouheng.png)
- [成员刷新后仍在](screenshots/member-persisted.png)
- [回归：演示回复](screenshots/regression-demo.png)
- [回归：本地回顾](screenshots/regression-local-summary.png)
- [桌面讨论](screenshots/desktop-discussion.png)
- [桌面总结](screenshots/desktop-summary.png)
- [窄屏](screenshots/mobile-chat.png)

## 环境限制

- 预览服务只绑在这台开发机的回环地址，协调方电脑打不开这个 localhost。
- 本环境没有 Windows，也没有 PowerShell，所以 `start.ps1` 只做了静态检查。
- 没有配置真实密钥，没有打开付费开关，没有调用收费模型。
- 解压后的首次启动会自己建 `backend/.venv` 并 `npm install`，需要本机 Python 3.11+ 和 Node.js 22。安装后 high 应为 0；moderate/low 见上文，不要 `--force`。

## 已知问题

- 设了 token 或费用上限时，首轮改为串行，避免并发把还没返回的用量一起发出去。没有这两项上限时，首轮仍然并发。
- 输入按提示词字符数预留。比供应商稍后回报的 token 更保守，可能更早停。未知费用在设了费用上限时直接拒绝，不会当成 0。
- 丢弃的独立首轮仍计入轮数。
- 开发依赖里仍有 11 项 moderate/low，见「依赖安全」。
- QQ / 微信未接通。

## 源码包与 Git 历史

- `artifacts/multi-llm-chat-room-src.zip`：不含 `node_modules`、`.next`、`.venv`、数据库、密钥和 `.git`。保留 lockfile、脚本、文档和 `docs/screenshots`。
- `artifacts/multi-llm-chat-room.bundle`：本地 commit 历史，不含密钥文件。在空目录还原：

```bash
git clone multi-llm-chat-room.bundle multi-llm-chat-room
cd multi-llm-chat-room
git rev-parse HEAD
git status --short
```

还原后的 HEAD 必须等于下面「当前提交」。工作区应为空。

## 当前提交

分组和网页桥提交后，用下面的命令核对。若其后只有记下哈希的修订，以 `git rev-parse HEAD` 为准，并确认功能提交仍是祖先。

元宝登录后的发送、读回和转发核对记在这份交接里。功能提交仍是：

`22e6489e2ea84f28eea1f25449bd1b63d178146c`

元宝一段完成即读回仍是祖先：

`3335c75d02aa85b33eb9e32f41d6acdd76f7286e`

元宝 A/B 读回仍是祖先：

`a847146d5b6864bb20531cf54294b73526829f90`

元宝新输入区和登录层仍是祖先：

`2c5fe1aa64fcafe4fd92f8f1414f1bdd2177a413`

元宝只写一次仍是祖先：

`0a4b93523deea8efc513fae858304b8b82b33663`

元宝 div 发送控件仍是祖先：

`776bb15e180858ae7275de37894e041d46ac51bd`

上一包仍是祖先：

`84f978e1ad08322480367071b246843b5a437ccb`

此前的边界修正仍是祖先：

`332bf76e4824b9ee872c20acf375779ef141ff92`

分组与网页桥仍是祖先：

`989b3b8c0e00b652a270e6b5a6728372e4abc228`

核对：

```bash
git rev-parse HEAD
git log -1 --oneline
git merge-base --is-ancestor 22e6489e2ea84f28eea1f25449bd1b63d178146c HEAD && echo ancestor-ok
git status --short
```

`ancestor-ok` 且工作区为空，就是这份交付。源码 zip 没有 `.git`，用 bundle 还原后再执行上面的命令。
