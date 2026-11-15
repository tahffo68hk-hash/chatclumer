"""Phone-width + 手机连接 panel check against a running LAN-mode app (LAN=1 scripts/start.sh).

Usage: python scripts/check_mobile_ui.py [LAN_IP] [OUT_DIR]
Reads the token from backend/data/mobile_token.json but never prints it. Screenshots keep the QR
blurred and the pair link masked.
"""
import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ip = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
out = Path(sys.argv[2] if len(sys.argv) > 2 else "/workspace")
token = json.loads((ROOT / "backend" / "data" / "mobile_token.json").read_text())["token"]
base = f"http://{ip}:43123"
problems = []

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    phone = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True,
                                user_agent="Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36")
    page = phone.new_page()
    r = page.goto(base + "/")
    if r.status != 401:
        problems.append(f"unpaired phone got {r.status}, expected 401")
    page.screenshot(path=str(out / "mobile-unpaired.png"))
    page.goto(f"{base}/m/pair?token={token}")
    page.wait_for_selector('[data-testid="nav-chat"]', timeout=60000)
    if page.url.rstrip("/") != base:
        problems.append("pair did not land on /")
    page.wait_for_timeout(2500)
    if page.locator('[data-testid="open-mobile"]').count():
        problems.append("手机连接 button visible on the phone (must be loopback-only)")
    sw = page.evaluate("document.documentElement.scrollWidth")
    if sw > 390:
        problems.append(f"horizontal scroll on phone: scrollWidth={sw}")
    box = page.locator("footer textarea").first.bounding_box()
    if not box or box["y"] + box["height"] > 844:
        problems.append(f"composer not visible at bottom: {box}")
    page.screenshot(path=str(out / "mobile-chat.png"))
    page.click('[data-testid="nav-people"]')
    page.wait_for_timeout(500)
    page.screenshot(path=str(out / "mobile-people.png"))
    manifest = page.evaluate("fetch('/manifest.webmanifest').then(r=>r.json())")
    if manifest.get("display") != "standalone":
        problems.append("manifest display is not standalone")
    theme = page.evaluate("document.querySelector('meta[name=theme-color]')?.content")
    apple = page.evaluate("!!document.querySelector('link[rel=apple-touch-icon]')")
    if theme != "#1b1916" or not apple:
        problems.append(f"theme-color/apple-touch-icon missing: {theme} {apple}")

    desk = browser.new_context(viewport={"width": 1280, "height": 860})
    d = desk.new_page()
    d.goto("http://127.0.0.1:43123/")
    d.wait_for_selector('[data-testid="open-mobile"]', timeout=60000)
    d.click('[data-testid="open-mobile"]')
    d.wait_for_selector('[data-testid="mobile-qr"] svg', timeout=15000)
    if d.locator('[data-testid="mobile-qr"]').get_attribute("data-revealed") != "0":
        problems.append("QR revealed by default")
    if token in d.locator('[data-testid="mobile-panel"]').inner_text():
        problems.append("token visible as text in panel")
    # 额外再糊一层，保证截图里的二维码无法识别
    d.add_style_tag(content='[data-testid="mobile-qr"]{filter:blur(28px)!important}')
    d.wait_for_timeout(300)
    d.screenshot(path=str(out / "mobile-panel.png"))
    d.click('[data-testid="qr-web"]')
    d.wait_for_timeout(300)
    d.screenshot(path=str(out / "mobile-panel-web.png"))
    browser.close()

print(json.dumps({"ok": not problems, "problems": problems, "shots": [str(out / n) for n in ("mobile-unpaired.png", "mobile-chat.png", "mobile-people.png", "mobile-panel.png", "mobile-panel-web.png")]}, ensure_ascii=False, indent=1))
sys.exit(1 if problems else 0)
