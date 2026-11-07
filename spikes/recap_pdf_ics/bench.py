"""Bench des moteurs PDF + .ics. Usage: python bench.py [N]  -> out/bench.json"""

import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

import pymupdf

import ics_export
import render
import samples

N = int(sys.argv[1]) if len(sys.argv) > 1 else 5
OUT = Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)


def _t(fn, n=N):
    ts, res = [], None
    for _ in range(n):
        t = time.perf_counter()
        res = fn()
        ts.append((time.perf_counter() - t) * 1000)
    return res, {"median_ms": round(statistics.median(ts), 1), "min_ms": round(min(ts), 1), "max_ms": round(max(ts), 1), "n": n}


async def _pw_warm(htmls):
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        t = time.perf_counter()
        b = await p.chromium.launch(executable_path=render.chrome_path() or None)
        launch_ms = (time.perf_counter() - t) * 1000
        res = {}
        for rid, h in htmls.items():
            ts = []
            for _ in range(N):
                t = time.perf_counter()
                pdf = await render.pdf_playwright_async(h, b)
                ts.append((time.perf_counter() - t) * 1000)
            res[rid] = {"median_ms": round(statistics.median(ts), 1), "min_ms": round(min(ts), 1), "max_ms": round(max(ts), 1), "n": N, "bytes": len(pdf)}
        await b.close()
        return round(launch_ms, 1), res


def main():
    report = {"chrome": render.chrome_path(), "recaps": {}}
    htmls = {}
    for rid in samples.RECAPS:
        r = samples.get_recap(rid)
        h, t_html = _t(lambda: render.render_html(r))
        htmls[rid] = h
        ics, t_ics = _t(lambda: ics_export.build_ics(r))
        (OUT / f"{rid}.ics").write_bytes(ics)
        rec = {"html": t_html | {"bytes": len(h)}, "ics": t_ics | {"bytes": len(ics)}, "ics_validation": ics_export.validate_ics(ics)}
        for eng, fn in render.ENGINES.items():
            n = 3 if eng != "weasyprint" else N
            pdf, t = _t(lambda: fn(h), n)
            (OUT / f"{rid}.{eng}.pdf").write_bytes(pdf)
            doc = pymupdf.open(stream=pdf, filetype="pdf")
            rec[eng] = t | {"bytes": len(pdf), "pages": doc.page_count, "producer": doc.metadata.get("producer"),
                            "links": sum(len(p.get_links()) for p in doc)}
            if rid == "demo-nantes":
                for i, p in enumerate(doc):
                    p.get_pixmap(dpi=70).save(OUT / f"{rid}.{eng}.p{i + 1}.png")
        report["recaps"][rid] = rec
    launch, warm = asyncio.run(_pw_warm(htmls))
    report["playwright_warm"] = {"browser_launch_ms": launch, "per_recap": warm}
    (OUT / "bench.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    for rid, rec in report["recaps"].items():
        print(rid, "html", rec["html"]["median_ms"], "ms | ics", rec["ics"]["median_ms"], "ms |",
              " | ".join(f"{e} {rec[e]['median_ms']} ms {rec[e]['bytes'] // 1024} KB {rec[e]['pages']}p {rec[e]['links']}liens" for e in render.ENGINES),
              "| playwright chaud", warm[rid]["median_ms"], "ms")
    print("lancement chromium", launch, "ms")


if __name__ == "__main__":
    main()
