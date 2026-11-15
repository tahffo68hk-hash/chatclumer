# 桌面壳（原型）

这是原型，**尚未在真实网站上验证**。它不能代替已经在 Chrome 里核对过的扩展。站点改版、登录墙、验证码和 Electron 自带的浏览器标识都可能让窗口打不开或填不进去。真要发消息时，仍以扩展那条已核对过的路径为准。

## 它做什么

- 打开已经在跑的应用页面 `http://127.0.0.1:43123`。桌面壳不另起后端或前端，启动仍然用 `scripts/start.sh` / `scripts/start.ps1`（安装脚本会去调它们）。
- 按 `extension/adapters/registry.json` 给每个网页 AI 一个自己的窗口。窗口里是 `WebContentsView`（旧版 Electron 则退回整个窗口加载该站）。分区是 `persist:<站点 id>`，例如 `persist:qwen`，所以你在这个窗口里登录一次，下次还在。
- 主进程代替扩展后台：向 `127.0.0.1:43124` 取一次性配对码并立刻配对，然后每 1.2 秒拉任务、把页面检查随心跳送回去。Node 请求不带 `Origin`，现有桥接会接受。不用把配对码抄到弹窗里。
- 每个站点窗口的 preload 在隔离世界里按扩展相同的顺序加载 `adapters/schema.js`、`adapters/registry.js`、`adapters/runtime.js`，再加上该站的 `guest.js` 或内置脚本和 `content.js`。`chrome.runtime` 只有一个最小替身，用来收 `run` / `health` / `dump` / `registry-get`。

## 它不做什么

- 不读取 Cookie，不从页面抽令牌，不调用站点的私有接口。
- 不关登录框，不填账号，不点验证码或滑块，不把证书错误放行，也不改用户代理去假装成普通 Chrome。有的网站会因此拒绝 Electron，这时用扩展。
- 不放宽扩展里的安全规则。仍然只写一次并核对；只点一次发送；页面没有确认发出就清空输入框并报告「已填入，未发送」。这些话和动作都在原来的 `extension/*.js` 里，桌面壳只是加载它们。
- 远端注册表仍只是数据。结构不合法、版本不比内置新、或页面里有选择器解析失败，就继续用内置。不执行远端代码。

## 怎么用

1. 先装好并启动本机服务：`bash scripts/install.sh`，或 Windows 的 `scripts\install.ps1`。
2. `cd desktop && npm install && npm start`。
3. 应用窗口是房间。旁边的「网页 AI」列表里打开要用的站。
4. 在房间里添加网页成员。来源用该站的 https 源，绑定键用窗口标题里的那一串。列表留空时，如果房间里这个来源只有一个绑定键，就用那个；否则用站点 id（例如 `qwen`）。
5. 在站点窗口里自己登录。登录弹窗没有注入自动化脚本。

同一时间只跑一个桌面壳，避免两个进程各点一次发送。

## 打包

`desktop/package.json` 里的 electron-builder 配置：

- Windows：`nsis`（可选目录、不要求管理员）和 `portable`
- Linux：`AppImage` 和 `deb`

`npm run dist` 由人在本机跑。GitHub Actions 里这个构建是可选项，只有手动触发并勾选 `build_desktop` 才执行，不随 tag 的应用包和扩展 zip 一起做。未签名的安装包可能被系统拦截，这和 GodMode 的说明是同一类问题；本仓库不提供绕过签名检查的步骤。

## 还没验证的部分

- 没有在 Qwen、文心、DeepSeek、豆包、元宝或其他真实站点上跑过这个壳。
- preload 在 `contextIsolation` 下能否让站点自己的框架认出这次输入，只在夹具 DOM 上做过单元测试，没有实页。
- 自动配对和心跳在本机假后端上对过协议，没有连着一个真的房间做端到端。
- Windows 安装包没有在 Windows 上打过。
