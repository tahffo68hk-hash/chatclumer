# 明早交接

## 位置

代码在当前工作区根目录。本地分支 `main`。功能提交是 `6e0a85b`。本交接说明的后续修订以 `git rev-parse --short HEAD` 为准，没有推送到远程。

本机预览（只在这台机器上）：

- 页面 http://127.0.0.1:43123
- 后端 http://127.0.0.1:43124

没有对外的预览地址。`127.0.0.1` 不能从你的电脑打开。源码包在文末。

## 启动

```bash
bash scripts/start.sh
```

停止：`bash scripts/stop.sh`。Windows 说明在 `scripts/start.ps1`，只绑定回环。`LAN=1` 会让前端监听 `0.0.0.0` 并打印无认证警告，后端仍然只在本机。

## 已完成

- 中文三栏房间：会话 / 唯一时间线 / 运行与上限。窄屏改为底栏单列。
- 成员可增删和停用。各自有 provider、精确 model id、昵称、角色。演示三人共用 `demo-synthesizer-v1`，角色不同，不假装是不同模型。
- 自由群聊、独立回答、交叉辩论、只总结。首轮独立并发；之后按公开发言选择下一位，可以 `reply_to`。
- 每房间一个调度任务。用户插话提升上下文版本，过时流标记 `stale_context`。AI 输出不会再触发一轮。刷新只读记录。
- 默认硬上限：3 轮、10 条 AI 消息、120 秒。token / 费用上限可配。到限不再发请求。总结默认本地回顾，不额外请求模型，六段只出现一次。
- 连接器代码：OpenAI 兼容（含 OpenRouter、DeepSeek、Qwen、xAI）、Anthropic、Gemini、Ollama。没有密钥不会伪造真实回复。

## 哪些能用

| 能力 | 状态 |
| --- | --- |
| 演示群的讨论、互评、引用、插话、停止、总结 | 现在可用，标明非真实模型 |
| OpenAI 兼容 / Anthropic / Gemini / OpenRouter / DeepSeek / Qwen / xAI | 需要对应密钥。可能计费的调用还要 `ALLOW_PAID_PROVIDERS=1`。本次没有真实调用 |
| Ollama | 需要本机已有服务和模型。程序不会下载模型 |
| QQ 官方机器人 | `BLOCKED_EXTERNAL`。可本地模拟命令，没有接通真实群 |
| 个人微信 | 拒绝。公众号 / 企业微信只有配置位，同样 `BLOCKED_EXTERNAL` |

## 三分钟试用

1. `bash scripts/start.sh`，打开 http://127.0.0.1:43123 。
2. 点「演示群」。确认橙色横幅写着合成回复不是真实模型。
3. 发送一个问题。看三人独立回答，然后时间线上出现「我读了 @某人」。
4. 运行中在输入框写 `@周衡 …` 并点「插话」。被打断的气泡会标成已丢弃。
5. 等结束，或点停止。底部只有一份总结：主要结论、共识、分歧、未验证事实、最推荐建议、下一步行动。
6. 刷新。状态保持已完成或已停止，讨论不会自己重开。

## 实际测试

2026-11-14，在本机执行：

- `cd backend && .venv/bin/pytest -q` → `17 passed in 2.01s`
- `cd frontend && npx tsc --noEmit` → 退出码 0
- `cd frontend && npm run build` → Next.js 15.5.29 编译成功
- `backend/.venv/bin/python scripts/browser_check.py` → 退出码 0，输出：

```
desktop discussion saved
clicked stop
status after summary: 已完成
status after reload: 已完成
mobile input value set: 手机上补一句：先停在可观
```

浏览器房间 `ea6b4845038a4ebc`：插话后上下文版本 2；第 1 轮三条独立回答 `discarded_reason=stale_context`；周衡在第 3 轮引用用户那句 `@周衡`；总结 1 条，provider 为本地回顾；结束原因 `limit_rounds`（达到轮数上限）。点停止时这一轮已经先触到轮数上限，所以结束原因不是用户停止。用户停止由单测 `test_user_stop_and_no_self_trigger` 覆盖。

更早的演示房间（例如 `60f15413ca1c46ca`）里，林知秋引用了苏晚的公开发言，苏晚再引用林知秋，同一条时间线、多轮。

单测覆盖：并发首轮、消息/轮数/token/费用上限、独立超时取消、用户停止且 AI 不自触发、插话丢弃且只有一个调度、暂停不叫下一位、提供方失败并脱敏、早停且总结一次、重启恢复不重复总结、未授权付费模型不伪装、OpenAI/Anthropic/Gemini/Ollama 解析、免费路由守卫、接口脱敏且刷新不重启。

截图（本次浏览器实拍，不是生成图）：

- `/opt/cursor/artifacts/desktop-discussion.png` 运行中，插话已进入时间线，过时回答标已丢弃，周衡正在说
- `/opt/cursor/artifacts/desktop-summary.png` 已完成，一份本地六段总结，3/3 轮，5/10 条
- `/opt/cursor/artifacts/desktop-after-reload.png` 刷新后仍是已完成，结束原因仍是轮数上限
- `/opt/cursor/artifacts/mobile-chat.png` 390 宽单列，底栏，输入框里有手机补句

## QQ / 微信

见 `docs/QQ_WECHAT.md`。两者都是 `BLOCKED_EXTERNAL`。不能说真实群已接通。

## 已知问题

- 插话如果发生在独立首轮，丢弃的那一轮仍计入 `current_round`。默认 3 轮时，后续互评轮次变少。
- 浏览器这次点停止输给了轮数上限，页面结束原因是「达到轮数上限」。
- 真实模型路径没有在这次用真实流量打过。未知费用不会调用。
- 预览服务是开发服务器，只绑定本机。

## 下一步

配置一把确认零费用的密钥后再做一次真实成员试聊。QQ 要有 AppID、token 和官方权限后才能改掉 `BLOCKED_EXTERNAL`。微信只走公众号或企业微信官方接口。

## 源码包

`/opt/cursor/artifacts/multi-llm-chat-room-src.zip`

不含 `node_modules`、`.next`、`.venv`、数据库、密钥和 `.git`。保留 lockfile、脚本和文档。
