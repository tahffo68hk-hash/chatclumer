"""Load the unpacked extension and run one fixture loop, then one guest Gemini attempt.

Writes docs/web-run.json. Does not print pairing tokens. A failed extension load is recorded
as such and does not get described as a real-site end-to-end pass.
"""

from __future__ import annotations

import json
import shutil
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "extension"
OUT = ROOT / "docs"
SHOTS = OUT / "screenshots"
API = "http://127.0.0.1:43124"
QUESTION = "请用中文给两条简短读书建议，每条一句话。"


def request(method: str, path: str, body: dict | None = None, token: str | None = None):
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(API + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read().decode()
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"raw": raw[:300]}
        return exc.code, payload


def main() -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    report = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "extension_loaded": False,
        "fixture": {"through": "not_run"},
        "sites": [],
    }
    profile = Path("/tmp/chat-room-bridge-profile")
    if profile.exists():
        shutil.rmtree(profile)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            context = playwright.chromium.launch_persistent_context(
                str(profile),
                headless=False,
                viewport={"width": 1280, "height": 900},
                ignore_default_args=["--disable-extensions"],
                args=[
                    f"--disable-extensions-except={EXT}",
                    f"--load-extension={EXT}",
                    "--no-first-run",
                    "--disable-default-apps",
                ],
            )
        except Exception as exc:
            report["extension_loaded"] = False
            report["extension_error"] = str(exc)[:400]
            manual_gemini(playwright, report)
            write(report)
            return
        try:
            worker = None
            for _ in range(30):
                if context.service_workers:
                    worker = context.service_workers[0]
                    break
                time.sleep(0.2)
            if worker is None:
                report["extension_error"] = "service worker did not start"
                manual_gemini(playwright, report)
                write(report)
                return
            report["extension_loaded"] = True
            report["extension_id"] = worker.url.split("/")[2]
            report["browser"] = "Chrome for Testing via Playwright. Branded Chrome 157 on this machine ignores --load-extension, so the unpacked extension was not loaded there."
            run_fixture(context, worker, report)
            run_gemini(context, worker, report)
        finally:
            context.close()
    write(report)


