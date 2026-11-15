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

### 0.5.1（2026-11-15）：0.5.0 实页回归后的修正（实页还没跑 0.5.1）

0.5.0 实页结果（用户测试）：文心、Z.ai 发送和读回与页面一致，文心转发也通过；智谱清言「已填入，未发送」（输入框核对 9/9，页面没有出现用户消息）；DeepSeek 回复出现了，但用户气泡已被虚拟列表移出 DOM，房间超时（AI 0→1，生成中 否）；Qwen 空输入框时页面检查误报「找不到发送键」，实际游客发送被无权限提示拒绝。

- **重复注入。** 扩展错误页里的「Identifier GUEST_DOM_SOURCE / DANGER has already been declared」来自同一页面再次 executeScript（绑定、弹窗「检查当前页」「导出诊断快照」都会走到）。现在所有注入脚本都放在守卫里：同一版本、扩展仍有效时第二次注入什么都不做，不重置进行中的任务，不重复挂监听；版本变了或旧实例已失效才重新装。后台注入前先问页面是否已装好同一版本，装好就不再注入。测试：`test_reinject_dom.py`（两次注入、任务进行中注入、版本升级、失效实例）。
- **智谱清言。** 逐项对比了 0.4.3 和 0.5.0：在真实 DOM 的空/已输入状态下，选中的输入框、发送键、可点判定、点击目标（`div.enter-icon-container` 中心）和写入方式完全相同；加一个只认输入事件（也测了只认可信事件）的框架状态模型后，两个版本的事件序列也相同（先合成清空，再 execCommand 可信写入），都只点一次就发出。0.5.0 唯一的逻辑差别是单元素角色改成按列表顺序回退，而导出的四个状态里每个角色都只有一个、都可见，不受影响。**没有找到代码层面的回归原因**；可能与当时的重复注入报错、站点改版或游客限流有关，无法离线确认。0.5.1 在「已填入，未发送」里附上点击过的元素（只有标签名和类名，不含文字），下次实页失败时能分辨点没点到。仍然只点一次、不重试。测试：`test_real_dom_zhipu_framework_state_sees_the_write_before_the_one_click`。
- **DeepSeek 虚拟列表。** 以前只认「相符用户消息之后的助手消息」，用户气泡被移出 DOM 后永远找不到回复。现在点击前一刻记下页面上已有的助手消息（节点和文字），确认发出后，如果相符的用户气泡已不在，只接受同时满足以下条件的回复：本任务已确认发出、是列表最后一条且是助手消息、点击前不在页面上、文字与点击前任何一条回复都不同。整列重挂载时旧回复以新节点出现也不会被当成新回复；页面上还留着相同问题的旧问答时，点击前的旧回复也不认。测试：`test_deepseek_reply_is_read_after_virtual_list_drops_the_user_bubble`、`test_deepseek_never_takes_an_old_reply_when_the_user_bubble_is_gone`。
- **Qwen 页面检查。** Qwen 输入框为空时不渲染发送键。注册表给 Qwen 加了 `send_after_input` 开关：输入框为空且找不到发送键时，检查结果记为「发送键要输入后才出现，未检查」，不算失败；输入框里已有文字仍找不到发送键才算缺失。页面检查从不写入、不点击。游客发送被无权限提示拒绝时，仍回报「千问游客发送被拒绝，可能需要登录」并清空输入框，不重试、不换入口。注册表版本 2026.11.15.2，`min_extension` 0.5.1。
- **游客站可用性。** 游客模式由站点决定、时有时无：会出现无权限、额度用完、要求登录或验证。不保证免费可用，也不保证同一站点今天能用明天还能用。
- **远端注册表的范围。** 只有游客站（Qwen、ChatGPT、文心、智谱清言、Z.ai）的选择器和规则会随远端注册表改变行为；DeepSeek、豆包、元宝的条目目前只用于页面检查。

### 0.5.0（2026-11-15）：适配器注册表

