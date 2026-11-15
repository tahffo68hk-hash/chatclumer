# 网页成员与分组

同一句问题先进入各自独立的分支。勾选至少两人后，先看预览里列出的公开答复，再合并成讨论组。没被勾上的历史不会默认传走。拆出去的人不再收到原组的新发言。页面不会声称模型忘掉了已经看见的内容。

发到网页的文字会离开这台电脑。网页不显示单价时，费用记为未知，不会写成 0。设了费用上限的房间不会向网页发送。

## 安装扩展并配对

1. `bash scripts/start.sh`
2. Chrome 打开 `chrome://extensions`，打开开发者模式，加载已解压的 `extension/`。
3. 房间里给成员绑定站点、来源和标签键，并打开受控自动发送。
4. 扩展弹窗粘贴本机配对码。配对令牌只留在浏览器里，不会写进聊天或日志。
5. 打开要使用的那个标签页，在弹窗里绑定。扩展不扫描其他标签，也不读 Cookie。

这台开发机的品牌版 Chrome 157 忽略 `--load-extension`。下面的扩展回路是用 Playwright 自带的 Chrome for Testing 加载未打包扩展跑的，不是把“浏览器能打开聊天”说成应用已经接通。

## 三分钟分组试用

1. 打开 http://127.0.0.1:43123 ，点「独立分支」。
2. 发一句。三个演示成员各自回答，正文带「非真实模型」。
3. 只勾两人，点「预览将共享的内容」。预览里应有这两人的公开答复，没有第三人。
4. 点「合并为讨论组」。底部「发给」可以选择全部分支或某一个组。
5. 勾住讨论组里的一人，点「拆成新分支」。刷新后房间不会自己重开。

## 时间

下面的北京时间都由记录里的 UTC 加 8 小时得到，没有另编钟点。

## 真实页面

| 日期 | 网址 | 登录 | 页面上的模型 | 做了什么 | 结果 |
| --- | --- | --- | --- | --- | --- |
| 2026-11-15 01:30 CST（2026-11-14T17:30:23Z） | http://127.0.0.1:43124/fixture/chat | 不需要。这是本地夹具，不是真实模型 | Fixture 本地 | 扩展发送一次，读完，再把公开答复转发一次。停止后仍是 2 条用户气泡 | 扩展回路通过。对面不是第二个真实模型 |
| 2026-11-15 01:30 CST（2026-11-14T17:30:36Z 起） | https://gemini.google.com/app | 游客。Sign in 可见 | Flash-Lite，这是页面上的模式名 | 扩展先发送读书建议。合并后的第二条发给同一页的，是演示成员「本地甲」的公开答复，不是另一个网页模型 | 这一条是 Gemini 加演示模型，不是两个真实网页模型互聊。扩展回路通过 |
| 2026-11-15 01:31 CST（2026-11-14T17:31:19Z） | https://chat.qwen.ai/ | 有登录按钮 | 按钮文字里有 Qwen3.7-Plus | 手动点了一次 Send。随后要求确认年龄 | 没有填出生年，没有读到回复 |
| 2026-11-15 | https://yuanbao.tencent.com/chat/ | 登录后仍是旧输入区。一轮 A/B 已读回答案 1 | 未把页面模式名当成精确模型 | 同一轮转发因换行被拆段，比较 145 对 128，没有发送 | 随后由扩展 0.2.9 把转发压成一段。见下一行 |
| 2026-11-15 07:46 CST | https://yuanbao.tencent.com/chat/ | 已登录。游客输入仍要先登录一次 | 未把页面模式名当成精确模型 | 扩展 0.2.9：第一轮发送并读回 A/B 的答案 1；第三轮把林知秋的公开答复转发一次并读回 | 已实页验证自动发送、读回、转发。元宝用户气泡与房间任务都是 2。没有多余发送，结束后输入框是空的。见 [房间读回](screenshots/yuanbao-forward-round3.png) |
| 2026-11-15 01:40 CST | https://chatglm.cn/ | 游客页可以人工使用 | 页面文字里有 GLM-5.3-Flash极致，不是精确底层 ID | 扩展不自动点击发送 | 游客可用，自动发送关闭 |
| 早前，本轮没有重试 | https://chatgpt.com/ | 挑战页 | 未能核验 | 打开后停住 | BLOCKED |
| 早前，本轮没有重试 | https://claude.ai/ | 403 | 未能核验 | 没有绕过 | BLOCKED |
| 2026-11-15 08:30 CST | https://chat.deepseek.com/ | 协调方已登录 | 未把页面模式名当成精确模型 | 0.3.0 发出了第一句并收到回复，但页面从 / 换到 /a/chat/s/ 后扩展误报未发送 | 0.3.1 以输入框已清空且地址已切换，或出现对应的用户消息，作为发送成功。读回仍待实页再核对 |
| 2026-11-15 09:00 CST | https://chat.deepseek.com/ | 已登录 | 未把页面模式名当成精确模型 | 0.3.1 发送正常，页面几秒内回完，但扩展一直判不出完成，等满约 120 秒后带「（可能未完整）」读回；第二轮转发在页面上已回答，却被房间 120 秒上限取消 | 原因：完成判定只在 `.ds-message` 内找复制/重新生成操作栏，实页操作栏在消息外面。0.3.2 里外都找；另以发送键状态判断是否仍在生成（空框且圆键可点＝停止键，回到 `ds-button--disabled`＝结束）；文字用 Date.now() 计稳定 2.5 秒收尾，判断不了是否在生成时稳定 6 秒收尾，看似仍在生成但 15 秒不变也收尾；等待用 MutationObserver 唤醒加轮询兜底，后台标签定时器被拉长也不至于空等。90 秒上限与部分读回保留。待实页再核对 |
| 早前，本轮没有重试 | https://grok.com/ | 登录与 Cookie 说明 | 未能核验 | 没有当成游客聊天 | 登录墙 |
| 2026-11-15 | https://www.doubao.com/chat/ | 已登录 | 未把页面模式名当成精确模型 | 0.3.0 第一轮发出并读回。第三轮转发没有写进编辑器 | 0.3.1 重新聚焦后再试插入、粘贴和 beforeinput。读回保留全角标点。转发仍待实页再核对 |