def run_fixture(context, worker, report) -> None:
    status, code = request("POST", "/api/ext/code")
    if status != 200:
        report["fixture"] = {"through": "extension", "result": "pair_code_failed", "status": status}
        return
    status, paired = request("POST", "/api/ext/pair", {"code": code["code"]})
    if status != 200 or "token" not in paired:
        report["fixture"] = {"through": "extension", "result": "pair_failed"}
        return
    token = paired["token"]
    status, room = request(
        "POST",
        "/api/sessions",
        {
            "title": "夹具回路",
            "layout": "branches",
            "max_rounds": 1,
            "max_ai_messages": 8,
            "max_seconds": 70,
            "summary_mode": "local",
        },
    )
    _, web = request(
        "POST",
        f"/api/sessions/{room['id']}/members",
        {"nickname": "网页甲", "role_name": "读者", "persona": "短答。", "provider": "demo", "model_id": "demo-synthesizer-v1"},
    )
    _, other = request(
        "POST",
        f"/api/sessions/{room['id']}/members",
        {"nickname": "本地乙", "role_name": "工程师", "persona": "短答。", "provider": "demo", "model_id": "demo-synthesizer-v1"},
    )
    status, _bound = request(
        "POST",
        f"/api/members/{web['id']}/web-bind",
        {
            "web_site": "fixture",
            "web_origin": "http://127.0.0.1:43124",
            "web_tab_key": "fixture-tab",
            "web_model_label": "Fixture 本地",
            "web_auto": True,
        },
    )
    page = context.pages[0] if context.pages else context.new_page()
    page.goto(f"{API}/fixture/chat", wait_until="domcontentloaded")
    page.wait_for_selector("#send")
    tabs = worker.evaluate(
        """async () => (await chrome.tabs.query({})).map((tab) => ({id: tab.id, url: tab.url || ""}))"""
    )
    fixture_tab = next((tab for tab in tabs if "/fixture/chat" in tab["url"]), None)
    if not fixture_tab:
        report["fixture"] = {"through": "extension", "result": "tab_not_visible", "tabs": [tab["url"] for tab in tabs]}
        return
    worker.evaluate(
        """async ({ token, tabId }) => {
          await chrome.storage.local.set({
            pairToken: token,
            bindings: { "fixture-tab": { tabId, origin: "http://127.0.0.1:43124" } },
          });
        }""",
        {"token": token, "tabId": fixture_tab["id"]},
    )
    request("POST", f"/api/sessions/{room['id']}/messages", {"content": QUESTION, "audience": "all"})
    try:
        page.wait_for_function(
            """() => document.querySelectorAll('#thread [data-role=assistant][data-state=complete]').length >= 1""",
            timeout=20000,
        )
    except Exception as exc:
        report["fixture"] = {"through": "extension", "result": "first_reply_missing", "detail": str(exc)[:200], "page": page.inner_text("body")[:300]}
        return
    if not wait_settled(room["id"], "网页甲"):
        report["fixture"] = {"through": "extension", "result": "first_reply_not_stored"}
        return
    first_users = page.locator("#thread [data-role=user]").count()
    first_text = page.locator("#thread [data-role=assistant]").last.inner_text()
    status, merged = request("POST", f"/api/sessions/{room['id']}/groups/merge", {"member_ids": [web["id"], other["id"]]})
    if status != 200:
        report["fixture"] = {"through": "extension", "result": "merge_failed", "status": status, "body": merged}
        return
    try:
        page.wait_for_function(
            """() => {
              const nodes = [...document.querySelectorAll('#thread [data-role=assistant][data-state=complete]')];
              return nodes.length >= 2 && (nodes[1].textContent || '').includes('公开答复');
            }""",
            timeout=25000,
        )
        if not wait_settled(room["id"], "网页甲", needed=2):
            raise RuntimeError("第二条夹具回复没有写回房间")
    except Exception as exc:
        report["fixture"] = {
            "through": "extension",
            "result": "second_reply_missing",
            "detail": str(exc)[:200],
            "users": page.locator("#thread [data-role=user]").count(),
            "page": page.inner_text("#thread")[:500],
        }
        return
    second = page.locator("#thread [data-role=user]").nth(1).inner_text()
    reply = page.locator("#thread [data-role=assistant]").nth(1).inner_text()
    request("POST", f"/api/sessions/{room['id']}/stop")
    time.sleep(3)
    users_after = page.locator("#thread [data-role=user]").count()
    page.screenshot(path=str(SHOTS / "fixture-bridge.png"), full_page=True)
    room_messages = request("GET", f"/api/sessions/{room['id']}/messages")[1]
    ai = [item for item in room_messages if item.get("nickname") == "网页甲" and item.get("status") == "complete"]
    report["fixture"] = {
        "through": "extension",
        "result": "passed" if first_users == 1 and users_after == 2 and "公开答复" in second and "夹具收到" in reply and len(ai) >= 2 else "failed",
        "url": f"{API}/fixture/chat",
        "guest": True,
        "displayed_model": "Fixture 本地",
        "first_user_count": first_users,
        "first_reply": first_text[:180],
        "second_prompt_has_public_reply": "公开答复" in second,
        "second_reply": reply[:180],
        "user_count_after_stop": users_after,
        "room_complete_replies": len(ai),
        "second_reply_stored": len(ai) >= 2,
        "room_model": ai[-1].get("model_id") if ai else "",
    }


