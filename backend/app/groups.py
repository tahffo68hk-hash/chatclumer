"""Branch and discussion groups. Original messages stay on the timeline."""

from __future__ import annotations

from .util import excerpt, new_id, now_iso


def visible_messages(messages: list[dict], group_id: str, member_id: str) -> list[dict]:
    chosen = []
    for message in messages:
        if message["status"] != "complete" or message.get("discarded_reason") or message.get("is_summary"):
            continue
        kind = message.get("event_kind")
        if message["author_type"] == "system" and message.get("group_id") == group_id and kind in {"merge", "split", "share"}:
            chosen.append(message)
            continue
        if message["author_type"] == "user":
            audience = message.get("audience") or "all"
            if audience == "all":
                chosen.append(message)
            elif audience == "group" and message.get("group_id") == group_id:
                chosen.append(message)
            elif audience == "member" and message.get("target_member_id") == member_id:
                chosen.append(message)
            continue
        if message["author_type"] == "ai" and message.get("group_id") == group_id:
            chosen.append(message)
    return chosen


def _public_ai(messages: list[dict], member_id: str, group_id: str | None) -> list[dict]:
    rows = [
        item
        for item in messages
        if item["author_type"] == "ai"
        and item["status"] == "complete"
        and not item.get("discarded_reason")
        and not item.get("is_summary")
        and item.get("member_id") == member_id
        and (group_id is None or item.get("group_id") == group_id)
    ]
    return rows


def share_plan(db, session_id: str, member_ids: list[str], message_ids: list[str] | None) -> dict:
    messages = db.list_messages(session_id)
    members = {item["id"]: item for item in db.list_members(session_id)}
    groups = {item["id"]: item for item in db.list_groups(session_id)}
    shares = []
    if message_ids:
        wanted = set(message_ids)
        for message in messages:
            if message["id"] not in wanted:
                continue
            if message["author_type"] != "ai" or message["status"] != "complete" or message.get("discarded_reason"):
                raise ValueError("只能分享已完成的公开答复")
            if message.get("member_id") not in member_ids:
                raise ValueError("分享的答复不属于选中的成员")
            shares.append(message)
    else:
        for member_id in member_ids:
            group_id = db.active_group_id(member_id)
            rows = _public_ai(messages, member_id, group_id)
            if rows:
                shares.append(rows[-1])
    lines = []
    for message in shares:
        member = members.get(message.get("member_id") or "")
        group = groups.get(message.get("group_id") or "")
        lines.append(
            {
                "message_id": message["id"],
                "member_id": message.get("member_id"),
                "nickname": (member or {}).get("nickname") or message.get("nickname") or "",
                "group_id": message.get("group_id"),
                "group_name": (group or {}).get("name") or "",
                "excerpt": excerpt(message.get("content") or "", 180),
            }
        )
    return {
        "member_ids": member_ids,
        "shares": lines,
        "note": "只会把下面这些公开答复交给新的讨论组。未选中的历史不会默认传过去。原消息仍留在时间线上。",
    }


def same_active_group(db, member_ids: list[str]) -> dict | None:
    groups = db.list_groups(db.get_member(member_ids[0])["session_id"]) if member_ids else []
    wanted = set(member_ids)
    for group in groups:
        if group["status"] != "active":
            continue
        if set(group["member_ids"]) == wanted:
            return group
    return None


def quote_block(plan: dict, title: str) -> str:
    lines = [title, plan["note"]]
    if not plan["shares"]:
        lines.append("选中的分支还没有可分享的公开答复。")
    for item in plan["shares"]:
        lines.append(
            f"- 来源 {item['message_id']} · {item['group_name'] or '未分组'} · {item['nickname']}：{item['excerpt']}"
        )
    return "\n".join(lines)
