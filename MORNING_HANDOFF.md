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

停止：`bash scripts/stop.sh`。Windows 用 `scripts/start.ps1`。脚本会先检查 `node`、`npm` 和 `py`/`python`，缺了就停并说明要装 Python 3.11+ 与 Node.js 22。前后端都只绑定 `127.0.0.1`。`LAN=1 bash scripts/start.sh` 才会让前端听 `0.0.0.0`，并打印无登录警告。

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

## 哪些能用

| 能力 | 状态 |
| --- | --- |
| 演示群讨论、互评、@、暂停/继续、运行中停止、本地回顾 | 现在可用，标明非真实模型 |
| 指定总结模型 | 代码路径和单测已接上。本机无密钥，浏览器里仍是本地回顾 |
| 有单价表之外的云端模型 | 需要密钥。设了费用上限、或 OpenRouter 不是 `:free` 时，未知价格拒绝请求 |
| `:free` OpenRouter | 需要 `OPENROUTER_API_KEY`，模型 ID 必须以 `:free` 结尾 |
| Ollama | 只连接已有服务，不下载模型 |
| QQ / 个人微信 | 未接通 |

## 三分钟试用

1. `bash scripts/start.sh`，打开 http://127.0.0.1:43123 。
2. 点「演示群」，看橙色横幅。设置里应有「指定总结模型（占用 1 条额度）」。
3. 发一句。看独立回答，再看时间线上的「我读了 @」。演示回复带「非真实模型」。
4. 运行中点「停止」。状态应变成「已停止」，结束原因是「用户停止」，而不是轮数上限。
5. 默认总结徽章是「本地回顾」。刷新后不会自己重开。

## 实际测试

北京时间 2026-11-15 00:41 CST 前后，在本机执行。

- `cd backend && .venv/bin/pytest -q` → `21 passed in 2.72s`
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

`scripts/start.ps1` 在这台 Linux 上没有 PowerShell，没有实际跑起来。静态核对：缺 Python/Node 会停并提示，端口写死 `127.0.0.1:43123` 和 `43124`。

截图在包内，相对本文件：

- [运行中停止前](docs/screenshots/stop-while-running.png)
- [停止后没有新消息](docs/screenshots/stopped-no-new-messages.png)
- [已暂停](docs/screenshots/paused.png)
- [已继续](docs/screenshots/resumed.png)
- [只点到周衡](docs/screenshots/mention-zhouheng.png)
- [成员刷新后仍在](docs/screenshots/member-persisted.png)
- [回归：演示回复](docs/screenshots/regression-demo.png)
- [回归：本地回顾](docs/screenshots/regression-local-summary.png)
- [桌面讨论](docs/screenshots/desktop-discussion.png)
- [桌面总结](docs/screenshots/desktop-summary.png)
- [窄屏](docs/screenshots/mobile-chat.png)

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

## 源码包

`artifacts/multi-llm-chat-room-src.zip`

不含 `node_modules`、`.next`、`.venv`、数据库、密钥和 `.git`。保留 lockfile、脚本、文档和 `docs/screenshots`。

## 当前提交

功能与交接在同一提交。完整哈希见下一行；若之后只有一行哈希修订，以 `git rev-parse HEAD` 为准。

`PENDING`
