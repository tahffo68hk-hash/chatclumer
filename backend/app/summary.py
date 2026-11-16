"""Local retrospective. This does not call a model."""

from __future__ import annotations

from .util import excerpt, reason_label

_DISAGREE = ("质疑", "反对", "并不", "不同意", "但是", "然而", "有问题", "不足以")
_UNVERIFIED = ("可能", "也许", "据说", "未验证", "大约", "估计", "不确定")
_RECOMMEND = ("建议", "下一步", "应该", "推荐", "先做", "先写")
_AGREE = ("同意", "认同", "一致", "我也这样")


def _sentences(text: str) -> list[str]:
    clean = (text or "").replace("【演示回复 · 非真实模型】", "").replace("【演示总结 · 非真实模型】", "")
    clean = clean.replace("【本地回顾 · 未额外请求模型】", "")
    parts = []
    buf = []
    for ch in clean:
        buf.append(ch)
        if ch in "。！？\n":
            sentence = "".join(buf).strip(" \n")
            if sentence:
                parts.append(sentence)
            buf = []
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return [p for p in parts if p and not p.startswith("##")]


def _uniq(items: list[str], limit: int) -> list[str]:
    out: list[str] = []
    for item in items:
        if item not in out:
            out.append(item)
        if len(out) >= limit:
            break
    return out


def _first_sentence(text: str) -> str:
    sentences = _sentences(text)
    return sentences[0] if sentences else excerpt(text, 80)


def build_summary(transcript: list[dict], end_reason: str | None, note: str = "") -> str:
    users = [m for m in transcript if m.get("author_type") == "user"]
    ais = [
        m
        for m in transcript
        if m.get("author_type") == "ai" and not m.get("is_summary") and m.get("status", "complete") == "complete"
    ]
    question = users[-1]["content"].strip() if users else "（没有用户问题）"
    latest: dict[str, dict] = {}
    for message in ais:
        key = message.get("member_id") or message.get("nickname") or message.get("id")
        latest[str(key)] = message

    if not ais:
        header = "【本地回顾 · 未额外请求模型】没有成员发言。这里只记录结束原因，不编造共识或建议。"
        if note:
            header = note.strip() + "\n" + header
        lines = [
            header,
            f"结束原因：{reason_label(end_reason) or '未记录'}",
            "",
            "## 主要结论",
            f"用户问题：{question}",
            "- 没有可回顾的成员公开发言。",
            "",
            "## 共识",
            "- 没有成员发言，这里不写共识。",
            "",
            "## 分歧",
            "- 没有成员发言，这里不写分歧。",
            "",
            "## 未验证事实",
            "- 没有成员发言可核查。",
            "",
            "## 最推荐建议",
            "- 没有成员建议。",
            "",
            "## 下一步行动",
            "- 添加网页成员，并在扩展里绑定当前标签页后再发送。未绑定不会发送。",
        ]
        return "\n".join(lines) + "\n"

    agree: list[str] = []
    disagree: list[str] = []
    unverified: list[str] = []
    recommend: list[str] = []
    for message in ais:
        nick = message.get("nickname") or "成员"
        for sentence in _sentences(message.get("content") or ""):
            if any(word in sentence for word in _DISAGREE):
                disagree.append(f"- {nick}：{sentence}")
            if any(word in sentence for word in _UNVERIFIED):
                unverified.append(f"- {sentence}")
            if any(word in sentence for word in _RECOMMEND):
                recommend.append(f"- {nick}：{sentence}")
            if any(word in sentence for word in _AGREE):
                agree.append(f"- {nick}：{sentence}")

    conclusions = []
    for message in latest.values():
        conclusions.append(
            f"- {message.get('nickname') or '成员'}（{message.get('role_name') or '角色'} / {message.get('provider') or '-'} / {message.get('model_id') or '-'}）：{_first_sentence(message.get('content') or '')}"
        )
    if not conclusions:
        conclusions = ["- 没有可回顾的成员公开发言。"]

    if not agree:
        agree = ["- 各成员回应了同一问题，但没有人明确宣布共识。这里不强行统一。"]
    if not disagree:
        disagree = ["- 公开记录里没有明确的对立句。这只说明分歧没有被说出来。"]
    if not unverified:
        unverified = ["- 这些发言没有附带外部核查，默认都还不是已验证事实。"]
    if not recommend:
        recommend = ["- 先把讨论收成一个可观察的小实验，再决定要不要继续。"]

    header = "【本地回顾 · 未额外请求模型】按公开句子摘录，不是模型重新综合。"
    if note:
        header = note.strip() + "\n" + header
    lines = [
        header,
        f"结束原因：{reason_label(end_reason) or '未记录'}",
        "",
        "## 主要结论",
        f"用户问题：{question}",
        * _uniq(conclusions, 6),
        "",
        "## 共识",
        * _uniq(agree, 4),
        "",
        "## 分歧",
        * _uniq(disagree, 4),
        "",
        "## 未验证事实",
        * _uniq(unverified, 4),
        "",
        "## 最推荐建议",
        _uniq(recommend, 1)[0],
        "",
        "## 下一步行动",
        "- 由用户决定采纳哪一条建议，或改写问题后再开一轮。",
        "- 给未验证的句子补证据，或明确标记为猜测。",
        "- 需要真实模型时，在服务器配置对应密钥；演示成员不会代替它们发言。",
    ]
    return "\n".join(lines) + "\n"