def run_gemini(context, worker, report) -> None:
    page = context.new_page()
    entry = {
        "date": report["date"],
        "url": "https://gemini.google.com/app",
        "through": "extension",
        "guest": None,
        "displayed_model": "",
        "actions": [],
        "result": "",
    }
    try:
        response = page.goto("https://gemini.google.com/app", wait_until="domcontentloaded", timeout=45000)
        entry["http_status"] = response.status if response else None
    except Exception as exc:
        entry["result"] = "BLOCKED"
        entry["actions"].append(f"打开失败：{str(exc)[:180]}")
        report["sites"].append(entry)
        return
    page.wait_for_timeout(2500)
    url = page.url
    entry["landed_url"] = url
    body = page.inner_text("body")[:1500]
    if "just a moment" in body.lower() or (entry.get("http_status") or 0) >= 400:
        entry["result"] = "BLOCKED"
        entry["actions"].append("挑战页或错误状态，已停止")
        page.screenshot(path=str(SHOTS / "gemini-blocked.png"), full_page=True)
        report["sites"].append(entry)
        return
    composer = page.locator("[aria-label='Enter a prompt for Gemini']")
    if composer.count() == 0:
        entry["guest"] = False
        entry["result"] = "login_wall" if "sign in" in body.lower() else "composer_missing"
        entry["actions"].append(f"没有找到输入框。当前 URL {url}")
        page.screenshot(path=str(SHOTS / "gemini-waiting.png"), full_page=True)
        report["sites"].append(entry)
        return
    entry["guest"] = "sign in" in body.lower()
    entry["actions"].append("游客输入框可见，未点击登录、升级或模式切换")
    model = ""
    picker = page.locator("button[aria-label^='Open mode picker']")
    if picker.count():
        model = picker.first.inner_text().strip()
    entry["displayed_model"] = model or "未能核验精确 model ID"
    status, room = request(
        "POST",
        "/api/sessions",
        {
            "title": "Gemini 网页",
            "layout": "branches",
            "max_rounds": 1,
            "max_ai_messages": 6,
            "max_seconds": 100,
            "summary_mode": "local",
        },
    )
    status, web = request(
        "POST",
        f"/api/sessions/{room['id']}/members",
        {"nickname": "网页乙", "role_name": "读者", "persona": "只根据看到的公开内容短答。", "provider": "demo", "model_id": "demo-synthesizer-v1"},
    )
    status, other = request(
        "POST",
        f"/api/sessions/{room['id']}/members",
        {"nickname": "本地甲", "role_name": "工程师", "persona": "短答。", "provider": "demo", "model_id": "demo-synthesizer-v1"},
    )
    request(
        "POST",
        f"/api/members/{web['id']}/web-bind",
        {
            "web_site": "gemini",
            "web_origin": "https://gemini.google.com",
            "web_tab_key": "gemini-tab",
            "web_model_label": entry["displayed_model"],
            "web_auto": True,
        },
    )
    tabs = worker.evaluate(
        """async () => (await chrome.tabs.query({})).map((tab) => ({id: tab.id, url: tab.url || ""}))"""
    )
    gemini_tab = next((tab for tab in tabs if "gemini.google.com" in tab["url"]), None)
    stored = worker.evaluate("""async () => chrome.storage.local.get(["pairToken"])""")
    if not gemini_tab or not stored.get("pairToken"):
        entry["result"] = "bind_failed"
        entry["actions"].append("扩展里看不到这个标签或还没有配对")
        report["sites"].append(entry)
        return
    worker.evaluate(
        """async ({ tabId }) => {
          const { pairToken, bindings } = await chrome.storage.local.get(["pairToken", "bindings"]);
          const next = bindings || {};
          next["gemini-tab"] = { tabId, origin: "https://gemini.google.com" };
          await chrome.storage.local.set({ pairToken, bindings: next });
        }""",
        {"tabId": gemini_tab["id"]},
    )
    before = page.locator("model-response").count()
    request("POST", f"/api/sessions/{room['id']}/messages", {"content": QUESTION, "audience": "all"})
    entry["actions"].append("经扩展提交第一条读书建议问题")
    try:
        page.wait_for_function(
            """(count) => document.querySelectorAll("model-response").length > count""",
            arg=before,
            timeout=50000,
        )
    except Exception as exc:
        entry["result"] = "first_reply_missing"
        entry["actions"].append(str(exc)[:180])
        page.screenshot(path=str(SHOTS / "gemini-no-reply.png"), full_page=True)
        request("POST", f"/api/sessions/{room['id']}/stop")
        report["sites"].append(entry)
        return
    page.wait_for_timeout(1500)
    first = page.locator("model-response").last.inner_text()[:300]
    entry["actions"].append(f"读到新回复：{first[:120]}")
    if not wait_settled(room["id"], "网页乙"):
        entry["result"] = "first_reply_not_stored"
        entry["actions"].append("页面上有回复，房间还没记成完成，已停止以免重复提交")
        request("POST", f"/api/sessions/{room['id']}/stop")
        report["sites"].append(entry)
        return
    request("POST", f"/api/sessions/{room['id']}/groups/merge", {"member_ids": [web["id"], other["id"]]})
    entry["actions"].append("合并后让扩展转发另一成员的公开答复")
    try:
        page.wait_for_function(
            """(count) => {
              const nodes = [...document.querySelectorAll("model-response")];
              const text = (nodes[nodes.length - 1]?.innerText || "").replace(/^Gemini said\\s*/i, "").trim();
              return nodes.length > count + 1 && text.length > 12;
            }""",
            arg=before,
            timeout=55000,
        )
        if not wait_settled(room["id"], "网页乙", needed=2):
            raise RuntimeError("第二条 Gemini 回复没有写回房间")
    except Exception as exc:
        entry["result"] = "forward_missing"
        entry["actions"].append(str(exc)[:180])
        page.screenshot(path=str(SHOTS / "gemini-forward-missing.png"), full_page=True)
        request("POST", f"/api/sessions/{room['id']}/stop")
        report["sites"].append(entry)
        return
    second = page.locator("model-response").last.inner_text()[:300]
    count_at_stop = page.locator("model-response").count()
    request("POST", f"/api/sessions/{room['id']}/stop")
    page.wait_for_timeout(4000)
    entry["actions"].append("停止后等待 4 秒，确认没有新的助手消息")
    room_messages = request("GET", f"/api/sessions/{room['id']}/messages")[1]
    stored = [item for item in room_messages if item.get("nickname") == "网页乙" and item.get("status") == "complete" and item.get("content")]
    entry["result"] = "passed" if page.locator("model-response").count() == count_at_stop and len(stored) >= 2 and second.strip() else "sent_after_stop" if page.locator("model-response").count() != count_at_stop else "second_not_stored"
    entry["room_complete_replies"] = len(stored)
    entry["room_model"] = stored[-1].get("model_id") if stored else ""
    entry["second_reply"] = second
    page.screenshot(path=str(SHOTS / "gemini-bridge.png"), full_page=True)
    report["sites"].append(entry)


