"""Fill the member dialog and confirm it calls web-bind. Does not open Gemini or Yuanbao."""

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:43123"


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(BASE, wait_until="networkidle")
        with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/api/sessions") and r.ok) as created:
            page.get_by_role("button", name="空白群", exact=True).click()
        room_id = created.value.json()["id"]
        page.get_by_test_id("session-item").first.click()
        page.get_by_role("button", name="成员", exact=True).click()
        page.get_by_test_id("connect-web-help").click()
        steps = page.get_by_test_id("connect-steps").inner_text()
        assert "配对码" in steps and "web-bind" not in steps
        assert "不会自动点击发送" in steps
        page.keyboard.press("Escape")
        page.get_by_test_id("add-member").click()
        page.get_by_test_id("member-nickname").fill("网页甲")
        page.get_by_test_id("member-role").fill("读者")
        page.get_by_test_id("member-provider").select_option("web")
        page.get_by_test_id("web-site").select_option("fixture")
        page.get_by_test_id("web-origin").fill("http://127.0.0.1:43124/fixture/chat")
        page.get_by_test_id("web-tab-key").fill("fixture-from-ui")
        page.get_by_test_id("web-auto").click()
        page.get_by_test_id("member-save").click()
        page.get_by_test_id("web-card").wait_for()
        assert page.get_by_test_id("bind-status").inner_text() == "已绑定标签页"
        member_id = page.get_by_test_id("member-id").input_value()
        assert page.get_by_test_id("tab-key").input_value() == "fixture-from-ui"
        assert member_id
        room = page.request.get(f"{BASE}/backend/api/sessions/{room_id}").json()
        member = next(item for item in room["members"] if item["id"] == member_id)
        assert member["web_site"] == "fixture"
        assert member["web_origin"] == "http://127.0.0.1:43124"
        assert member["web_tab_key"] == "fixture-from-ui"
        assert member["web_auto"] is True
        page.get_by_test_id("message-input").fill("先记下这句，不要当成定论。")
        page.get_by_test_id("send-button").click()
        page.get_by_test_id("favorite-button").first.wait_for()
        page.get_by_test_id("favorite-button").first.click()
        page.get_by_test_id("fav-title").fill("待查的一句")
        page.get_by_test_id("save-highlight").click()
        page.get_by_test_id("fav-title").wait_for(state="hidden")
        page.get_by_test_id("open-cards").click()
        card = page.get_by_test_id("highlight-card").inner_text()
        assert "不是已核实事实" in card
        page.keyboard.press("Escape")
        page.get_by_test_id("open-settings").click()
        page.get_by_test_id("theme-select").select_option("dark")
        page.keyboard.press("Escape")
        page.reload(wait_until="networkidle")
        assert page.evaluate("document.documentElement.classList.contains('dark')")
        page.screenshot(path="docs/screenshots/web-bind-member.png")
        browser.close()
    print("web-bind-ui passed", member_id)


if __name__ == "__main__":
    main()
