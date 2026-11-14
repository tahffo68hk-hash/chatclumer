"""Drive the branch-room UI once. Saves screenshots; exits non-zero on a broken flow."""

from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 860})
        page.goto("http://127.0.0.1:43123", wait_until="networkidle")
        page.get_by_test_id("create-branches").click()
        page.get_by_test_id("branch-bar").wait_for()
        page.get_by_test_id("message-input").fill("请用一句话分别给出一条读书建议")
        page.get_by_test_id("send-button").click()
        page.wait_for_function(
            """() => [...document.querySelectorAll('[data-testid=message]')]
              .filter((el) => el.innerText.includes('我独立判断')).length >= 2""",
            timeout=25000,
        )
        page.get_by_test_id("pick-林知秋").check()
        page.get_by_test_id("pick-周衡").check()
        page.get_by_test_id("preview-merge").click()
        preview = page.get_by_test_id("merge-preview")
        preview.wait_for()
        text = preview.inner_text()
        if "林知秋" not in text or "周衡" not in text:
            raise SystemExit(f"preview missing names: {text[:400]}")
        if "苏晚" in text:
            raise SystemExit("preview included an unselected member")
        page.screenshot(path=str(OUT / "branches-preview.png"), full_page=True)
        page.get_by_test_id("confirm-merge").click()
        page.get_by_test_id("audience").wait_for(timeout=20000)
        page.get_by_test_id("pick-林知秋").uncheck()
        page.get_by_test_id("split-fresh").click()
        page.wait_for_timeout(800)
        page.screenshot(path=str(OUT / "branches-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(400)
        page.screenshot(path=str(OUT / "branches-mobile.png"), full_page=True)
        if page.get_by_test_id("stop-button").is_enabled():
            page.get_by_test_id("stop-button").click()
            page.wait_for_timeout(400)
        page.reload(wait_until="networkidle")
        page.get_by_test_id("branch-bar").wait_for()
        pill = page.get_by_test_id("status-pill").inner_text()
        if "进行" in pill or pill.strip() == "running":
            raise SystemExit(f"refresh restarted the room: {pill}")
        browser.close()
    print("branch ui ok")


if __name__ == "__main__":
    main()
