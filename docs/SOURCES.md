# 来源与许可证笔记

本次实现是原创代码，没有复制下列仓库的源码。只核对了 README、调度概念和许可证，访问失败的细节没有重试。

| 仓库 | 查阅到的许可证 | 借用的概念 | 没有做的事 |
| --- | --- | --- | --- |
| [SummerSec/OpenChat](https://github.com/SummerSec/OpenChat) | README 自述 MIT；仓库未挂 LICENSE 文件 | 多成员、流式、未配置时用 mock、总结只基于公开正文 | 不复制其前端直连密钥或 CORS 代理做法 |
| [gyhdc/multi-agent-group-chat](https://github.com/gyhdc/multi-agent-group-chat) | 未找到 LICENSE 文件，不视为可复制代码 | 共享时间线、选择性回复、中途插话、回复某条消息 | 不复制实现；本仓库不用其 agent/CLI 路径 |
| [theopenco/llmgateway](https://github.com/theopenco/llmgateway) | 社区代码 AGPLv3，`ee/` 为商业许可 | 提供方、路由、用量日志这个产品方向 | 不引入该项目，避免 AGPL 依赖 |
| [BerriAI/litellm](https://github.com/BerriAI/litellm) | 主体 MIT，enterprise 目录另有许可 | 统一 OpenAI 兼容调用、成本未知就不要假装知道 | 不内嵌 LiteLLM |
| [ollama/ollama](https://github.com/ollama/ollama) | MIT | 本地 `/api/chat` 连接器 | 不下载模型 |
| [aiscouncil/registry](https://github.com/aiscouncil/registry) | MIT | 模型目录只作“精确 model id”的参考 | 不复制 models.json |
| [tencent-connect/bot-docs](https://github.com/tencent-connect/bot-docs) | MIT 文档 | QQ 官方机器人需要 AppID、token 和权限 | 不连接真实 QQ |

公开产品形态只作界面参考，没有抓取其代码：Rauno、Pachat、AISCouncil、Sprapp、Plurilog、mumo、LLM Gateway Group Chat。
