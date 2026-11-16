"""Browser acceptance: stop while running, pause/resume, @member, saved provider."""

import json
import sys
import urllib.request

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:43123"
API = "http://127.0.0.1:43124"
OUT = "/opt/cursor/artifacts"


def api(method: str, path: str, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(API + path, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as res:
        return json.loads(res.read().decode())


def message_count(page) -> int:
    return page.locator("[data-testid=message]").count()


def main() -> int:
    notes = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/usr/local/bin/google-chrome",
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(BASE, wait_until="networkidle", timeout=60000)

        def commit(text: str) -> None:
            box = page.get_by_test_id("message-input")
            box.click()
            box.fill(text)
            page.wait_for_function(
                """(expected) => {
                  const input = document.querySelector('[data-testid=message-input]');
                  const btn = document.querySelector('[data-testid=send-button]');
                  return input && input.value.includes(expected) && btn && !btn.disabled;
                }""",
                arg=text[:6],
                timeout=10000,
            )
            page.get_by_test_id("send-button").click()

        if not page.get_by_test_id("create-demo").is_visible():
            page.get_by_test_id("demo-tools").locator("summary").click()
        page.get_by_test_id("create-demo").click()
        page.locator("h2", has_text="未命名群聊").wait_for()
        sid = api("GET", "/api/sessions")[0]["id"]
        api("PATCH", f"/api/sessions/{sid}", {"max_rounds": 8, "max_seconds": 180})
        page.reload(wait_until="networkidle")
        page.get_by_text("0/8").wait_for()
        commit("请慢慢讨论这个房间该不该继续。")
        page.get_by_test_id("status-pill").filter(has_text="运行中").wait_for(timeout=15000)
        page.screenshot(path=f"{OUT}/stop-while-running.png")
        page.get_by_test_id("stop-button").click()
        page.get_by_test_id("status-pill").filter(has_text="已停止").wait_for(timeout=15000)
        reason = page.get_by_test_id("end-reason").inner_text()
        if "用户停止" not in reason:
            raise SystemExit(f"stop reason was {reason}")
        if "轮数上限" in reason:
            raise SystemExit("stopped by round cap")
        quiet = message_count(page)
        page.wait_for_timeout(4000)
        later = message_count(page)
        status = page.get_by_test_id("status-pill").inner_text()
        if later != quiet or status != "已停止":
            raise SystemExit(f"activity after stop messages {quiet}->{later} status {status}")
        detail = api("GET", f"/api/sessions/{sid}")["session"]
        if detail["status"] != "stopped" or detail["end_reason"] != "user_stop":
            raise SystemExit(f"api status {detail['status']} {detail['end_reason']}")
        page.screenshot(path=f"{OUT}/stopped-no-new-messages.png")
        notes.append(f"stop ok messages={later} reason={detail['end_reason']}")

        if not page.get_by_test_id("create-demo").is_visible():
            page.get_by_test_id("demo-tools").locator("summary").click()
        page.get_by_test_id("create-demo").click()
        page.locator("h2", has_text="未命名群聊").wait_for()
        sid = api("GET", "/api/sessions")[0]["id"]
        api("PATCH", f"/api/sessions/{sid}", {"max_rounds": 8, "max_seconds": 180})
        page.reload(wait_until="networkidle")
        commit("先跑起来，然后暂停。")
        page.get_by_test_id("status-pill").filter(has_text="运行中").wait_for(timeout=15000)
        page.get_by_test_id("pause-button").click()
        page.get_by_test_id("status-pill").filter(has_text="已暂停").wait_for(timeout=10000)
        page.wait_for_timeout(1500)
        paused_count = message_count(page)
        page.wait_for_timeout(3000)
        if message_count(page) != paused_count or page.get_by_test_id("status-pill").inner_text() != "已暂停":
            raise SystemExit("pause did not hold")
        page.screenshot(path=f"{OUT}/paused.png")
        page.get_by_test_id("resume-button").click()
        page.get_by_test_id("status-pill").filter(has_text="运行中").wait_for(timeout=10000)
        page.screenshot(path=f"{OUT}/resumed.png")
        page.get_by_test_id("stop-button").click()
        page.get_by_test_id("status-pill").filter(has_text="已停止").wait_for(timeout=10000)
        notes.append("pause/resume ok")

        if not page.get_by_test_id("create-demo").is_visible():
            page.get_by_test_id("demo-tools").locator("summary").click()
        page.get_by_test_id("create-demo").click()
        page.locator("h2", has_text="未命名群聊").wait_for()
        commit("@周衡 只由你回答一个更小的下一步。")
        page.get_by_text("非真实模型").first.wait_for(timeout=20000)
        page.wait_for_timeout(2500)
        texts = page.locator("[data-testid=message]").all_inner_texts()
        joined = "\n".join(texts)
        if "周衡" not in joined:
            raise SystemExit("mention did not reach 周衡")
        for other in ("林知秋", "苏晚"):
            if other in joined:
                raise SystemExit(f"@{other} spoke without being mentioned")
        page.screenshot(path=f"{OUT}/mention-zhouheng.png")
        if page.get_by_test_id("stop-button").is_enabled():
            page.get_by_test_id("stop-button").click()
            page.get_by_test_id("status-pill").filter(has_text="已停止").wait_for(timeout=10000)
        notes.append("mention only 周衡")

        page.get_by_role("button", name="成员", exact=True).click()
        page.get_by_test_id("add-member").click()
        page.get_by_test_id("member-nickname").fill("钱路")
        page.get_by_test_id("member-role").fill("观察")
        page.get_by_test_id("member-provider").select_option("anthropic")
        page.get_by_test_id("member-model").fill("claude-sonnet-4-5-20250929")
        page.get_by_test_id("member-save").click()
        page.get_by_text("anthropic · claude-sonnet-4-5-20250929").wait_for(timeout=10000)
        page.reload(wait_until="networkidle")
        page.get_by_role("button", name="成员", exact=True).click()
        page.get_by_text("anthropic · claude-sonnet-4-5-20250929").wait_for(timeout=10000)
        page.screenshot(path=f"{OUT}/member-persisted.png")
        notes.append("member persisted")
        browser.close()
    print("\n".join(notes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