### 支持的网页 AI（扩展 0.4.2，2026-11-15）

0.4.1 实页测试时，ChatGPT、文心、智谱、Z.ai 都报「已填入，未发送」，Qwen 被误判成登录墙。0.4.2 的选择器改为从实页 DOM 导出（`/workspace/dom-dumps`，已整理成 `backend/tests/fixtures/real_dom/`，DeepSeek 只留聊天栏，没有侧栏历史和账号名）里取，并用这些真实 DOM 做测试（`backend/tests/test_real_dom.py`）：点一次发送后换入同站的真实「生成中」「完成」DOM 和地址，检查发送确认、读回和完成判定。没有站点自己的脚本，所以仍不等于实页端到端。

0.4.1 的问题：ChatGPT 点到了听写按钮（`lightweight-composer-send` 图标在听写键上），真正的发送键是 `button[data-composer-submit]`；Z.ai 的 Tailwind 类名 `disabled:bg-…-disabled` 被当成禁用；智谱的助手消息是 `.answer[id^=row-answer-]`，不是 `.conversation.answer`；文心、智谱发出后扩展看到的输入框仍有原文，而旧的发送确认要求输入框先清空；Qwen 的门槛检测范围太宽。

发送确认（10 秒内任一条成立）：出现文字相符的新用户消息（NFKC 规范化后比较站点的用户消息正文）；地址换成该站的会话地址；或点击后输入框被清空且出现新的助手消息。确认后输入框若还留着原文，会清掉，免得之后被误发。门槛只看真正打开的弹窗、提示条和验证框：ChatGPT 页面里藏着未打开的「Log in or sign up」`<dialog>`，对话下方的「Log in for a more personalized…」横幅也不算登录墙。

