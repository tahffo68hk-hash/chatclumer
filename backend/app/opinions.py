"""Rule-only grouping of explicit replies. No model call and no invented consensus."""

from __future__ import annotations

NOTICE = "只列出带回复关系、并且角色或原文里写明质疑、反驳或不同意的发言。这不是独立事实核查。没有这类关系时列表是空的，这里不编共识。"
CARD_NOTE = "收藏的是讨论里的原话和备注，不是已核实事实。"


def discussion_splits(messages: list[dict]) -> dict:
    by_id = {item["id"]: item for item in messages}
    items = []
    for message in messages:
        if message.get("status") != "complete" or message.get("discarded_reason"):
            continue
        parent = by_id.get(message.get("reply_to_id") or "")
        if not parent:
            continue
        role = message.get("role_name") or ""
        content = (message.get("content") or "").strip()
        head = content[:80]
        explicit_role = any(word in role for word in ("质疑", "反对", "反驳"))
        explicit_text = any(word in head for word in ("质疑", "反驳", "不同意", "我反对"))
        if not explicit_role and not explicit_text:
            continue
        items.append(
            {
                "kind": "待核实",
                "label": "讨论观点",
                "message_id": message["id"],
                "source_message_id": parent["id"],
                "nickname": message.get("nickname") or "",
                "source_nickname": parent.get("nickname") or "",
                "member_id": message.get("member_id"),
                "source_member_id": parent.get("member_id"),
                "excerpt": content[:160],
                "source_excerpt": (parent.get("content") or "")[:160],
            }
        )
    return {"items": items, "consensus": [], "notice": NOTICE}
