# 明早交接

## 位置

代码在当前工作区根目录，本地分支 `main`。没有推送、没有部署、没有公开发布。功能与本说明的 Git HEAD 以 `git rev-parse --short HEAD` 为准；写这一版时上一版功能提交是 `6e0a85b`，验收修复在其后的提交。

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
- 默认上限 3 轮、10 条 AI 消息、120 秒。到限不再发请求。
- 连接器：OpenAI 兼容、Anthropic、Gemini、Ollama。没有密钥不会伪装。

## 不要当成已经完成的事

- 默认总结是**本地规则摘录**，把公开句子分进六段。它不是模型重新综合。界面徽章写「本地回顾」，正文写「按公开句子摘录，不是模型重新综合」。只有把总结改成某个成员，并且不是用户停止/超时/失败、还剩额度和时间，才会再请求那一个成员。结构不完整就改回本地回顾，不再发第二次。
- 自由群聊不是固定全员轮询：首轮在没有 token/费用上限时并发独立回答；之后每轮通常只点一位（提及 +100、上一位建议 +40、刚说过的人 -35）。提示词带已公开记录。演示模板在被点到时总会写一段话，不会自己弃权。真实模型可以写出「没有新的观点」，之后调度可以不再点他。调度在发请求之前决定本轮谁不开口，模型不能零请求弃权。
- 没有单价的 OpenRouter 模型（不是明确的 `:free` 结尾）直接拒绝，不会按 0 美元放行，也不会去掉后缀改走收费模型。`:free` 请求关闭 OpenRouter fallback。这次没有真实调用。
- QQ / 微信仍是 `BLOCKED_EXTERNAL`。

## 哪些能用

| 能力 | 状态 |
| --- | --- |
| 演示群讨论、互评、@、暂停/继续、运行中停止、本地总结 | 现在可用，标明非真实模型 |
| 有单价表之外的云端模型 | 需要密钥。设了费用上限、或 OpenRouter 不是 `:free` 时，未知价格拒绝请求 |
| `:free` OpenRouter | 需要 `OPENROUTER_API_KEY`，模型 ID 必须以 `:free` 结尾 |
| Ollama | 只连接已有服务，不下载模型 |
| QQ / 个人微信 | 未接通 |

## 三分钟试用

1. `bash scripts/start.sh`，打开 http://127.0.0.1:43123 。
2. 点「演示群」，看橙色横幅。
3. 发一句。看独立回答，再看时间线上的「我读了 @」。
4. 运行中点「停止」。状态应变成「已停止」，结束原因是「用户停止」，而不是轮数上限。
5. 总结徽章是「本地回顾」。刷新后不会自己重开。

## 实际测试

北京时间 2026-11-15 00:30 CST 前后，在本机执行。

- `cd backend && .venv/bin/pytest -q` → `19 passed in 2.50s`
- `backend/.venv/bin/python scripts/browser_accept.py` → 退出码 0：

```
stop ok messages=7 reason=user_stop
pause/resume ok
mention only 周衡
member persisted
```

运行中截图时轮次是 1/8，三人正在说。点击停止后状态是已停止，结束原因是用户停止，又等了 4 秒，消息条数没有增加。暂停后状态保持已暂停，继续后回到运行中。`@周衡` 的时间线里没有林知秋和苏晚发言。手工添加的成员是 Anthropic、模型 ID `claude-sonnet-4-5-20250929`，刷新后仍在，没有发起真实请求。

单测新增：输入 token 超过上限时 0 次请求；token 上限下首轮不会并发打出第二个请求；交叉轮不是全员固定轮询；OpenRouter 非 `:free` 在有费用上限时不联网；`:free` 请求体模型 ID 不变，且 `allow_fallbacks` 为 false，不重试。

`scripts/start.ps1` 在这台 Linux 上没有 PowerShell，没有实际跑起来。静态核对：缺 Python/Node 会停并提示，端口写死 `127.0.0.1:43123` 和 `43124`。

截图相对交付目录：

- `artifacts/stop-while-running.png`
- `artifacts/stopped-no-new-messages.png`
- `artifacts/paused.png`
- `artifacts/resumed.png`
- `artifacts/mention-zhouheng.png`
- `artifacts/member-persisted.png`

## 环境限制

- 预览服务只绑在这台开发机的回环地址，协调方电脑打不开这个 localhost。
- 本环境没有 Windows，也没有 PowerShell，所以 `start.ps1` 只做了静态检查。
- 没有配置真实密钥，没有打开付费开关，没有调用收费模型。
- 解压后的首次启动会自己建 `backend/.venv` 并 `npm install`，需要本机 Python 3.11+ 和 Node.js 22。

## 已知问题

- 设了 token 或费用上限时，首轮改为串行，避免并发把还没返回的用量一起发出去。没有这两项上限时，首轮仍然并发。
- 输入按提示词字符数预留。比供应商稍后回报的 token 更保守，可能更早停。
- 丢弃的独立首轮仍计入轮数。
- QQ / 微信未接通。

## 源码包

`artifacts/multi-llm-chat-room-src.zip`

不含 `node_modules`、`.next`、`.venv`、数据库、密钥和 `.git`。保留 lockfile、脚本和文档。
