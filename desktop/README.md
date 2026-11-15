# 桌面壳（原型）

尚未在真实网站上验证。不要把它当成已经可以代替扩展的正式版本。

它打开 `http://127.0.0.1:43123`，并为 `extension/adapters/registry.json` 里的每个站点开一个窗口。每个窗口使用独立的持久分区（例如 `persist:qwen`），登录由你自己完成。主进程走本机 `127.0.0.1:43124` 自动配对，轮询任务，发送心跳。页面里的写入、单击和「已填入，未发送」仍由 `extension/` 里的同一批脚本完成。

不读取 Cookie，不抽取令牌，不调用站点私有接口，不绕过登录、验证码或证书校验。没有改用户代理去伪装成普通 Chrome。

```bash
cd desktop
npm install
npm start
```

先要本机服务已经在跑（`scripts/install.sh` 或 `scripts/start.sh`）。打包配置在 `package.json` 的 `build` 里：Windows 是 nsis 和 portable，Linux 是 AppImage 和 deb。`npm run dist` 不会在发布工作流里自动执行。

说明见 [docs/DESKTOP.md](../docs/DESKTOP.md)。
