"""Mesure le temps de rendu de index.html dans le Chrome local (CDP) et fait des captures.

Usage : python -m http.server 8765 (dans spikes/survol) puis
        python spikes/survol/mesure_rendu.py [course.json] [--play]
"""

import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent / "data"


def main():
    data = (
        sys.argv[1]
        if len(sys.argv) > 1 and not sys.argv[1].startswith("--")
        else "data/course.json"
    )
    play = "--play" in sys.argv
    extra = "&terrain=0" if "--sans-terrain" in sys.argv else ""
    tag = Path(data).stem + ("_sans_terrain" if extra else "")
    with sync_playwright() as p:
        b = p.chromium.connect_over_cdp("http://localhost:29229")
        ctx = b.contexts[0]
        page = ctx.new_page()
        page.set_viewport_size({"width": 1400, "height": 860})
        t0 = time.time()
        page.goto(f"http://127.0.0.1:8765/index.html?data={data}{extra}")
        page.wait_for_function(
            "window.__metrics && window.__metrics.first_idle_ms", timeout=60000
        )
        m = page.evaluate("window.__metrics")
        m["wall_until_idle_s"] = round(time.time() - t0, 2)
        page.screenshot(path=str(OUT / f"capture_{tag}_vue.png"))
        if play:
            page.click("#play")
            page.wait_for_timeout(16000)
            page.screenshot(path=str(OUT / f"capture_{tag}_weekend.png"))
            page.wait_for_timeout(22000)
            page.screenshot(path=str(OUT / f"capture_{tag}_parcours.png"))
            page.wait_for_function(
                "window.__metrics.animation_totale_s", timeout=120000
            )
            page.wait_for_timeout(1500)
            page.screenshot(path=str(OUT / f"capture_{tag}_arrivee.png"))
            m = {**m, **page.evaluate("window.__metrics")}
        print(json.dumps(m, indent=1))
        (OUT / f"mesures_rendu_{tag}.json").write_text(json.dumps(m, indent=1))
        page.close()


if __name__ == "__main__":
    main()
