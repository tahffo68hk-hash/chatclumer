"""Turn the 2026-11-15 real-page DOM dumps into test fixtures.

usage: python scripts/make_dom_fixtures.py /workspace/dom-dumps

Guest-site dumps are kept whole (no account on the page). Logged-in dumps (DeepSeek) keep only the
chat column: the sidebar with chat history titles and the account name is dropped. Output goes to
backend/tests/fixtures/real_dom/<site>-<state>.html.gz with the source URL on the first line.
"""

import gzip
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "backend" / "tests" / "fixtures" / "real_dom"
GUEST = ["qwen", "chatgpt", "wenxin", "chatglm", "zai"]
LOGGED_IN = ["deepseek"]
STATES = ["0-empty", "1-typed", "2-streaming", "3-done"]

TRIM = """() => {
  const box = document.querySelector('textarea');
  const send = document.querySelector("div[role='button'].ds-button--circle");
  const list = document.querySelector('.ds-virtual-list-visible-items');
  const need = [box, send, list].filter(Boolean);
  let col = box;
  while (col && !need.every((el) => col.contains(el))) col = col.parentElement;
  const keep = (col || document.body).cloneNode(true);
  keep.querySelectorAll('a[href*="/a/chat/s/"]').forEach((el) => el.remove());
  return '<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>' + keep.outerHTML + '</body></html>';
}"""


def main(src: Path) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        for site in GUEST + LOGGED_IN:
            for state in STATES:
                path = src / f"{site}-{state}.html"
                raw = path.read_text(encoding="utf-8")
                first, _, rest = raw.partition("\n")
                if site in LOGGED_IN:
                    page = browser.new_page()
                    page.route("**/*", lambda route: route.abort())
                    page.set_content(rest, wait_until="domcontentloaded")
                    rest = page.evaluate(TRIM)
                    page.close()
                (OUT / f"{site}-{state}.html.gz").write_bytes(gzip.compress((first + "\n" + rest).encode("utf-8"), 9))
        browser.close()


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "/workspace/dom-dumps"))
