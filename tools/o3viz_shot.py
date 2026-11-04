"""Load the o3viz viewer on one bundle in headless Chromium and write a screenshot.

Needs `playwright` (pip install playwright; playwright install chromium); not a Wyrd dependency.
Usage: python tools/o3viz_shot.py BUNDLE_DIR OUT.png [--colour METRIC] [--select ID]
Exit code 1 if the page logged a console error or did not become ready.
"""

from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def shoot(bundle: Path, out: Path, colour: str, select: str, size: str = "") -> list[str]:
    from playwright.sync_api import sync_playwright

    from wyrd.o3viz import serve

    srv = serve.make_server(bundle, 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    errors: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader"])
        page = browser.new_page(viewport={"width": 1500, "height": 900})
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{srv.server_address[1]}/")
        page.wait_for_selector("body[data-ready='1']", timeout=30000)
        page.evaluate("window.__o3viz.stop()")
        if colour:
            page.evaluate("n => window.__o3viz.setColour(n)", colour)
        if size:
            page.evaluate("n => window.__o3viz.setSize(n)", size)
        if select:
            page.evaluate("id => window.__o3viz.select(id)", select)
        page.wait_for_timeout(600)
        page.screenshot(path=str(out))
        browser.close()
    srv.shutdown()
    return errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("bundle")
    ap.add_argument("out")
    ap.add_argument("--colour", default="")
    ap.add_argument("--size", default="")
    ap.add_argument("--select", default="")
    a = ap.parse_args()
    errs = shoot(Path(a.bundle), Path(a.out), a.colour, a.select, a.size)
    for e in errs:
        print("console error:", e, file=sys.stderr)
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
