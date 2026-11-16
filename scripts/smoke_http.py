"""HTTP smoke against a running local room. Not a real-model check.

The demo template path is a fixture: it must stay labeled and must not be what a blank room does.
"""

import json
import sys
import time
import urllib.error
import urllib.request

API = "http://127.0.0.1:43124"
FRONT = "http://127.0.0.1:43123"


def call(method: str, url: str, body=None, timeout=10):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            raw = res.read().decode()
            return res.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            payload = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = raw
        return exc.code, payload


def wait_terminal(sid: str):
    for _ in range(40):
        status, payload = call("GET", f"{API}/api/sessions/{sid}")
        if status != 200:
            raise SystemExit(f"session read failed: {status}")
        state = payload["session"]["status"]
        if state in {"finished", "stopped", "failed"}:
            return payload
        time.sleep(0.25)
    raise SystemExit(f"session did not finish: {sid}")


def main() -> int:
    status, health = call("GET", f"{API}/api/health")
    if status != 200 or health.get("service") != "multi-llm-chat-room":
        raise SystemExit(f"backend health failed: {status}")
    status, front = call("GET", f"{FRONT}/backend/api/health")
    if status != 200 or front.get("service") != "multi-llm-chat-room":
        raise SystemExit(f"frontend proxy health failed: {status}")
    print("health ok")

    status, created = call("POST", f"{API}/api/sessions", {"title": "空白房间"})
    if status != 200:
        raise SystemExit(f"create blank failed: {status} {created}")
    sid = created["id"]
    status, detail = call("GET", f"{API}/api/sessions/{sid}")
    members = detail["members"]
    if members:
        raise SystemExit(f"blank room created members: {[item['nickname'] for item in members]}")
    status, sent = call("POST", f"{API}/api/sessions/{sid}/messages", {"content": "这句不该引出假回复"})
    if status != 200:
        raise SystemExit(f"send failed: {status} {sent}")
    done = wait_terminal(sid)
    messages = call("GET", f"{API}/api/sessions/{sid}/messages")[1]
    authors = [item.get("author_type") for item in messages]
    if any(item.get("author_type") == "ai" or item.get("is_demo") for item in messages):
        raise SystemExit(f"blank room stored a model or demo message: {authors}")
    system = [item for item in messages if item.get("author_type") == "system"]
    if len(system) != 1:
        raise SystemExit(f"blank room system notes: {len(system)}")
    note = system[0].get("content") or ""
    if "各成员回应了" in note or "可观察的小实验" in note:
        raise SystemExit("blank room invented a discussion")
    if "没有可回顾的成员公开发言" not in note:
        raise SystemExit("blank room did not say there were no replies")
    if done["members"]:
        raise SystemExit("blank room grew members")
    print("blank room stayed empty")

    status, demo = call("POST", f"{API}/api/sessions", {"title": "夹具演示", "template": "demo"})
    if status != 200:
        raise SystemExit(f"fixture demo create failed: {status}")
    status, demo_detail = call("GET", f"{API}/api/sessions/{demo['id']}")
    providers = {item["provider"] for item in demo_detail["members"]}
    if providers != {"demo"}:
        raise SystemExit(f"fixture demo members are not labeled demo: {providers}")
    print("fixture demo template still creates labeled demo members")

    req = urllib.request.Request(f"{FRONT}/")
    with urllib.request.urlopen(req, timeout=20) as res:
        html = res.read().decode("utf-8", "replace")
        if res.status != 200 or "新建房间" not in html and "多模型群聊" not in html:
            raise SystemExit(f"room page failed: {res.status}")
    print("room page ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