def wait_settled(session_id: str, nickname: str, needed: int = 1) -> bool:
    deadline = time.time() + 30
    while time.time() < deadline:
        messages = request("GET", f"/api/sessions/{session_id}/messages")[1]
        session = request("GET", f"/api/sessions/{session_id}")[1]["session"]
        stored = [
            item for item in messages
            if item.get("nickname") == nickname and item.get("status") == "complete" and item.get("content")
        ]
        if len(stored) >= needed and session.get("status") not in {"running", "paused"}:
            return True
        time.sleep(0.3)
    return False


def manual_gemini(playwright, report) -> None:
    entry = {
        "date": report["date"],
        "url": "https://gemini.google.com/app",
        "through": "manual_dom_not_extension",
        "result": "",
        "actions": ["扩展没有装上，这一条不能算扩展到房间的端到端"],
    }
    browser = playwright.chromium.launch(channel="chrome", headless=False)
    page = browser.new_page()
    try:
        page.goto("https://gemini.google.com/app", wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2000)
        entry["landed_url"] = page.url
        if page.locator("[aria-label='Enter a prompt for Gemini']").count() == 0:
            entry["result"] = "login_or_blocked"
            entry["actions"].append("没有输入框，已停止")
        else:
            entry["result"] = "composer_visible_send_not_attempted"
            entry["actions"].append("只确认输入框可见。扩展未加载，不再另发一条以免和失败的自动发送叠在一起。")
        page.screenshot(path=str(SHOTS / "gemini-manual.png"), full_page=True)
    except Exception as exc:
        entry["result"] = "BLOCKED"
        entry["actions"].append(str(exc)[:180])
    finally:
        browser.close()
    report["sites"].append(entry)


def write(report) -> None:
    target = OUT / "web-run.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in report if k != "extension_id"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
