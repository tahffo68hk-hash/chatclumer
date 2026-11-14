# 多模型群聊

一个中文共享时间线。一次提问后，多个模型先各自回答，再阅读彼此已经公开的发言，选择回复、质疑或补充。这是聊天房间，不是多 Agent 框架，也不调用工具。

没有密钥时整间房是 **DEMO**。合成回复每一行都带「非真实模型」，不会伪装成 GPT、Claude、Gemini 或 Grok。

## 启动

需要 Python 3.11+ 和 Node.js 22。默认只监听本机。

```bash
bash scripts/start.sh
```

- 页面：http://127.0.0.1:43123
- 后端：http://127.0.0.1:43124
- 停止：`bash scripts/stop.sh`。它只结束本次启动记下的进程树。端口若仍被其他进程占用，会报出 PID 并失败，不会把别人的 HTTP 200 当成已启动。

Windows 可参考 `scripts/start.ps1`，同样只绑定回环地址。

局域网仅在你明确接受无登录风险时使用：

```bash
LAN=1 bash scripts/start.sh
```

前端会监听 `0.0.0.0:43123` 并打印警告。后端仍在 `127.0.0.1`。不要把没有认证的服务暴露到公网或做端口转发。

## 密钥

复制 `.env.example` 里的名字到环境变量，或在页面「密钥」里写入服务器文件 `backend/data/secrets.json`（权限 600）。接口只返回是否已配置，不回显原文。可能计费的云端调用需要 `ALLOW_PAID_PROVIDERS=1`，默认关闭。Ollama 只连接 `OLLAMA_BASE_URL`，不会下载模型。

网页成员和分组说明在 `docs/WEB_ACCESS.md`。扩展只配对本机 `127.0.0.1:43124`，不会读取 Cookie。

## 测试

```bash
cd backend && .venv/bin/pytest -q
cd frontend && npx tsc --noEmit && npm run build
backend/.venv/bin/python scripts/browser_check.py
```

聊天记录在 `backend/data/chat.db`（SQLite，已忽略）。来源和许可证见 `docs/SOURCES.md`。QQ / 微信见 `docs/QQ_WECHAT.md`，当前都是 `BLOCKED_EXTERNAL`。
