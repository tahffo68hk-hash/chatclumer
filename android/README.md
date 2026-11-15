# ChatCluster 安卓客户端

手机上的远程客户端。它连到你电脑上已经在跑的 ChatCluster（页面端口 43123），用系统 WebView 打开同一套网页。网页里的 AI 成员仍由那台电脑上的浏览器扩展驱动，手机不登录这些网站，也不读取扩展里的令牌。

不依赖 Google Play 服务。扫码使用内嵌的 zxing，方便在没有 Play 商店的手机上安装。

## 安装

1. 把 `chatclumer-android-release.apk`（或调试包）传到手机。
2. 打开文件。如果系统拦截，到设置里允许来自当前应用（文件管理器或浏览器）的安装，也就是「允许未知来源」或「安装未知应用」。
3. 安装完成后打开 ChatCluster。

更新时如果提示签名不一致，先卸载旧版再装。用调试密钥签的包，换一台电脑重新构建后签名会变，不能覆盖安装。

## 配对

1. 在电脑上用手机模式启动：`LAN=1 bash scripts/start.sh`（Windows：`$env:LAN="1"; .\scripts\start.ps1`）。不加 `LAN=1` 时页面只监听本机，手机连不上。
2. 在电脑上打开 http://127.0.0.1:43123 ，点顶部「手机连接」。二维码默认是模糊的，点一下才显示。选「安卓 App 扫码」。
3. 手机和电脑在同一局域网，或两边都登录同一个 Tailscale 账号。
4. 在手机上点「扫描二维码」。二维码内容是 `chatclumer://pair?u=<电脑地址>&t=<口令>`。也可以用系统相机扫，装好本应用后会直接打开。
5. 不想扫码时，点「手动输入」，填写面板里的地址（例如 `http://192.168.1.5:43123`）和口令。没写 `http://` 时按明文 HTTP 处理。

连接前会请求 `GET /m/ping`，而且**不附带口令**。只有返回的 `app` 等于 `chatclumer` 才会保存。从手机上看，这个接口里的 `auth` 通常是 `false`，这不代表配对失败。随后 WebView 打开 `/m/pair?token=…`，电脑设置 HttpOnly 的 `cc_session` 并跳转到页面。

可以保存多台电脑，分别重命名、删除或重新连接。口令在列表里只显示末四位。

## 使用

- 下拉刷新当前页。
- 系统返回键先走网页历史，再回到电脑列表。
- 旋转屏幕不会重新加载页面。
- 网页里的文件选择（`<input type=file>`）会打开系统文件选择器。
- 离开当前电脑地址的链接用系统浏览器打开。
- 界面跟随系统深色或浅色。网页自身的主题由页面控制。

连不上时会看到说明和「重试」。口令被拒绝（HTTP 401）时可以重新扫描。同一 IP 在 10 分钟内提交 10 个不同的错误口令后，电脑会返回 429 和 `Retry-After`。应用会显示还要等多久，并在倒计时结束前**不再发起连接**，避免越试越被锁。

## 为什么允许明文 HTTP

家里的 ChatCluster 通常是 `http://192.168.x.x:43123`，没有证书。Android 9 起默认禁止明文流量。网络安全配置只能按域名放行，不能按网段放行一个事先不知道的局域网地址，所以 `app/src/main/res/xml/network_security_config.xml` 允许明文 HTTP。应用仍然先确认对方是 ChatCluster，并且 WebView 只停留在你确认过的那个源（协议、主机和端口）。Tailscale 地址同样可能是 HTTP；Tailscale 链路本身是加密的。咖啡馆这类公共 Wi-Fi 上不要开手机模式。

## 口令存在哪里

地址和口令放在 `EncryptedSharedPreferences`（Android Keystore 里的 AES 密钥）中。应用关闭了备份和设备迁移，避免口令进云备份。日志里不写口令，界面上打码。请不要把配对二维码发给别人。

## 构建

需要 JDK 17 或更高，以及 Android SDK（`compileSdk` / `targetSdk` 36，`minSdk` 24）。设置 `ANDROID_HOME`，或在 `android/local.properties` 里写 `sdk.dir`。

```bash
cd android
./gradlew test
./gradlew assembleDebug assembleRelease
```

调试包在 `app/build/outputs/apk/debug/`，发布包在 `app/build/outputs/apk/release/`。两边都可以安装。

## 签名

发布包优先使用环境变量里的密钥库：

| 变量 | 含义 |
| --- | --- |
| `CHATCLUMER_KEYSTORE` | 密钥库文件路径 |
| `CHATCLUMER_KEYSTORE_PASSWORD` | 库密码 |
| `CHATCLUMER_KEY_ALIAS` | 密钥别名 |
| `CHATCLUMER_KEY_PASSWORD` | 密钥密码，省略时沿用库密码 |

GitHub Actions 也可以用 secret `CHATCLUMER_KEYSTORE_BASE64`（密钥库的 base64）加上面的密码和别名。

**如果这些变量没有配齐，发布包会用 Android 调试密钥签名，这样仍然能安装。** 这不是应用商店签名。调试密钥是每台机器自己生成的（密码是公开的 `android`，证书却各不相同），所以：

- 换电脑或换 CI 运行器重新构建后，不能覆盖安装到旧包上，需要先卸载。
- 任何人都可以用调试密钥做出一个能安装的包，不能把它当成「只有你能更新」的身份。
- 要让以后的包能覆盖安装，请自己生成一把密钥库，妥善保管，并在本地和 CI 里用上面的变量指向它。

```bash
keytool -genkeypair -keystore chatclumer.keystore -alias chatclumer -keyalg RSA -keysize 2048 -validity 10000
```

不要把密钥库提交进仓库。

## 测试

```bash
cd android && ./gradlew test
```

单测覆盖二维码和 `chatclumer://pair` 深链解析、地址校验（拒绝非 http(s)、必须有主机）、WebView 是否留在同一源，以及 `/m/ping` 的 JSON、不发送口令、429 的 `Retry-After` 和等待期间不再请求。

## 和电脑端的约定

实现以 `frontend/server/mobile-auth.mjs` 为准：

- 二维码：`chatclumer://pair?u=<百分号编码的基址>&t=<口令>`。口令是 base64url，二维码里通常不再编码一次。
- `GET /m/ping` 无需口令，返回 `{"app":"chatclumer","version":"0.6.0","auth":true|false}`，并带 `Access-Control-Allow-Origin: *`。这个 CORS 头是给浏览器的；原生请求只看 JSON。手机上未配对时 `auth` 为 `false`。
- `GET /m/pair?token=` 成功时设置 `cc_session`（HttpOnly、SameSite=Lax、Path=/，明文 HTTP 上不带 Secure）并 302 到 `/`。
- 其它请求也可以用 `Authorization: Bearer <口令>`。WebView 里的页面和事件流走 Cookie，因为 `EventSource` 不能自定义头，而且给 WebView 加额外请求头有机会带到别的网站。应用不会在 `/m/ping` 上附带口令：错误的 Bearer 也会被算进锁定次数。
- 未配对的页面返回 401 HTML。同一 IP 在 10 分钟内出现 10 个不同的错误口令后返回 429，`Retry-After` 是秒。
- 口令可以重复使用，所以重新连接会再次打开 `/m/pair`。在电脑上更换口令后，旧手机需要重新扫码。
