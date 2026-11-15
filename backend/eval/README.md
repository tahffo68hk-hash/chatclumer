# 评测：单模型 vs 群聊

固定 10 道题（4 道推理、3 道事实、3 道观点，见 `questions.json`），同一批成员各跑两遍：

- **单模型**：第一个成员独立回答一轮。
- **群聊**：全部成员自由讨论（默认 3 轮），取房间结束时的本地回顾作为群聊答案。

## 评分

- 推理题和事实题：答案里要有参考答案，并且不含已知的错误答案，才算对。
- 观点题：按题目列出的要点被提到的比例计分。
- 可选 LLM 评委：用 `--judge-member` 指定一个 API 成员，对每个答案打 1–5 分。默认不启用。

## 运行

```bash
cd backend
.venv/bin/python -m eval.run_eval --mock --out eval/results/mock            # 模拟成员，不调用任何模型
.venv/bin/python -m eval.run_eval --members my_members.json --out eval/results/mine
```

`my_members.json` 示例（本机 Ollama 免费；其他 API 成员沿用应用里的密钥和“允许可能计费的调用”开关）：

```json
[
  {"nickname": "甲1", "provider": "ollama", "model_id": "qwen2.5:7b"},
  {"nickname": "乙2", "provider": "openai_compatible", "model_id": "local", "api_base": "http://127.0.0.1:1234/v1"}
]
```

网页成员需要浏览器扩展和打开的页面，不在评测里。

## 自带的结果

`results/mock/` 是**模拟运行**。成员是 `mock.py` 里写死的回答，只能证明评测流程能跑通，不能说明哪个模型更好，也不能说明群聊更好。真实结果要用你自己配置的成员再跑一遍。

模拟结果里 r2 的群聊答案被判错：本地回顾在“分歧”一段里引用了第一个成员最初的错误说法。这暴露了用回顾当答案的一个局限，所以没有修饰。
