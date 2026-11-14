import pytest

pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.browser

from playwright.sync_api import sync_playwright

from app.main import FIXTURE_HTML


def test_fixture_stop_button_halts_the_visible_reply():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        page.set_content(FIXTURE_HTML)
        page.fill("#composer", "请用中文给两条简短的读书建议，每条一句话。")
        page.click("#send")
        page.wait_for_selector("button[aria-label='Stop response']")
        clicked = page.evaluate(
            """() => {
              const labels = new Set(["Stop", "Stop response", "Stop Answering", "停止", "停止生成", "停止回答", "停止对话"]);
              const el = [...document.querySelectorAll("button")].find((node) => labels.has(node.getAttribute("aria-label") || "") && !node.hidden);
              if (!el) return false;
              el.click();
              return true;
            }"""
        )
        page.wait_for_timeout(300)
        state = page.locator("#thread [data-role=assistant]").get_attribute("data-state")
        text = page.locator("#thread [data-role=assistant]").inner_text()
        browser.close()
    assert clicked
    assert state == "stopped"
    assert text != "夹具收到：请用中文给两条简短的读书建议，每条一句话。"
