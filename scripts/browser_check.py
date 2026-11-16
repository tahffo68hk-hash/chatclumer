"""Real browser pass against the local room. Saves screenshots under /opt/cursor/artifacts."""

import sys
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:43123"
OUT = "/opt/cursor/artifacts"


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
            try:
                _wait_ready(page, text)
            except Exception:
                value = box.input_value()
                disabled = page.get_by_test_id("send-button").is_disabled()
                page.screenshot(path=f"{OUT}/debug-commit.png")
                raise SystemExit(f"commit failed value={value!r} button_disabled={disabled}")

        def _wait_ready(page, text):
            page.wait_for_function(
                """(expected) => {
                  const input = document.querySelector('[data-testid=message-input]');
                  const btn = document.querySelector('[data-testid=send-button]');
                  return input && input.value.includes(expected) && btn && !btn.disabled;
                }""",
                arg=text[:8],
                timeout=15000,
            )

        if not page.get_by_test_id("create-demo").is_visible():
            page.get_by_test_id("demo-tools").locator("summary").click()
        page.get_by_test_id("create-demo").click()
        page.locator("h2", has_text="未命名群聊").wait_for()
        commit("我们现在该不该把内部评审做成多模型群聊，而不是并排比较？")
        page.get_by_test_id("send-button").click()
        page.get_by_text("非真实模型").first.wait_for(timeout=20000)
        commit("@周衡 先补充一个更小的下一步，不要展开新话题。")
        page.get_by_test_id("send-button").click()
        page.get_by_text("我读了 @").first.wait_for(timeout=30000)
        page.screenshot(path=f"{OUT}/desktop-discussion.png")
        notes.append("desktop discussion saved")
        stop = page.get_by_test_id("stop-button")
        if stop.is_enabled():
            stop.click()
            notes.append("clicked stop")
        else:
            notes.append("stop already disabled")
        page.get_by_test_id("summary").wait_for(timeout=20000)
        page.screenshot(path=f"{OUT}/desktop-summary.png")
        status = page.get_by_test_id("status-pill").inner_text()
        notes.append(f"status after summary: {status}")
        page.reload(wait_until="networkidle")
        page.get_by_text("我读了 @").first.wait_for(timeout=20000)
        status_after = page.get_by_test_id("status-pill").inner_text()
        notes.append(f"status after reload: {status_after}")
        if status_after == "运行中":
            raise SystemExit("reload restarted the room")
        page.screenshot(path=f"{OUT}/desktop-after-reload.png")
        mobile = browser.new_page(viewport={"width": 390, "height": 844})
        mobile.goto(BASE, wait_until="networkidle")
        mobile.get_by_text("我读了 @").first.wait_for(timeout=20000)
        mobile.get_by_test_id("message-input").fill("手机上补一句：先停在可观察的下一步。")
        mobile.wait_for_function(
            "() => document.querySelector('[data-testid=message-input]').value.includes('手机上')",
            timeout=10000,
        )
        mobile.screenshot(path=f"{OUT}/mobile-chat.png")
        notes.append(f"mobile input value set: {mobile.get_by_test_id('message-input').input_value()[:12]}")
        browser.close()
    print("\n".join(notes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
