# QQ 与微信

状态：网页房间不依赖它们。没有完成官方鉴权之前，两者都是 `BLOCKED_EXTERNAL`。

## QQ 官方机器人

QQ 机器人使用腾讯开放平台的 AppID 和 token，权限按频道或群机器人单独申请。本仓库只做配置层和本地命令模拟：

- 环境变量或服务器密钥：`QQ_APP_ID`、`QQ_BOT_TOKEN`、`QQ_BOT_SECRET`
- `GET /api/integrations/status`：缺任一凭证时 `qq.state = BLOCKED_EXTERNAL`；凭证齐全也只是 `CONFIGURED_UNVERIFIED`，因为没有完成官方网关握手
- `POST /api/integrations/qq/simulate`：本地解析 `/start 问题`、`/status`、`/stop`、`/result`，并操作当前房间。响应里 `external_delivery` 固定为 `BLOCKED_EXTERNAL`，`simulated: true`

这不能说真实 QQ 群已经接通。

## 微信

个人微信没有官方群机器人接口。本仓库拒绝 itchat、WeChaty 或其他非官方自动化。

官方渠道只留配置位，默认不向外发送：

- 微信公众平台：`WECHAT_OA_APPID`、`WECHAT_OA_TOKEN`
- 企业微信应用：`WECOM_CORP_ID`、`WECOM_AGENT_ID`、`WECOM_AGENT_SECRET`

`POST /api/integrations/wechat/simulate` 返回 `BLOCKED_EXTERNAL`，并且 `personal_wechat: refused`。有合法权限之后，也应走公众号或企业微信的官方消息 API，而不是个人号。