- 游客站（DeepSeek、豆包、元宝不在此列，它们的条目只供页面检查）的选择器和规则从 `guest.js` 搬到了 `extension/adapters/registry.json`，规则可以写 has、self、closest、not、all、any。引擎读取注册表编译成规格，单元素角色按列表顺序回退。0.4.4 的全部真实 DOM 测试照原样通过，**实页还没有用 0.5.0 再跑**。
- 后台默认每 6 小时检查一次远端注册表（本仓库的 raw 文件），也可以在弹窗里改地址或关闭。只有结构校验通过、版本比内置新、所有选择器在页面里都能解析时，才会启用。
- 页面检查：弹窗里的「检查当前页」，以及每 30 秒随心跳上报一次。检查只找元素，不写入、不点击，结果显示在成员卡片上。
- 诊断快照：只保留聊天栏结构，正文和 `data-*` 里的文字都会打码。

### 0.4.4（2026-11-15）

文心、智谱 0.4.3 实页已通过。修正了本地回顾的引用范围：同一房间里再次发起时，「主要结论」等各段以前会引用此前运行的成员答复（例如之前的 Qwen、Z.ai、DeepSeek）。现在本地回顾、模型总结的输入和总结结构补全，都只取本次运行的内容：触发本次运行的那条用户消息、运行中追加的用户消息，以及本次运行的 AI 答复。回归测试是 `test_local_summary_only_uses_the_current_run`。

### 扩展 0.4.3 实页状态（2026-11-15）

| 站点 | 实页状态 |
| --- | --- |
| Qwen、Z.ai、DeepSeek | 0.4.2 实页端到端已通过（DeepSeek 要登录，并放在单独的可见窗口里） |
| 豆包、元宝 | 较早版本实页已通过（要登录） |
| 文心、智谱清言 | 0.4.3 实页已通过（0.4.2 曾报「已填入，未发送（9/9）」） |
| ChatGPT 游客 | 不可靠：游客额度用完后页面出现「Sign in to continue」。0.4.3 在写入前识别，回报「ChatGPT 需要登录后才能继续（游客额度可能用完）」，不写入、不重试 |

0.4.3 的改动：

- **写入方式。** 文心、智谱先聚焦、全选，再用 `document.execCommand('insertText')` 写入。这样 beforeinput/input 由浏览器自己发出，Vue 等框架能认到。备选是原生 setter 加 `InputEvent('input', {inputType:'insertText'})`、composition 事件和 `change`。Qwen、Z.ai、ChatGPT 仍先用实页跑通过的原生 setter，`execCommand` 只作备选。每种写法都是：先清空、写一次、按 NFKC 核对，不一致就清空再换下一种。
- **智谱的发送键。** 要等发送键去掉 `.enter-icon-container.empty`，才算站点认到了文字（最多等 1.5 秒）。两种写法都没认到时，清空输入框，回报「站点没认到这次输入」，不点击。
- **点击位置。** 仍只点一次。文心点发送图标 `img#ci-submit-button-ai` 本身；智谱点发送键中心处的元素（elementFromPoint）。
- **文心的示例提示。** 文心的发送图标在空框时也是 active，输入框占位符是一条轮换的示例提示。点击后如果页面出现的新用户消息明显不是待发文本，就判定发错了内容，立即停下报错，不再点。

**第二轮只有一个网页收到转发，是设计如此，不是 bug。** 自由讨论的每个交叉轮只选一位发言者，只有辩论模式第 2 轮选两位（`engine.py` `_select`）。选人时，上一位发言者会被扣分，还没在交叉轮发过言的成员会加分，所以其他成员会在之后的轮次轮到。前提是房间的最大轮数还够。

**前端事件流断线后自动重连。** 按 1、2、4、8 秒退避，之后每 15 秒重试一次。连上后用服务端的 snapshot 和一次重新读取补齐房间状态，「连接断了」横幅随之消失，不用手动刷新。检查脚本是 `scripts/check_sse_reconnect.py`。

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
