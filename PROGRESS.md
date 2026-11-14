# 进度

P0 收口已在本机做完：依赖 high 用 overrides 修掉且未 `--force`；指定总结模型走真实 provider，硬上限覆盖这一次请求；无凭证、停止、预算不足时保留本地回顾。默认总结仍是规则摘录。启动和停止按本次进程树清理，端口被其他进程占用时立即失败。

未做，且不阻塞网页：

- QQ / 微信仍是 `BLOCKED_EXTERNAL`。本轮不做 P1。
- 没有真实收费模型调用。指定总结模型只在单测里用 mock provider 走过一次。
- Windows 脚本只在 Linux 上做了静态检查，没有在 Windows 上跑过。
- 开发工具链仍有 11 项 moderate/low（shadcn CLI、eslint），不在页面运行时。
