"""The room's event stream reconnects by itself (0.4.3).

The first two /events requests are aborted, so the page sees the stream drop. It must show the
「连接断了」 banner, retry with backoff, clear the banner once a stream is back, and keep
rendering new messages without a reload. Run against the started app (scripts/start.sh).
"""

from playwright.sync_api import sync_playwright


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 860})
        seen = {"events": 0}

        def handle(route):
            seen["events"] += 1
            if seen["events"] <= 2:
                route.abort()
            else:
                route.continue_()

        page.goto("http://127.0.0.1:43123", wait_until="domcontentloaded")
        page.get_by_test_id("create-demo").click()
        page.get_by_test_id("message-input").wait_for()
        page.wait_for_timeout(800)
        # 新开一间房，让它的事件流从被掐断开始。
        page.route("**/api/sessions/*/events", handle)
        page.get_by_test_id("create-demo").click()
        page.get_by_test_id("link-down").wait_for(timeout=10000)
        page.get_by_test_id("link-down").wait_for(state="detached", timeout=20000)
        if seen["events"] < 3:
            raise SystemExit(f"expected a reconnect, saw {seen['events']} event requests")
        page.get_by_test_id("message-input").fill("断线重连后的一条消息")
        page.get_by_test_id("send-button").click()
        page.wait_for_function(
            "() => document.body.innerText.includes('断线重连后的一条消息')", timeout=15000
        )
        if page.get_by_test_id("link-down").count():
            raise SystemExit("banner came back")
        if page.get_by_test_id("stop-button").is_enabled():
            page.get_by_test_id("stop-button").click()
        browser.close()
    print(f"sse reconnect ok ({seen['events']} event requests)")


if __name__ == "__main__":
    main()