| 站点 | 需要登录吗 | 0.4.2 选择器（来自实页 DOM） | 把握 |
| --- | --- | --- | --- |
| Qwen https://chat.qwen.ai/ | 游客发送当前被服务端拒绝 | 输入 `textarea.message-input-textarea`；发送 `button.send-button[aria-label=Send]`；停止 `button.stop-button[aria-label=Stop]`；用户 `.qwen-chat-message-user p.user-message-content`；助手 `.qwen-chat-message-assistant`（生成中 `.response-loading`）；提示条「You do not have permission to access this resource」→ 回报「千问游客发送被拒绝，可能需要登录」并清空输入框；年龄确认仍只回报 | 输入、发送、停止、消息结构有实页 DOM；回复正文 `.response-message-content.phase-answer` 和完成标记没见过真实回复，不确定 |
| ChatGPT https://chatgpt.com/ | 游客（/ → /uc/<id>） | 输入 `textarea#mobile-composer-prompt`；发送 `button[data-composer-submit]`（`aria-label` 变成 Stop generating 时是停止）；用户 `li[data-message-role=user] [data-user-message-copy]`；助手 `li[data-message-role=assistant] [data-assistant-markdown-root]`；完成 `data-message-complete` 且无 `aria-busy=true` | 有实页 DOM；生成中的停止状态没抓到（回复太快） |
| 文心 https://wenxin.baidu.com/（chat.baidu.com、yiyan.baidu.com 会跳到这里，三个源算同一个绑定） | 游客（/search/<id>） | 输入 `textarea#chat-textarea`；发送 `span.ci-submit-button`（内有 `img#ci-submit-button-ai`）；停止 `img.ci-submit-pause`；用户 `.cs-question-bubble .cs-question-pure-text`；助手 `.conversation-flow-answer-container .ai-entry-block.ai-markdown .cosd-markdown-content`；生成/完成 `.chat-qa-container[data-chat-status=GENERATING/COMPLETE]` | 有实页 DOM，状态属性明确 |
| 智谱清言 https://chatglm.cn/main/alltoolsdetail?lang=zh | 游客（地址加 `&cid=`） | 输入 `#search-input-box textarea`；发送 `div.enter.is-main-chat`（生成中加 `.searching`，就是停止键）；用户 `.conversation.question .question-txt`；助手 `.answer[id^=row-answer-]`，正文 `.answer-content-wrap .markdown-body`，排除 `.text-advance-thinking-content`；生成中 `.answer-loading`；完成 `.interact-container .copy/.regenerate` | 有实页 DOM |
| Z.ai https://chat.z.ai/ | 游客（/c/<uuid>） | 输入 `textarea#chat-input`；发送 `button#send-message-button`；停止 `button[aria-label=Stop][data-slot=button]`；用户 `.user-message [data-user-bubble]`；助手 `.chat-assistant`（外框 `div[id^=message-]`），正文 `.chat-markdown`，排除 `.thinking-chain-container`；生成中 `._common-loading`；完成 `button[aria-label=Copy/Regenerate]` | 有实页 DOM |
| 元宝 / DeepSeek / 豆包 | 要先在该标签页登录一次 | 元宝、豆包实页已通过。DeepSeek 的选择器在实页 DOM 上全部命中（用户、助手、正文、完成标记、发送键状态），0.4.1 实页「超时。AI 0→0」不是选择器问题，较可能是标签页在后台时 DeepSeek 的虚拟消息列表不渲染；0.4.2 的超时说明会写出标签页是否在后台，请把 DeepSeek 放在单独的可见窗口里 | 见 `yuanbao.js`、`deepseek.js`、`doubao.js` |
| Gemini | 游客 | 扩展回路通过（见上表） | 见 `content.js` |
| Kimi、Grok、Copilot、Hugging Face Chat | 要登录 | 不接入游客模式 | — |
| 千问 qianwen.com（tongyi.com）、秘塔 metaso.cn | 首次发送弹滑块验证 | 不代做验证，不接入 | — |
| Perplexity | 游客回复只是「注册并重复您的请求」 | 无实际用处，不接入 | — |
| duck.ai | 本机网络 ERR_CONNECTION_CLOSED | 没有绕过 | — |
| you.com、phind.com | you.com 已无游客聊天，phind.com 已 404 | — | — |
| chat.mistral.ai | 浏览器里已有登录会话，没有做游客测试 | 未接入 | — |

游客站共用 `extension/guest.js`，安全规则与 DeepSeek/豆包相同：先清空再一次写入，用 NFKC 规范化比对；只按一次发送键（pointer 序列）；10 秒内没出现对应的用户消息或换地址，就回报「已填入，未发送」并清空输入框；同一任务号去重；最多读 90 秒，超时带「（可能未完整）」读回；停止、超时、取消都清空输入框。完成判定：最后一条相符用户消息之后的回复有文字，且有完成标记或确认不在生成，文字按 Date.now() 稳定 2.5 秒；判断不了是否在生成时稳定 6 秒；看似仍在生成但 15 秒不变也收尾。弹窗里出现站点确认、人机验证或登录/注册字样时只回报，不点、不重试。这些都还是夹具结果，逐站实页核对之前不要当成端到端已通过。

同一条请求会记在标签页里。刷新后不会把已经点过发送的请求再点一次。发送按钮只接受明确的 Send / 发送，不会去点升级、订阅、购买或删除。站点若出现验证、年龄确认或额度用尽，这一站就停。

夹具回复以「夹具收到：」开头，用来证明扩展和房间接得上，不能当成 Gemini 或其他模型。

## 验收时要分开看

- 后端 `pytest` 覆盖分组隔离、只分享选中的公开答复、拆分后不再收到原组新话、@、合并取消进行中的任务，以及扩展的配对、来源、重放和停止。
- `scripts/check_branch_ui.py` 在浏览器里走了预览、合并、拆分和刷新。
- `scripts/check_web_bridge.py` 是扩展装上之后的夹具与 Gemini。记录时间见上表。Gemini 那一轮的另一个成员是演示模型。
- 协调方人工截图：[元宝游客停止](screenshots/yuanbao-guest-stop-manual.webp)。那不是扩展回路。
- 本机元宝尝试：[发送没有形成回复](screenshots/yuanbao-vm-guest.png)。
- 品牌版 Chrome 可以在 `chrome://extensions` 打开开发者模式，选择「加载已解压的扩展程序」并选中 `extension/`。命令行 `--load-extension` 被忽略，不代表不能手工加载。
- 配对码在房间的「设置」里生成，只在本机页面 http://127.0.0.1:43123 上签发。粘贴到扩展弹窗后，令牌留在扩展里，不会写入聊天或导出文件。
- 网页成员在添加或编辑时填写来源、页面地址、绑定键和受控自动发送。保存会调用 `/api/members/{id}/web-bind`。成员卡片上的成员 ID 和绑定键可以选中复制。状态分为未绑定、已绑定标签页、掉线。分步说明在成员栏和设置里的「连接网页 AI」。
- 手机可以打开群聊。网页桥仍要这台开着扩展的电脑。拆出成员默认解除原标签页，绑定新会话前不会再向原网页发送。选择「沿用已有记忆」才会继续用原来的标签，并且页面会说明原网页还记得已读内容。
- 设了 token 上限时，网页成员直接拒绝，不会把字符数当成精确 token。分支房间的消息条数和时间不因合并或再次开始而清零。
- 清单里的 content_scripts 只有本机夹具和 Gemini。元宝、DeepSeek、豆包、智谱、Qwen、ChatGPT、文心（chat.baidu.com / wenxin.baidu.com / yiyan.baidu.com）、Z.ai 在 optional_host_permissions 里。绑定这些站点时，扩展会请求该源的主机权限，再用 `chrome.scripting.registerContentScripts` 登记对应脚本，并注入当前标签。没有授予就不会注入。DeepSeek 注入 `deepseek.js`，豆包注入 `doubao.js`，游客站注入 `guest.js`。实页发送还没有再核对。
- 2026-11-15 起元宝游客聊天需要先在该标签页登录一次。2026-11-15 07:46，扩展 0.2.9 在已登录的实页上核对了自动发送、A/B 读回（答案 1）和第三轮转发：各发送一次，读回与页面一致，元宝用户气泡与房间任务都是 2，没有多余发送，结束后输入框是空的。网页转发仍压成一段，超过约 800 字会截断。网页读取上限 90 秒，桥接等待 120 秒。同一轮失败后不再转发，除非重新发起。智谱游客可用，扩展不自动点发送。DeepSeek 和豆包在 2026-11-15 08:30 由协调方登录后做了只读 DOM 记录。扩展 0.3.0 按该结构接入，实页发送和读回还没有再核对。未登录不发送。豆包打开 `/security/doubao-region-ban` 时只回报「豆包当前网络地区不可用」。
- 成员保存后是「已配置，等待扩展绑定」。扩展心跳确认标签页仍在，才显示「已绑定标签页」。大约 20 秒没有心跳，或标签页已关闭，显示「掉线」。同名或绑定校验失败时，错误留在成员对话框里；新建失败不会留下半个成员。
- Qwen 只写在 `docs/qwen-run.json`，是手动 DOM，不是扩展端到端。
- 品牌版 Chrome 装不上扩展时，不能把手动打开网页说成真实站点端到端已经通过。
